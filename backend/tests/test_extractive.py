from app.graph.evidence import EvidenceSet
from app.graph.extractive import extractive_answer
from app.models import Chunk, QueryPlan, QueryType, RetrievedChunk

NAMES = {"ACME": "Acme Robotics Inc."}


def _chunk(cid: str, text: str, kind: str = "text", section: str = "item_7") -> RetrievedChunk:
    return RetrievedChunk(
        chunk=Chunk(
            id=cid, ticker="ACME", cik=1, fiscal_year=2024, accession="a", filing_date="2025-02-01", section=section,
            section_title=section, kind=kind, text=text, page_start=31, page_end=31, source_url="https://www.sec.gov/x",
        )
    )


TABLE = (
    "Net sales by category (dollars in millions)\n"
    "2024 | Change | 2023\n"
    "Portion of total net sales included in deferred revenue | $50 | 4% | $40\n"
    "Total net sales | $1,250 | 25% | $1,000"
)


def test_reads_the_requested_year_cell_from_the_closest_row():
    ev = EvidenceSet()
    ev.add_passage(_chunk("t1", TABLE, kind="table"))
    plan = QueryPlan(query_type=QueryType.FACT_LOOKUP, tickers=["ACME"], fiscal_years=[2023], metrics=["revenue"], needs_facts=True)
    out = extractive_answer("What was Acme's total net sales in fiscal 2023?", plan, ev, NAMES)
    assert "Total net sales for 2023 was $1,000" in out and "millions" in out and "[S1]" in out
    assert "$40" not in out


def test_quotes_a_stated_figure_but_never_computes():
    ev = EvidenceSet()
    ev.add_passage(_chunk("s1", "Gross margin increased to 61.5% in fiscal 2024 from 58.0% in fiscal 2023. Operating expenses grew."))
    plan = QueryPlan(query_type=QueryType.RATIO, tickers=["ACME"], fiscal_years=[2024], metrics=["gross_margin"], needs_facts=True)
    out = extractive_answer("What was Acme's gross margin in fiscal 2024?", plan, ev, NAMES)
    assert "61.5%" in out and "[S1]" in out


def test_narrative_quotes_and_abstention():
    ev = EvidenceSet()
    ev.add_passage(_chunk("r1", "We depend on a single supplier in Taiwan for controllers. A disruption could delay shipments.", section="item_1a"))
    plan = QueryPlan(query_type=QueryType.NARRATIVE, tickers=["ACME"], needs_narrative=True)
    out = extractive_answer("What supplier risks does Acme describe?", plan, ev, NAMES)
    assert "Taiwan" in out and out.count("[S1]") >= 1
    empty = extractive_answer("What supplier risks does Acme describe?", plan, EvidenceSet(), NAMES)
    assert empty.startswith("I can't answer that")
