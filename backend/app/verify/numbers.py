"""Extract numeric claims from answer text and normalize them to base units.

Each mention carries a tolerance derived from its displayed precision (e.g. "$383.3 billion" ±$0.05B,
"6.4%" ±0.05pp), so verification accepts correct rounding but rejects wrong numbers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

_SCALE_WORDS = {
    "trillion": 12, "tn": 12, "t": 12,
    "billion": 9, "bn": 9, "b": 9,
    "million": 6, "mn": 6, "mm": 6, "m": 6,
    "thousand": 3, "k": 3,
}

_NUM = r"(?P<num>-?\(?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?|-?\(?\d+(?:\.\d+)?\)?)"
_PATTERN = re.compile(
    r"(?P<cur>\$|USD\s?)?\s?" + _NUM +
    r"(?:\s?(?P<scale>trillion|billion|million|thousand|tn|bn|mm|mn|[TBMK])\b)?"
    r"(?:\s?(?P<pct>%|percent\b|percentage\s+points?\b|pp\b|pts?\b|bps\b|basis\s+points\b|x\b|times\b))?",
    re.I,
)

# contexts in which a number is an identifier, not a financial claim
_SKIP_BEFORE = re.compile(r"(fy|fiscal\s+year|fiscal|item|note|notes|page|p\.|pp\.|part|section|form|rule|\[[a-z]?)\s*$", re.I)


@dataclass
class NumberMention:
    raw: str
    value: Decimal  # base units: USD, or percent points for percentages, or plain ratio
    kind: str  # usd | percent | ratio | plain
    tolerance: Decimal
    start: int
    end: int


def _decimals(num: str) -> int:
    return len(num.split(".")[1]) if "." in num else 0


def extract_numbers(text: str) -> list[NumberMention]:
    # drop citation markers like [F1], [C2][S3]
    clean = re.sub(r"\[[FCS]\d+\]", lambda m: " " * len(m.group(0)), text)
    out: list[NumberMention] = []
    for m in _PATTERN.finditer(clean):
        num = m.group("num")
        if not num or not re.search(r"\d", num):
            continue
        cur, scale, pct = m.group("cur"), m.group("scale"), m.group("pct")
        negative = num.startswith("-") or (num.startswith("(") and num.endswith(")"))
        digits = num.strip("-()").replace(",", "")
        try:
            base = Decimal(digits)
        except Exception:
            continue
        before = clean[max(0, m.start() - 14) : m.start()]
        if _SKIP_BEFORE.search(before) and not cur and not pct:
            continue
        # bare years and small counts are not financial claims
        if not cur and not pct and not scale:
            if re.fullmatch(r"(19|20)\d\d", digits):
                continue
            if "." not in digits and base < 100:
                continue
        if scale and len(scale) == 1 and not cur:
            # single-letter suffix without $ is too ambiguous (e.g. "Item 7A"), unless it is B/M after a decimal
            if scale.upper() not in ("B", "M") or "." not in digits:
                continue
        dec = _decimals(digits)
        unit_tol = Decimal(5) * Decimal(10) ** (-(dec + 1))
        if pct:
            p = pct.lower()
            if p in ("bps",) or p.startswith("basis"):
                value, tol, kind = base / 100, unit_tol / 100, "percent"
            elif p in ("x", "times"):
                value, tol, kind = base, unit_tol, "ratio"
            else:
                value, tol, kind = base, unit_tol, "percent"
        elif cur or scale:
            exp = _SCALE_WORDS.get((scale or "").lower(), 0)
            mult = Decimal(10) ** exp
            value, tol, kind = base * mult, unit_tol * mult, "usd"
        else:
            value, tol, kind = base, unit_tol, ("ratio" if "." in digits and base < 100 else "plain")
        if negative:
            value = -value
        out.append(NumberMention(raw=m.group(0).strip(), value=value, kind=kind, tolerance=tol, start=m.start(), end=m.end()))
    return out


def candidate_values(value: Decimal, unit: str) -> list[tuple[Decimal, str]]:
    """Representations under which a source value may legitimately appear in prose."""
    if unit == "ratio":
        return [(value * 100, "percent"), (value, "ratio")]
    if unit == "USD":
        return [(value, "usd"), (abs(value), "usd")]
    if unit == "USD/shares":
        return [(value, "usd")]
    return [(value, "plain")]


def matches(mention: NumberMention, value: Decimal, unit: str) -> bool:
    for cand, kind in candidate_values(value, unit):
        if mention.kind == "plain" and kind in ("usd", "plain"):
            # "383,285" or "383,285 million" style: try common filing scales
            for exp in (0, 6, 3):
                if abs(mention.value * Decimal(10) ** exp - cand) <= mention.tolerance * Decimal(10) ** exp:
                    return True
            continue
        if mention.kind == "ratio" and kind == "percent":
            continue
        if mention.kind != kind and not (mention.kind == "ratio" and kind == "ratio"):
            continue
        if abs(abs(mention.value) - abs(cand)) <= mention.tolerance:
            return True
    return False


def number_in_text(mention: NumberMention, passage: str) -> bool:
    """A narrative number is supported if the same figure appears in the cited passage."""
    for pm in extract_numbers(passage):
        if pm.kind == mention.kind or {pm.kind, mention.kind} <= {"usd", "plain"}:
            tol = max(pm.tolerance, mention.tolerance)
            if abs(abs(pm.value) - abs(mention.value)) <= tol:
                return True
            # passage tables are typically "in millions"
            if pm.kind == "plain" and abs(pm.value * Decimal(10) ** 6 - abs(mention.value)) <= max(tol * Decimal(10) ** 6, mention.tolerance):
                return True
    return False
