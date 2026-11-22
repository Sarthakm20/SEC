"""Public entry point: answer a question with a given experiment configuration."""

from __future__ import annotations

import time
import uuid

from app.companies import SEED_COMPANIES
from app.db import repo
from app.graph.workflow import EXPERIMENTS, RunContext, build_graph, default_checkpointer
from app.llm.base import UsageTracker
from app.llm.providers import OfflineLLM
from app.models import AnswerResponse, QueryPlan, QueryType, Verdict, VerificationReport
from app.services import Services, get_services
from app.verify.auditor import EvidenceAuditor


def _previous_plan(thread_id: str | None) -> QueryPlan | None:
    if not thread_id:
        return None
    runs = repo.list_runs(limit=1, thread_id=thread_id)
    if not runs:
        return None
    prev = repo.get_run(runs[0]["run_id"])
    return prev.plan if prev else None


def answer_question(
    question: str,
    experiment: str = "E",
    thread_id: str | None = None,
    services: Services | None = None,
    persist: bool = True,
    offline: bool = False,
) -> AnswerResponse:
    svc = services or get_services()
    question = " ".join(question.split())[: svc.settings.max_question_chars]
    t0 = time.perf_counter()
    cfg = EXPERIMENTS[experiment]
    companies = repo.list_companies() or list(SEED_COMPANIES.values())
    tracker = UsageTracker()
    llm = OfflineLLM() if offline else svc.llm
    ctx = RunContext(
        settings=svc.settings,
        engine=svc.engine,
        retriever=svc.retriever,
        llm=llm,
        auditor=EvidenceAuditor(svc.engine, svc.reranker),
        tracker=tracker,
        companies=companies,
        experiment=cfg,
        previous_plan=_previous_plan(thread_id),
    )
    run_id = uuid.uuid4().hex[:16]
    graph = build_graph(ctx, default_checkpointer())
    final = graph.invoke({"question": question, "trace": []}, {"configurable": {"thread_id": run_id}})

    ev = final["ev"]
    plan: QueryPlan = final["plan"]
    verification: VerificationReport = final.get("verification") or VerificationReport(verdict=Verdict.INSUFFICIENT_EVIDENCE)
    limitations: list[str] = list(final.get("gaps", []))
    limitations += final.get("period_notes", [])
    for c in ev.calcs.values():
        limitations += c.warnings
    limitations += verification.notes
    if plan.query_type == QueryType.OUT_OF_SCOPE:
        limitations += plan.notes
    if llm.offline and not cfg.use_xbrl:
        limitations.append(f"Baseline pipeline {experiment}: the answer quotes retrieved 10-K passages only (no XBRL facts, no calculations, no LLM).")
    elif llm.offline and plan.query_type != QueryType.OUT_OF_SCOPE:
        limitations.append("No LLM configured: the answer was composed deterministically from verified evidence.")
    usage = tracker.usage
    if usage.provider == "none":
        usage.provider, usage.model = llm.provider, llm.model

    resp = AnswerResponse(
        run_id=run_id,
        question=question,
        answer=final.get("draft", ""),
        plan=plan,
        facts=[f.model_copy(update={"evidence_id": eid}) for eid, f in ev.facts.items()],
        calculations=list(ev.calcs.values()),
        passages=list(ev.passages.values()),
        verification=verification,
        trace=final.get("trace", []),
        usage=usage,
        limitations=list(dict.fromkeys(limitations)),
        latency_ms=round((time.perf_counter() - t0) * 1000, 1),
        experiment=experiment,
    )
    if persist:
        repo.save_run(resp, thread_id=thread_id)
    return resp
