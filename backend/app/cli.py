"""Command line entry point.

  python -m app.cli ingest [--tickers AAPL MSFT NVDA] [--years 2023 2024 2025]
  python -m app.cli ask "How did Apple's revenue change in FY2025 vs FY2024?" [--experiment E]
  python -m app.cli status
  python -m app.cli test-llm [--provider gemini]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time


def _cmd_ingest(args: argparse.Namespace) -> int:
    from app.config import get_settings
    from app.ingest.pipeline import ingest_company
    from app.sec.client import EdgarClient
    from app.services import get_services

    s = get_settings()
    svc = get_services()
    tickers = [t.upper() for t in (args.tickers or s.default_tickers)]
    years = args.years or s.default_fiscal_years
    print(f"Ingesting {tickers} for fiscal years {years}")
    print(f"Embedding model: {svc.embedder.name} (dim {svc.embedder.dim}); vector collection: {svc.store.collection}")
    with EdgarClient(s) as client:
        for t in tickers:
            summary = ingest_company(
                t, years, client, svc.embedder, svc.store, progress=print,
                chunk_target_tokens=s.chunk_target_tokens, chunk_overlap_tokens=s.chunk_overlap_tokens,
            )
            print(f"[{t}] done in {summary.seconds}s: {json.dumps(summary.filings)}")
    print(f"Vector points: {svc.store.count()}")
    return 0


def _cmd_status(_: argparse.Namespace) -> int:
    from app.db import repo

    for c in repo.list_companies():
        fl = repo.list_filings(c.ticker)
        print(f"{c.ticker:5s} {c.name:30s} filings: " + ", ".join(f"FY{f['fiscal_year']}({f['n_chunks']} chunks)" for f in fl))
    print(f"chunks total: {len(repo.load_all_chunks())}")
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    from app.graph.pipelines import answer_question

    resp = answer_question(args.question, experiment=args.experiment)
    print(resp.answer)
    print()
    print(f"verdict: {resp.verification.verdict.value}  latency: {resp.latency_ms:.0f} ms  llm: {resp.usage.provider}/{resp.usage.model}")
    for ev in resp.trace:
        print(f"  [{ev.status:4s}] {ev.label}")
    if args.json:
        print(resp.model_dump_json(indent=2))
    return 0


def _cmd_test_llm(args: argparse.Namespace) -> int:
    from app.config import get_settings
    from app.llm.base import LLMError
    from app.llm.providers import build_llm

    s = get_settings()
    provider = args.provider or s.llm_provider
    print(f"=== Testing LLM Configuration ===")
    print(f"Configured provider : {provider}")
    print(f"Configured model    : {s.llm_model or '(default for provider)'}")

    if provider == "gemini":
        has_key = bool(s.gemini_api_key or os.environ.get("GEMINI_API_KEY"))
        print(f"Gemini API key      : {'[OK] Detected' if has_key else '[MISSING] Not found in .env or environment'}")
        if not has_key:
            print("\nError: Please add GEMINI_API_KEY=your_key to D:\\SEC\\.env and try again.")
            return 1
    elif provider == "openai":
        has_key = bool(s.openai_api_key or os.environ.get("OPENAI_API_KEY"))
        print(f"OpenAI API key      : {'[OK] Detected' if has_key else '[MISSING] Not found in .env or environment'}")
        if not has_key:
            print("\nError: Please add OPENAI_API_KEY=your_key to D:\\SEC\\.env and try again.")
            return 1

    try:
        llm = build_llm(s, provider=provider)
        print(f"Active provider instance: {llm.provider} (model: {llm.model})")
        if getattr(llm, "offline", False):
            print("\n[OK] Offline mode active: Answers are synthesized deterministically without LLM calls.")
            return 0

        print("\n1. Testing basic text generation...")
        t0 = time.perf_counter()
        resp = llm.complete(
            system="You are a financial research assistant. Answer concisely.",
            user="In 10 words or less, say hello and mention your model name.",
            max_tokens=60,
        )
        dt = (time.perf_counter() - t0) * 1000
        print(f"  Response ({dt:.0f} ms): {resp.text.strip()}")
        print(f"  Tokens: {resp.input_tokens} in, {resp.output_tokens} out")

        print("\n2. Testing JSON schema output...")
        t0 = time.perf_counter()
        schema = {
            "type": "object",
            "properties": {"status": {"type": "string"}, "answer": {"type": "string"}},
            "required": ["status", "answer"],
        }
        resp_json = llm.complete(
            system="You are a strict JSON generator.",
            user="Generate a JSON object with status='verified' and answer='Ready'.",
            max_tokens=60,
            json_schema=schema,
        )
        dt = (time.perf_counter() - t0) * 1000
        print(f"  Raw response ({dt:.0f} ms): {resp_json.text.strip()}")
        parsed = json.loads(resp_json.text)
        print(f"  Successfully parsed JSON: {parsed}")

        print("\n[SUCCESS] LLM provider is verified and functioning properly!")
        return 0
    except LLMError as e:
        print(f"\n[LLM ERROR] {e}")
        return 1
    except Exception as e:
        print(f"\n[UNEXPECTED ERROR] {type(e).__name__}: {e}")
        return 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="secrag")
    sub = p.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("ingest", help="download + index 10-K filings and XBRL facts")
    pi.add_argument("--tickers", nargs="*")
    pi.add_argument("--years", nargs="*", type=int)
    pi.set_defaults(func=_cmd_ingest)
    ps = sub.add_parser("status", help="show ingested companies and filings")
    ps.set_defaults(func=_cmd_status)
    pa = sub.add_parser("ask", help="answer a question end-to-end")
    pa.add_argument("question")
    pa.add_argument("--experiment", default="E", choices=list("ABCDE"))
    pa.add_argument("--json", action="store_true")
    pa.set_defaults(func=_cmd_ask)
    pt = sub.add_parser("test-llm", help="test configured LLM provider and connectivity")
    pt.add_argument("--provider", choices=["gemini", "openai", "anthropic", "ollama", "offline"])
    pt.set_defaults(func=_cmd_test_llm)
    args = p.parse_args(argv)
    try:
        return args.func(args)
    finally:
        import sys

        if "app.services" in sys.modules:
            from app.services import get_services

            svc = get_services()
            if "store" in svc.__dict__:
                svc.store.close()


if __name__ == "__main__":
    sys.exit(main())
