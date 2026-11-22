"""Evaluation metrics (Recommendations §3.4)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal

from app.models import AnswerResponse, Chunk, ClaimStatus, Verdict
from app.verify.numbers import extract_numbers

USD_REL_TOL = Decimal("0.005")  # 0.5% relative (covers $X.XB rounding)
PCT_ABS_TOL = Decimal("0.15")  # 0.15 percentage points
RATIO_ABS_TOL = Decimal("0.02")


# ----------------------------------------------------------------------------- retrieval
def is_relevant(chunk: Chunk, rel: dict) -> bool:
    if rel.get("tickers") and chunk.ticker not in rel["tickers"]:
        return False
    if rel.get("fiscal_years") and chunk.fiscal_year not in rel["fiscal_years"]:
        return False
    if rel.get("sections") and chunk.section not in rel["sections"]:
        return False
    text = (chunk.text + " " + (chunk.subsection or "")).lower()
    if rel.get("keywords_all") and not all(_has(text, k) for k in rel["keywords_all"]):
        return False
    if rel.get("keywords_any") and not any(_has(text, k) for k in rel["keywords_any"]):
        return False
    return True


def _has(text: str, keyword: str) -> bool:
    """Substring match for stems ("competit"); whole-word match for short keywords ("AI" must not match "said")."""
    k = keyword.lower()
    if len(k) <= 3:
        return re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", text) is not None
    return k in text


def retrieval_metrics(ranked: list[Chunk], rel: dict, all_chunks: list[Chunk], k: int) -> dict:
    relevant_ids = {c.id for c in all_chunks if is_relevant(c, rel)}
    flags = [c.id in relevant_ids for c in ranked[:k]]
    hit = any(flags)
    first = next((i for i, f in enumerate(flags) if f), None)
    dcg = sum(1 / math.log2(i + 2) for i, f in enumerate(flags) if f)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(relevant_ids))))
    return {
        "relevant_in_corpus": len(relevant_ids),
        f"hit@{k}": float(hit),
        f"recall@{k}": (sum(flags) / min(k, len(relevant_ids))) if relevant_ids else 0.0,
        "mrr": (1 / (first + 1)) if first is not None else 0.0,
        f"ndcg@{k}": (dcg / ideal) if ideal else 0.0,
        f"precision@{k}": (sum(flags) / len(flags)) if flags else 0.0,
    }


# ----------------------------------------------------------------------------- answers
@dataclass
class NumberScore:
    found: bool
    rel_error: float | None


def _score_expected(answer: str, exp: dict) -> NumberScore:
    target = Decimal(str(exp["value"]))
    unit = exp["unit"]
    best: Decimal | None = None
    for m in extract_numbers(answer):
        if unit == "USD" and m.kind in ("usd", "plain"):
            for v in (m.value, m.value * Decimal(10) ** 6):
                err = abs(abs(v) - abs(target)) / abs(target) if target else abs(v)
                best = err if best is None or err < best else best
        elif unit == "USD/shares" and m.kind in ("usd", "ratio", "plain"):
            err = abs(abs(m.value) - abs(target)) / abs(target)
            best = err if best is None or err < best else best
        elif unit == "percent" and m.kind == "percent":
            err = abs(abs(m.value) - abs(target)) / max(abs(target), Decimal(1))
            if abs(abs(m.value) - abs(target)) <= PCT_ABS_TOL:
                err = Decimal(0)
            best = err if best is None or err < best else best
        elif unit == "ratio" and m.kind in ("ratio", "plain"):
            if abs(m.value - target) <= RATIO_ABS_TOL:
                best = Decimal(0)
            else:
                err = abs(m.value - target) / abs(target)
                best = err if best is None or err < best else best
    if best is None:
        return NumberScore(False, None)
    found = best <= USD_REL_TOL if unit in ("USD", "USD/shares") else best == 0 or best <= Decimal("0.005")
    return NumberScore(found, float(best))


def answer_metrics(resp: AnswerResponse, gold: dict, all_chunks: list[Chunk]) -> dict:
    out: dict = {}
    expected = gold.get("expected") or []
    abstained = resp.verification.verdict == Verdict.INSUFFICIENT_EVIDENCE or bool(
        re.search(r"can't answer|cannot answer|insufficient evidence|not available|no reported", resp.answer, re.I)
    ) and not any(_score_expected(resp.answer, e).found for e in expected)
    out["abstained"] = abstained
    if expected:
        scores = [_score_expected(resp.answer, e) for e in expected]
        out["numbers_expected"] = len(scores)
        out["numbers_found"] = sum(s.found for s in scores)
        out["exact_match"] = float(all(s.found for s in scores))
        errs = [s.rel_error for s in scores if s.rel_error is not None]
        out["mean_rel_error"] = (sum(errs) / len(errs)) if errs else None
    if gold.get("expect_entity"):
        out["entity_mentioned"] = float(gold["expect_entity"].lower() in resp.answer.lower())

    # citation quality
    cites = re.findall(r"\[([FCS]\d+)\]", resp.answer)
    ev_ids = {f.evidence_id for f in resp.facts} | {c.evidence_id for c in resp.calculations} | {p.evidence_id for p in resp.passages}
    fy = set(gold.get("fiscal_years") or [])
    tick = set(gold.get("tickers") or [])
    rel = gold.get("relevant")
    precise = 0
    for c in cites:
        if c not in ev_ids:
            continue
        if c.startswith("F"):
            f = next(f for f in resp.facts if f.evidence_id == c)
            ok = (not tick or f.ticker in tick) and (not fy or f.fiscal_year in fy or f.fiscal_year + 1 in fy)
        elif c.startswith("C"):
            k = next(k for k in resp.calculations if k.evidence_id == c)
            ok = (not tick or k.ticker in tick) and (not fy or k.fiscal_year in fy)
        else:
            p = next(p for p in resp.passages if p.evidence_id == c)
            ok = is_relevant(p.chunk, rel) if rel else (not tick or p.chunk.ticker in tick)
        precise += int(ok)
    out["citations"] = len(cites)
    out["citation_precision"] = (precise / len(cites)) if cites else None
    claims = [c for c in resp.verification.claims if c.numbers or c.status != ClaimStatus.INTERPRETATION or len(c.sentence) > 60]
    out["citation_coverage"] = (sum(1 for c in claims if c.citations) / len(claims)) if claims else None
    judged = [c for c in resp.verification.claims if c.citations or c.numbers]
    out["faithfulness"] = (
        sum(1 for c in judged if c.status != ClaimStatus.UNSUPPORTED and "weak support from cited passage" not in c.issues) / len(judged)
        if judged else None
    )
    if rel:
        cited_passages = [p for p in resp.passages if p.evidence_id in cites]
        out["cites_relevant_passage"] = float(any(is_relevant(p.chunk, rel) for p in cited_passages))

    # task success
    if not gold.get("answerable", True):
        out["task_success"] = float(abstained)
    elif expected and rel:
        out["task_success"] = float(out["exact_match"] == 1.0 and out.get("cites_relevant_passage", 0) == 1.0)
    elif expected:
        ok = out["exact_match"] == 1.0 and out.get("entity_mentioned", 1.0) == 1.0
        out["task_success"] = float(ok)
    elif rel:
        out["task_success"] = float(out.get("cites_relevant_passage", 0) == 1.0 and not abstained)
    out["verdict"] = resp.verification.verdict.value
    out["latency_ms"] = resp.latency_ms
    out["cost_usd"] = resp.usage.estimated_cost_usd
    out["input_tokens"] = resp.usage.input_tokens
    out["output_tokens"] = resp.usage.output_tokens
    return out
