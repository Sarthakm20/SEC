"""Discover annual (10-K) filings for a company from the EDGAR submissions API."""

from __future__ import annotations

from typing import Any

from app.models import Company, Filing


def fiscal_year_by_accession(company_facts: dict[str, Any]) -> dict[str, int]:
    """Map 10-K accession -> its fiscal-year focus (`fy`).

    In the companyfacts API, `fy` is a property of the *filing* (DocumentFiscalYearFocus), so every
    fact tagged with a given accession carries that filing's fiscal year, including prior-year
    comparatives. We use it to label each filing's own reporting period.
    """
    out: dict[str, int] = {}
    for taxonomy in company_facts.get("facts", {}).values():
        for concept in taxonomy.values():
            for rows in concept.get("units", {}).values():
                for r in rows:
                    if r.get("form") in ("10-K", "10-K/A") and r.get("fy") and r.get("accn"):
                        out.setdefault(r["accn"], int(r["fy"]))
    return out


def list_annual_filings(
    company: Company,
    submissions: dict[str, Any],
    fy_by_accn: dict[str, int] | None = None,
    include_amendments: bool = False,
) -> list[Filing]:
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    wanted = {"10-K", "10-K/A"} if include_amendments else {"10-K"}
    filings: list[Filing] = []
    for i, form in enumerate(forms):
        if form not in wanted:
            continue
        accn = recent["accessionNumber"][i]
        report_date = recent["reportDate"][i]
        fy = (fy_by_accn or {}).get(accn) or int(report_date[:4])
        filings.append(
            Filing(
                accession=accn,
                cik=company.cik,
                ticker=company.ticker,
                form=form,
                filing_date=recent["filingDate"][i],
                report_date=report_date,
                fiscal_year=fy,
                primary_document=recent["primaryDocument"][i],
            )
        )
    filings.sort(key=lambda f: f.report_date, reverse=True)
    return filings
