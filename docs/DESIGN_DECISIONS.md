# Design decisions

The decisions that shape this system, why each was made, what was rejected, and where it lives in the code.
Each one is written as the answer to a question a reviewer is likely to ask.

---

## 1. Why doesn't the LLM do the math?

**Decision.** Every number in an answer is either a reported XBRL fact or the output of a formula evaluated in
Python `Decimal`. The LLM only plans (when the rules are unsure) and writes prose around numbers it is given.

**Why.** Text-only RAG has to find a figure in prose, and many figures are never stated in prose at all:
free cash flow, debt-to-equity, exact growth rates. The ablation shows the effect: numeric exact match is
0.14–0.21 for text-only pipelines A–C on the 108-question set (0.36 even with Gemini as the reader) and 1.00 once XBRL facts and the `Decimal` engine are used (D/E).

**Rejected.** Letting the LLM compute ("chain of thought arithmetic"): it can be right most of the time, but
it can't be audited, and one wrong digit in a financial answer is a failure.

**Code.** `app/finance/engine.py` (metric results + calculation records), `app/finance/metrics.py` (registry).

## 2. Why a restricted AST evaluator instead of `eval` or generated code?

**Decision.** Formulas are parsed with `ast.parse(mode="eval")`. Only numeric literals, variables bound to
verified facts, `+ - * /`, unary minus and parentheses are allowed; anything else raises `FormulaError`.

**Why.** Formulas may one day be proposed by an LLM planner. A whitelist evaluator means a malicious or
mistaken formula can only produce a wrong number (which verification catches), never execute code.

**Code.** `app/finance/safe_eval.py` (60 lines; the whitelist is the whole security argument).

## 3. Which fiscal year does an XBRL fact belong to?

**Decision.** A fact's fiscal year is taken from the filing whose *own* reporting period ends on the fact's end
date, not from the `fy` field of SEC companyfacts.

**Why.** In companyfacts, `fy` is the fiscal year of the *filing*. A FY2025 10-K re-reports FY2024 and FY2023 as
comparatives, all tagged `fy=2025`. Using `fy` directly assigns three different years' revenue to "FY2025".
Annual facts are recognized by duration (350–380 days, which covers 52/53-week years) or by an instant on a
fiscal-year-end date.

**Code.** `app/ingest/xbrl.py` (`_period_end_by_accession`, `normalize_company_facts`).

## 4. What happens when a later filing restates a number?

**Decision.** The value from the original filing for that fiscal year is canonical. If a later 10-K reports a
different value for the same concept and period, a `FactConflict` is stored and the verifier surfaces it.

**Why.** "What did Apple report for FY2023?" has one answer: what the FY2023 10-K said. Silently swapping in
a recast value (for example NVIDIA's split-adjusted EPS) would make answers disagree with the source document
the citation points to. Surfacing the conflict lets the user see both.

**Code.** `app/ingest/xbrl.py` (conflict detection), `app/verify/auditor.py` (conflict reporting).

## 5. How is a fact traced back to a page in the 10-K?

**Decision.** At ingestion, each canonical fact is looked up in the filing's inline-XBRL tags (concept + period,
non-dimensional contexts only). The rendered value is recomputed from the tag's `scale`/`sign` and must equal the
API value; only then are page, table title and row label attached.

**Why.** A citation like "p. 29, Consolidated Statements of Operations, Total net sales" is checkable by a human
in seconds. Requiring the rendered value to match means a wrong location is left out, never shown.

**Code.** `app/ingest/xbrl.py` (`locate_facts_in_document`), `app/ingest/html_parser.py`.

## 6. Why is verification rule-based instead of an LLM judge?

**Decision.** The auditor checks, in code: citation ids exist; every number matches a cited fact/calculation
(within the precision it is displayed at) or appears in a cited passage; every calculation recomputes from its
stored inputs; inputs re-read from the fact store are unchanged; fiscal years in a sentence match its evidence;
narrative sentences are supported by their passage (lexical overlap, plus cross-encoder score when available).

**Why.** An LLM checking another LLM is not independent evidence. Deterministic checks are reproducible and
testable, and they bound what a prompt injection can achieve: an injected instruction can change wording, but it
cannot get an unsupported number or a fake citation past the verifier.

**Display-precision tolerance.** "$383.3 billion" is accepted for 383,285,000,000 because the display has 0.1B
precision; "$383.9 billion" is rejected. Rounding is allowed, wrong numbers are not.

**Code.** `app/verify/auditor.py`, `app/verify/numbers.py`.

## 7. Why rules first in the planner, with the LLM only as a fallback?

**Decision.** Query classification is regex/keyword rules with a confidence score; an LLM planner is called only
when confidence is below 0.6 (experiment E with an LLM configured). LLM plans are validated against the known
tickers, metric keys and section keys.

**Why.** Rules are free, fast (~1 ms), deterministic and unit-testable. **The cost is brittleness**, which this
project measured rather than assumed: a held-out set of paraphrased questions (`evaluation/gold/heldout_paraphrase.jsonl`)
written after the planner was built scored lower than the original gold set and exposed real phrasing bugs, for
example "in 2024" being treated as a forecast. See the README results section for the numbers.

**Code.** `app/graph/planner.py`; tests in `tests/test_planner_retrieval.py`.

## 8. Why hybrid retrieval with RRF and a cross-encoder?

**Decision.** BM25 and dense (BGE-small, Qdrant) retrieval each return candidates; Reciprocal Rank Fusion
(k=60) merges them; a cross-encoder reranks the top 15 and the best 6 become evidence.

**Why.** 10-K language mixes exact terms (BM25 wins: "State Aid", "Activision") and paraphrase (dense wins).
RRF needs no score calibration between the two, because it only uses ranks. The cross-encoder fixes ordering.
The ablation keeps retrieval and answer quality separate on purpose, and the reranker's value turned out to
depend on the question set: on the original 53 questions (MiniLM reranker) it lifted Hit@10 from 0.93 to 1.00,
but on the 108-question, 10-company set (`bge-reranker-base`) Hit@10 was 0.957 without it and 0.913 with it.
In neither case did it raise end-to-end success for an extractive reader. It stays in the pipeline for MRR on
narrative questions, but this result says it should be re-evaluated per corpus, not assumed to help.

**Calibration caveat.** Cross-encoder logits have a different scale per model, so the "is any passage relevant
enough?" threshold is calibrated per reranker (`RERANKER_SUFFICIENCY_THRESHOLDS` in `app/config.py`), on the main
gold set only. Switching the default reranker without recalibrating made relevant passages look insufficient.

**Code.** `app/retrieval/hybrid.py`, `app/retrieval/reranker.py`, `app/config.py`.

## 9. Why a LangGraph state machine instead of autonomous agents?

**Decision.** Three logical components (planning & retrieval, financial analysis, verification & synthesis) as
fixed graph nodes with two bounded loops: retrieval expansion (max 2 rounds) and draft repair (max 1).

**Why.** Every path through the graph is enumerable and each node emits a trace event, so a run can be explained
step by step. Bounded loops give the "agentic" benefit without unbounded cost or latency. Measured honestly, that
benefit is conditional: with the MiniLM reranker the sufficiency/expansion loop recovered weak first-pass retrieval
(narrative success 0.78 → 1.00 from D to E on 53 questions); with `bge-reranker-base` the first pass is already
sufficient and E = D (0.982) on 108 questions. The repair loop matters only when an LLM writes the draft.

**Code.** `app/graph/workflow.py`.

## 10. Why does everything work with no LLM at all?

**Decision.** `LLM_PROVIDER=offline` (the default) composes answers from verified evidence with deterministic
templates; baselines A–C use an extractive reader that quotes retrieved text and never calculates.

**Why.** It makes the benchmark reproducible at $0, makes CI possible without secrets, and shows which part of
the gain comes from the architecture rather than from a stronger model. With an LLM (e.g. Gemini's free tier),
a model-written draft must still pass verification; a draft that fails twice is replaced by the deterministic
answer.

**Code.** `app/llm/providers.py`, `app/graph/synthesis.py`, `app/graph/extractive.py`.

---

## Known trade-offs

| Trade-off | Current choice | What would change it |
|---|---|---|
| Planner coverage vs. determinism | Rules + optional LLM fallback | A larger paraphrase set showing rules can't keep up → LLM-first planning with rule validation |
| Original vs. restated values | Original filing is canonical | A use case that needs "latest known value" → expose both, let the user choose |
| Debt definition | Term debt + commercial paper + short-term borrowings, leases excluded | Different analyst convention → it's a registry entry in `metrics.py`, shown with every result |
| Conversation memory | In-process LangGraph checkpointer | Multiple API workers → a persistent checkpointer (Postgres) |
| Rate limiting | In-process sliding window | Multiple instances → shared store (Redis) |
