# SEC 10-K Verifiable Financial Intelligence Platform

[![CI](https://github.com/Sarthakm20/SEC/actions/workflows/ci.yml/badge.svg)](https://github.com/Sarthakm20/SEC/actions/workflows/ci.yml)

Answers questions about SEC 10-K filings with **numbers you can audit**. Reported figures come from SEC
XBRL (the filer's own tagged values), every derived metric is computed in Python `Decimal` with a
recorded formula, narrative context comes from hybrid retrieval over the 10-K text, and a
deterministic verification layer checks every citation and every number in the answer before it is shown.

Built from `SEC_Filing_Agentic_RAG_Blueprint.docx` and `SEC_Filing_Agentic_RAG_Recommendations_with_Visuals.docx`.
Scope: 10 companies across tech, retail and banking (AAPL, MSFT, NVDA, AMZN, GOOGL, META, ORCL, WMT, COST, JPM),
fiscal years 2023–2025 of 10-K text plus the full XBRL history. Fiscal years follow each filer's convention
(Walmart ends in January, Oracle in May, Costco in August/September). Design rationale: [`docs/DESIGN_DECISIONS.md`](docs/DESIGN_DECISIONS.md).

```
                     Next.js + Tailwind + Recharts  (Overview · Research assistant · Compare · Inspector · Benchmark)
                                         │  /api/* proxied
                     FastAPI  (validation, API key, rate limit, audit log, structured errors)
                                         │
        LangGraph  plan ─► financials ─► retrieve ─► sufficiency ⟲ expand ─► synthesize ─► verify ⟲ repair ─► answer
                     │          │            │                                 │              │
             rules (+LLM if   XBRL facts   BM25 + Qdrant dense                 LLM or       citation ids, number matching,
             ambiguous)       + Decimal    → RRF → cross-encoder               deterministic recompute, source re-read, periods,
                              engine                                           template      conflicts, claim support → verdict
                                         │
     SEC data layer: EDGAR submissions · companyfacts XBRL · 10-K inline-XBRL HTML     Knowledge layer: Qdrant · BM25 · PostgreSQL/SQLite
```

## Results (gold benchmark, 53 questions)

`python -m evaluation.run_benchmark` — latest run (`backend/evaluation/results/`):

All five pipelines run with no LLM ($0): A–C answer with the extractive reader (quotes from retrieved text,
no calculations), D–E with deterministic synthesis over verified evidence.

| Pipeline | Hit@10 | MRR | nDCG@10 | Numeric EM | Citation precision | Correct abstentions | Task success | p50 latency |
|---|---|---|---|---|---|---|---|---|
| A · dense → reader | 0.929 | 0.839 | 0.667 | 0.167 | 0.918 | 0.400 | 0.340 | 490 ms |
| B · BM25 + dense → RRF → reader | 0.929 | 0.827 | 0.677 | 0.250 | **0.941** | 0.400 | 0.415 | 534 ms |
| C · B + cross-encoder rerank | **1.000** | **0.907** | **0.712** | 0.222 | 0.922 | 0.400 | 0.396 | 2.0 s |
| D · XBRL + Decimal + verification | 1.000 | 0.907 | 0.712 | **1.000** | 0.921 | **1.000** | 0.943 | 29 ms |
| E · D + agentic loop (iterative retrieval, sufficiency, repair) | 1.000 | 0.907 | 0.712 | **1.000** | 0.921 | **1.000** | **0.981** | 29 ms |

| Task success by category | A | B | C | D | E |
|---|---|---|---|---|---|
| direct lookup (12) | 0.33 | 0.58 | 0.58 | 1.00 | 1.00 |
| cross-year (6) | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 |
| ratio (9) | 0.11 | 0.11 | 0.11 | 1.00 | 1.00 |
| cross-company (4) | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 |
| trend (3) | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 |
| narrative (9) | 0.89 | 1.00 | 0.89 | 0.78 | 1.00 |
| footnote (3) | 0.67 | 0.67 | 1.00 | 0.67 | 0.67 |
| multi-hop (2) | 0.50 | 0.50 | 0.00 | 1.00 | 1.00 |
| unanswerable (5) | 0.40 | 0.40 | 0.40 | 1.00 | 1.00 |

How to read it:
- **The structured path is the big win.** Text-only RAG gets 17–25% of numeric answers exactly right; with XBRL facts + Decimal calculations it is 100%. Baselines fail mostly on numbers the 10-K never states in prose (free cash flow, debt-to-equity, exact growth rates), on the wrong figure for the right words (Microsoft *Cloud* growth instead of total revenue growth), and on cross-company / multi-year questions.
- **Abstention** comes from the verification-first design: baselines confidently answer "Tesla's revenue" with NVIDIA passages and "NVIDIA's stock price" with employee-stock-plan text (40% correct abstentions vs. 100%).
- **Reranking** lifts retrieval (Hit@10 0.93 → 1.00, MRR 0.83 → 0.91) but not end-to-end success for an extractive reader (B 0.415 vs C 0.396): better-ranked passages are not always the ones with quotable figures. Retrieval quality and answer quality need separate measurement, which is the point of the ablation.
- **E vs. D**: the sufficiency check + query expansion recovers narrative questions where the first retrieval pass is weak (narrative 0.78 → 1.00).
- Faithfulness is 1.0 for every pipeline and is not shown: verbatim quotes are trivially "supported". Exact match and citation precision are the discriminating metrics here; faithfulness becomes informative once an LLM paraphrases.
- Remaining E miss (q041, "How does Apple recognize revenue"): the MiniLM reranker ranks Apple's "Basis of presentation" note above the revenue-recognition passage. Trying `RERANKER_MODEL=BAAI/bge-reranker-base` is the next experiment.

Gold-set integrity: `python -m evaluation.crosscheck_gold` matches **34/34 reported gold values** exactly against SEC XBRL facts (independent of the QA pipeline); 27 derived values (percentages/ratios) list their formula for human review. Two relevance labels were corrected after inspection and are annotated in the file (`label_note`). Gold values have not yet been signed off by a human reviewer.

## Quick start (local, no Docker)

Requirements: Python 3.11+, Node 20+.

```bash
cp .env.example .env            # set SEC_USER_AGENT="YourApp you@example.com" (SEC requires a contact)

cd backend
python -m venv .venv && .venv/Scripts/activate      # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements.lock.txt
python -m app.cli ingest                            # AAPL, MSFT, NVDA × FY2023–2025 (~10 min on CPU, downloads ~150 MB of models)
python -m app.cli ask "How did Apple's revenue change in fiscal 2025 compared to fiscal 2024?"
uvicorn app.api.main:app --port 8000

cd ../frontend
npm install && npm run build && npm start           # http://localhost:3000  (proxies /api to :8000)
```

Other commands:

```bash
python -m app.cli ingest --tickers AMZN GOOGL --years 2024 2025   # any SEC filer by ticker
python -m app.cli status
python -m pytest -q                                               # 74 tests, offline (synthetic company, hash embeddings)
python -m evaluation.crosscheck_gold                              # gold values vs raw SEC XBRL facts
python -m evaluation.run_benchmark [--experiments D E] [--limit 20]
python -m evaluation.run_benchmark --gold evaluation/gold/heldout_paraphrase.jsonl --experiments C E
python -m app.cli test-llm                                        # check the configured LLM key + model
```

CI (GitHub Actions) runs the tests, the frontend typecheck/build, and builds all three Docker images on every push.

Embedded Qdrant allows one process per storage folder; the benchmark automatically works on a snapshot copy so it can run while the API is up.

## Docker (production topology: PostgreSQL + Qdrant server)

```bash
cp .env.example .env    # set SEC_USER_AGENT (and an LLM key if wanted)
docker compose up -d --build
docker compose exec backend python -m app.cli ingest
# UI http://localhost:3000 · API http://localhost:8000/docs
```

## Public demo (Hugging Face Spaces, free CPU tier)

`deploy/huggingface/` builds one container: the Next.js UI on port 7860 proxying to FastAPI, with a read-only
snapshot of the ingested data. The demo runs `LLM_PROVIDER=offline`, so visitors cannot spend an API quota.

```bash
pip install -U huggingface_hub && hf auth login          # token with write access
# create a Space at https://huggingface.co/new-space  (SDK: Docker, Blank)
bash deploy/huggingface/push_space.sh <hf-username>/<space-name>
```

## LLM configuration (optional — the platform runs at $0 without one)

The default is `LLM_PROVIDER=offline`: answers are composed deterministically from the verified facts,
calculations and passages. Retrieval, the financial engine, verification and experiments D/E work identically;
only the prose is plainer. Baselines A–C are answered by an **extractive reader** (`app/graph/extractive.py`):
it quotes retrieved sentences and table cells (reading the requested fiscal-year column), never calculates, and
has no scope routing, so they are measured end to end at $0.

| Provider | Cost | Setting | Notes |
|---|---|---|---|
| Offline (default) | free | `LLM_PROVIDER=offline` | Deterministic synthesis; no data leaves the machine except SEC downloads |
| Gemini | free tier | `LLM_PROVIDER=gemini`, `GEMINI_API_KEY`, `LLM_MODEL` | Google AI Studio key; rate-limited, and free tiers change |
| Ollama | free, local | `LLM_PROVIDER=ollama`, `LLM_MODEL` | Needs a GPU or a fast CPU and ≥16 GB RAM to be practical |
| Anthropic / OpenAI | paid | `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | Anthropic default `claude-opus-5-5` with refusal fallback |

Using Gemini for free: create **one** API key at Google AI Studio (a Gemini app subscription does not include API
access; free-tier limits are per project, so extra keys add nothing). Set `LLM_PROVIDER=gemini`, `GEMINI_API_KEY=…`
and `LLM_MODEL=gemini-3.5-flash-lite` in `.env`, run `python -m app.cli test-llm`, and restart the API. Free-tier
quotas are per model: `gemini-3.5-flash` ran out after about 20 requests in a day, `gemini-3.5-flash-lite` handled a full benchmark. Older models
return 404 "no longer available to new users"; a 503 means "high demand, retry later".

Free-tier handling is built in: calls are paced (`LLM_MIN_INTERVAL_SECONDS`, default 6 s), per-minute 429s wait for
the delay Google suggests, and a used-up *daily* quota fails fast. Failed calls fall back to the template/extractive
reader, and the report's `readers_used` shows exactly which reader answered each question (flagged as MIXED when
they differ). A full benchmark is several hundred calls; run one experiment at a time (`--experiments A`) if the
daily quota runs out.

The LLM only (a) plans when the rule-based planner is unsure and (b) writes prose. It never does arithmetic,
and its draft must pass verification: a draft with an unsupported number or an invalid citation is sent back
once with the auditor's findings, and if it fails again it is replaced by the deterministic answer.
Token usage and estimated cost are recorded per query.

## How the recommendations were implemented

| Recommendation | Implementation |
|---|---|
| XBRL is the source of truth for numbers (§3.1) | `app/ingest/xbrl.py`: companyfacts → annual facts. Fiscal year derived from each filing's own period (the API's `fy` is the *filing's* year); duplicates across filings resolved to the original report; restatements recorded as conflicts |
| Dual-path ingestion, HTML for narrative (§3.1) | `app/ingest/html_parser.py`: one pass yields page-aware blocks, printed page numbers, Items 1/1A/7/7A + Notes (longest span wins over the table of contents), bold sub-headings, tables as row-preserving chunks |
| Evidence-aware citations (§4.4) | Every XBRL fact is located in the 10-K's inline-XBRL tags: page, statement title, row label, and the displayed value is cross-checked against the API value (e.g. AAPL FY2025 revenue → p. 29, Consolidated Statements of Operations, "Total net sales"). Chunks carry accession, section, sub-section, pages, URL |
| Three components, not four agents (§3.2) | LangGraph nodes; only planning-under-ambiguity and prose use an LLM |
| Deterministic engine (§4.1) | `app/finance/`: concept registry with per-company concept resolution, `Decimal`, AST-sandboxed formula evaluator, calculation records (formula, inputs, periods, accession, definition, warnings); unit, period-type, period-alignment, prior-year spacing, definition-change and gross-profit identity checks |
| Verification instead of "zero hallucination" (§3.3) | `app/verify/auditor.py`: citation existence, number-to-evidence matching with displayed-precision tolerance, recomputation, source-fact re-read, period validation, conflict surfacing, claim support (lexical + cross-encoder), abstention; verdict = verified / partially verified / not enough evidence / failed |
| Hybrid retrieval + reranking (Blueprint §3) | BM25 + Qdrant (BGE) → RRF → cross-encoder; candidate counts are settings tuned via the benchmark |
| Cross-company + period alignment (§4.2) | `/api/compare` with fiscal-label or calendar-overlap alignment and explicit period notes |
| Evaluation + ablation (§3.4) | `backend/evaluation/`: gold set, Recall/Hit/MRR/nDCG, numeric EM/error, citation precision/coverage, faithfulness, abstention, task success, latency, cost; experiments A–E |
| Security (§4.5) | Injection scan at ingestion, evidence isolation in delimited blocks, sandboxed math (no generated code runs), input limits, optional API key, rate limit, audit log, SEC-only fetch allowlist |
| Persistence & reproducibility (§4.6) | PostgreSQL/SQLite for companies, filings, facts, conflicts, chunks, query runs, calculation logs; LangGraph checkpointer; follow-up questions inherit company/year/metric per conversation thread |
| Execution trace, not thought logs (§6.1) | Each node emits an observable event ("Retrieved 34 candidate passages · reranked to 6", "Verified 8/8 citations · 10/10 numbers") |
| Model-provider abstraction + cost tracking (§5.1–5.2) | `app/llm/` |

## Project layout

```
backend/
  app/sec/            EDGAR client (User-Agent, ≤8 req/s, retries, disk cache), filing discovery
  app/ingest/         XBRL normalization + fact locator, 10-K HTML parser, chunker, pipeline
  app/finance/        metric registry, Decimal engine, sandboxed evaluator, formatting
  app/retrieval/      embeddings, Qdrant store, BM25, reranker, hybrid retriever
  app/verify/         number extraction, evidence auditor
  app/graph/          planner, evidence registry, synthesis, LangGraph workflow, entry point
  app/llm/            Anthropic / OpenAI-compatible / offline providers, usage tracking
  app/api/            FastAPI app, security
  evaluation/         gold questions (main + held-out), metrics, cross-check, benchmark runner, results
  tests/              unit + end-to-end tests
frontend/             Next.js app (Overview, Research assistant, Compare, Inspector, Benchmark)
deploy/huggingface/   single-container demo for Hugging Face Spaces
docs/                 DESIGN_DECISIONS.md: the main design choices and their trade-offs
.github/workflows/    CI
docker-compose.yml    postgres, qdrant, backend, frontend
```

## Known limitations

- Without an LLM, baselines A–C use the extractive reader, a weaker reader than an LLM would be; with a (free) Gemini key the same benchmark measures LLM-read baselines instead.
- The default reranker is `BAAI/bge-reranker-base` (~1 GB, about 8 s per reranked question on a laptop CPU). `RERANKER_MODEL=Xenova/ms-marco-MiniLM-L-6-v2` is much faster. The sufficiency threshold is calibrated per reranker.
- The rule-based planner is brittle to phrasing it has not seen; the held-out set measures this (see Results).
- Fiscal-year labels follow each filer's convention (NVIDIA's FY2025 ended January 2025); comparisons say so explicitly. XBRL facts can be newer than the ingested 10-K text (FY2026 facts exist for several filers), so "latest" may resolve to a year with numbers but no narrative.
- JPMorgan's 10-K titles its MD&A "Management's discussion and analysis" rather than "Item 7", so JPM has no `item_7` section; MD&A questions for JPM fall back to other sections.
- Restated values: the original filing's value is canonical and later restatements are flagged (e.g. NVIDIA's split-adjusted EPS).
- Debt-to-equity uses term debt + commercial paper + short-term borrowings (excludes leases); the definition is shown with every result.
- Gold values are cross-checked against raw XBRL and each lists its 10-K line item, but they have not yet been signed off by a human reviewer.
