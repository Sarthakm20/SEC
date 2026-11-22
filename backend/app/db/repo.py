"""Thin repository layer translating between domain models and rows."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import delete, insert, select

from app.db.database import session_scope
from app.db.tables import (
    CalculationLogRow,
    ChunkRow,
    CompanyRow,
    FactConflictRow,
    FactRow,
    FilingRow,
    QueryRunRow,
)
from app.ingest.xbrl import FactConflict
from app.models import AnswerResponse, CalculationRecord, Chunk, Company, Fact, FactLocation, Filing

_BATCH = 2000


def _batched(rows: list[dict], n: int = _BATCH) -> Iterable[list[dict]]:
    for i in range(0, len(rows), n):
        yield rows[i : i + n]


# ----------------------------------------------------------------------------- companies & filings
def upsert_company(c: Company) -> None:
    with session_scope() as s:
        s.merge(CompanyRow(ticker=c.ticker, cik=c.cik, name=c.name, fiscal_year_end=c.fiscal_year_end))


def list_companies() -> list[Company]:
    with session_scope() as s:
        rows = s.scalars(select(CompanyRow).order_by(CompanyRow.ticker)).all()
        return [Company(ticker=r.ticker, cik=r.cik, name=r.name, fiscal_year_end=r.fiscal_year_end) for r in rows]


def upsert_filing(f: Filing, sections: dict, n_chunks: int, n_facts_located: int) -> None:
    with session_scope() as s:
        s.merge(
            FilingRow(
                accession=f.accession,
                ticker=f.ticker,
                cik=f.cik,
                form=f.form,
                filing_date=f.filing_date,
                report_date=f.report_date,
                fiscal_year=f.fiscal_year,
                primary_document=f.primary_document,
                sections=sections,
                n_chunks=n_chunks,
                n_facts_located=n_facts_located,
            )
        )


def _filing_from_row(r: FilingRow) -> Filing:
    return Filing(
        accession=r.accession,
        cik=r.cik,
        ticker=r.ticker,
        form=r.form,
        filing_date=r.filing_date,
        report_date=r.report_date,
        fiscal_year=r.fiscal_year,
        primary_document=r.primary_document,
    )


def list_filings(ticker: str | None = None) -> list[dict]:
    with session_scope() as s:
        q = select(FilingRow).order_by(FilingRow.ticker, FilingRow.fiscal_year.desc())
        if ticker:
            q = q.where(FilingRow.ticker == ticker)
        out = []
        for r in s.scalars(q).all():
            f = _filing_from_row(r)
            out.append(
                {
                    **f.model_dump(),
                    "url": f.url,
                    "index_url": f.index_url,
                    "sections": r.sections,
                    "n_chunks": r.n_chunks,
                    "n_facts_located": r.n_facts_located,
                }
            )
        return out


# ----------------------------------------------------------------------------- facts
def _fact_to_row(f: Fact) -> dict:
    d = f.model_dump()
    d["location"] = f.location.model_dump() if f.location else None
    return d


def _row_to_fact(r: FactRow) -> Fact:
    return Fact(
        id=r.id,
        ticker=r.ticker,
        cik=r.cik,
        concept=r.concept,
        label=r.label,
        value=r.value,
        unit=r.unit,
        period_type=r.period_type,  # type: ignore[arg-type]
        start=r.start,
        end=r.end,
        fiscal_year=r.fiscal_year,
        fiscal_period=r.fiscal_period,
        accession=r.accession,
        form=r.form,
        filed=r.filed,
        source_url=r.source_url,
        location=FactLocation(**r.location) if r.location else None,
    )


def replace_facts(ticker: str, facts: list[Fact], conflicts: list[FactConflict]) -> None:
    with session_scope() as s:
        s.execute(delete(FactRow).where(FactRow.ticker == ticker))
        s.execute(delete(FactConflictRow).where(FactConflictRow.ticker == ticker))
        rows = [_fact_to_row(f) for f in facts]
        for batch in _batched(rows):
            s.execute(insert(FactRow), batch)
        crow = [
            {"ticker": c.ticker, "concept": c.concept, "unit": c.unit, "start": c.start, "end": c.end, "values": c.values}
            for c in conflicts
        ]
        for batch in _batched(crow):
            s.execute(insert(FactConflictRow), batch)


def load_facts(ticker: str) -> list[Fact]:
    with session_scope() as s:
        rows = s.scalars(select(FactRow).where(FactRow.ticker == ticker)).all()
        return [_row_to_fact(r) for r in rows]


def get_fact(fact_id: str) -> Fact | None:
    with session_scope() as s:
        r = s.get(FactRow, fact_id)
        return _row_to_fact(r) if r else None


def load_conflicts(ticker: str) -> list[FactConflict]:
    with session_scope() as s:
        rows = s.scalars(select(FactConflictRow).where(FactConflictRow.ticker == ticker)).all()
        return [FactConflict(r.ticker, r.concept, r.unit, r.start, r.end, r.values) for r in rows]


# ----------------------------------------------------------------------------- chunks
def _row_to_chunk(r: ChunkRow) -> Chunk:
    return Chunk(
        id=r.id,
        ticker=r.ticker,
        cik=r.cik,
        fiscal_year=r.fiscal_year,
        accession=r.accession,
        filing_date=r.filing_date,
        section=r.section,
        section_title=r.section_title,
        subsection=r.subsection,
        kind=r.kind,  # type: ignore[arg-type]
        table_id=r.table_id,
        text=r.text,
        page_start=r.page_start,
        page_end=r.page_end,
        source_url=r.source_url,
        injection_flags=r.injection_flags or [],
    )


def replace_chunks(accession: str, chunks: list[Chunk]) -> None:
    with session_scope() as s:
        s.execute(delete(ChunkRow).where(ChunkRow.accession == accession))
        rows = [c.model_dump() for c in chunks]
        for batch in _batched(rows):
            s.execute(insert(ChunkRow), batch)


def load_all_chunks() -> list[Chunk]:
    with session_scope() as s:
        return [_row_to_chunk(r) for r in s.scalars(select(ChunkRow).order_by(ChunkRow.id)).all()]


def get_chunk(chunk_id: str) -> Chunk | None:
    with session_scope() as s:
        r = s.get(ChunkRow, chunk_id)
        return _row_to_chunk(r) if r else None


# ----------------------------------------------------------------------------- runs & calculation logs
def save_run(resp: AnswerResponse, thread_id: str | None = None) -> None:
    with session_scope() as s:
        s.merge(
            QueryRunRow(
                id=resp.run_id,
                thread_id=thread_id,
                question=resp.question,
                experiment=resp.experiment,
                answer=resp.answer,
                verdict=resp.verification.verdict.value,
                latency_ms=resp.latency_ms,
                payload=resp.model_dump(mode="json"),
            )
        )
        for c in resp.calculations:
            s.merge(_calc_row(resp.run_id, c))


def _calc_row(run_id: str, c: CalculationRecord) -> CalculationLogRow:
    return CalculationLogRow(
        id=f"{run_id}:{c.id}"[:96],
        run_id=run_id,
        metric=c.metric,
        ticker=c.ticker,
        fiscal_year=c.fiscal_year,
        formula=c.formula,
        inputs=[i.model_dump() for i in c.inputs],
        result=c.result,
        display=c.display,
        warnings=c.warnings,
    )


def get_run(run_id: str) -> AnswerResponse | None:
    with session_scope() as s:
        r = s.get(QueryRunRow, run_id)
        return AnswerResponse.model_validate(r.payload) if r else None


def list_runs(limit: int = 50, thread_id: str | None = None) -> list[dict]:
    with session_scope() as s:
        q = select(QueryRunRow).order_by(QueryRunRow.created_at.desc()).limit(limit)
        if thread_id:
            q = q.where(QueryRunRow.thread_id == thread_id)
        return [
            {
                "run_id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "question": r.question,
                "verdict": r.verdict,
                "experiment": r.experiment,
                "latency_ms": r.latency_ms,
                "thread_id": r.thread_id,
            }
            for r in s.scalars(q).all()
        ]
