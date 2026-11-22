"""Hybrid retrieval: BM25 + dense (Qdrant) -> Reciprocal Rank Fusion -> cross-encoder rerank.

Modes map directly onto the ablation study:
  A: mode="dense", rerank=False      B: mode="hybrid", rerank=False      C/D/E: mode="hybrid", rerank=True
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from app.config import Settings, get_settings
from app.ingest.chunker import index_text
from app.models import Chunk, RetrievalScores, RetrievedChunk
from app.retrieval.bm25 import BM25Index
from app.retrieval.embeddings import Embedder
from app.retrieval.reranker import Reranker
from app.retrieval.vector_store import VectorStore


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return scores


@dataclass
class RetrievalFilters:
    tickers: list[str] | None = None
    fiscal_years: list[int] | None = None
    sections: list[str] | None = None

    def describe(self) -> str:
        parts = []
        if self.tickers:
            parts.append("tickers=" + ",".join(self.tickers))
        if self.fiscal_years:
            parts.append("FY=" + ",".join(map(str, self.fiscal_years)))
        if self.sections:
            parts.append("sections=" + ",".join(self.sections))
        return "; ".join(parts) or "none"


@dataclass
class RetrievalResult:
    passages: list[RetrievedChunk]
    candidates: int
    bm25_hits: int
    dense_hits: int
    timings_ms: dict[str, float] = field(default_factory=dict)
    mode: str = "hybrid"
    reranked: bool = False


class HybridRetriever:
    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        reranker: Reranker | None,
        chunks: list[Chunk],
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.embedder = embedder
        self.store = store
        self.reranker = reranker
        self._lock = threading.Lock()
        self.refresh(chunks)

    def refresh(self, chunks: list[Chunk]) -> None:
        with self._lock:
            self.chunks = {c.id: c for c in chunks}
            self.bm25 = BM25Index(chunks)

    def retrieve(
        self,
        query: str,
        filters: RetrievalFilters | None = None,
        mode: str = "hybrid",
        rerank: bool = True,
        candidates: int | None = None,
        top_n: int | None = None,
    ) -> RetrievalResult:
        f = filters or RetrievalFilters()
        k = candidates or self.settings.retrieval_candidates
        n = top_n or self.settings.rerank_top_n
        timings: dict[str, float] = {}
        scores: dict[str, RetrievalScores] = {}

        bm25_ids: list[str] = []
        if mode in ("hybrid", "bm25"):
            t0 = time.perf_counter()
            hits = self.bm25.search(query, k, f.tickers, f.fiscal_years, f.sections)
            timings["bm25"] = (time.perf_counter() - t0) * 1000
            for r, h in enumerate(hits, 1):
                scores.setdefault(h.chunk_id, RetrievalScores()).bm25_rank = r
                scores[h.chunk_id].bm25_score = round(h.score, 4)
            bm25_ids = [h.chunk_id for h in hits]

        dense_ids: list[str] = []
        if mode in ("hybrid", "dense"):
            t0 = time.perf_counter()
            qv = self.embedder.embed_query(query)
            hits_d = self.store.search(qv, k, f.tickers, f.fiscal_years, f.sections)
            timings["dense"] = (time.perf_counter() - t0) * 1000
            for r, h in enumerate(hits_d, 1):
                if h.chunk_id not in self.chunks:
                    continue
                scores.setdefault(h.chunk_id, RetrievalScores()).dense_rank = r
                scores[h.chunk_id].dense_score = round(h.score, 4)
            dense_ids = [h.chunk_id for h in hits_d if h.chunk_id in self.chunks]

        rankings = [r for r in (bm25_ids, dense_ids) if r]
        fused = reciprocal_rank_fusion(rankings, self.settings.rrf_k)
        for cid, s in fused.items():
            scores[cid].rrf_score = round(s, 6)
        ordered = sorted(fused, key=lambda c: -fused[c])[:k]

        reranked = False
        if rerank and self.reranker is not None and ordered:
            t0 = time.perf_counter()
            head, tail = ordered[: self.settings.rerank_candidates], ordered[self.settings.rerank_candidates :]
            docs = [index_text(self.chunks[c])[: self.settings.rerank_max_chars] for c in head]
            rs = self.reranker.score(query, docs)
            timings["rerank"] = (time.perf_counter() - t0) * 1000
            for cid, s in zip(head, rs):
                scores[cid].rerank_score = round(s, 4)
            ordered = [c for c, _ in sorted(zip(head, rs), key=lambda x: -x[1])] + tail
            reranked = True

        passages = [RetrievedChunk(chunk=self.chunks[c], scores=scores[c]) for c in ordered[:n]]
        return RetrievalResult(
            passages=passages,
            candidates=len(fused),
            bm25_hits=len(bm25_ids),
            dense_hits=len(dense_ids),
            timings_ms={k2: round(v, 1) for k2, v in timings.items()},
            mode=mode,
            reranked=reranked,
        )
