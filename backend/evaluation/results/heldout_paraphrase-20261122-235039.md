# Benchmark report — 2026-11-22T18:13:23.427395+00:00

Questions: 29 · LLM: offline/template-synthesizer · embeddings: fastembed:BAAI/bge-small-en-v1.5 · reranker: fastembed:BAAI/bge-reranker-base · corpus: 2130 chunks

| Exp | Hit@10 | Recall@10 | MRR | nDCG@10 | Numeric EM | Cit. precision | Cit. coverage | Faithfulness | Abstention acc. | Task success | p50 ms | Cost/q $ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C | 1.000 | 0.725 | 1.000 | 0.801 | 0.300 | 0.949 | 0.709 | 1.000 | 0.600 | 0.448 | 8301.7 | 0.000 |
| E | 1.000 | 0.725 | 1.000 | 0.801 | 0.850 | 0.904 | 0.795 | 1.000 | 1.000 | 0.828 | 53.0 | 0.000 |

Experiments:
- **C** — Reranked RAG: hybrid → cross-encoder → reader. Answer metrics: computed (extractive reader).
- **E** — Agentic Financial RAG: D + LangGraph routing, iterative retrieval, sufficiency checks. Answer metrics: computed (deterministic template).

Per-category task success:

| Category | C | E |
|---|---|---|
| cross_company | 0.00 | 1.00 |
| cross_year | 0.00 | 1.00 |
| direct_lookup | 0.71 | 0.86 |
| footnote | 1.00 | 0.00 |
| narrative | 1.00 | 0.67 |
| ratio | 0.17 | 0.83 |
| trend | 0.00 | 0.50 |
| unanswerable | 0.60 | 1.00 |
