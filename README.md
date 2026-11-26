# SEC 10-K Verifiable Financial Intelligence Platform

[![CI](https://github.com/Sarthakm20/SEC/actions/workflows/ci.yml/badge.svg)](https://github.com/Sarthakm20/SEC/actions/workflows/ci.yml)

Answers questions about SEC 10-K filings with **numbers you can audit**. Reported figures come from SEC
XBRL (the filer's own tagged values), every derived metric is computed in Python `Decimal` with a
recorded formula, narrative context comes from hybrid retrieval over the 10-K text, and a
deterministic verification layer checks every citation and every number in the answer before it is shown.

Built from `SEC_Filing_Agentic_RAG_Blueprint.docx` and `SEC_Filing_Agentic_RAG_Recommendations_with_Visuals.docx`.
Scope: 10 companies across tech, retail and banking (AAPL, MSFT, NVDA, AMZN, GOOGL, META, ORCL, WMT, COST, JPM),
10-K text for each filer's four latest fiscal years (FY2023–2026; FY2022–2025 for the calendar-year filers AMZN,
GOOGL, META and JPM, whose FY2026 10-K is not out yet) plus the full XBRL history. Fiscal years follow each filer's
convention (Walmart ends in January, Oracle in May, Costco in August/September). The benchmark results below were
measured on the FY2023–2025 text, before the extra year was added. Design rationale: [`docs/DESIGN_DECISIONS.md`](docs/DESIGN_DECISIONS.md).

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

## Results

Three question sets, all with expected values cross-checked against raw SEC XBRL facts (`python -m evaluation.crosscheck_gold`):

| Set | Questions | Written | Used for tuning? |
|---|---|---|---|
| Main (`gold/questions.jsonl`) | 108 over 10 companies | 53 with the system, 55 added for the 10-company expansion before the system saw them | yes (it is the development set) |
| Held-out v1 (`gold/heldout_paraphrase.jsonl`) | 29 paraphrases | after the planner was built | its failures were fixed, so it is no longer blind |
| Held-out v2 (`gold/heldout_v2.jsonl`) | 20, all 10 companies | after all fixes, [committed before its first run](https://github.com/Sarthakm20/SEC/commit/96c0491) | never |

### Generalization (the honest number)

| | Text-only RAG (C) | This system (E) |
|---|---|---|
| Held-out v1, **blind** run | 0.448 | **0.759** right for the right reason (0.828 as scored; 2 "abstentions" were accidental, see below) |
| 55 new main-set questions, before any fix | — | **0.909** |
| Held-out v2, **blind** run | 0.350 | **0.950** (19/20) |

The blind runs found real bugs, each fixed with a regression test: "in 2024" was treated as a forecast; "Meta" did not
resolve to META; older 10-Ks of frequent filers (JPM, META) sat on paginated EDGAR pages that were never read; Walmart's
table-formatted headings and Alphabet's table-formatted page header broke section parsing; the sufficiency threshold
had been tuned for a different reranker. Two v1 trap questions ("market cap", "good investment") only *looked*
correct because that miscalibrated threshold made the answer say "Not available"; fixing the threshold exposed them.
Held-out v2's one miss: "What is Costco's dividend yield?" is answered instead of refused (dividend yield needs a share price).

### Main set: ablation (108 questions, $0, no LLM)

| Pipeline | Hit@10 | MRR | nDCG@10 | Numeric EM | Citation precision | Correct abstentions | Task success | p50 latency |
|---|---|---|---|---|---|---|---|---|
| A · dense → reader | 0.913 | 0.792 | 0.589 | 0.143 | 0.870 | 0.50 | 0.287 | 1.5 s |
| B · BM25 + dense → RRF → reader | 0.957 | 0.829 | 0.617 | 0.208 | 0.880 | 0.30 | 0.343 | 1.6 s |
| C · B + cross-encoder rerank | 0.913 | 0.744 | 0.607 | 0.208 | 0.891 | 0.30 | 0.333 | 8.9 s |
| D · XBRL + Decimal + verification | 0.957 | 0.764 | 0.626 | **1.000** | **0.940** | **1.00** | **0.982** | 81 ms |
| E · D + agentic loop | 0.957 | 0.764 | 0.626 | **1.000** | **0.940** | **1.00** | **0.982** | 97 ms |

A–C are from the run before the last three fixes (`benchmark-20261123-022408.json`); D–E after them. Reranker:
`bge-reranker-base`. Original 53 questions: E = 1.000; the 55 new ones: 0.964.

| Task success by category | n | A | B | C | D | E |
|---|---|---|---|---|---|---|
| direct lookup | 25 | 0.32 | 0.44 | 0.48 | 1.00 | 1.00 |
| cross-year | 12 | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 |
| ratio | 21 | 0.10 | 0.19 | 0.19 | 1.00 | 1.00 |
| cross-company | 9 | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 |
| trend | 8 | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 |
| narrative | 16 | 0.81 | 0.88 | 0.88 | 0.94 | 0.94 |
| footnote | 5 | 0.40 | 0.80 | 0.60 | 0.80 | 0.80 |
| multi-hop | 2 | 0.50 | 0.50 | 0.00 | 1.00 | 1.00 |
| unanswerable | 10 | 0.50 | 0.30 | 0.30 | 1.00 | 1.00 |

How to read it:
- **The structured path is the big win.** Text-only RAG gets 14–21% of numeric answers exactly right; XBRL facts + `Decimal` math get 100%. Baselines fail on figures the 10-K never states in prose (free cash flow, margins, growth), on the wrong figure for the right words, and on every cross-company and multi-year question.
- **Abstention** comes from the verification-first design: baselines answer forecasts and market-data questions with whatever text they retrieve (30–50% correct abstentions vs. 100%).
- **Reranking did not help on this corpus.** C ranks *worse* than B (Hit@10 0.913 vs 0.957, MRR 0.744 vs 0.829) at 5× the latency; on the original 53 questions with MiniLM it had lifted Hit@10 from 0.93 to 1.00. Retrieval and answer quality are measured separately precisely so results like this show up.
- **E = D on this set.** With `bge-reranker-base` the first retrieval pass is already sufficient, so the sufficiency/expansion loop adds no measured gain here; with the earlier MiniLM reranker it lifted narrative success from 0.78 to 1.00.
- **Remaining main-set misses:** q059 asks about AWS *segment* sales and gets Amazon's total revenue (segment-level metrics are not in the registry); q108 retrieves the wrong part of Alphabet's tax note.

### With an LLM reader (Gemini, free tier)

The critique of the table above is that A–C use a weak extractive reader. So the best text-only pipeline (B) and the
full system (E) were also run with `gemini-3.5-flash-lite` writing the answers (`benchmark-20261123-043646.json`):

| Pipeline (Gemini reader) | Numeric EM | Correct abstentions | False abstentions | Faithfulness | Answers failing verification | Task success |
|---|---|---|---|---|---|---|
| B · hybrid RAG → Gemini | 0.364 | 0.60 | 0.32 | 0.840 | **10 of 108** | 0.491 |
| E · this system, Gemini writes the prose | **1.000** | **1.00** | 0.02 | **0.987** | 0 | **0.982** |

- An LLM reader lifts text-only RAG from 0.343 to 0.491 task success, but the gap to E stays large: without
  structured facts the model still cannot produce figures the 10-K never states. **10 of B's answers failed
  verification** (a number not found in any evidence, or a citation to evidence that does not exist); B reports the
  verdict but does not enforce it. It also refused 32% of answerable questions.
- In E, Gemini wrote all 98 answers to answerable questions; the 10 unanswerable ones are refused before any LLM call
  (that is the "MIXED 98/108" in the report). The verifier and the `Decimal` engine keep numeric accuracy at 1.000
  whichever model writes the prose. The run cost $0 (about 111k input / 17k output tokens for E).
- A first attempt with `gemini-3.5-flash` ran out of its free daily quota after about 20 calls; the runner fell back
  cleanly and the report now says so explicitly (kept as `gemini-3.5-flash-quota-exhausted-*.json`).

## Quick start (local, no Docker)

Requirements: Python 3.11+, Node 20+.

```bash
cp .env.example .env            # set SEC_USER_AGENT="YourApp you@example.com" (SEC requires a contact)

cd backend
python -m venv .venv && .venv/Scripts/activate      # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements.lock.txt
# full corpus used by the UI: all 10 companies, four fiscal years each (~50 min on CPU, downloads ~150 MB of models)
python -m app.cli ingest --tickers AAPL MSFT NVDA ORCL WMT COST --years 2023 2024 2025 2026
python -m app.cli ingest --tickers AMZN GOOGL META JPM --years 2022 2023 2024 2025
# or a quick start: python -m app.cli ingest   (AAPL, MSFT, NVDA × FY2023–2025, ~10 min)
python -m app.cli ask "How did Apple's revenue change in fiscal 2025 compared to fiscal 2024?"
uvicorn app.api.main:app --port 8000

cd ../frontend
npm install && npm run build && npm start           # http://localhost:3000  (proxies /api to :8000)
```

Other commands:

```bash
python -m app.cli ingest --tickers AMZN GOOGL --years 2024 2025   # any SEC filer by ticker
python -m app.cli status
python -m pytest -q                                               # 81 tests, offline (synthetic company, hash embeddings)
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
docker compose exec backend python -m app.cli ingest     # quick start; for the full corpus run the two ingest commands above via exec
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
- Fiscal-year labels follow each filer's convention (NVIDIA's FY2025 ended January 2025); comparisons say so explicitly. XBRL facts cover more years than the ingested 10-K text; the Overview only offers years whose text is ingested, and questions about other years are answered from XBRL figures without narrative.
- JPMorgan's 10-K titles its MD&A "Management's discussion and analysis" rather than "Item 7", so JPM has no `item_7` section; MD&A questions for JPM fall back to other sections.
- Restated values: the original filing's value is canonical and later restatements are flagged (e.g. NVIDIA's split-adjusted EPS).
- Debt-to-equity uses term debt + commercial paper + short-term borrowings (excludes leases); the definition is shown with every result.
- Gold values are cross-checked against raw XBRL and each lists its 10-K line item, but they have not yet been signed off by a human reviewer.
