"""Lazily constructed singletons shared by the API, CLI and evaluation harness."""

from __future__ import annotations

import threading
from functools import cached_property

from app.config import Settings, get_settings
from app.db import repo
from app.finance.engine import FinancialEngine
from app.retrieval.embeddings import Embedder, build_embedder
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.reranker import Reranker, build_reranker
from app.retrieval.vector_store import VectorStore


class Services:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._lock = threading.Lock()

    @cached_property
    def embedder(self) -> Embedder:
        return build_embedder(self.settings)

    @cached_property
    def store(self) -> VectorStore:
        return VectorStore(self.embedder.dim, self.embedder.name, self.settings)

    @cached_property
    def reranker(self) -> Reranker | None:
        return build_reranker(self.settings)

    @cached_property
    def retriever(self) -> HybridRetriever:
        return HybridRetriever(self.embedder, self.store, self.reranker, repo.load_all_chunks(), self.settings)

    @cached_property
    def engine(self) -> FinancialEngine:
        return FinancialEngine()

    @cached_property
    def llm(self):
        from app.llm.providers import build_llm

        return build_llm(self.settings)

    def refresh_indexes(self) -> None:
        with self._lock:
            if "retriever" in self.__dict__:
                self.retriever.refresh(repo.load_all_chunks())
            if "engine" in self.__dict__:
                self.engine.invalidate()


_services: Services | None = None
_slock = threading.Lock()


def get_services() -> Services:
    global _services
    with _slock:
        if _services is None:
            _services = Services()
        return _services
