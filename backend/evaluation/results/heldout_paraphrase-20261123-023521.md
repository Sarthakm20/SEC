# Benchmark report — 2026-11-22T20:54:41.386690+00:00

Questions: 29 · LLM: offline/template-synthesizer · embeddings: fastembed:BAAI/bge-small-en-v1.5 · reranker: fastembed:BAAI/bge-reranker-base · corpus: 9792 chunks

| Exp | Hit@10 | Recall@10 | MRR | nDCG@10 | Numeric EM | Cit. precision | Cit. coverage | Faithfulness | Abstention acc. | Task success | p50 ms | Cost/q $ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C | 1.000 | 0.800 | 1.000 | 0.859 | 0.300 | 0.962 | 0.709 | 1.000 | 0.600 | 0.448 | 12829.5 | 0.000 |
| E | 1.000 | 0.800 | 1.000 | 0.859 | 1.000 | 0.972 | 0.822 | 1.000 | 0.600 | 0.931 | 82.6 | 0.000 |

Experiments:
- **C** — Reranked RAG: hybrid → cross-encoder → reader. Answer metrics: computed (extractive reader).
- **E** — Agentic Financial RAG: D + LangGraph routing, iterative retrieval, sufficiency checks. Answer metrics: computed (deterministic template).

Per-category task success:

| Category | C | E |
|---|---|---|
| cross_company | 0.00 | 1.00 |
| cross_year | 0.00 | 1.00 |
| direct_lookup | 0.71 | 1.00 |
| footnote | 1.00 | 1.00 |
| narrative | 1.00 | 1.00 |
| ratio | 0.17 | 1.00 |
| trend | 0.00 | 1.00 |
| unanswerable | 0.60 | 0.60 |
