"""Domain models shared across ingestion, retrieval, the financial engine, verification and the API.

Evidence IDs follow one convention everywhere so that citations can be validated programmatically:
  F<n>  — an XBRL fact (verified, reported value)
  C<n>  — a deterministic calculation record (derived metric)
  S<n>  — a narrative source passage (10-K text chunk)
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Company(BaseModel):
    ticker: str
    cik: int
    name: str
    fiscal_year_end: str | None = None  # MMDD as reported by EDGAR

    @property
    def cik10(self) -> str:
        return f"{self.cik:010d}"


class Filing(BaseModel):
    accession: str  # 0000320193-24-000123
    cik: int
    ticker: str
    form: str
    filing_date: str
    report_date: str  # period of report (fiscal year end)
    fiscal_year: int
    primary_document: str

    @property
    def accession_nodash(self) -> str:
        return self.accession.replace("-", "")

    @property
    def url(self) -> str:
        return (
            f"https://www.sec.gov/Archives/edgar/data/{self.cik}/"
            f"{self.accession_nodash}/{self.primary_document}"
        )

    @property
    def index_url(self) -> str:
        return (
            f"https://www.sec.gov/Archives/edgar/data/{self.cik}/"
            f"{self.accession_nodash}/{self.accession}-index.htm"
        )


class FactLocation(BaseModel):
    """Where an XBRL fact is rendered inside the 10-K HTML (from the inline-XBRL tag)."""

    page: int | None = None
    table_title: str | None = None
    row_label: str | None = None
    element_id: str | None = None
    displayed_value: str | None = None


class Fact(BaseModel):
    """A normalized, reported XBRL fact — the ground truth for numbers."""

    id: str
    ticker: str
    cik: int
    concept: str  # e.g. us-gaap:Revenues
    label: str
    value: str  # Decimal serialized as string to avoid float drift
    unit: str  # USD, USD/shares, shares
    period_type: Literal["duration", "instant"]
    start: str | None = None
    end: str
    fiscal_year: int
    fiscal_period: str = "FY"
    accession: str
    form: str
    filed: str
    source_url: str | None = None
    location: FactLocation | None = None
    evidence_id: str | None = None  # F<n>, assigned when used as evidence in an answer


class SectionKey(str, Enum):
    BUSINESS = "item_1"
    RISK_FACTORS = "item_1a"
    MDA = "item_7"
    MARKET_RISK = "item_7a"
    FIN_STATEMENTS = "item_8"
    NOTES = "notes"


SECTION_TITLES: dict[str, str] = {
    "item_1": "Item 1. Business",
    "item_1a": "Item 1A. Risk Factors",
    "item_7": "Item 7. Management's Discussion and Analysis",
    "item_7a": "Item 7A. Quantitative and Qualitative Disclosures About Market Risk",
    "item_8": "Item 8. Financial Statements and Supplementary Data",
    "notes": "Notes to Consolidated Financial Statements",
}


class Chunk(BaseModel):
    id: str
    ticker: str
    cik: int
    fiscal_year: int
    accession: str
    filing_date: str
    section: str
    section_title: str
    subsection: str | None = None
    kind: Literal["text", "table"] = "text"
    table_id: str | None = None
    text: str
    page_start: int | None = None
    page_end: int | None = None
    source_url: str
    injection_flags: list[str] = Field(default_factory=list)


class RetrievalScores(BaseModel):
    bm25_rank: int | None = None
    bm25_score: float | None = None
    dense_rank: int | None = None
    dense_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None


class RetrievedChunk(BaseModel):
    chunk: Chunk
    scores: RetrievalScores = Field(default_factory=RetrievalScores)
    evidence_id: str | None = None  # S<n>, assigned when selected as evidence


class CalcInput(BaseModel):
    name: str  # symbol used in the formula, e.g. revenue_t
    fact_id: str | None = None
    evidence_id: str | None = None
    concept: str | None = None
    value: str
    unit: str
    start: str | None = None
    end: str
    fiscal_year: int
    accession: str | None = None


class CalculationRecord(BaseModel):
    """Auditable provenance for every derived number (Recommendations §3.3)."""

    id: str
    evidence_id: str | None = None  # C<n>
    metric: str
    label: str
    ticker: str
    fiscal_year: int
    formula: str
    inputs: list[CalcInput]
    result: str  # Decimal as string, full precision
    result_unit: Literal["ratio", "USD", "USD/shares", "shares"]
    display: str
    definition: str | None = None
    warnings: list[str] = Field(default_factory=list)


class EvidenceKind(str, Enum):
    FACT = "fact"
    CALCULATION = "calculation"
    PASSAGE = "passage"


class ClaimStatus(str, Enum):
    VERIFIED_FACT = "verified_fact"
    CALCULATED = "calculated"
    INTERPRETATION = "interpretation"
    UNSUPPORTED = "unsupported"


class ClaimCheck(BaseModel):
    sentence: str
    status: ClaimStatus
    citations: list[str] = Field(default_factory=list)
    numbers: list[str] = Field(default_factory=list)
    support_score: float | None = None
    issues: list[str] = Field(default_factory=list)


class Verdict(str, Enum):
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    FAILED = "failed"


class VerificationReport(BaseModel):
    verdict: Verdict
    citations_total: int = 0
    citations_valid: int = 0
    invalid_citations: list[str] = Field(default_factory=list)
    numbers_total: int = 0
    numbers_supported: int = 0
    unsupported_numbers: list[str] = Field(default_factory=list)
    period_issues: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    claims: list[ClaimCheck] = Field(default_factory=list)
    recomputed_calculations: int = 0
    notes: list[str] = Field(default_factory=list)


class TraceEvent(BaseModel):
    step: str
    label: str
    status: Literal["ok", "warn", "error", "skip"] = "ok"
    duration_ms: float = 0.0
    detail: dict[str, Any] = Field(default_factory=dict)


class QueryType(str, Enum):
    FACT_LOOKUP = "fact_lookup"
    CROSS_YEAR = "cross_year"
    RATIO = "ratio"
    CROSS_COMPANY = "cross_company"
    TREND = "trend"
    NARRATIVE = "narrative"
    HYBRID = "hybrid"
    OUT_OF_SCOPE = "out_of_scope"


class QueryPlan(BaseModel):
    query_type: QueryType
    tickers: list[str] = Field(default_factory=list)
    fiscal_years: list[int] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    needs_facts: bool = False
    needs_narrative: bool = False
    sections: list[str] = Field(default_factory=list)
    narrative_query: str | None = None
    sub_questions: list[str] = Field(default_factory=list)
    planner: Literal["rules", "llm"] = "rules"
    notes: list[str] = Field(default_factory=list)


class Usage(BaseModel):
    provider: str = "none"
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0
    estimated_cost_usd: float = 0.0
    embedding_calls: int = 0
    rerank_calls: int = 0


class AnswerResponse(BaseModel):
    run_id: str
    question: str
    answer: str
    plan: QueryPlan
    facts: list[Fact] = Field(default_factory=list)
    calculations: list[CalculationRecord] = Field(default_factory=list)
    passages: list[RetrievedChunk] = Field(default_factory=list)
    verification: VerificationReport
    trace: list[TraceEvent] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    limitations: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0
    experiment: str = "E"
