from decimal import Decimal

import pytest

from app.finance import units
from app.finance.engine import FinancialEngine, recompute
from app.finance.safe_eval import FormulaError, evaluate
from app.ingest.xbrl import FactConflict
from tests.factories import acme_facts


@pytest.fixture()
def engine() -> FinancialEngine:
    facts = acme_facts()
    conflicts = [FactConflict("ACME", "us-gaap:NetIncomeLoss", "USD", "2023-01-01", "2023-12-31",
                              [{"accession": "a", "value": "150000000", "filed": "2024-02-15"}, {"accession": "b", "value": "149000000", "filed": "2025-02-15"}])]
    return FinancialEngine(lambda t: facts if t == "ACME" else [], lambda t: conflicts if t == "ACME" else [])


# ----------------------------------------------------------------------------- sandboxed evaluator
def test_safe_eval_arithmetic():
    assert evaluate("(a - b) / b", {"a": Decimal(125), "b": Decimal(100)}) == Decimal("0.25")
    assert evaluate("-a * 2", {"a": Decimal("1.5")}) == Decimal("-3.0")


@pytest.mark.parametrize("formula", ["__import__('os').system('x')", "a.real", "a[0]", "[a for a in b]", "lambda: 1", "a ** 2", "open('f')"])
def test_safe_eval_rejects_non_arithmetic(formula):
    with pytest.raises(FormulaError):
        evaluate(formula, {"a": Decimal(1), "b": Decimal(2)})


def test_safe_eval_division_by_zero_and_unknown_names():
    with pytest.raises(FormulaError):
        evaluate("a / b", {"a": Decimal(1), "b": Decimal(0)})
    with pytest.raises(FormulaError):
        evaluate("a + c", {"a": Decimal(1)})


# ----------------------------------------------------------------------------- formatting
def test_format_values():
    assert units.format_usd(Decimal("383285000000")) == "$383.29B"
    assert units.format_usd(Decimal("-11043000000")) == "-$11.04B"
    assert units.format_usd_millions(Decimal("383285000000")) == "$383,285 million"
    assert units.format_percent(Decimal("0.064255")) == "6.4%"
    assert units.format_ratio(Decimal("1.8723")) == "1.87"


# ----------------------------------------------------------------------------- engine
def test_reported_fact(engine):
    r = engine.compute("ACME", "revenue", 2024)
    assert r.ok and r.kind == "reported" and r.value == "1250000000" and r.display == "$1.25B"


def test_growth_and_margins(engine):
    g = engine.compute("ACME", "revenue_growth", 2024)
    assert g.ok and Decimal(g.value) == Decimal("0.25") and g.display == "25.0%"
    assert {i.name for i in g.calculation.inputs} == {"revenue", "revenue_prev"}
    assert engine.compute("ACME", "gross_margin", 2024).display == "60.0%"
    assert engine.compute("ACME", "operating_margin", 2024).display == "24.0%"
    assert engine.compute("ACME", "free_cash_flow", 2024).display == "$300.00M"
    assert engine.compute("ACME", "current_ratio", 2024).display == "1.50"
    assert engine.compute("ACME", "rd_intensity", 2024).display == "10.0%"


def test_composite_debt_fallback(engine):
    r = engine.compute("ACME", "debt_to_equity", 2024)
    # LongTermDebt not reported -> non-current + current = 400M; / equity 800M = 0.5
    assert r.ok and Decimal(r.value) == Decimal("0.5")
    assert "term_debt_noncurrent" in r.calculation.formula
    assert any("not reported" in w for w in r.warnings)


def test_missing_year_is_an_error_not_a_guess(engine):
    r = engine.compute("ACME", "revenue_growth", 2023)  # needs FY2022 revenue
    assert not r.ok and "FY2022" in r.error


def test_restatement_conflict_surfaces(engine):
    r = engine.compute("ACME", "net_income_growth", 2024)
    assert r.ok and any("restated" in w.lower() for w in r.warnings)


def test_change_between_and_recompute(engine):
    out = {r.metric: r for r in engine.change_between("ACME", "revenue", 2023, 2024)}
    assert out["revenue_abs_change"].display == "$250.00M"
    assert out["revenue_pct_change"].display == "25.0%"
    for r in out.values():
        assert recompute(r.calculation) == Decimal(r.calculation.result)


def test_unknown_metric(engine):
    assert engine.compute("ACME", "ebitda_magic", 2024).error
