"""Extractive reader — the no-LLM reader for baseline experiments A–C.

Baselines A–C answer only from retrieved 10-K passages (no XBRL, no calculation engine). Without an LLM,
this reader stands in for "→ LLM": it quotes what the filing text says and never computes anything.

  * numeric questions: find the table row whose label matches the requested metric and read the cell
    under the requested fiscal-year column; otherwise quote the best sentence that states a figure
  * narrative questions: quote the most relevant sentence from each top passage
  * abstains only when nothing relevant was retrieved (naive RAG has no planner-level scope checks)

It is deliberately honest about its limits: a ratio or growth rate is reported only if the filing text
states it, and figures keep the table's own scale ("in millions").
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.graph.evidence import EvidenceSet
from app.graph.planner import _SYNONYMS
from app.models import SECTION_TITLES, QueryPlan, RetrievedChunk
from app.retrieval.bm25 import tokenize

_YEAR = re.compile(r"\b(19|20)\d\d\b")
_NUMBER = re.compile(r"\$?\(?\d[\d,]*(?:\.\d+)?\)?%?")
_SCALE_NOTE = re.compile(r"\((?:dollars\s+)?in\s+(millions|thousands|billions)[^)]*\)|in\s+(millions|thousands|billions)", re.I)
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def _metric_phrases(metrics: list[str]) -> list[str]:
    keys = set(metrics) | {m.removesuffix("_growth") for m in metrics}
    return [p for p, k in _SYNONYMS if k in keys]


@dataclass
class _Unit:
    eid: str
    rc: RetrievedChunk
    text: str
    score: float
    cell: str | None = None  # value read from a table cell
    cell_year: int | None = None
    row_label: str | None = None
    scale: str | None = None


def _table_units(eid: str, rc: RetrievedChunk, phrases: list[str], q_tokens: set[str], years: list[int], rank_bonus: float) -> list[_Unit]:
    lines = rc.chunk.text.split("\n")
    rows = [[c.strip() for c in ln.split("|")] for ln in lines if "|" in ln]
    if not rows:
        return []
    title = next((ln for ln in lines if "|" not in ln), "")
    scale_m = _SCALE_NOTE.search(rc.chunk.text)
    scale = (scale_m.group(1) or scale_m.group(2)).lower() if scale_m else None
    header = next((r for r in rows if sum(bool(_YEAR.search(c)) for c in r) >= 1), None)
    header_years: list[int | None] = []
    if header:
        for c in header:
            m = _YEAR.search(c)
            header_years.append(int(m.group(0)) if m else None)
    out: list[_Unit] = []
    for r in rows:
        if r is header or len(r) < 2:
            continue
        label, values = r[0], r[1:]
        lab = label.lower().strip(" :")
        # closeness of the row label to the metric: "Total net sales" (1.0) beats
        # "Portion of total net sales that was included in deferred revenue" (~0.25)
        hit = max((len(p) / max(len(lab), 1) + (0.5 if lab.startswith(p) or lab.startswith("total " + p) else 0) for p in phrases if p in lab), default=0.0)
        overlap = len(q_tokens & set(tokenize(label)))
        if not hit and overlap == 0:
            continue
        # align value cells with the header's year columns (right-aligned when the header lacks a label cell)
        aligned: list[tuple[int | None, str]] = []
        if header_years:
            hy = header_years[-len(values):] if len(header_years) >= len(values) else header_years + [None] * (len(values) - len(header_years))
            aligned = list(zip(hy, values))
        target = None
        for y in sorted(years, reverse=True) or [None]:
            target = next(((yy, v) for yy, v in aligned if yy == y and _NUMBER.search(v)), None) if y else None
            if target:
                break
        if target is None and aligned:
            target = next(((yy, v) for yy, v in aligned if yy is not None and _NUMBER.search(v)), None)
        score = 3.0 * min(hit, 1.5) + 0.5 * overlap + rank_bonus + (1.5 if target and target[0] in years else 0)
        out.append(_Unit(eid, rc, f"{label} | " + " | ".join(values), score, cell=target[1] if target else None,
                         cell_year=target[0] if target else None, row_label=label, scale=scale))
        if title and not out[-1].text.startswith(title):
            out[-1].text = f"{title}: {out[-1].text}"
    return out


def _sentence_units(eid: str, rc: RetrievedChunk, phrases: list[str], q_tokens: set[str], years: list[int], numeric: bool, rank_bonus: float) -> list[_Unit]:
    out = []
    for s in _SENT.split(rc.chunk.text):
        s = s.strip()
        if not 30 <= len(s) <= 600:
            continue
        low = s.lower()
        overlap = len(q_tokens & set(tokenize(s)))
        hit = any(p in low for p in phrases)
        has_num = bool(re.search(r"\$\s?\d|\d+(\.\d+)?\s?(%|percent|billion|million)", s))
        yr = any(str(y) in s for y in years)
        score = overlap + 2.0 * hit + rank_bonus + (1.0 if yr else 0) + (1.5 if (numeric and has_num) else 0)
        out.append(_Unit(eid, rc, s, score))
    return out


def extractive_answer(question: str, plan: QueryPlan, ev: EvidenceSet, names: dict[str, str]) -> str:
    if not ev.passages:
        return "I can't answer that from the retrieved passages: no relevant 10-K text was found."
    numeric = bool(plan.metrics)
    phrases = _metric_phrases(plan.metrics)
    q_tokens = {t for t in tokenize(question) if len(t) > 2 and not t.isdigit()}
    years = plan.fiscal_years
    by_ticker: dict[str, list[tuple[str, RetrievedChunk]]] = {}
    for eid, rc in ev.passages.items():
        by_ticker.setdefault(rc.chunk.ticker, []).append((eid, rc))

    lines: list[str] = []
    best_overall = 0.0
    for ticker in plan.tickers or list(by_ticker):
        items = by_ticker.get(ticker, [])
        name = names.get(ticker, ticker)
        units: list[_Unit] = []
        for rank, (eid, rc) in enumerate(items):
            bonus = 1.0 / (1 + rank)
            if rc.chunk.kind == "table":
                units += _table_units(eid, rc, phrases, q_tokens, years, bonus)
            else:
                units += _sentence_units(eid, rc, phrases, q_tokens, years, numeric, bonus)
        if not units:
            lines.append(f"{name}: no relevant passage was retrieved.")
            continue
        units.sort(key=lambda u: -u.score)
        best_overall = max(best_overall, units[0].score)
        if numeric:
            cell = next((u for u in units if u.cell), None)
            if cell and cell.score >= units[0].score - 1.0:
                where = _where(cell.rc)
                scale = f" ({cell.scale}, as presented in the filing)" if cell.scale else ""
                fy = f" for {cell.cell_year}" if cell.cell_year else ""
                lines.append(f"{name}: {cell.row_label}{fy} was {cell.cell}{scale}, per the {where} [{cell.eid}].")
                others = [u for u in units if u is not cell and u.cell is None][:1]
                for u in others:
                    lines.append(f"- \"{u.text}\" [{u.eid}]")
                continue
            top = [u for u in units if re.search(r"\d", u.text)][:2] or units[:1]
        else:
            seen: set[str] = set()
            top = []
            for u in units:
                if u.eid not in seen:
                    top.append(u)
                    seen.add(u.eid)
                if len(top) == 3:
                    break
        lines.append(f"{name} ({_where(top[0].rc)}):")
        for u in top:
            lines.append(f"- \"{u.text}\" [{u.eid}]")

    if best_overall < 1.5:
        return "I can't answer that from the retrieved passages: none of them address the question."
    return "\n".join(lines)


def _where(rc: RetrievedChunk) -> str:
    ch = rc.chunk
    page = f", p. {ch.page_start}" if ch.page_start else ""
    return f"FY{ch.fiscal_year} 10-K, {SECTION_TITLES.get(ch.section, ch.section_title)}{page}"
