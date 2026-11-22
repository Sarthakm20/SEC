"""Evidence auditor — deterministic verification of a synthesized answer (Recommendations §3.3).

An LLM checking another LLM is not independent proof, so every check here is programmatic:
  1. citation existence    — every [F#]/[C#]/[S#] must point to evidence actually provided
  2. numeric support       — every financial number in the answer must match a cited fact/calculation
                             (within displayed-precision tolerance) or appear in a cited passage
  3. recomputation         — every calculation record is re-evaluated from its stored inputs
  4. source-fact integrity — calculation inputs are re-read from the fact store and compared
  5. period validation     — fiscal years mentioned in a sentence must match its cited evidence
  6. conflict detection    — inputs restated in later filings are surfaced
  7. claim support         — narrative sentences must be supported by their cited passage
                             (lexical overlap and, when available, cross-encoder relevance)
  8. abstention            — answers that decline for lack of evidence are labelled as such
"""

from __future__ import annotations

import math
import re
from decimal import Decimal

from app.finance.engine import FinancialEngine, recompute
from app.models import (
    CalculationRecord,
    ClaimCheck,
    ClaimStatus,
    Fact,
    QueryPlan,
    RetrievedChunk,
    Verdict,
    VerificationReport,
)
from app.retrieval.bm25 import tokenize
from app.retrieval.reranker import Reranker
from app.verify.numbers import extract_numbers, matches, number_in_text

_CITE = re.compile(r"\[([FCS]\d+)\]")
_FY_MENTION = re.compile(r"\b(?:fy\s*|fiscal\s+(?:year\s+)?)(20\d\d)\b", re.I)
SYSTEM_NOTE = re.compile(r"^\s*(note|not available|limitations?)\s*:", re.I)  # system disclosures, not claims
ABSTAIN_MARKERS = re.compile(r"(cannot answer|can't answer|insufficient evidence|not (?:available|reported|contained) in|no (?:reported|evidence)|unable to (?:find|answer))", re.I)


_BOUNDARY = re.compile(r"[.!?][\"”')\]]*\s+(?=[A-Z(\"“])")
_ABBREV = re.compile(r"(?:^|\s)(?:Inc|Corp|Co|Ltd|LLC|No|Nos|vs|U\.S|e\.g|i\.e|Mr|Ms|Dr|St|Jr|Item|Note|[A-Z]|\d+[A-Z]?)\.$")


def split_sentences(text: str) -> list[str]:
    """Split per line, then on sentence boundaries that are not abbreviations ("Apple Inc.", "Item 1A.")."""
    out: list[str] = []
    for line in text.split("\n"):
        line = re.sub(r"^\s*[-•*]\s+", "", line).strip()
        if not line:
            continue
        start = 0
        for m in _BOUNDARY.finditer(line):
            head = line[start : m.start() + 1]
            if _ABBREV.search(head):
                continue
            out.append(line[start : m.end()].strip())
            start = m.end()
        out.append(line[start:].strip())
    return [s for s in out if len(s) > 2]


def _overlap(sentence: str, passage: str) -> float:
    s = {t for t in tokenize(re.sub(r"\[[FCS]\d+\]", "", sentence)) if not t.isdigit() and len(t) > 2}
    if not s:
        return 1.0
    p = set(tokenize(passage))
    return len(s & p) / len(s)


class EvidenceAuditor:
    def __init__(self, engine: FinancialEngine | None = None, reranker: Reranker | None = None, support_threshold: float = 0.35) -> None:
        self.engine = engine
        self.reranker = reranker
        self.support_threshold = support_threshold

    def audit(
        self,
        answer: str,
        facts: dict[str, Fact],
        calcs: dict[str, CalculationRecord],
        passages: dict[str, RetrievedChunk],
        plan: QueryPlan | None = None,
        question: str = "",
    ) -> VerificationReport:
        rep = VerificationReport(verdict=Verdict.VERIFIED)
        evidence_ids = set(facts) | set(calcs) | set(passages)

        # 3 + 4: calculations are recomputed and their inputs re-checked against the fact store
        for cid, rec in calcs.items():
            try:
                again = recompute(rec)
            except Exception as exc:  # pragma: no cover - defensive
                rep.conflicts.append(f"{cid}: recomputation failed ({exc})")
                continue
            if abs(again - Decimal(rec.result)) > Decimal("1e-12") * max(Decimal(1), abs(again)):
                rep.conflicts.append(f"{cid}: recomputed {again} ≠ recorded {rec.result}")
            else:
                rep.recomputed_calculations += 1
            if self.engine is not None:
                for inp in rec.inputs:
                    if not inp.fact_id:
                        continue
                    src = self._lookup_fact(inp.fact_id, rec.ticker)
                    if src is None:
                        rep.conflicts.append(f"{cid}: input {inp.name} references unknown fact {inp.fact_id}")
                    elif Decimal(src.value) != Decimal(inp.value):
                        rep.conflicts.append(f"{cid}: input {inp.name}={inp.value} differs from source fact {src.value}")
            for w in rec.warnings:
                if "restated" in w.lower() or "recast" in w.lower():
                    rep.conflicts.append(f"{cid}: {w}")
        if self.engine is not None:
            for fid, f in facts.items():
                c = self.engine.conflicts_for(f)
                if c:
                    rep.conflicts.append(f"{fid}: {c.describe()}")
        rep.conflicts = list(dict.fromkeys(rep.conflicts))

        # 1: citations
        cited = _CITE.findall(answer)
        rep.citations_total = len(cited)
        rep.invalid_citations = sorted({c for c in cited if c not in evidence_ids})
        rep.citations_valid = sum(1 for c in cited if c in evidence_ids)

        question_numbers = {n.raw for n in extract_numbers(question)}
        abstained = bool(ABSTAIN_MARKERS.search(answer))

        # 2, 5, 7: per-sentence checks
        for sent in split_sentences(answer):
            cites = _CITE.findall(sent)
            nums = [n for n in extract_numbers(sent) if n.raw not in question_numbers]
            check = ClaimCheck(sentence=sent, status=ClaimStatus.INTERPRETATION, citations=cites, numbers=[n.raw for n in nums])
            bad = [c for c in cites if c not in evidence_ids]
            if bad:
                check.issues.append(f"cites non-existent evidence {bad}")
            valid_cites = [c for c in cites if c in evidence_ids]

            matched_kinds: set[str] = set()
            for n in nums:
                rep.numbers_total += 1
                ok_kind = self._support_number(n, valid_cites, facts, calcs, passages)
                if ok_kind is None:
                    # allow numbers supported by *any* provided evidence but flag the missing citation
                    ok_kind = self._support_number(n, list(evidence_ids), facts, calcs, passages)
                    if ok_kind is not None:
                        check.issues.append(f"number {n.raw} matches evidence that the sentence does not cite")
                if ok_kind is None:
                    rep.unsupported_numbers.append(n.raw)
                    check.issues.append(f"number {n.raw} not found in any evidence")
                else:
                    rep.numbers_supported += 1
                    matched_kinds.add(ok_kind)

            # period validation: sentence says FY2024 but cites evidence from another year
            for y in {int(y) for y in _FY_MENTION.findall(sent)}:
                years = self._evidence_years(valid_cites, facts, calcs, passages)
                if years and y not in years:
                    msg = f"sentence mentions FY{y} but cited evidence covers FY{sorted(years)}"
                    check.issues.append(msg)
                    rep.period_issues.append(msg)

            if any(i.startswith("number") and "not found" in i for i in check.issues) or bad:
                check.status = ClaimStatus.UNSUPPORTED
            elif "calc" in matched_kinds:
                check.status = ClaimStatus.CALCULATED
            elif "fact" in matched_kinds:
                check.status = ClaimStatus.VERIFIED_FACT
            else:
                s_cites = [c for c in valid_cites if c in passages]
                if s_cites:
                    best = 0.0
                    for c in s_cites:
                        best = max(best, self._support(sent, passages[c].chunk.text))
                    check.support_score = round(best, 3)
                    if best < self.support_threshold:
                        check.issues.append("weak support from cited passage")
                elif nums:
                    check.status = ClaimStatus.VERIFIED_FACT if matched_kinds == {"passage"} else check.status
                elif len(sent) > 60 and not abstained and not sent.rstrip().endswith(":") and not SYSTEM_NOTE.match(sent):
                    check.issues.append("no citation")
            rep.claims.append(check)

        # verdict
        failed = bool(rep.invalid_citations or rep.unsupported_numbers or any("≠" in c or "differs" in c for c in rep.conflicts))
        has_evidence = bool(evidence_ids)
        if abstained and (not has_evidence or rep.numbers_total == 0):
            rep.verdict = Verdict.INSUFFICIENT_EVIDENCE
        elif failed:
            rep.verdict = Verdict.FAILED
        elif rep.period_issues or any(c.issues for c in rep.claims) or rep.citations_total == 0:
            rep.verdict = Verdict.PARTIALLY_VERIFIED
        else:
            rep.verdict = Verdict.VERIFIED
        if rep.conflicts and rep.verdict == Verdict.VERIFIED:
            rep.notes.append("Some inputs were restated in later filings; the original reported values were used.")
        return rep

    # ------------------------------------------------------------------ helpers
    def _lookup_fact(self, fact_id: str, ticker: str) -> Fact | None:
        assert self.engine is not None
        return self.engine.fact_by_id(fact_id.split("|")[0] or ticker, fact_id)

    def _support_number(self, n, cites, facts, calcs, passages) -> str | None:
        for c in cites:
            if c in facts and matches(n, Decimal(facts[c].value), facts[c].unit):
                return "fact"
            if c in calcs and matches(n, Decimal(calcs[c].result), calcs[c].result_unit):
                return "calc"
        for c in cites:
            if c in passages and number_in_text(n, passages[c].chunk.text):
                return "passage"
        return None

    @staticmethod
    def _evidence_years(cites, facts, calcs, passages) -> set[int]:
        years: set[int] = set()
        for c in cites:
            if c in facts:
                years.add(facts[c].fiscal_year)
            elif c in calcs:
                years.update(i.fiscal_year for i in calcs[c].inputs)
                years.add(calcs[c].fiscal_year)
            elif c in passages:
                fy = passages[c].chunk.fiscal_year
                years.update({fy, fy - 1, fy - 2})  # a 10-K discusses its year plus two comparative years
        return years

    def _support(self, sentence: str, passage: str) -> float:
        lexical = _overlap(sentence, passage)
        if self.reranker is None:
            return lexical
        try:
            logit = self.reranker.score(re.sub(r"\[[FCS]\d+\]", "", sentence), [passage])[0]
            semantic = 1 / (1 + math.exp(-logit))
        except Exception:
            return lexical
        return max(lexical, semantic)
