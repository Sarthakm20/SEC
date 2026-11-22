"""Filing discovery must look past the 'recent' window: frequent filers (JPM, META) push older 10-Ks into
the paginated `filings.files` pages of the EDGAR submissions API."""

from app.models import Company
from app.sec.filings import list_annual_filings

CO = Company(ticker="BIG", cik=1, name="Big Filer Co")


def _block(rows):
    keys = ["accessionNumber", "form", "filingDate", "reportDate", "primaryDocument"]
    return {k: [r[i] for r in rows] for i, k in enumerate(keys)}


RECENT = _block([
    ("0001-26-000001", "10-K", "2026-02-15", "2025-12-31", "big-2025.htm"),
    ("0001-26-000002", "424B2", "2026-03-01", "", "note.htm"),
])
OLDER = _block([
    ("0001-25-000009", "10-K", "2025-02-14", "2024-12-31", "big-2024.htm"),
    ("0001-24-000009", "10-K", "2024-02-16", "2023-12-31", "big-2023.htm"),
])
SUBS = {"filings": {"recent": RECENT, "files": [{"name": "CIK0000000001-submissions-001.json", "filingFrom": "2023-01-01", "filingTo": "2025-12-31"}]}}


def test_older_10ks_are_found_on_paginated_pages():
    fetched = []

    def fetch_page(name):
        fetched.append(name)
        return OLDER

    filings = list_annual_filings(CO, SUBS, fetch_page=fetch_page)
    assert [f.fiscal_year for f in filings] == [2025, 2024, 2023]
    assert fetched == ["CIK0000000001-submissions-001.json"]


def test_pages_are_skipped_when_recent_window_covers_wanted_years():
    def fetch_page(name):  # pragma: no cover - must not be called
        raise AssertionError("should not fetch")

    filings = list_annual_filings(CO, SUBS, fetch_page=fetch_page, years=[2025])
    assert [f.fiscal_year for f in filings] == [2025]


def test_without_fetcher_only_recent_is_used():
    assert [f.fiscal_year for f in list_annual_filings(CO, SUBS)] == [2025]
