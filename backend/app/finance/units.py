"""Unit/scale normalization and canonical display formatting.

All values are stored in base units (e.g. USD, not millions) as Decimal. Display strings are
generated here only, so the verifier can parse any number in an answer back to base units and
compare it to the source with a rounding tolerance that matches the displayed precision.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

SCALES = {
    "trillion": Decimal(10) ** 12,
    "billion": Decimal(10) ** 9,
    "million": Decimal(10) ** 6,
    "thousand": Decimal(10) ** 3,
}
_SUFFIX = [("T", Decimal(10) ** 12), ("B", Decimal(10) ** 9), ("M", Decimal(10) ** 6), ("K", Decimal(10) ** 3)]


def q(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def format_usd(value: Decimal, places: int = 2) -> str:
    sign = "-" if value < 0 else ""
    v = abs(value)
    for suffix, scale in _SUFFIX[:3]:  # T, B, M
        if v >= scale:
            return f"{sign}${q(v / scale, places)}{suffix}"
    return f"{sign}${q(v, 0):,}"


def format_usd_millions(value: Decimal) -> str:
    """Filing-style display: $383,285 million."""
    sign = "-" if value < 0 else ""
    return f"{sign}${q(abs(value) / SCALES['million'], 0):,} million"


def format_percent(ratio: Decimal, places: int = 1) -> str:
    return f"{q(ratio * 100, places)}%"


def format_ratio(ratio: Decimal, places: int = 2) -> str:
    return f"{q(ratio, places)}"


def format_value(value: Decimal, unit: str, as_percent: bool = False) -> str:
    if unit == "USD":
        return format_usd(value)
    if unit == "USD/shares":
        return f"${q(value, 2)}"
    if unit == "shares":
        return f"{q(value / SCALES['million'], 1)}M shares"
    if as_percent:
        return format_percent(value)
    return format_ratio(value)


def assert_same_unit(units: list[str]) -> str | None:
    distinct = sorted(set(units))
    if len(distinct) > 1:
        return f"unit mismatch across inputs: {', '.join(distinct)}"
    return None
