"""Embedding provider abstraction (BGE via fastembed by default; replaceable)."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

from app.config import Settings, get_settings


class Embedder(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    def __init__(self, model: str, cache_dir: str | None = None) -> None:
        from fastembed import TextEmbedding

        self.name = f"fastembed:{model}"
        try:  # use the cached model without contacting the HF hub
            self._model = TextEmbedding(model_name=model, cache_dir=cache_dir, local_files_only=True)
        except Exception:
            self._model = TextEmbedding(model_name=model, cache_dir=cache_dir)
        self.dim = len(next(iter(self._model.embed(["dimension probe"]))))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.passage_embed(texts, batch_size=32)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._model.query_embed(text))).tolist()


class OpenAIEmbedder:
    def __init__(self, model: str, api_key: str) -> None:
        from openai import OpenAI

        self.name = f"openai:{model}"
        self._client = OpenAI(api_key=api_key or None)
        self._model = model
        self.dim = len(self.embed_query("dimension probe"))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 256):
            resp = self._client.embeddings.create(model=self._model, input=texts[i : i + 256])
            out.extend(d.embedding for d in resp.data)
        return out

    def embed_query(self, text: str) -> list[float]:
        return self._client.embeddings.create(model=self._model, input=[text]).data[0].embedding


class HashEmbedder:
    """Deterministic hashed bag-of-words embedding. For tests / fully offline smoke runs only."""

    def __init__(self, dim: int = 384) -> None:
        self.name = f"hash:{dim}"
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0 if (h >> 8) & 1 else -1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def build_embedder(settings: Settings | None = None) -> Embedder:
    s = settings or get_settings()
    if s.embedding_provider == "openai":
        return OpenAIEmbedder(s.embedding_model or "text-embedding-3-small", s.openai_api_key)
    if s.embedding_provider == "hash":
        return HashEmbedder()
    return FastEmbedEmbedder(s.embedding_model, cache_dir=str(s.data_dir / "models"))
