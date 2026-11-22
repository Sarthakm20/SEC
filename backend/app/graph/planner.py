"""Query planning: classification + decomposition.

Rules first (deterministic, cheap, testable). An LLM is consulted only when the rules cannot tell
what is being asked (Recommendations §3.2: "LLM when ambiguity or decomposition warrants it").
"""

from __future__ import annotations

import json
import re
from datetime import date

from app.companies import aliases_for, resolve_tickers
from app.finance.metrics import DERIVED, REPORTED
from app.llm.base import LLM, LLMError, UsageTracker
from app.models import Company, QueryPlan, QueryType

RATIO_METRICS = {"gross_margin", "operating_margin", "net_margin", "debt_to_equity", "current_ratio", "rd_intensity"}

_GROWTH_WORDS = re.compile(r"\b(grow|grew|growth|change[ds]?|increase[ds]?|decrease[ds]?|decline[ds]?|rise|rose|fell|fall|drop(ped)?|compared?\s+(to|with)|vs\.?|versus|yoy|year[- ]over[- ]year)\b", re.I)
_TREND_WORDS = re.compile(r"\b(trend|over\s+the\s+(last|past)\s+\w+\s+years?|since\s+(fy)?\s*20\d\d|each\s+year|multi[- ]year|history|evolv\w*|over\s+time)\b", re.I)
_ALL_COMPANIES = re.compile(r"\b(which\s+compan(y|ies)|all\s+(three\s+)?compan(y|ies)|across\s+(the\s+)?compan(y|ies)|each\s+compan(y|ies)|these\s+compan(y|ies))\b", re.I)
_FORECAST = re.compile(
    r"\b(will\s+be|forecast|predict|projection|next\s+(?:fiscal\s+)?years?|forward\s+(?:pe|p/e|estimates?|guidance)|"
    r"analyst\s+consensus|stock\s+price|share\s+price|target\s+price|should\s+i\s+(buy|sell|invest))\b",
    re.I,
)


def _mentions_future_year(years: list[int]) -> bool:
    """A year after the current calendar year cannot be in any filed 10-K. ("in 2024" is a lookup, not a forecast.)"""
    return any(y > date.today().year for y in years)

_POSSESSIVE_NAME = re.compile(r"\b([A-Z][A-Za-z0-9&.\-]{1,30})(?:'s|’s)\b")
_NOT_A_COMPANY = {"what", "it", "that", "there", "here", "who", "where", "how", "let", "today", "year", "company", "management", "industry", "world", "america", "europe", "china", "taiwan"}
_POLICY_ONLY = re.compile(r"\b(recogni[sz]e[sd]?|accounting\s+polic\w*|account\s+for|policy\s+on|how\s+does\s+\w+\s+(define|measure|treat))\b", re.I)
_NUMERIC_ASK = re.compile(r"\b(how\s+much|what\s+(was|were|is|are)\s+(the\s+)?(\w+'s\s+)?(total|amount|revenue|net|operating|gross|free|r&d|diluted)|amount|figure|value|grow|growth|change[ds]?|increase|decrease|compare|trend|margin|ratio)\b", re.I)
_SHARE_OF_REVENUE = re.compile(r"\b(percent(age)?|share|proportion|fraction|%)\s+of\s+(its\s+|their\s+|total\s+)?(revenue|net\s+sales|sales)\b", re.I)
_RISK_CUE = re.compile(r"\brisks?\b|\bthreats?\b|\bvulnerab", re.I)


def unknown_company(question: str, companies: list[Company]) -> str | None:
    """A possessive proper noun ("Tesla's revenue") that is not an ingested company."""
    known = {a for c in companies for a in aliases_for(c)}
    for m in _POSSESSIVE_NAME.finditer(question):
        name = m.group(1)
        if name.lower() not in known and name.lower() not in _NOT_A_COMPANY:
            return name
    return None


NARRATIVE_CUES: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"\brisks?\b|\bthreats?\b|\buncertaint|\bvulnerab|\bexposure\b", re.I), ["item_1a"]),
    (re.compile(r"\bsupply\s+chain|\bsupplier|\bmanufactur|\bsingle[- ]source|\bgeopolit|\bexport\s+control|\btariff|\bchina\b|\btaiwan\b", re.I), ["item_1a", "item_7"]),
    (re.compile(r"\bwhy\b|\bdriv(e|er|ers|en|ing)\b|\bdrove\b|\bcaus(e|ed|es)\b|\battribut|\bexplain|\breason|\bdue\s+to\b|\bcontribut|\bprimarily\b|\bfactors?\b", re.I), ["item_7"]),
    (re.compile(r"\bmd&a\b|\bmanagement'?s?\s+discussion|\boutlook\b|\bliquidity\b|\bcapital\s+return|\bbuyback|\brepurchase|\bdividend", re.I), ["item_7"]),
    (re.compile(r"\baccounting\s+polic|\brecogni[sz]e|\brevenue\s+recognition|\bfootnote|\bnotes?\s+to\b|\bleases?\b|\bincome\s+tax|\beffective\s+tax|\bstock[- ]based\s+compensation|\bgoodwill|\bderivative|\bcontingenc|\blitigation|\blegal\s+proceeding|\bsegment", re.I), ["notes", "item_7"]),
    (re.compile(r"\bcompetit|\bstrateg|\bproducts?\b|\bbusiness\s+model|\bemployees|\bhuman\s+capital|\bcustomers?\b|\bmarkets?\s+(they|it)\s+serve|\bdescribe\s+(the|its|their)\s+business", re.I), ["item_1", "item_1a"]),
    (re.compile(r"\binterest\s+rate\s+risk|\bforeign\s+(currency|exchange)|\bmarket\s+risk|\bhedg", re.I), ["item_7a"]),
    (re.compile(r"\bai\b|\bartificial\s+intelligence|\bdata\s+cent(er|re)|\bcloud\b|\bregulat|\bantitrust|\bprivacy|\bcyber", re.I), ["item_1a", "item_7", "item_1"]),
    (re.compile(r"\bdescribe|\bdiscuss|\bmention|\bsay\s+about|\bwhat\s+does\s+the\s+10-k|\baccording\s+to|\bdisclos", re.I), []),
]

_YEAR = re.compile(r"\b(?:fy\s*'?|fiscal\s+(?:year\s+)?)?(20\d\d)\b", re.I)
_FY_SHORT = re.compile(r"\bfy\s*'?(\d\d)\b", re.I)
_LAST_N = re.compile(r"\b(?:last|past|previous)\s+(two|three|four|five|\d)\s+(?:fiscal\s+)?years?\b", re.I)
_FYP = r"(?:fy\s*|fiscal\s+(?:year\s+)?)?"
_RANGE = re.compile(r"\b(?:from\s+)?" + _FYP + r"(20\d\d)\s*(?:-|–|to|through|until)\s*" + _FYP + r"(20\d\d)\b", re.I)
_LATEST = re.compile(r"\b(latest|most\s+recent|current|last\s+fiscal\s+year|this\s+year)\b", re.I)
_NUM_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5}


def _synonym_table() -> list[tuple[str, str]]:
    table: list[tuple[str, str]] = []
    for key, m in DERIVED.items():
        table += [(s, key) for s in m.synonyms]
    for key, it in REPORTED.items():
        table += [(s, key) for s in it.synonyms]
    return sorted(table, key=lambda x: -len(x[0]))


_SYNONYMS = _synonym_table()


def extract_metrics(text: str) -> list[str]:
    lowered = " " + text.lower().replace("’", "'") + " "
    found: list[tuple[int, str]] = []
    taken: list[tuple[int, int]] = []
    for phrase, key in _SYNONYMS:
        for m in re.finditer(rf"(?<![a-z]){re.escape(phrase)}(?:s|es)?(?![a-z])", lowered):
            span = (m.start(), m.end())
            if any(not (span[1] <= a or span[0] >= b) for a, b in taken):
                continue
            taken.append(span)
            found.append((m.start(), key))
    ordered: list[str] = []
    for _, k in sorted(found):
        if k not in ordered:
            ordered.append(k)
    return ordered


def extract_years(text: str, available: list[int]) -> tuple[list[int], list[str]]:
    notes: list[str] = []
    years: set[int] = set()
    latest = max(available) if available else None
    m = _RANGE.search(text)
    if m:
        a, b = sorted((int(m.group(1)), int(m.group(2))))
        if b - a <= 10:
            years.update(range(a, b + 1))
    for m in _YEAR.finditer(text):
        years.add(int(m.group(1)))
    for m in _FY_SHORT.finditer(text):
        years.add(2000 + int(m.group(1)))
    m = _LAST_N.search(text)
    if m and latest:
        n = _NUM_WORDS.get(m.group(1).lower(), None) or int(m.group(1))
        years.update(range(latest - n + 1, latest + 1))
        notes.append(f"'{m.group(0)}' resolved to FY{latest - n + 1}–FY{latest}")
    if not years and _LATEST.search(text) and latest:
        years.add(latest)
        notes.append(f"'latest' resolved to FY{latest}")
    return sorted(years), notes


def rule_plan(
    question: str,
    companies: list[Company],
    available_years: dict[str, list[int]],
    previous: QueryPlan | None = None,
) -> tuple[QueryPlan, float]:
    """Returns (plan, confidence 0..1)."""
    notes: list[str] = []
    tickers = resolve_tickers(question, companies)
    if not tickers and _ALL_COMPANIES.search(question):
        tickers = [c.ticker for c in companies]
        notes.append("question refers to all ingested companies")
    is_followup = bool(previous) and len(question.split()) <= 12 and bool(
        re.match(r"^\s*(and|what\s+about|how\s+about|same\s+for|now|also|vs\.?|compared)", question, re.I)
    )
    same_company = False
    if not tickers and previous and previous.tickers:
        tickers = list(previous.tickers)
        same_company = True
        notes.append("company carried over from the previous question in this conversation")
    elif tickers and previous and previous.tickers and set(tickers) == set(previous.tickers):
        same_company = True

    pool = sorted({y for t in (tickers or [c.ticker for c in companies]) for y in available_years.get(t, [])})
    years, ynotes = extract_years(question, pool)
    notes += ynotes
    metrics = extract_metrics(question)
    if "rd_expense" in metrics and _SHARE_OF_REVENUE.search(question):
        # "what percentage of revenue went to R&D" asks for the ratio, not two separate amounts
        metrics = ["rd_intensity"] + [m for m in metrics if m not in ("rd_expense", "revenue", "rd_intensity")]
    if not metrics and is_followup and previous:
        metrics = list(previous.metrics)
        if metrics:
            notes.append("metric carried over from the previous question")
    if not years and is_followup and previous and previous.fiscal_years:
        if same_company or not tickers:
            years = list(previous.fiscal_years)
            notes.append(f"fiscal year FY{years} carried over from previous question for same company")
        else:
            # Different company: inherit only if year is available, and add period clarification note
            avail_for_tickers = [available_years.get(t, []) for t in tickers]
            common_years = [y for y in previous.fiscal_years if all(y in av for av in avail_for_tickers)]
            if common_years:
                years = common_years
                notes.append(f"fiscal year FY{years} carried over to {', '.join(tickers)} (verify filing dates)")

    sections: list[str] = []
    narrative_hits = 0
    for pat, secs in NARRATIVE_CUES:
        if pat.search(question):
            narrative_hits += 1
            for s in secs:
                if s not in sections:
                    sections.append(s)
    # "revenue growth" contains a growth word but is a numeric question; narrative needs a real cue
    needs_narrative = narrative_hits > 0
    if needs_narrative and metrics and _POLICY_ONLY.search(question) and not _NUMERIC_ASK.search(question):
        notes.append("accounting-policy question: metric words treated as topic, not as a number request")
        metrics = []
    if _RISK_CUE.search(question) and not metrics:
        # risk questions are answered from Item 1A first (Item 7A for market risk); expansion can widen later
        sections = [s_ for s_ in sections if s_ in ("item_1a", "item_7a")] or ["item_1a"]
    if is_followup and previous and not metrics and not needs_narrative:
        needs_narrative = previous.needs_narrative
        sections = list(previous.sections)
    needs_facts = bool(metrics)
    growth = bool(_GROWTH_WORDS.search(question))
    trend = bool(_TREND_WORDS.search(question)) or len(years) >= 3

    confidence = 0.9
    named = resolve_tickers(question, companies)
    stranger = None if named else unknown_company(question, companies)
    if stranger:
        qtype = QueryType.OUT_OF_SCOPE
        tickers = []
        notes.append(f"'{stranger}' is not among the ingested companies ({', '.join(c.ticker for c in companies)}); run ingestion for it first")
    elif (_FORECAST.search(question) or _mentions_future_year(years)) and not needs_narrative:
        qtype = QueryType.OUT_OF_SCOPE
        notes.append("forecasts, stock prices and investment advice are not contained in 10-K filings")
    elif not tickers:
        qtype = QueryType.OUT_OF_SCOPE if not (metrics or needs_narrative) else QueryType.NARRATIVE
        if qtype == QueryType.NARRATIVE:
            tickers = [c.ticker for c in companies]
            notes.append("no company named; searching all ingested companies")
            confidence = 0.5
        else:
            notes.append("no ingested company, metric or filing topic recognized")
            confidence = 0.3
    elif not (metrics or needs_narrative):
        qtype = QueryType.NARRATIVE
        needs_narrative = True
        confidence = 0.4
    elif len(tickers) > 1 and metrics:
        qtype = QueryType.CROSS_COMPANY
    elif metrics and needs_narrative:
        qtype = QueryType.HYBRID
    elif metrics and trend:
        qtype = QueryType.TREND
    elif metrics and (growth or len(years) == 2):
        qtype = QueryType.CROSS_YEAR
    elif metrics and any(m in RATIO_METRICS or m in ("free_cash_flow", "total_debt") for m in metrics):
        qtype = QueryType.RATIO
    elif metrics:
        qtype = QueryType.FACT_LOOKUP
    else:
        qtype = QueryType.NARRATIVE

    # growth phrasing on a reported item -> compute YoY growth too
    if metrics and growth and qtype in (QueryType.CROSS_YEAR, QueryType.HYBRID, QueryType.CROSS_COMPANY) and len(years) <= 1:
        for m in list(metrics):
            if m in REPORTED and REPORTED[m].unit == "USD" and f"{m}_growth" not in metrics:
                metrics.append(f"{m}_growth")  # engine computes any <item>_growth with the YoY formula
    if needs_narrative and not sections:
        sections = ["item_1a", "item_7", "item_1"]

    plan = QueryPlan(
        query_type=qtype,
        tickers=tickers,
        fiscal_years=years,
        metrics=metrics,
        needs_facts=needs_facts and qtype != QueryType.OUT_OF_SCOPE,
        needs_narrative=needs_narrative and qtype != QueryType.OUT_OF_SCOPE,
        sections=sections,
        narrative_query=question if needs_narrative else None,
        sub_questions=[f"{t}: {question}" for t in tickers] if len(tickers) > 1 and needs_narrative else [],
        planner="rules",
        notes=notes,
    )
    return plan, confidence


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "query_type": {"type": "string", "enum": [q.value for q in QueryType]},
        "tickers": {"type": "array", "items": {"type": "string"}},
        "fiscal_years": {"type": "array", "items": {"type": "integer"}},
        "metrics": {"type": "array", "items": {"type": "string"}},
        "needs_narrative": {"type": "boolean"},
        "sections": {"type": "array", "items": {"type": "string"}},
        "narrative_query": {"type": "string"},
    },
    "required": ["query_type", "tickers", "fiscal_years", "metrics", "needs_narrative", "sections", "narrative_query"],
    "additionalProperties": False,
}

PLANNER_SYSTEM = """You classify questions about SEC 10-K filings for a financial research system.
Return JSON only. Use only tickers, metric keys and section keys from the lists provided.
query_type meanings: fact_lookup (one reported number), cross_year (change between years), ratio (derived ratio),
cross_company (compare companies), trend (3+ years), narrative (risks/explanations/policies text), hybrid (numbers + explanation),
out_of_scope (not answerable from 10-K filings: forecasts, stock prices, advice, unrelated topics).
narrative_query: a concise search query for the narrative part (empty string if none)."""


def llm_plan(question: str, companies: list[Company], available_years: dict[str, list[int]], llm: LLM, tracker: UsageTracker) -> QueryPlan | None:
    user = (
        f"Question: {question}\n\n"
        f"Ingested companies: {json.dumps({c.ticker: c.name for c in companies})}\n"
        f"Fiscal years available: {json.dumps(available_years)}\n"
        f"Metric keys: {json.dumps(sorted(list(REPORTED) + list(DERIVED)))}\n"
        "Section keys: item_1 (Business), item_1a (Risk Factors), item_7 (MD&A), item_7a (Market risk), notes (Notes to financial statements)"
    )
    try:
        resp = llm.complete(PLANNER_SYSTEM, user, max_tokens=1500, json_schema=PLAN_SCHEMA)
        tracker.record_llm(resp)
        data = json.loads(resp.text)
    except (LLMError, json.JSONDecodeError, ValueError):
        return None
    valid_t = {c.ticker for c in companies}
    valid_m = set(REPORTED) | set(DERIVED)
    valid_s = {"item_1", "item_1a", "item_7", "item_7a", "notes"}
    try:
        qtype = QueryType(data.get("query_type"))
    except ValueError:
        return None
    metrics = [m for m in data.get("metrics", []) if m in valid_m]
    needs_narr = bool(data.get("needs_narrative"))
    return QueryPlan(
        query_type=qtype,
        tickers=[t for t in data.get("tickers", []) if t in valid_t],
        fiscal_years=[int(y) for y in data.get("fiscal_years", []) if isinstance(y, int) and 1990 < y < 2100],
        metrics=metrics,
        needs_facts=bool(metrics) and qtype != QueryType.OUT_OF_SCOPE,
        needs_narrative=needs_narr and qtype != QueryType.OUT_OF_SCOPE,
        sections=[s for s in data.get("sections", []) if s in valid_s] or (["item_1a", "item_7"] if needs_narr else []),
        narrative_query=(data.get("narrative_query") or question) if needs_narr else None,
        planner="llm",
        notes=["planned by LLM because rule-based classification was ambiguous"],
    )
