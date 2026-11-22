"""LangGraph orchestration of the three logical components (Recommendations §3.2):

  (1) Planning & Retrieval   — plan → retrieve ⟲ (sufficiency check → query expansion)
  (2) Financial Analysis     — financials (XBRL lookup + deterministic Decimal calculations)
  (3) Verification & Synthesis — synthesize → verify ⟲ (repair once) → finalize / abstain

Only planning-under-ambiguity and synthesis use an LLM; every other node is deterministic.
Each node appends an observable TraceEvent (no private model reasoning is exposed).
"""

from __future__ import annotations

import operator
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.config import Settings
from app.finance.engine import FinancialEngine, MetricResult
from app.finance.metrics import COMPARISON_METRICS, DERIVED, REPORTED
from app.graph import synthesis
from app.graph.evidence import EvidenceSet
from app.graph.extractive import extractive_answer
from app.graph.planner import llm_plan, rule_plan
from app.llm.base import LLM, LLMError, UsageTracker
from app.models import (
    Company,
    QueryPlan,
    QueryType,
    TraceEvent,
    Verdict,
    VerificationReport,
)
from app.retrieval.hybrid import HybridRetriever, RetrievalFilters
from app.verify.auditor import EvidenceAuditor

QTYPE_LABEL = {
    QueryType.FACT_LOOKUP: "fact lookup",
    QueryType.CROSS_YEAR: "cross-year comparison",
    QueryType.RATIO: "ratio calculation",
    QueryType.CROSS_COMPANY: "cross-company comparison",
    QueryType.TREND: "multi-year trend",
    QueryType.NARRATIVE: "narrative question",
    QueryType.HYBRID: "hybrid (numbers + narrative)",
    QueryType.OUT_OF_SCOPE: "out of scope",
}


@dataclass(frozen=True)
class ExperimentConfig:
    name: str
    description: str
    retrieval_mode: str  # dense | hybrid
    rerank: bool
    use_xbrl: bool  # structured facts + deterministic engine
    enforce_verification: bool  # failing drafts are repaired / replaced
    agentic: bool  # LLM planning under ambiguity, iterative retrieval, sufficiency-based abstention


EXPERIMENTS: dict[str, ExperimentConfig] = {
    "A": ExperimentConfig("A", "Baseline RAG: dense retrieval → reader", "dense", False, False, False, False),
    "B": ExperimentConfig("B", "Hybrid RAG: BM25 + dense → RRF → reader", "hybrid", False, False, False, False),
    "C": ExperimentConfig("C", "Reranked RAG: hybrid → cross-encoder → reader", "hybrid", True, False, False, False),
    "D": ExperimentConfig("D", "Financial RAG: XBRL + narrative RAG → Decimal math → verification", "hybrid", True, True, True, False),
    "E": ExperimentConfig("E", "Agentic Financial RAG: D + LangGraph routing, iterative retrieval, sufficiency checks", "hybrid", True, True, True, True),
}


class State(TypedDict, total=False):
    question: str
    plan: QueryPlan
    results: list[MetricResult]
    ev: EvidenceSet
    period_notes: list[str]
    gaps: list[str]
    filters: dict[str, Any]
    retrieval_query: str
    iteration: int
    expand: bool
    draft: str
    synth_mode: str
    repair_attempts: int
    repair_issues: list[str]
    verification: VerificationReport
    trace: Annotated[list[TraceEvent], operator.add]


@dataclass
class RunContext:
    settings: Settings
    engine: FinancialEngine
    retriever: HybridRetriever
    llm: LLM
    auditor: EvidenceAuditor
    tracker: UsageTracker
    companies: list[Company]
    experiment: ExperimentConfig
    previous_plan: QueryPlan | None = None


@contextmanager
def _timer():
    t = {"ms": 0.0}
    t0 = time.perf_counter()
    yield t
    t["ms"] = round((time.perf_counter() - t0) * 1000, 1)


def _ev(step: str, label: str, ms: float, status: str = "ok", **detail: Any) -> TraceEvent:
    return TraceEvent(step=step, label=label, status=status, duration_ms=ms, detail=detail)  # type: ignore[arg-type]


def build_graph(ctx: RunContext, checkpointer: Any | None = None):
    cfg = ctx.experiment
    names = {c.ticker: c.name for c in ctx.companies}

    def narrative_years(ticker: str) -> list[int]:
        return sorted({c.fiscal_year for c in ctx.retriever.chunks.values() if c.ticker == ticker})

    def fact_years(ticker: str) -> list[int]:
        try:
            return ctx.engine.available_years(ticker)
        except Exception:
            return []

    # ------------------------------------------------------------------ (1) planning
    def plan_node(state: State) -> State:
        with _timer() as t:
            avail = {c.ticker: sorted(set(fact_years(c.ticker)) | set(narrative_years(c.ticker))) for c in ctx.companies}
            plan, confidence = rule_plan(state["question"], ctx.companies, avail, ctx.previous_plan)
            if cfg.agentic and confidence < 0.6 and not ctx.llm.offline:
                alt = llm_plan(state["question"], ctx.companies, avail, ctx.llm, ctx.tracker)
                if alt is not None and (alt.tickers or alt.query_type == QueryType.OUT_OF_SCOPE):
                    plan = alt
        label = f"Query classified: {QTYPE_LABEL[plan.query_type]}"
        if plan.tickers:
            label += f" · {', '.join(plan.tickers)}"
        if plan.fiscal_years:
            label += f" · FY{', FY'.join(map(str, plan.fiscal_years))}"
        return {
            "plan": plan, "results": [], "ev": EvidenceSet(), "gaps": [], "period_notes": [], "iteration": 0,
            "repair_attempts": 0, "repair_issues": [],
            "trace": [_ev("plan", label, t["ms"], planner=plan.planner, confidence=confidence, metrics=plan.metrics, sections=plan.sections, notes=plan.notes)],
        }

    # ------------------------------------------------------------------ (2) financial analysis
    def financials_node(state: State) -> State:
        plan = state["plan"]
        if not (plan.needs_facts and cfg.use_xbrl) or plan.query_type == QueryType.OUT_OF_SCOPE:
            reason = "structured XBRL path disabled in this experiment" if plan.needs_facts else "no financial metrics requested"
            return {"trace": [_ev("financials", "Financial engine skipped", 0, "skip", reason=reason)]}
        ev: EvidenceSet = state["ev"]
        results: list[MetricResult] = []
        gaps: list[str] = list(state.get("gaps", []))
        notes: list[str] = []
        with _timer() as t:
            tickers = plan.tickers
            common_latest = None
            if not plan.fiscal_years:
                per = [max(fact_years(tk) or [0]) for tk in tickers]
                if plan.needs_narrative:
                    per = [max(narrative_years(tk) or [p]) for tk, p in zip(tickers, per)]
                common_latest = min(per) if per else None
            for tk in tickers:
                years = plan.fiscal_years or ([common_latest] if common_latest else [])
                metrics = plan.metrics or (COMPARISON_METRICS if plan.query_type == QueryType.CROSS_COMPANY else [])
                is_trend = plan.query_type == QueryType.TREND or len(years) >= 3
                for m in metrics:
                    if m.endswith("_growth"):
                        base = m.removesuffix("_growth")
                        targets = years[1:] if (is_trend and len(years) > 1) else years[-1:]
                        for y in targets:
                            r = ctx.engine.compute(tk, m, y)
                            results.append(r)
                            if r.ok and not is_trend and base in REPORTED:
                                # YoY growth: show both underlying values and the absolute change too
                                results.append(ctx.engine.compute(tk, base, y))
                                results.append(ctx.engine.compute(tk, base, y - 1))
                                results.extend(x for x in ctx.engine.change_between(tk, base, y - 1, y) if x.metric.endswith("abs_change"))
                        continue
                    for y in years:
                        results.append(ctx.engine.compute(tk, m, y))
                    if len(years) >= 2 and not (is_trend and len(years) > 2):
                        results.extend(ctx.engine.change_between(tk, m, years[0], years[-1]))
            # de-duplicate (same metric/ticker/year)
            seen: set[tuple[str, str, int]] = set()
            uniq: list[MetricResult] = []
            for r in results:
                key = (r.ticker, r.metric, r.fiscal_year)
                if key not in seen:
                    seen.add(key)
                    uniq.append(r)
            results = uniq
            for r in results:
                if r.ok:
                    ev.add_result(r)
                elif r.error:
                    gaps.append(r.error)
            if plan.query_type == QueryType.CROSS_COMPANY and len(tickers) > 1:
                cmp = ctx.engine.compare(tickers, ["revenue"], plan.fiscal_years[-1] if plan.fiscal_years else (common_latest or 0))
                notes = [n for n in cmp["period_notes"] if "different dates" in n]
        n_facts = len(ev.facts)
        n_calcs = len(ev.calcs)
        label = f"Extracted {n_facts} financial fact{'s' * (n_facts != 1)} · executed {n_calcs} calculation{'s' * (n_calcs != 1)}"
        status = "ok" if any(r.ok for r in results) else "warn"
        return {
            "results": results, "ev": ev, "gaps": list(dict.fromkeys(gaps)), "period_notes": notes,
            "trace": [_ev("financials", label, t["ms"], status, facts=n_facts, calculations=n_calcs, missing=len([r for r in results if not r.ok]))],
        }

    # ------------------------------------------------------------------ (1) retrieval
    def retrieve_node(state: State) -> State:
        plan = state["plan"]
        # Baselines A–C have no structured path and no scope routing: they always answer from retrieved text.
        text_only = not cfg.use_xbrl
        numeric_via_text = plan.needs_facts and text_only
        if not text_only and (plan.query_type == QueryType.OUT_OF_SCOPE or not plan.needs_narrative):
            return {"trace": [_ev("retrieve", "Narrative retrieval skipped", 0, "skip", reason="question is fully answered by structured data" if plan.needs_facts else "out of scope")]}
        ev: EvidenceSet = state["ev"]
        iteration = state.get("iteration", 0)
        filters = state.get("filters") or {}
        query = state.get("retrieval_query") or plan.narrative_query or state["question"]
        if not filters:
            years = plan.fiscal_years
            if numeric_via_text and years:
                years = sorted(set(years) | {max(years) + 1})  # later 10-Ks also report prior-year comparatives
            filters = {"years": years, "sections": None if numeric_via_text else plan.sections}
        top_n = ctx.settings.rerank_top_n
        per_ticker = max(2, top_n // max(1, len(plan.tickers))) if len(plan.tickers) > 1 else top_n
        stats = {"candidates": 0, "selected": 0, "timings": {}}
        with _timer() as t:
            latest_requested = any("'latest' resolved" in n for n in plan.notes)
            for tk in plan.tickers or [None]:
                years = filters.get("years") or ([max(narrative_years(tk))] if tk and narrative_years(tk) and not numeric_via_text and plan.query_type != QueryType.TREND else None)
                if years and tk and latest_requested and not set(years) & set(narrative_years(tk)) and narrative_years(tk):
                    # "latest"/"current" resolved to a year with XBRL data but no ingested 10-K text: use the newest filing
                    years = [max(narrative_years(tk))]
                rf = RetrievalFilters(tickers=[tk] if tk else None, fiscal_years=years or None, sections=filters.get("sections") or None)
                res = ctx.retriever.retrieve(query, rf, mode=cfg.retrieval_mode, rerank=cfg.rerank, top_n=per_ticker)
                ctx.tracker.record_embedding(1 if cfg.retrieval_mode in ("dense", "hybrid") else 0)
                if res.reranked:
                    ctx.tracker.record_rerank(1)
                for p in res.passages:
                    ev.add_passage(p)
                stats["candidates"] += res.candidates
                stats["selected"] += len(res.passages)
                for k, v in res.timings_ms.items():
                    stats["timings"][k] = round(stats["timings"].get(k, 0) + v, 1)
        rr = "reranked to" if cfg.rerank else "selected"
        label = f"Retrieved {stats['candidates']} candidate passages · {rr} {stats['selected']} evidence sources"
        if iteration:
            label = f"Retrieval round {iteration + 1}: " + label
        return {
            "ev": ev, "filters": filters, "retrieval_query": query,
            "trace": [_ev("retrieve", label, t["ms"], "ok" if stats["selected"] else "warn", mode=cfg.retrieval_mode, rerank=cfg.rerank, query=query, filters={k: v for k, v in filters.items()}, **stats)],
        }

    # ------------------------------------------------------------------ sufficiency (agentic)
    def sufficiency_node(state: State) -> State:
        plan = state["plan"]
        ev: EvidenceSet = state["ev"]
        if not plan.needs_narrative or plan.query_type == QueryType.OUT_OF_SCOPE:
            return {"expand": False}
        with _timer() as t:
            threshold = ctx.settings.min_rerank_score_for_sufficiency
            missing = []
            for tk in plan.tickers:
                ps = [p for p in ev.passages.values() if p.chunk.ticker == tk]
                good = [p for p in ps if p.scores.rerank_score is None or p.scores.rerank_score >= threshold]
                if not good:
                    missing.append(tk)
        iteration = state.get("iteration", 0)
        can_expand = cfg.agentic and iteration + 1 < ctx.settings.max_retrieval_iterations + 1 and iteration < ctx.settings.max_retrieval_iterations
        if missing and can_expand:
            return {"expand": True, "trace": [_ev("sufficiency", f"Evidence insufficient for {', '.join(missing)} — broadening search", t["ms"], "warn", missing=missing)]}
        gaps = list(state.get("gaps", []))
        if missing:
            gaps.append(f"no sufficiently relevant 10-K passage found for {', '.join(missing)}")
        label = "Evidence sufficiency check passed" if not missing else f"Evidence still insufficient for {', '.join(missing)}"
        return {"expand": False, "gaps": gaps, "trace": [_ev("sufficiency", label, t["ms"], "ok" if not missing else "warn", missing=missing)]}

    def expand_node(state: State) -> State:
        plan = state["plan"]
        filters = dict(state.get("filters") or {})
        it = state.get("iteration", 0) + 1
        changes = []
        if filters.get("sections"):
            filters["sections"] = None
            changes.append("searched all 10-K sections")
        elif filters.get("years"):
            filters["years"] = None
            changes.append("searched all ingested fiscal years")
        query = state.get("retrieval_query") or state["question"]
        if plan.metrics:
            extra = " ".join(REPORTED[m].label if m in REPORTED else DERIVED[m].label if m in DERIVED else m for m in plan.metrics)
            if extra.lower() not in query.lower():
                query = f"{query} {extra}"
                changes.append("added metric terms to query")
        return {"filters": filters or {"years": None, "sections": None}, "retrieval_query": query, "iteration": it,
                "trace": [_ev("expand", "Query expanded: " + ("; ".join(changes) or "relaxed filters"), 0, "ok", iteration=it)]}

    def after_sufficiency(state: State) -> str:
        return "expand" if state.get("expand") else "synthesize"

    # ------------------------------------------------------------------ (3) synthesis & verification
    def synthesize_node(state: State) -> State:
        plan = state["plan"]
        ev: EvidenceSet = state["ev"]
        gaps = state.get("gaps", [])
        repair = state.get("repair_attempts", 0) > 0
        with _timer() as t:
            mode = "template"
            draft = ""
            err = None
            text_only = not cfg.use_xbrl  # baselines answer whatever they retrieved, with no scope routing
            use_llm = not ctx.llm.offline and not ev.is_empty() and (text_only or plan.query_type != QueryType.OUT_OF_SCOPE)
            if use_llm:
                ev_text = synthesis.render_evidence(ev, names)
                user = (
                    synthesis.build_repair_prompt(state["question"], plan, ev_text, state.get("draft", ""), state.get("repair_issues", []))
                    if repair else synthesis.build_user_prompt(state["question"], plan, ev_text, gaps)
                )
                try:
                    resp = ctx.llm.complete(synthesis.SYSTEM_PROMPT, user, max_tokens=ctx.settings.llm_max_tokens)
                    ctx.tracker.record_llm(resp)
                    draft, mode = resp.text.strip(), "llm"
                except LLMError as exc:
                    err = str(exc)
            if not draft and text_only:
                draft, mode = extractive_answer(state["question"], plan, ev, names), "extractive"
            if not draft:
                draft = synthesis.template_answer(state["question"], plan, state.get("results", []), ev, names, gaps, state.get("period_notes", []))
        how = {
            "llm": " with LLM",
            "extractive": " by extractive reading of retrieved passages (no LLM, no calculations)",
            "template": " from verified evidence (deterministic template)",
        }[mode]
        label = ("Repaired answer" if repair else "Synthesized answer") + how
        detail: dict[str, Any] = {"mode": mode, "evidence": {"facts": len(ev.facts), "calculations": len(ev.calcs), "passages": len(ev.passages)}}
        if err:
            detail["llm_error"] = err
        return {"draft": draft, "synth_mode": mode, "trace": [_ev("synthesize", label, t["ms"], "warn" if err else "ok", **detail)]}

    def verify_node(state: State) -> State:
        ev: EvidenceSet = state["ev"]
        with _timer() as t:
            rep = ctx.auditor.audit(state["draft"], ev.facts, ev.calcs, ev.passages, state["plan"], state["question"])
            if state.get("gaps") and rep.verdict == Verdict.VERIFIED:
                rep.verdict = Verdict.PARTIALLY_VERIFIED
                rep.notes.append("Part of the question could not be answered from the available evidence.")
            if cfg.use_xbrl and (state["plan"].query_type == QueryType.OUT_OF_SCOPE or (ev.is_empty() and state.get("gaps"))):
                rep.verdict = Verdict.INSUFFICIENT_EVIDENCE
        label = (
            f"Verified {rep.citations_valid}/{rep.citations_total} citations · {rep.numbers_supported}/{rep.numbers_total} numbers · "
            f"recomputed {rep.recomputed_calculations} calculation{'s' * (rep.recomputed_calculations != 1)} → {rep.verdict.value.replace('_', ' ')}"
        )
        status = {"verified": "ok", "partially_verified": "warn", "insufficient_evidence": "warn", "failed": "error"}[rep.verdict.value]
        issues = [f"unsupported number {n}" for n in rep.unsupported_numbers] + [f"invalid citation {c}" for c in rep.invalid_citations] + rep.period_issues
        return {"verification": rep, "repair_issues": issues, "trace": [_ev("verify", label, t["ms"], status, unsupported_numbers=rep.unsupported_numbers, invalid_citations=rep.invalid_citations, conflicts=rep.conflicts[:5])]}

    def after_verify(state: State) -> str:
        rep: VerificationReport = state["verification"]
        if not cfg.enforce_verification or rep.verdict != Verdict.FAILED:
            return "finalize"
        if state.get("synth_mode") == "llm" and state.get("repair_attempts", 0) < 1:
            return "repair"
        return "fallback"

    def repair_node(state: State) -> State:
        return {"repair_attempts": state.get("repair_attempts", 0) + 1,
                "trace": [_ev("repair", "Verification failed — asking the model to repair the draft", 0, "warn", issues=state.get("repair_issues", []))]}

    def fallback_node(state: State) -> State:
        """Self-correction of last resort: replace an unverifiable draft with the deterministic answer."""
        ev: EvidenceSet = state["ev"]
        plan = state["plan"]
        draft = synthesis.template_answer(state["question"], plan, state.get("results", []), ev, names, state.get("gaps", []), state.get("period_notes", []))
        rep = ctx.auditor.audit(draft, ev.facts, ev.calcs, ev.passages, plan, state["question"])
        rep.notes.append("The model-written draft failed verification twice and was replaced by the deterministic evidence-based answer.")
        return {"draft": draft, "synth_mode": "template", "verification": rep,
                "trace": [_ev("fallback", f"Replaced unverifiable draft with deterministic answer → {rep.verdict.value.replace('_', ' ')}", 0, "warn")]}

    g = StateGraph(State)
    g.add_node("plan", plan_node)
    g.add_node("financials", financials_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("sufficiency", sufficiency_node)
    g.add_node("expand", expand_node)
    g.add_node("synthesize", synthesize_node)
    g.add_node("verify", verify_node)
    g.add_node("repair", repair_node)
    g.add_node("fallback", fallback_node)
    g.add_edge(START, "plan")
    g.add_edge("plan", "financials")
    g.add_edge("financials", "retrieve")
    g.add_edge("retrieve", "sufficiency")
    g.add_conditional_edges("sufficiency", after_sufficiency, {"expand": "expand", "synthesize": "synthesize"})
    g.add_edge("expand", "retrieve")
    g.add_edge("synthesize", "verify")
    g.add_conditional_edges("verify", after_verify, {"finalize": END, "repair": "repair", "fallback": "fallback"})
    g.add_edge("repair", "synthesize")
    g.add_edge("fallback", END)
    return g.compile(checkpointer=checkpointer)


_CHECKPOINTER = InMemorySaver()


def default_checkpointer() -> InMemorySaver:
    return _CHECKPOINTER
