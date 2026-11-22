---
title: SEC 10-K Verifiable Financial Q&A
emoji: 📊
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
short_description: Audit-ready answers over SEC 10-K filings (XBRL + RAG)
---

Ask questions about the 10-K filings of the ingested companies. Every number comes from SEC XBRL data or a
recorded `Decimal` calculation, and every answer is checked by a deterministic verifier before it is shown.

This demo runs **offline** (no LLM, $0): answers are composed from verified evidence by templates.
Source code, benchmark and design notes: https://github.com/Sarthakm20/SEC

The first start takes a few minutes while the embedding and reranker models download.
