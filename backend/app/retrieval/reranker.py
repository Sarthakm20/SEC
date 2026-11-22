"""Cross-encoder reranking (fastembed ONNX cross-encoders, or Cohere Rerank API).

Note: reranker scores measure query–passage relevance, not answer correctness (Recommendations §7).
"""

from __future__ import annotations

from typing import Protocol

import httpx

from app.config import Settings, get_settings


class Reranker(Protocol):
    name: str

    def score(self, query: str, documents: list[str]) -> list[float]: ...


class FastEmbedReranker:
    def __init__(self, model: str, cache_dir: str | None = None) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self.name = f"fastembed:{model}"
        try:  # use the cached model without contacting the HF hub
            self._model = TextCrossEncoder(model_name=model, cache_dir=cache_dir, local_files_only=True)
        except Exception:
            self._model = TextCrossEncoder(model_name=model, cache_dir=cache_dir)

    def score(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        return [float(s) for s in self._model.rerank(query, documents, batch_size=32)]


class CohereReranker:
    def __init__(self, api_key: str, model: str = "rerank-v3.5") -> None:
        self.name = f"cohere:{model}"
        self._key = api_key
        self._model = model

    def score(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        resp = httpx.post(
            "https://api.cohere.com/v2/rerank",
            headers={"Authorization": f"Bearer {self._key}"},
            json={"model": self._model, "query": query, "documents": documents},
            timeout=30,
        )
        resp.raise_for_status()
        out = [0.0] * len(documents)
        for r in resp.json()["results"]:
            out[r["index"]] = float(r["relevance_score"])
        return out


def build_reranker(settings: Settings | None = None) -> Reranker | None:
    s = settings or get_settings()
    if s.reranker_provider == "none":
        return None
    if s.reranker_provider == "cohere":
        return CohereReranker(s.cohere_api_key, s.reranker_model if s.reranker_model.startswith("rerank") else "rerank-v3.5")
    return FastEmbedReranker(s.reranker_model, cache_dir=str(s.data_dir / "models"))
