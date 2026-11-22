"""Gold benchmark + controlled ablation study (experiments A–E).

  python -m evaluation.run_benchmark                      # all experiments, all questions
  python -m evaluation.run_benchmark --experiments D E --limit 20
  python -m evaluation.run_benchmark --offline            # force deterministic synthesis
  python -m evaluation.run_benchmark --gold evaluation/gold/heldout_paraphrase.jsonl --experiments E
                                                          # held-out set: results go to heldout_paraphrase-*.json, latest.json untouched

Retrieval metrics are computed for every experiment. Answer-level metrics for A–C need an LLM
(those baselines answer from retrieved text only); without one they are reported as n/a.
"""

from __future__ import annotations

import os
import shutil
import tempfile

# Embedded Qdrant allows one process per storage folder. If the API server is running against the live
# store, benchmark against a snapshot copy instead (set before any app module reads settings).
if not os.environ.get("QDRANT_URL") and not os.environ.get("QDRANT_PATH"):
    _live = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "qdrant")
    if os.path.isdir(_live):
        _snap = os.path.join(tempfile.mkdtemp(prefix="secrag-bench-"), "qdrant")
        shutil.copytree(_live, _snap, ignore=shutil.ignore_patterns("*.lock", ".lock"))
        os.environ["QDRANT_PATH"] = _snap

import argparse
import json
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.db import repo
from app.graph.pipelines import answer_question
from app.graph.planner import rule_plan
from app.graph.workflow import EXPERIMENTS
from app.retrieval.hybrid import RetrievalFilters
from app.services import get_services
from evaluation.metrics import answer_metrics, retrieval_metrics

GOLD = Path(__file__).parent / "gold" / "questions.jsonl"
RESULTS = Path(__file__).parent / "results"


def _mean(xs: list) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def run(experiments: list[str], limit: int | None, k: int, offline: bool, gold: Path = GOLD) -> dict:
    svc = get_services()
    items = [json.loads(line) for line in gold.read_text(encoding="utf-8").splitlines() if line.strip()]
    if limit:
        items = items[:limit]
    chunks = list(svc.retriever.chunks.values())
    companies = repo.list_companies()
    avail = {c.ticker: sorted({ch.fiscal_year for ch in chunks if ch.ticker == c.ticker} | set(svc.engine.available_years(c.ticker))) for c in companies}
    llm_offline = offline or svc.llm.offline
    report: dict = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "gold_file": gold.name,
        "questions": len(items),
        "k": k,
        "llm": {"provider": "offline" if llm_offline else svc.llm.provider, "model": "template-synthesizer" if llm_offline else svc.llm.model},
        "embedding": svc.embedder.name,
        "reranker": svc.reranker.name if svc.reranker else None,
        "corpus_chunks": len(chunks),
        "experiments": {},
    }
    for exp in experiments:
        cfg = EXPERIMENTS[exp]
        per_q = []
        print(f"\n=== Experiment {exp}: {cfg.description}")
        # A–C without an LLM are answered by the extractive reader (quotes from retrieved passages, no math)
        reader = "llm" if not llm_offline else ("deterministic template" if cfg.use_xbrl else "extractive reader")
        for it in items:
            row: dict = {"id": it["id"], "category": it["category"]}
            # ---- retrieval
            if it.get("relevant"):
                plan, _ = rule_plan(it["question"], companies, avail)
                years = plan.fiscal_years or None
                rf = RetrievalFilters(tickers=plan.tickers or None, fiscal_years=years, sections=plan.sections or None)
                res = svc.retriever.retrieve(it["question"], rf, mode=cfg.retrieval_mode, rerank=cfg.rerank, top_n=k)
                row.update(retrieval_metrics([p.chunk for p in res.passages], it["relevant"], chunks, k))
            # ---- answer
            t0 = time.perf_counter()
            resp = answer_question(it["question"], experiment=exp, persist=False, offline=llm_offline)
            row.update(answer_metrics(resp, it, chunks))
            row["wall_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            # which reader actually wrote the answer (an LLM call that fails falls back to template/extractive)
            synth = [e for e in resp.trace if e.step in ("synthesize", "fallback")]
            row["reader_used"] = "template" if synth and synth[-1].step == "fallback" else (synth[-1].detail.get("mode") if synth else None)
            per_q.append(row)
            status = row.get("task_success")
            print(f"  {it['id']} [{it['category']:13s}] success={status} verdict={row.get('verdict')} hit@{k}={row.get(f'hit@{k}')}")
        agg = _aggregate(per_q, k)
        used = {r.get("reader_used") for r in per_q if r.get("reader_used")}
        agg["readers_used"] = {m: sum(1 for r in per_q if r.get("reader_used") == m) for m in sorted(used)}
        mixed = " — MIXED: some LLM calls failed and fell back" if len(used) > 1 else ""
        agg["answer_metrics"] = f"computed ({reader}){mixed}"
        report["experiments"][exp] = {"description": cfg.description, "reader": reader, "summary": agg, "per_question": per_q}
    return report


def _aggregate(rows: list[dict], k: int) -> dict:
    keys = [f"hit@{k}", f"recall@{k}", "mrr", f"ndcg@{k}", "exact_match", "mean_rel_error", "citation_precision",
            "citation_coverage", "faithfulness", "task_success", "entity_mentioned", "cost_usd"]
    out = {key: _mean([r.get(key) for r in rows]) for key in keys}
    unans = [r for r in rows if r["category"] == "unanswerable" and "abstained" in r]
    ans = [r for r in rows if r["category"] != "unanswerable" and "abstained" in r]
    out["abstention_accuracy"] = _mean([float(r["abstained"]) for r in unans])
    out["false_abstention_rate"] = _mean([float(r["abstained"]) for r in ans])
    lat = [r["latency_ms"] for r in rows if r.get("latency_ms") is not None]
    out["latency_p50_ms"] = round(statistics.median(lat), 1) if lat else None
    out["latency_p95_ms"] = round(sorted(lat)[int(0.95 * (len(lat) - 1))], 1) if lat else None
    by_cat = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    out["by_category"] = {c: {"n": len(rs), "task_success": _mean([r.get("task_success") for r in rs]), f"hit@{k}": _mean([r.get(f"hit@{k}") for r in rs])} for c, rs in by_cat.items()}
    return out


def to_markdown(report: dict) -> str:
    k = report["k"]
    cols = [("hit@%d" % k, "Hit@%d" % k), ("recall@%d" % k, "Recall@%d" % k), ("mrr", "MRR"), ("ndcg@%d" % k, "nDCG@%d" % k),
            ("exact_match", "Numeric EM"), ("citation_precision", "Cit. precision"), ("citation_coverage", "Cit. coverage"),
            ("faithfulness", "Faithfulness"), ("abstention_accuracy", "Abstention acc."), ("task_success", "Task success"),
            ("latency_p50_ms", "p50 ms"), ("cost_usd", "Cost/q $")]
    lines = [
        f"# Benchmark report — {report['created_at']}",
        "",
        f"Questions: {report['questions']} · LLM: {report['llm']['provider']}/{report['llm']['model']} · embeddings: {report['embedding']} · reranker: {report['reranker']} · corpus: {report['corpus_chunks']} chunks",
        "",
        "| Exp | " + " | ".join(c[1] for c in cols) + " |",
        "|---|" + "---|" * len(cols),
    ]
    for exp, data in report["experiments"].items():
        s = data["summary"]
        vals = []
        for key, _ in cols:
            v = s.get(key)
            vals.append("n/a" if v is None else (f"{v:.3f}" if isinstance(v, float) and key not in ("latency_p50_ms",) else str(v)))
        lines.append(f"| {exp} | " + " | ".join(vals) + " |")
    lines += ["", "Experiments:"]
    for exp, data in report["experiments"].items():
        lines.append(f"- **{exp}** — {data['description']}. Answer metrics: {data['summary']['answer_metrics']}.")
    lines += ["", "Per-category task success:", ""]
    cats = sorted({c for d in report["experiments"].values() for c in d["summary"]["by_category"]})
    lines.append("| Category | " + " | ".join(report["experiments"]) + " |")
    lines.append("|---|" + "---|" * len(report["experiments"]))
    for c in cats:
        row = []
        for d in report["experiments"].values():
            v = d["summary"]["by_category"].get(c, {}).get("task_success")
            row.append("n/a" if v is None else f"{v:.2f}")
        lines.append(f"| {c} | " + " | ".join(row) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--experiments", nargs="*", default=list(EXPERIMENTS))
    p.add_argument("--limit", type=int)
    p.add_argument("--k", type=int, default=10)
    p.add_argument("--offline", action="store_true")
    p.add_argument("--gold", type=Path, default=GOLD, help="gold JSONL file (default: the main 53-question set)")
    args = p.parse_args()
    gold = args.gold.resolve()
    report = run(args.experiments, args.limit, args.k, args.offline, gold)
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    main_set = gold == GOLD.resolve()
    prefix = "benchmark" if main_set else gold.stem
    (RESULTS / f"{prefix}-{stamp}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = to_markdown(report)
    (RESULTS / f"{prefix}-{stamp}.md").write_text(md, encoding="utf-8")
    # latest.json feeds the UI benchmark page and only ever holds the main gold set
    (RESULTS / ("latest.json" if main_set else f"{gold.stem}-latest.json")).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\n" + md)
    svc = get_services()
    if "store" in svc.__dict__:
        svc.store.close()  # release the embedded Qdrant snapshot cleanly
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
