"""Normalize SEC companyfacts XBRL into annual, de-duplicated, provenance-rich facts.

Key normalization rules
  * Only 10-K facts; annual duration facts (350–380 days) or instants at a fiscal year end.
  * `fy` in companyfacts is the *filing's* fiscal year, not the fact's: each 10-K re-reports prior
    years as comparatives. A fact's fiscal year is the `fy` of the filing whose own reporting period
    ends on the fact's end date.
  * The same (concept, unit, period) appears in up to three filings. The canonical source is the
    filing for that fiscal year (the original report). If a later filing reports a different value
    (restatement / recast), a conflict is recorded and surfaced by the verification layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.ingest.html_parser import ParsedDocument
from app.models import Company, Fact, FactLocation, Filing

ANNUAL_MIN_DAYS = 350
ANNUAL_MAX_DAYS = 380


@dataclass
class FactConflict:
    ticker: str
    concept: str
    unit: str
    start: str | None
    end: str
    values: list[dict[str, Any]]  # [{accession, value, filed}]

    def describe(self) -> str:
        vals = ", ".join(f"{v['value']} ({v['accession']}, filed {v['filed']})" for v in self.values)
        return f"{self.ticker} {self.concept} period ending {self.end} reported with different values: {vals}"


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def fact_id(ticker: str, concept: str, unit: str, start: str | None, end: str) -> str:
    return f"{ticker}|{concept}|{unit}|{start or ''}|{end}"


def _period_end_by_accession(company_facts: dict[str, Any]) -> dict[str, str]:
    """Each 10-K's own fiscal-period end = latest annual duration end among its facts."""
    out: dict[str, str] = {}
    for taxonomy in company_facts.get("facts", {}).values():
        for concept in taxonomy.values():
            for rows in concept.get("units", {}).values():
                for r in rows:
                    if r.get("form") not in ("10-K", "10-K/A") or not r.get("start"):
                        continue
                    if not (ANNUAL_MIN_DAYS <= _days(r["start"], r["end"]) <= ANNUAL_MAX_DAYS):
                        continue
                    accn = r["accn"]
                    if r["end"] > out.get(accn, ""):
                        out[accn] = r["end"]
    return out


def normalize_company_facts(
    company: Company,
    company_facts: dict[str, Any],
    filings: list[Filing],
    taxonomies: tuple[str, ...] = ("us-gaap", "dei"),
) -> tuple[list[Fact], list[FactConflict]]:
    period_end_by_accn = _period_end_by_accession(company_facts)
    fy_by_accn: dict[str, int] = {}
    for taxonomy in company_facts.get("facts", {}).values():
        for concept in taxonomy.values():
            for rows in concept.get("units", {}).values():
                for r in rows:
                    if r.get("form") in ("10-K", "10-K/A") and r.get("fy"):
                        fy_by_accn.setdefault(r["accn"], int(r["fy"]))
    # fiscal year label for each fiscal-year-end date
    fy_by_end: dict[str, int] = {}
    for accn, end in period_end_by_accn.items():
        if accn in fy_by_accn:
            fy_by_end.setdefault(end, fy_by_accn[accn])
    for f in filings:
        fy_by_end.setdefault(f.report_date, f.fiscal_year)
    filing_by_accn = {f.accession: f for f in filings}

    facts: list[Fact] = []
    conflicts: list[FactConflict] = []
    for tax_name in taxonomies:
        taxonomy = company_facts.get("facts", {}).get(tax_name, {})
        for concept_name, concept in taxonomy.items():
            label = concept.get("label") or concept_name
            for unit, rows in concept.get("units", {}).items():
                grouped: dict[tuple[str | None, str], list[dict[str, Any]]] = {}
                for r in rows:
                    if r.get("form") not in ("10-K", "10-K/A"):
                        continue
                    end = r["end"]
                    start = r.get("start")
                    if end not in fy_by_end:
                        continue  # not a fiscal-year-end date (e.g. a mid-year instant)
                    if start is not None and not (ANNUAL_MIN_DAYS <= _days(start, end) <= ANNUAL_MAX_DAYS):
                        continue
                    grouped.setdefault((start, end), []).append(r)
                for (start, end), rs in grouped.items():
                    fy = fy_by_end[end]
                    # canonical = original filing for that fiscal year, else earliest filed
                    rs_sorted = sorted(rs, key=lambda r: (period_end_by_accn.get(r["accn"]) != end, r["filed"]))
                    canon = rs_sorted[0]
                    distinct = {Decimal(str(r["val"])) for r in rs}
                    if len(distinct) > 1:
                        seen: dict[str, dict[str, Any]] = {}
                        for r in rs_sorted:
                            seen.setdefault(r["accn"], {"accession": r["accn"], "value": str(r["val"]), "filed": r["filed"]})
                        conflicts.append(
                            FactConflict(company.ticker, f"{tax_name}:{concept_name}", unit, start, end, list(seen.values()))
                        )
                    filing = filing_by_accn.get(canon["accn"])
                    src = filing.url if filing else (
                        f"https://www.sec.gov/Archives/edgar/data/{company.cik}/{canon['accn'].replace('-', '')}/"
                    )
                    concept_q = f"{tax_name}:{concept_name}"
                    facts.append(
                        Fact(
                            id=fact_id(company.ticker, concept_q, unit, start, end),
                            ticker=company.ticker,
                            cik=company.cik,
                            concept=concept_q,
                            label=label,
                            value=str(Decimal(str(canon["val"]))),
                            unit=unit,
                            period_type="duration" if start else "instant",
                            start=start,
                            end=end,
                            fiscal_year=fy,
                            fiscal_period="FY",
                            accession=canon["accn"],
                            form=canon["form"],
                            filed=canon["filed"],
                            source_url=src,
                        )
                    )
    return facts, conflicts


# --------------------------------------------------------------------------- inline XBRL locator
def _ix_value(display: str, scale: int, sign: str | None) -> Decimal | None:
    cleaned = display.replace(",", "").replace("$", "").strip()
    if cleaned in ("", "—", "-", "–"):
        return Decimal(0)
    try:
        v = Decimal(cleaned) * (Decimal(10) ** scale)
    except Exception:
        return None
    return -v if sign == "-" else v


def locate_facts_in_document(facts: list[Fact], doc: ParsedDocument, accession: str) -> int:
    """Attach page / table / row provenance to facts reported in this filing. Returns #located.

    Only facts whose canonical accession is this filing are located. The rendered value is
    cross-checked against the API value; a mismatch leaves the fact un-located.
    """
    index: dict[tuple[str, str | None, str | None], list] = {}
    for ix in doc.ix_facts:
        ctx = doc.contexts.get(ix.context_ref)
        if ctx is None or ctx.dimensional:
            continue
        key = (ix.concept, ctx.start, ctx.end or ctx.instant)
        index.setdefault(key, []).append(ix)
    located = 0
    for fact in facts:
        if fact.accession != accession:
            continue
        cands = index.get((fact.concept, fact.start, fact.end))
        if not cands:
            continue
        expected = Decimal(fact.value)
        matching = [c for c in cands if _ix_value(c.display, c.scale, c.sign) == expected]
        if not matching:
            continue
        dense = [c for c in matching if c.table_fact_count >= 20]
        best = dense[0] if dense else max(matching, key=lambda c: c.table_fact_count)
        title = doc.blocks[best.table_block].table_title if best.table_block is not None else None
        fact.location = FactLocation(
            page=int(doc.page_label(best.page)) if (doc.page_label(best.page) or "").isdigit() else best.page,
            table_title=title,
            row_label=best.row_label,
            element_id=best.element_id,
            displayed_value=best.display,
        )
        located += 1
    return located
