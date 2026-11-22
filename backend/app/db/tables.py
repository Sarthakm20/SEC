"""Relational schema (PostgreSQL in production, SQLite for local dev/tests)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class CompanyRow(Base):
    __tablename__ = "companies"
    ticker: Mapped[str] = mapped_column(String(12), primary_key=True)
    cik: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(255))
    fiscal_year_end: Mapped[str | None] = mapped_column(String(4), nullable=True)


class FilingRow(Base):
    __tablename__ = "filings"
    accession: Mapped[str] = mapped_column(String(32), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(12), index=True)
    cik: Mapped[int] = mapped_column(Integer)
    form: Mapped[str] = mapped_column(String(12))
    filing_date: Mapped[str] = mapped_column(String(10))
    report_date: Mapped[str] = mapped_column(String(10))
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    primary_document: Mapped[str] = mapped_column(String(255))
    sections: Mapped[dict] = mapped_column(JSON, default=dict)
    n_chunks: Mapped[int] = mapped_column(Integer, default=0)
    n_facts_located: Mapped[int] = mapped_column(Integer, default=0)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class FactRow(Base):
    __tablename__ = "facts"
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(12))
    cik: Mapped[int] = mapped_column(Integer)
    concept: Mapped[str] = mapped_column(String(160))
    label: Mapped[str] = mapped_column(Text)
    value: Mapped[str] = mapped_column(String(64))
    unit: Mapped[str] = mapped_column(String(32))
    period_type: Mapped[str] = mapped_column(String(10))
    start: Mapped[str | None] = mapped_column(String(10), nullable=True)
    end: Mapped[str] = mapped_column(String(10))
    fiscal_year: Mapped[int] = mapped_column(Integer)
    fiscal_period: Mapped[str] = mapped_column(String(4), default="FY")
    accession: Mapped[str] = mapped_column(String(32))
    form: Mapped[str] = mapped_column(String(12))
    filed: Mapped[str] = mapped_column(String(10))
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (Index("ix_facts_lookup", "ticker", "concept", "fiscal_year"),)


class FactConflictRow(Base):
    __tablename__ = "fact_conflicts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(12))
    concept: Mapped[str] = mapped_column(String(160))
    unit: Mapped[str] = mapped_column(String(32))
    start: Mapped[str | None] = mapped_column(String(10), nullable=True)
    end: Mapped[str] = mapped_column(String(10))
    values: Mapped[list] = mapped_column(JSON)

    __table_args__ = (Index("ix_conflicts_lookup", "ticker", "concept", "end"),)


class ChunkRow(Base):
    __tablename__ = "chunks"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(12), index=True)
    cik: Mapped[int] = mapped_column(Integer)
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    accession: Mapped[str] = mapped_column(String(32), index=True)
    filing_date: Mapped[str] = mapped_column(String(10))
    section: Mapped[str] = mapped_column(String(16))
    section_title: Mapped[str] = mapped_column(String(255))
    subsection: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(8))
    table_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_url: Mapped[str] = mapped_column(Text)
    injection_flags: Mapped[list] = mapped_column(JSON, default=list)


class QueryRunRow(Base):
    __tablename__ = "query_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text)
    experiment: Mapped[str] = mapped_column(String(4))
    answer: Mapped[str] = mapped_column(Text)
    verdict: Mapped[str] = mapped_column(String(32))
    latency_ms: Mapped[float] = mapped_column(Float)
    payload: Mapped[dict] = mapped_column(JSON)  # full AnswerResponse


class CalculationLogRow(Base):
    __tablename__ = "calculation_logs"
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    metric: Mapped[str] = mapped_column(String(64))
    ticker: Mapped[str] = mapped_column(String(12))
    fiscal_year: Mapped[int] = mapped_column(Integer)
    formula: Mapped[str] = mapped_column(Text)
    inputs: Mapped[list] = mapped_column(JSON)
    result: Mapped[str] = mapped_column(String(64))
    display: Mapped[str] = mapped_column(String(64))
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
