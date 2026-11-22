import pytest

from app.companies import SEED_COMPANIES, resolve_tickers
from app.graph.planner import extract_metrics, extract_years, rule_plan
from app.models import QueryType
from app.retrieval.bm25 import BM25Index, tokenize
from app.retrieval.hybrid import reciprocal_rank_fusion
from tests.factories import acme_chunks

COMPANIES = list(SEED_COMPANIES.values())
AVAIL = {"AAPL": [2023, 2024, 2025], "MSFT": [2023, 2024, 2025], "NVDA": [2023, 2024, 2025]}


@pytest.mark.parametrize(
    "q,qtype,tickers,metrics",
    [
        ("What was Apple's total net sales in fiscal 2023?", QueryType.FACT_LOOKUP, ["AAPL"], ["revenue"]),
        ("How did Apple's revenue change in 2023 compared to 2022?", QueryType.CROSS_YEAR, ["AAPL"], ["revenue"]),
        ("What was Microsoft's operating margin in fiscal 2024?", QueryType.RATIO, ["MSFT"], ["operating_margin"]),
        ("Compare the operating margins of Apple, Microsoft and NVIDIA in fiscal 2024", QueryType.CROSS_COMPANY, ["AAPL", "MSFT", "NVDA"], ["operating_margin"]),
        ("Show Apple's revenue trend from fiscal 2023 to fiscal 2025", QueryType.TREND, ["AAPL"], ["revenue"]),
        ("What supply chain risks does Apple describe?", QueryType.NARRATIVE, ["AAPL"], []),
        ("Why did NVIDIA's revenue increase in fiscal 2025?", QueryType.HYBRID, ["NVDA"], ["revenue"]),
        ("What is NVIDIA's current stock price?", QueryType.OUT_OF_SCOPE, ["NVDA"], []),
        ("Should I buy Microsoft stock?", QueryType.OUT_OF_SCOPE, ["MSFT"], []),
        ("What was Tesla's revenue in 2024?", QueryType.OUT_OF_SCOPE, [], []),
        ("How does Apple recognize revenue?", QueryType.NARRATIVE, ["AAPL"], []),
        ("How did NVIDIA's revenue change in fiscal 2025 and what drove the change?", QueryType.HYBRID, ["NVDA"], ["revenue"]),
    ],
)
def test_rule_plan(q, qtype, tickers, metrics):
    plan, _ = rule_plan(q, COMPANIES, AVAIL)
    assert plan.query_type == qtype
    if tickers is not None:
        assert plan.tickers == tickers
    for m in metrics:
        assert any(p.startswith(m) for p in plan.metrics)


@pytest.mark.parametrize(
    "q,qtype",
    [
        # a plain past year ("in 2024") is a lookup, not a forecast
        ("What was Apple's revenue in 2024?", QueryType.FACT_LOOKUP),
        ("What was Microsoft's gross margin in 2025?", QueryType.RATIO),
        ("How much net income did NVIDIA report in 2023?", QueryType.FACT_LOOKUP),
        # a year after the current calendar year is a forecast
        ("What will Apple's revenue be in 2031?", QueryType.OUT_OF_SCOPE),
        ("What is Microsoft's net income in 2031?", QueryType.OUT_OF_SCOPE),
        # "percentage of revenue spent on R&D" is the R&D-intensity ratio
        ("What percentage of its revenue did Apple spend on research and development in 2024?", QueryType.RATIO),
    ],
)
def test_plain_years_are_not_forecasts(q, qtype):
    plan, _ = rule_plan(q, COMPANIES, AVAIL)
    assert plan.query_type == qtype


def test_year_extraction():
    assert extract_years("from FY2022 to FY2024", [2025])[0] == [2022, 2023, 2024]
    assert extract_years("over the last three years", [2023, 2024, 2025])[0] == [2023, 2024, 2025]
    assert extract_years("in FY24", [])[0] == [2024]


def test_metric_synonyms_and_plurals():
    assert extract_metrics("net sales and R&D as a percentage of revenue") == ["revenue", "rd_intensity"]
    assert extract_metrics("debt-to-equity and free cash flows") == ["debt_to_equity", "free_cash_flow"]


def test_followup_inherits_context():
    first, _ = rule_plan("What was Apple's operating margin in fiscal 2024?", COMPANIES, AVAIL)
    follow, _ = rule_plan("What about Microsoft?", COMPANIES, AVAIL, previous=first)
    assert follow.tickers == ["MSFT"] and follow.metrics == ["operating_margin"] and follow.fiscal_years == [2024]


def test_entity_resolution_word_boundaries():
    assert resolve_tickers("Apple and NVIDIA", COMPANIES) == ["AAPL", "NVDA"]
    assert resolve_tickers("pineapple farms", COMPANIES) == []


def test_rrf_rewards_agreement():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "c", "a"]], k=60)
    assert max(fused, key=fused.get) == "b"


def test_bm25_filters_and_terms():
    idx = BM25Index(acme_chunks())
    hits = idx.search("single-source supplier Taiwan", 3)
    assert hits[0].chunk_id.endswith("item_1a-0000")
    assert idx.search("Taiwan supplier", 3, sections=["notes"]) == []
    assert "r&d" in tokenize("R&D spending") and "debt" in tokenize("debt-to-equity")


def test_fiscal_range_and_risk_sections():
    plan, _ = rule_plan("Show Apple's revenue trend from fiscal 2023 to fiscal 2025.", COMPANIES, AVAIL)
    assert plan.fiscal_years == [2023, 2024, 2025]
    risk, _ = rule_plan("What risks related to artificial intelligence does Microsoft describe in fiscal 2024?", COMPANIES, AVAIL)
    assert risk.sections == ["item_1a"]


def test_sufficiency_threshold_follows_reranker():
    from app.config import Settings

    assert Settings(reranker_model="BAAI/bge-reranker-base", min_rerank_score_for_sufficiency=None).sufficiency_threshold == -4.5
    assert Settings(reranker_model="Xenova/ms-marco-MiniLM-L-6-v2", min_rerank_score_for_sufficiency=None).sufficiency_threshold == -2.0
    assert Settings(reranker_model="BAAI/bge-reranker-base", min_rerank_score_for_sufficiency=-1.0).sufficiency_threshold == -1.0


def test_company_whose_name_is_its_ticker():
    """'Meta' must resolve to META even though the alias equals the ticker; lower-case 'meta' in prose must not."""
    from app.models import Company

    meta = Company(ticker="META", cik=1326801, name="Meta Platforms, Inc.")
    cs = COMPANIES + [meta]
    assert resolve_tickers("Which had the higher operating margin: Meta or Apple?", cs) == ["META", "AAPL"]
    assert resolve_tickers("META revenue 2025", cs) == ["META"]
    assert resolve_tickers("a meta-analysis of Apple's risks", cs) == ["AAPL"]


@pytest.mark.parametrize(
    "q",
    [
        "What is Microsoft's market cap today?",
        "Is Apple a good investment right now?",
        "What is NVIDIA's P/E ratio?",
        "Is Microsoft stock worth buying?",
    ],
)
def test_market_data_and_advice_are_out_of_scope(q):
    plan, _ = rule_plan(q, COMPANIES, AVAIL)
    assert plan.query_type == QueryType.OUT_OF_SCOPE


def test_investment_plans_are_still_narrative():
    plan, _ = rule_plan("How does Apple plan to invest in artificial intelligence?", COMPANIES, AVAIL)
    assert plan.query_type != QueryType.OUT_OF_SCOPE
