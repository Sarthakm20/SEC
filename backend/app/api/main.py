"""FastAPI application layer.

  uvicorn app.api.main:app --port 8000
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import __version__
from app.api.security import rate_limit, require_api_key
from app.config import BACKEND_DIR, get_settings
from app.db import repo
from app.finance.engine import MetricResult
from app.finance.metrics import COMPARISON_METRICS, DERIVED, REPORTED
from app.graph.pipelines import answer_question
from app.graph.workflow import EXPERIMENTS
from app.llm.base import LLMError
from app.models import AnswerResponse
from app.services import get_services

log = logging.getLogger("secrag.api")
audit = logging.getLogger("secrag.audit")


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    svc = get_services()
    # warm models and indexes so the first user query is not slow
    _ = svc.retriever, svc.engine, svc.reranker
    log.info("ready: %d chunks indexed, LLM provider=%s", len(svc.retriever.chunks), svc.llm.provider)
    yield
    if "store" in svc.__dict__:
        svc.store.close()


settings = get_settings()
app = FastAPI(title="SEC 10-K Verifiable Financial Intelligence API", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)


@app.exception_handler(LLMError)
async def _llm_error(_: Request, exc: LLMError) -> JSONResponse:
    return JSONResponse(status_code=503 if exc.retryable else 502, content={"error": "llm_error", "detail": str(exc)})


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception) -> JSONResponse:  # pragma: no cover - defensive
    log.exception("unhandled error")
    return JSONResponse(status_code=500, content={"error": "internal_error", "detail": type(exc).__name__})


# ----------------------------------------------------------------------------- helpers
def _metric_json(r: MetricResult) -> dict:
    return {
        "metric": r.metric,
        "label": r.label,
        "ticker": r.ticker,
        "fiscal_year": r.fiscal_year,
        "kind": r.kind,
        "value": r.value,
        "display": r.display,
        "unit": r.unit,
        "period_start": r.period_start,
        "period_end": r.period_end,
        "fact": r.fact.model_dump() if r.fact else None,
        "calculation": r.calculation.model_dump() if r.calculation else None,
        "warnings": r.warnings,
        "error": r.error,
    }


def _years(ticker: str) -> dict:
    svc = get_services()
    narrative = sorted({c.fiscal_year for c in svc.retriever.chunks.values() if c.ticker == ticker})
    facts = svc.engine.available_years(ticker)
    return {"facts": facts, "filings": narrative}


def _ticker_or_404(ticker: str) -> str:
    t = ticker.upper()
    if t not in {c.ticker for c in repo.list_companies()}:
        raise HTTPException(404, f"company {ticker} has not been ingested")
    return t


# ----------------------------------------------------------------------------- routes
api = Depends(require_api_key)


@app.get("/api/health")
def health() -> dict:
    svc = get_services()
    return {
        "status": "ok",
        "version": __version__,
        "llm": {"provider": svc.llm.provider, "model": svc.llm.model},
        "embedding": svc.embedder.name,
        "reranker": svc.reranker.name if svc.reranker else None,
        "chunks": len(svc.retriever.chunks),
        "companies": [c.ticker for c in repo.list_companies()],
    }


@app.get("/api/companies", dependencies=[api])
def companies() -> list[dict]:
    out = []
    for c in repo.list_companies():
        out.append({**c.model_dump(), "years": _years(c.ticker), "filings": repo.list_filings(c.ticker)})
    return out


@app.get("/api/companies/{ticker}/overview", dependencies=[api])
def overview(ticker: str, fiscal_year: int | None = None) -> dict:
    t = _ticker_or_404(ticker)
    eng = get_services().engine
    years = _years(t)
    fy = fiscal_year or (max(years["filings"]) if years["filings"] else max(years["facts"]))
    kpis = []
    for item in ("revenue", "net_income", "operating_cash_flow", "free_cash_flow"):
        cur = eng.compute(t, item, fy)
        growth = eng.compute(t, f"{item}_growth", fy) if item in REPORTED else None
        if item == "free_cash_flow":
            prev = eng.compute(t, item, fy - 1)
            yoy = None
            if cur.ok and prev.ok and Decimal(prev.value) != 0:  # type: ignore[arg-type]
                yoy = str((Decimal(cur.value) - Decimal(prev.value)) / abs(Decimal(prev.value)))  # type: ignore[arg-type]
        else:
            yoy = growth.value if growth and growth.ok else None
        kpis.append({**_metric_json(cur), "yoy": yoy, "yoy_calculation": growth.calculation.model_dump() if growth and growth.calculation else None})
    ratios = [_metric_json(eng.compute(t, m, fy)) for m in ("gross_margin", "operating_margin", "net_margin", "rd_intensity", "current_ratio", "debt_to_equity")]
    trend_years = [y for y in years["facts"] if y <= fy][-5:]
    trend = []
    for y in trend_years:
        row: dict = {"fiscal_year": y}
        for item in ("revenue", "net_income", "operating_cash_flow", "free_cash_flow"):
            r = eng.compute(t, item, y)
            row[item] = float(Decimal(r.value) / Decimal(10) ** 9) if r.ok else None  # USD billions for charting
        trend.append(row)
    filing = next((f for f in repo.list_filings(t) if f["fiscal_year"] == fy), None)
    company = next(c for c in repo.list_companies() if c.ticker == t)
    return {"company": company.model_dump(), "fiscal_year": fy, "years": years, "kpis": kpis, "ratios": ratios, "trend": trend, "filing": filing}


@app.get("/api/compare", dependencies=[api])
def compare(
    tickers: str = Query(..., description="comma-separated tickers"),
    fiscal_year: int = Query(...),
    metrics: str | None = None,
    align: Literal["fiscal", "calendar"] = "fiscal",
) -> dict:
    ts = [_ticker_or_404(t.strip()) for t in tickers.split(",") if t.strip()][:6]
    ms = [m.strip() for m in metrics.split(",")] if metrics else COMPARISON_METRICS
    unknown = [m for m in ms if m not in REPORTED and m not in DERIVED and not m.endswith("_growth")]
    if unknown:
        raise HTTPException(422, f"unknown metrics: {unknown}")
    res = get_services().engine.compare(ts, ms, fiscal_year, align)
    res["rows"] = [{"metric": r["metric"], "label": r["label"], "values": {t: _metric_json(v) for t, v in r["values"].items()}} for r in res["rows"]]
    return res


@app.get("/api/metrics", dependencies=[api])
def metric_registry() -> dict:
    return {
        "reported": [{"key": k, "label": v.label, "concepts": list(v.concepts), "period_type": v.period_type, "unit": v.unit} for k, v in REPORTED.items()],
        "derived": [{"key": k, "label": v.label, "formula": v.formula, "definition": v.definition, "percent": v.display_percent} for k, v in DERIVED.items()],
        "comparison_defaults": COMPARISON_METRICS,
    }


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000)
    experiment: Literal["A", "B", "C", "D", "E"] = "E"
    thread_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


@app.post("/api/query", response_model=AnswerResponse, dependencies=[api, Depends(rate_limit)])
def query(req: QueryRequest, request: Request) -> AnswerResponse:
    t0 = time.perf_counter()
    resp = answer_question(req.question, experiment=req.experiment, thread_id=req.thread_id)
    audit.info(
        json.dumps({
            "event": "query", "run_id": resp.run_id, "client": request.client.host if request.client else None,
            "experiment": req.experiment, "verdict": resp.verification.verdict.value, "latency_ms": round((time.perf_counter() - t0) * 1000),
            "llm": f"{resp.usage.provider}/{resp.usage.model}", "tokens_in": resp.usage.input_tokens, "tokens_out": resp.usage.output_tokens,
            "cost_usd": resp.usage.estimated_cost_usd,
        })
    )
    return resp


@app.get("/api/runs", dependencies=[api])
def runs(limit: int = Query(30, le=200), thread_id: str | None = None) -> list[dict]:
    return repo.list_runs(limit, thread_id)


@app.get("/api/runs/{run_id}", response_model=AnswerResponse, dependencies=[api])
def run(run_id: str) -> AnswerResponse:
    r = repo.get_run(run_id)
    if r is None:
        raise HTTPException(404, "run not found")
    return r


@app.get("/api/sources/chunk/{chunk_id}", dependencies=[api])
def chunk_source(chunk_id: str) -> dict:
    c = repo.get_chunk(chunk_id)
    if c is None:
        raise HTTPException(404, "chunk not found")
    return c.model_dump()


@app.get("/api/sources/fact", dependencies=[api])
def fact_source(fact_id: str) -> dict:
    f = repo.get_fact(fact_id)
    if f is None:
        raise HTTPException(404, "fact not found")
    conflict = get_services().engine.conflicts_for(f)
    return {**f.model_dump(), "conflict": conflict.describe() if conflict else None}


@app.get("/api/experiments", dependencies=[api])
def experiments() -> list[dict]:
    return [{"id": k, "description": v.description, "retrieval_mode": v.retrieval_mode, "rerank": v.rerank, "use_xbrl": v.use_xbrl,
             "enforce_verification": v.enforce_verification, "agentic": v.agentic} for k, v in EXPERIMENTS.items()]


@app.get("/api/eval/latest", dependencies=[api])
def eval_latest() -> dict:
    p = BACKEND_DIR / "evaluation" / "results" / "latest.json"
    if not p.exists():
        raise HTTPException(404, "no benchmark has been run yet: python -m evaluation.run_benchmark")
    data = json.loads(p.read_text(encoding="utf-8"))
    for exp in data.get("experiments", {}).values():
        exp.pop("per_question", None)
    return data


@app.get("/api/eval/gold", dependencies=[api])
def eval_gold() -> dict:
    """Latest gold-set cross-check against SEC XBRL; `stale` means the gold file changed after that check."""
    p = BACKEND_DIR / "evaluation" / "results" / "gold_crosscheck.json"
    if not p.exists():
        raise HTTPException(404, "gold set not cross-checked yet: python -m evaluation.crosscheck_gold")
    data = json.loads(p.read_text(encoding="utf-8"))
    gold = BACKEND_DIR / "evaluation" / "gold" / "questions.jsonl"
    current = hashlib.sha256(gold.read_bytes()).hexdigest() if gold.exists() else None
    data["stale"] = current is not None and data.get("gold_sha256") != current
    return data


@app.get("/api/suggestions", dependencies=[api])
def suggestions() -> list[str]:
    return [
        "How did Apple's revenue change in fiscal 2025 compared to fiscal 2024?",
        "Compare the operating margins of Apple, Microsoft and NVIDIA in fiscal 2025.",
        "What was Microsoft's free cash flow in fiscal 2025?",
        "Why did NVIDIA's revenue increase in fiscal 2025?",
        "What supply chain risks does Apple describe in its fiscal 2025 10-K?",
        "How has NVIDIA's gross margin evolved over fiscal 2023 through 2025?",
        "What was Apple's debt-to-equity ratio at fiscal year end 2025?",
        "How does Apple recognize revenue?",
    ]

