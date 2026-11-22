"""Deterministic financial analysis engine (Recommendations §4.1).

Every number it returns is either
  * a reported XBRL fact (kind="reported"), or
  * a derived metric computed with Python Decimal through the restricted evaluator, returned with a
    CalculationRecord holding the formula, every input fact (concept, value, unit, period, accession),
    the full-precision result, guardrail warnings and the metric definition.

Guardrails: unit consistency, period-type checks (flow vs. balance), fiscal-period alignment of all
inputs, prior-year spacing for growth metrics, concept-consistency across years, restatement
conflicts, and accounting identities (gross profit = revenue − cost of revenue).
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.finance import units
from app.finance.metrics import DERIVED, REPORTED, DerivedMetric, label_for
from app.finance.safe_eval import FormulaError, evaluate, variables_in
from app.ingest.xbrl import FactConflict
from app.models import CalcInput, CalculationRecord, Fact

# When a component concept is not reported, an equivalent composite may be used instead.
COMPOSITES: dict[str, str] = {
    "term_debt": "(term_debt_noncurrent + term_debt_current)",
    "gross_profit": "(revenue - cost_of_revenue)",
}


class MetricResult(BaseModel):
    metric: str
    label: str
    ticker: str
    fiscal_year: int
    kind: str  # reported | derived
    value: str | None = None
    display: str | None = None
    unit: str | None = None
    period_end: str | None = None
    period_start: str | None = None
    fact: Fact | None = None
    calculation: CalculationRecord | None = None
    input_facts: list[Fact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.value is not None


def _days_between(a: str, b: str) -> int:
    return abs((date.fromisoformat(b) - date.fromisoformat(a)).days)


class _TickerIndex:
    def __init__(self, facts: list[Fact], conflicts: list[FactConflict]) -> None:
        self.by_concept_year: dict[tuple[str, int], list[Fact]] = {}
        self.by_id: dict[str, Fact] = {}
        for f in facts:
            self.by_concept_year.setdefault((f.concept, f.fiscal_year), []).append(f)
            self.by_id[f.id] = f
        self.conflicts: dict[tuple[str, str], FactConflict] = {(c.concept, c.end): c for c in conflicts}
        self.concept_choice: dict[str, str | None] = {}
        years = {f.fiscal_year for f in facts if f.concept.startswith("us-gaap:")}
        self.years = sorted(years)


class FinancialEngine:
    def __init__(
        self,
        fact_loader: Callable[[str], list[Fact]] | None = None,
        conflict_loader: Callable[[str], list[FactConflict]] | None = None,
    ) -> None:
        if fact_loader is None or conflict_loader is None:
            from app.db import repo

            fact_loader = fact_loader or repo.load_facts
            conflict_loader = conflict_loader or repo.load_conflicts
        self._load_facts = fact_loader
        self._load_conflicts = conflict_loader
        self._cache: dict[str, _TickerIndex] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ indexing
    def invalidate(self, ticker: str | None = None) -> None:
        with self._lock:
            if ticker:
                self._cache.pop(ticker, None)
            else:
                self._cache.clear()

    def _idx(self, ticker: str) -> _TickerIndex:
        with self._lock:
            if ticker not in self._cache:
                self._cache[ticker] = _TickerIndex(self._load_facts(ticker), self._load_conflicts(ticker))
            return self._cache[ticker]

    def available_years(self, ticker: str) -> list[int]:
        idx = self._idx(ticker)
        return [y for y in idx.years if self.get_item(ticker, "revenue", y)[0] is not None]

    def _candidates(self, idx: _TickerIndex, item_key: str, fy: int) -> dict[str, Fact]:
        item = REPORTED[item_key]
        out: dict[str, Fact] = {}
        for concept in item.concepts:
            for f in idx.by_concept_year.get((concept, fy), []):
                if f.unit == item.unit and f.period_type == item.period_type:
                    out[concept] = f
                    break
        return out

    def resolve_concept(self, ticker: str, item_key: str) -> str | None:
        """Pick the candidate concept with the best recent multi-year coverage for this company."""
        idx = self._idx(ticker)
        if item_key in idx.concept_choice:
            return idx.concept_choice[item_key]
        item = REPORTED[item_key]
        recent = idx.years[-6:]
        best: tuple[int, int, str] | None = None
        for prio, concept in enumerate(item.concepts):
            cover = sum(
                1
                for y in recent
                for f in idx.by_concept_year.get((concept, y), [])
                if f.unit == item.unit and f.period_type == item.period_type
            )
            if cover and (best is None or (cover, -prio) > (best[0], best[1])):
                best = (cover, -prio, concept)
        idx.concept_choice[item_key] = best[2] if best else None
        return idx.concept_choice[item_key]

    def get_item(self, ticker: str, item_key: str, fy: int) -> tuple[Fact | None, list[str]]:
        idx = self._idx(ticker)
        cands = self._candidates(idx, item_key, fy)
        if not cands:
            return None, []
        preferred = self.resolve_concept(ticker, item_key)
        if preferred and preferred in cands:
            return cands[preferred], []
        concept, fact = next(iter(cands.items()))
        return fact, [
            f"{ticker} FY{fy}: {label_for(item_key)} uses {concept} (company's usual concept {preferred} not reported that year)"
        ]

    def fact_by_id(self, ticker: str, fact_id: str) -> Fact | None:
        return self._idx(ticker).by_id.get(fact_id)

    def conflicts_for(self, fact: Fact) -> FactConflict | None:
        return self._idx(fact.ticker).conflicts.get((fact.concept, fact.end))

    # ------------------------------------------------------------------ public API
    def compute(self, ticker: str, metric: str, fy: int) -> MetricResult:
        if metric in REPORTED:
            return self._reported(ticker, metric, fy)
        if metric in DERIVED:
            return self._derived(ticker, DERIVED[metric], fy)
        m = re.fullmatch(r"(\w+)_growth", metric)
        if m and m.group(1) in REPORTED:
            item = m.group(1)
            dm = DerivedMetric(
                key=metric,
                label=f"{REPORTED[item].label} growth (YoY)",
                formula=f"({item} - {item}_prev) / {item}_prev",
                result_unit="ratio",
                display_percent=True,
                definition=f"Change in reported {REPORTED[item].label.lower()} versus the prior fiscal year.",
            )
            return self._derived(ticker, dm, fy)
        return MetricResult(metric=metric, label=metric, ticker=ticker, fiscal_year=fy, kind="derived", error=f"unknown metric '{metric}'")

    def custom(self, ticker: str, fy: int, key: str, label: str, formula: str, percent: bool = False) -> MetricResult:
        """Evaluate a planner-proposed formula over registry items — still sandboxed and fully audited."""
        unknown = {v.removesuffix("_prev") for v in variables_in(formula)} - set(REPORTED)
        if unknown:
            return MetricResult(metric=key, label=label, ticker=ticker, fiscal_year=fy, kind="derived", error=f"unknown items: {sorted(unknown)}")
        dm = DerivedMetric(key=key, label=label, formula=formula, result_unit="ratio", display_percent=percent, definition=f"Custom formula: {formula}")
        return self._derived(ticker, dm, fy)

    def change_between(self, ticker: str, metric: str, y_from: int, y_to: int) -> list[MetricResult]:
        """Absolute and relative change of a metric between two fiscal years, as calculation records.

        Reported USD items -> absolute change (USD) and percent change; ratio metrics -> point change.
        """
        a, b = self.compute(ticker, metric, y_from), self.compute(ticker, metric, y_to)
        label = label_for(metric)
        if not (a.ok and b.ok):
            err = a.error or b.error or "missing input"
            return [MetricResult(metric=f"{metric}_change", label=f"Change in {label}", ticker=ticker, fiscal_year=y_to, kind="derived", error=err)]
        va, vb = Decimal(a.value), Decimal(b.value)  # type: ignore[arg-type]
        ins = []
        facts_used: list[Fact] = []
        for name, res, val in ((f"{metric}_fy{y_from}", a, va), (f"{metric}_fy{y_to}", b, vb)):
            src_fact = res.fact
            ins.append(
                CalcInput(
                    name=name,
                    fact_id=src_fact.id if src_fact else None,
                    concept=src_fact.concept if src_fact else f"calc:{res.calculation.id if res.calculation else metric}",
                    value=str(val), unit=res.unit or "", start=res.period_start, end=res.period_end or "",
                    fiscal_year=res.fiscal_year, accession=src_fact.accession if src_fact else None,
                )
            )
            facts_used.extend(res.input_facts)
        n_a, n_b = ins[0].name, ins[1].name
        warns = list(dict.fromkeys(a.warnings + b.warnings))
        out: list[MetricResult] = []
        is_usd = (a.unit == "USD")
        specs = (
            [("abs_change", f"Change in {label} (FY{y_from}→FY{y_to})", f"{n_b} - {n_a}", "USD", False),
             ("pct_change", f"% change in {label} (FY{y_from}→FY{y_to})", f"({n_b} - {n_a}) / {n_a}", "ratio", True)]
            if is_usd else
            [("pt_change", f"Change in {label} (FY{y_from}→FY{y_to}), percentage points", f"({n_b} - {n_a}) * 100", "ratio", False)]
        )
        for suffix, lbl, formula, runit, pct in specs:
            try:
                result = evaluate(formula, {n_a: va, n_b: vb})
            except FormulaError as exc:
                out.append(MetricResult(metric=f"{metric}_{suffix}", label=lbl, ticker=ticker, fiscal_year=y_to, kind="derived", error=str(exc)))
                continue
            if runit == "USD":
                display = units.format_usd(result)
            elif pct:
                display = units.format_percent(result)
            else:
                display = f"{units.q(result, 1)} pts"
            rec = CalculationRecord(
                id=f"{ticker}:{metric}_{suffix}:FY{y_from}-FY{y_to}", metric=f"{metric}_{suffix}", label=lbl, ticker=ticker,
                fiscal_year=y_to, formula=formula, inputs=ins, result=str(result), result_unit=runit,  # type: ignore[arg-type]
                display=display, definition=f"Computed from the FY{y_from} and FY{y_to} values of {label}.", warnings=warns,
            )
            out.append(MetricResult(
                metric=f"{metric}_{suffix}", label=lbl, ticker=ticker, fiscal_year=y_to, kind="derived", value=str(result),
                display=display, unit=runit, period_end=b.period_end, period_start=a.period_start, calculation=rec,
                input_facts=facts_used, warnings=warns,
            ))
        return out

    def trend(self, ticker: str, metric: str, years: list[int]) -> list[MetricResult]:
        return [self.compute(ticker, metric, y) for y in sorted(years)]

    def compare(self, tickers: list[str], metrics: list[str], fiscal_year: int, align: str = "fiscal") -> dict:
        """Side-by-side comparison with explicit period alignment notes (Recommendations §4.2)."""
        resolved_fy: dict[str, int] = {}
        notes: list[str] = []
        for t in tickers:
            resolved_fy[t] = self.calendar_aligned_year(t, fiscal_year) if align == "calendar" else fiscal_year
        rows = []
        for m in metrics:
            rows.append({"metric": m, "label": label_for(m), "values": {t: self.compute(t, m, resolved_fy[t]) for t in tickers}})
        ends: dict[str, tuple[str | None, str | None]] = {}
        for t in tickers:
            rev = self.compute(t, "revenue", resolved_fy[t])
            ends[t] = (rev.period_start, rev.period_end)
        distinct_ends = {e[1] for e in ends.values() if e[1]}
        if len(distinct_ends) > 1:
            span = "; ".join(f"{t} FY{resolved_fy[t]}: {s} → {e}" for t, (s, e) in ends.items())
            notes.append(
                "Fiscal years end on different dates, so periods are not identical — " + span + ". "
                "Values are compared by each company's own fiscal year; differences partly reflect timing."
            )
        notes.append("All figures are as reported in USD from SEC XBRL; derived metrics use the definitions shown.")
        return {"fiscal_year": fiscal_year, "align": align, "resolved_fiscal_years": resolved_fy, "rows": rows, "period_notes": notes}

    def calendar_aligned_year(self, ticker: str, calendar_year: int) -> int:
        """Fiscal year whose reporting period overlaps calendar_year the most."""
        best: tuple[int, int] | None = None
        y0, y1 = date(calendar_year, 1, 1), date(calendar_year, 12, 31)
        for fy in self.available_years(ticker):
            fact, _ = self.get_item(ticker, "revenue", fy)
            if not fact or not fact.start:
                continue
            s, e = date.fromisoformat(fact.start), date.fromisoformat(fact.end)
            overlap = (min(e, y1) - max(s, y0)).days
            if best is None or overlap > best[0]:
                best = (overlap, fy)
        return best[1] if best else calendar_year

    # ------------------------------------------------------------------ internals
    def _reported(self, ticker: str, key: str, fy: int) -> MetricResult:
        item = REPORTED[key]
        fact, warns = self.get_item(ticker, key, fy)
        if fact is None:
            return MetricResult(
                metric=key, label=item.label, ticker=ticker, fiscal_year=fy, kind="reported",
                error=f"{ticker} has no reported {item.label.lower()} for FY{fy} in SEC XBRL data",
            )
        conflict = self.conflicts_for(fact)
        if conflict:
            warns.append("Restated/recast in a later filing: " + conflict.describe())
        v = Decimal(fact.value)
        return MetricResult(
            metric=key, label=item.label, ticker=ticker, fiscal_year=fy, kind="reported",
            value=str(v), display=units.format_value(v, fact.unit), unit=fact.unit,
            period_end=fact.end, period_start=fact.start, fact=fact, input_facts=[fact], warnings=warns,
        )

    def _derived(self, ticker: str, dm: DerivedMetric, fy: int) -> MetricResult:
        formula = dm.formula
        warnings: list[str] = []
        inputs: dict[str, tuple[Fact | None, int]] = {}
        # resolve variables, expanding composites where a component isn't reported
        for _ in range(10):
            changed = False
            for var in sorted(variables_in(formula)):
                if var in inputs:
                    continue
                item_key, year = (var[:-5], fy - 1) if var.endswith("_prev") else (var, fy)
                if item_key not in REPORTED:
                    return self._fail(ticker, dm, fy, f"formula references unknown item '{item_key}'")
                fact, w = self.get_item(ticker, item_key, year)
                warnings.extend(w)
                if fact is None and item_key in COMPOSITES:
                    repl = COMPOSITES[item_key]
                    if var.endswith("_prev"):
                        repl = re.sub(r"\b([a-z_]+)\b", r"\1_prev", repl)
                    formula = re.sub(rf"\b{var}\b", repl, formula)
                    warnings.append(f"{label_for(item_key)} not reported for FY{year}; used {COMPOSITES[item_key]}")
                    changed = True
                    break
                inputs[var] = (fact, year)
            if not changed:
                break

        values: dict[str, Decimal] = {}
        calc_inputs: list[CalcInput] = []
        used: list[Fact] = []
        for var, (fact, year) in sorted(inputs.items()):
            item_key = var.removesuffix("_prev")
            if fact is None:
                if item_key in dm.optional_items:
                    values[var] = Decimal(0)
                    # only noteworthy if the company normally reports this item
                    if self.resolve_concept(ticker, item_key) is not None:
                        warnings.append(f"{label_for(item_key)} not reported for FY{year}; treated as 0")
                    continue
                return self._fail(ticker, dm, fy, f"{ticker} has no reported {label_for(item_key).lower()} for FY{year} in SEC XBRL data")
            values[var] = Decimal(fact.value)
            used.append(fact)
            calc_inputs.append(
                CalcInput(
                    name=var, fact_id=fact.id, concept=fact.concept, value=fact.value, unit=fact.unit,
                    start=fact.start, end=fact.end, fiscal_year=fact.fiscal_year, accession=fact.accession,
                )
            )
            conflict = self.conflicts_for(fact)
            if conflict:
                warnings.append("Input restated/recast in a later filing: " + conflict.describe())

        # ---- guardrails
        unit_err = units.assert_same_unit([f.unit for f in used])
        if unit_err:
            return self._fail(ticker, dm, fy, unit_err)
        for f in used:
            expected = REPORTED[self._item_for_concept(f.concept)].period_type if self._item_for_concept(f.concept) else None
            if expected and f.period_type != expected:
                return self._fail(ticker, dm, fy, f"period-type mismatch for {f.concept}: {f.period_type} vs {expected}")
        current = [f for f, ci in zip(used, calc_inputs) if not ci.name.endswith("_prev")]
        prior = [f for f, ci in zip(used, calc_inputs) if ci.name.endswith("_prev")]
        if len({f.end for f in current}) > 1:
            return self._fail(ticker, dm, fy, "inputs refer to different period end dates: " + ", ".join(sorted({f.end for f in current})))
        if current and prior:
            gap = _days_between(prior[0].end, current[0].end)
            if not 330 <= gap <= 400:
                return self._fail(ticker, dm, fy, f"prior-period input is {gap} days earlier, not one fiscal year")
            cur_c = {f.concept.split(":")[1] for f in current}
            pri_c = {f.concept.split(":")[1] for f in prior}
            if cur_c != pri_c:
                warnings.append(f"definition changed between years: {sorted(pri_c)} vs {sorted(cur_c)}")

        try:
            result = evaluate(formula, values)
        except FormulaError as exc:
            return self._fail(ticker, dm, fy, f"calculation error: {exc}")

        if "gross_profit_identity" in dm.cross_checks:
            gp, _ = self.get_item(ticker, "gross_profit", fy)
            rev, _ = self.get_item(ticker, "revenue", fy)
            cogs, _ = self.get_item(ticker, "cost_of_revenue", fy)
            if gp and rev and cogs:
                diff = Decimal(rev.value) - Decimal(cogs.value) - Decimal(gp.value)
                if diff != 0:
                    warnings.append(f"identity check: revenue − cost of revenue differs from reported gross profit by {units.format_usd(diff)}")

        result_unit = "USD" if dm.result_unit == "USD" else "ratio"
        display = units.format_usd(result) if result_unit == "USD" else (
            units.format_percent(result) if dm.display_percent else units.format_ratio(result)
        )
        period_end = current[0].end if current else (used[0].end if used else None)
        period_start = current[0].start if current else None
        record = CalculationRecord(
            id=f"{ticker}:{dm.key}:FY{fy}",
            metric=dm.key,
            label=dm.label,
            ticker=ticker,
            fiscal_year=fy,
            formula=formula,
            inputs=calc_inputs,
            result=str(result),
            result_unit=result_unit,  # type: ignore[arg-type]
            display=display,
            definition=dm.definition,
            warnings=warnings,
        )
        return MetricResult(
            metric=dm.key, label=dm.label, ticker=ticker, fiscal_year=fy, kind="derived", value=str(result),
            display=display, unit=result_unit, period_end=period_end, period_start=period_start,
            calculation=record, input_facts=used, warnings=warnings,
        )

    @staticmethod
    def _item_for_concept(concept: str) -> str | None:
        for key, item in REPORTED.items():
            if concept in item.concepts:
                return key
        return None

    @staticmethod
    def _fail(ticker: str, dm: DerivedMetric, fy: int, msg: str) -> MetricResult:
        return MetricResult(metric=dm.key, label=dm.label, ticker=ticker, fiscal_year=fy, kind="derived", error=msg)


def recompute(record: CalculationRecord) -> Decimal:
    """Independent re-evaluation of a calculation record from its stored inputs (used by the auditor)."""
    values = {i.name: Decimal(i.value) for i in record.inputs}
    for name in variables_in(record.formula):
        values.setdefault(name, Decimal(0))  # optional items treated as 0 (warned at compute time)
    return evaluate(record.formula, values)
