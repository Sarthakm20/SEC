"""Company registry and entity resolution (ticker / name aliases -> canonical ticker)."""

from __future__ import annotations

import re

from app.models import Company

# Initial scope per Recommendations §9.1. Additional companies can be ingested by ticker; their
# CIK is resolved from SEC's company_tickers.json at ingestion time.
SEED_COMPANIES: dict[str, Company] = {
    "AAPL": Company(ticker="AAPL", cik=320193, name="Apple Inc."),
    "MSFT": Company(ticker="MSFT", cik=789019, name="Microsoft Corporation"),
    "NVDA": Company(ticker="NVDA", cik=1045810, name="NVIDIA Corporation"),
}

SEED_ALIASES: dict[str, list[str]] = {
    "AAPL": ["apple", "apple inc", "aapl"],
    "MSFT": ["microsoft", "microsoft corp", "microsoft corporation", "msft"],
    "NVDA": ["nvidia", "nvidia corp", "nvidia corporation", "nvda"],
    # Common names differ from SEC's registrant names ("Amazon.com, Inc.", "Meta Platforms, Inc.", ...).
    # Aliases only apply once a company is ingested. Tesla and Netflix are deliberately not ingested:
    # they are the "company not in the corpus" abstention cases in the gold sets.
    "AMZN": ["amazon", "amazon.com", "amzn"],
    "GOOGL": ["alphabet", "google", "googl"],
    "META": ["meta", "meta platforms", "facebook"],
    "JPM": ["jpmorgan", "jp morgan", "jpmorgan chase", "jpm"],
    "WMT": ["walmart", "wal-mart", "wmt"],
    "COST": ["costco", "costco wholesale"],
    "ORCL": ["oracle", "orcl"],
}

_CORP_SUFFIX = re.compile(r"\b(inc|corp|corporation|co|company|ltd|plc|holdings)\.?$", re.I)


def aliases_for(company: Company) -> list[str]:
    names = set(SEED_ALIASES.get(company.ticker, []))
    names.add(company.ticker.lower())
    base = company.name.lower().replace(",", "").strip()
    names.add(base)
    stripped = _CORP_SUFFIX.sub("", base).strip()
    if len(stripped) >= 3:
        names.add(stripped)
    return sorted(names, key=len, reverse=True)


def resolve_tickers(text: str, companies: list[Company]) -> list[str]:
    """Return tickers mentioned in text, in order of first appearance."""
    lowered = text.lower()
    found: list[tuple[int, str]] = []
    for company in companies:
        best: int | None = None
        for alias in aliases_for(company):
            # tickers must match as upper-case whole words to avoid e.g. "now" style collisions
            if alias == company.ticker.lower():
                m = re.search(rf"\b{re.escape(company.ticker)}\b", text)
            else:
                m = re.search(rf"\b{re.escape(alias)}(?:'s|’s)?\b", lowered)
            if m and (best is None or m.start() < best):
                best = m.start()
        if best is not None:
            found.append((best, company.ticker))
    return [t for _, t in sorted(found)]
