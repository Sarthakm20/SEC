"""Dual-path ingestion: SEC XBRL (numbers) + 10-K HTML (narrative), per company."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.companies import SEED_COMPANIES
from app.db import repo
from app.ingest.chunker import chunk_document, index_text
from app.ingest.html_parser import parse_10k_html
from app.ingest.xbrl import locate_facts_in_document, normalize_company_facts
from app.models import Company
from app.retrieval.embeddings import Embedder
from app.retrieval.vector_store import VectorStore
from app.sec.client import EdgarClient
from app.sec.filings import fiscal_year_by_accession, list_annual_filings

log = logging.getLogger(__name__)


@dataclass
class IngestSummary:
    ticker: str
    name: str
    facts: int = 0
    conflicts: int = 0
    filings: list[dict] = field(default_factory=list)
    seconds: float = 0.0


def resolve_company(ticker: str, client: EdgarClient) -> Company:
    t = ticker.upper()
    if t in SEED_COMPANIES:
        return SEED_COMPANIES[t].model_copy()
    for row in client.company_tickers().values():
        if row["ticker"].upper() == t:
            return Company(ticker=t, cik=int(row["cik_str"]), name=row["title"])
    raise ValueError(f"Unknown ticker {ticker}")


def ingest_company(
    ticker: str,
    fiscal_years: list[int],
    client: EdgarClient,
    embedder: Embedder,
    store: VectorStore,
    progress: Callable[[str], None] = lambda m: log.info(m),
    chunk_target_tokens: int = 350,
    chunk_overlap_tokens: int = 50,
) -> IngestSummary:
    t0 = time.perf_counter()
    company = resolve_company(ticker, client)
    subs = client.submissions(company.cik, use_cache=False)
    if ticker.upper() not in SEED_COMPANIES:  # keep curated display names for seeded companies
        company.name = subs.get("name") or company.name
    company.fiscal_year_end = subs.get("fiscalYearEnd")
    progress(f"[{company.ticker}] {company.name} (CIK {company.cik}), fiscal year end {company.fiscal_year_end}")

    facts_json = client.company_facts(company.cik, use_cache=False)
    filings = list_annual_filings(
        company, subs, fiscal_year_by_accession(facts_json),
        # older pages of the submissions index are immutable history, so the disk cache is safe
        fetch_page=lambda name: client.fetch_json(f"{client.DATA_BASE}/submissions/{name}"),
        years=list(fiscal_years),
    )
    facts, conflicts = normalize_company_facts(company, facts_json, filings)
    progress(f"[{company.ticker}] XBRL: {len(facts)} annual facts, {len(conflicts)} restatement conflicts")

    summary = IngestSummary(ticker=company.ticker, name=company.name, facts=len(facts), conflicts=len(conflicts))
    selected = [f for f in filings if f.fiscal_year in set(fiscal_years)]
    missing = sorted(set(fiscal_years) - {f.fiscal_year for f in selected})
    if missing:
        progress(f"[{company.ticker}] no 10-K found for FY {missing}")

    repo.upsert_company(company)
    for filing in selected:
        progress(f"[{company.ticker}] FY{filing.fiscal_year} 10-K {filing.accession} -> {filing.url}")
        html = client.filing_document(filing.url)
        doc = parse_10k_html(html)
        located = locate_facts_in_document(facts, doc, filing.accession)
        chunks = chunk_document(doc, filing, company, chunk_target_tokens, chunk_overlap_tokens)
        sections = {
            k: {
                "title": s.title,
                "page_start": doc.page_label(doc.blocks[s.start_block].page) if s.start_block < len(doc.blocks) else None,
                "page_end": doc.page_label(doc.blocks[s.end_block - 1].page) if 0 < s.end_block <= len(doc.blocks) else None,
                "chunks": sum(1 for c in chunks if c.section == k),
            }
            for k, s in doc.sections.items()
        }
        repo.replace_chunks(filing.accession, chunks)
        t1 = time.perf_counter()
        vectors = embedder.embed_documents([index_text(c) for c in chunks])
        store.delete_accession(filing.accession)
        store.upsert(chunks, vectors)
        flagged = sum(1 for c in chunks if c.injection_flags)
        progress(
            f"[{company.ticker}] FY{filing.fiscal_year}: sections={list(doc.sections)} chunks={len(chunks)} "
            f"embedded in {time.perf_counter() - t1:.1f}s, facts located in HTML={located}, injection-flagged={flagged}"
        )
        repo.upsert_filing(filing, sections, len(chunks), located)
        summary.filings.append(
            {"fiscal_year": filing.fiscal_year, "accession": filing.accession, "chunks": len(chunks), "facts_located": located, "sections": list(doc.sections)}
        )
    repo.replace_facts(company.ticker, facts, conflicts)
    summary.seconds = round(time.perf_counter() - t0, 1)
    return summary
