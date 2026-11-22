"""Discover annual (10-K) filings for a company from the EDGAR submissions API."""

from __future__ import annotations

from collections.abc import Callable
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
    fetch_page: Callable[[str], dict[str, Any]] | None = None,
    years: list[int] | None = None,
) -> list[Filing]:
    """10-K filings, newest first.

    `filings.recent` holds only the latest ~1,000 filings. Frequent filers (banks issuing notes, companies
    with many Form 4s) push older 10-Ks onto paginated pages listed in `filings.files`; when `fetch_page`
    is given, those pages are read until every requested fiscal year is found (all pages if `years` is None).
    """
    wanted_forms = {"10-K", "10-K/A"} if include_amendments else {"10-K"}
    by_accn: dict[str, Filing] = {}

    def collect(block: dict[str, Any]) -> None:
        for i, form in enumerate(block.get("form", [])):
            if form not in wanted_forms:
                continue
            accn = block["accessionNumber"][i]
            report_date = block["reportDate"][i]
            if not report_date:
                continue
            fy = (fy_by_accn or {}).get(accn) or int(report_date[:4])
            by_accn.setdefault(accn, Filing(
                accession=accn,
                cik=company.cik,
                ticker=company.ticker,
                form=form,
                filing_date=block["filingDate"][i],
                report_date=report_date,
                fiscal_year=fy,
                primary_document=block["primaryDocument"][i],
            ))

    def missing() -> bool:
        have = {f.fiscal_year for f in by_accn.values()}
        return years is None or not set(years) <= have

    filings_root = submissions.get("filings", {})
    collect(filings_root.get("recent", {}))
    if fetch_page is not None:
        for page in filings_root.get("files", []):
            if not missing():
                break
            collect(fetch_page(page["name"]))
    return sorted(by_accn.values(), key=lambda f: f.report_date, reverse=True)
