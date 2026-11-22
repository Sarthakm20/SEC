"""Qdrant vector store (embedded local mode for dev; server URL in docker-compose)."""

from __future__ import annotations

import uuid
from pathlib import Path
from dataclasses import dataclass

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.config import Settings, get_settings
from app.models import Chunk

_NS = uuid.UUID("6f1c2f8e-6a3e-4a8a-9c64-1f0d6c9b9a11")


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_NS, chunk_id))


@dataclass
class DenseHit:
    chunk_id: str
    score: float


class VectorStore:
    def __init__(self, dim: int, embedder_name: str, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if self.settings.qdrant_url:
            self.client = QdrantClient(url=self.settings.qdrant_url, timeout=30)
        else:
            path = Path(self.settings.qdrant_path) if self.settings.qdrant_path else self.settings.data_dir / "qdrant"
            path.mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(path))
        # one collection per embedding model so switching models never mixes vector spaces
        safe = embedder_name.replace("/", "_").replace(":", "_").replace(".", "_")
        self.collection = f"{self.settings.qdrant_collection}__{safe}"
        self.dim = dim
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                self.collection,
                vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
            )
            for field, schema in () if not self.settings.qdrant_url else (
                ("ticker", qm.PayloadSchemaType.KEYWORD),
                ("fiscal_year", qm.PayloadSchemaType.INTEGER),
                ("section", qm.PayloadSchemaType.KEYWORD),
                ("accession", qm.PayloadSchemaType.KEYWORD),
            ):
                try:
                    self.client.create_payload_index(self.collection, field, schema)
                except Exception:  # local mode ignores payload indexes
                    pass

    def count(self) -> int:
        return self.client.count(self.collection).count

    def delete_accession(self, accession: str) -> None:
        self.client.delete(
            self.collection,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(must=[qm.FieldCondition(key="accession", match=qm.MatchValue(value=accession))])
            ),
        )

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        points = [
            qm.PointStruct(
                id=point_id(c.id),
                vector=v,
                payload={
                    "chunk_id": c.id,
                    "ticker": c.ticker,
                    "fiscal_year": c.fiscal_year,
                    "section": c.section,
                    "accession": c.accession,
                    "kind": c.kind,
                },
            )
            for c, v in zip(chunks, vectors)
        ]
        for i in range(0, len(points), 256):
            self.client.upsert(self.collection, points=points[i : i + 256])

    def search(
        self,
        vector: list[float],
        limit: int,
        tickers: list[str] | None = None,
        fiscal_years: list[int] | None = None,
        sections: list[str] | None = None,
    ) -> list[DenseHit]:
        must: list[qm.Condition] = []
        if tickers:
            must.append(qm.FieldCondition(key="ticker", match=qm.MatchAny(any=tickers)))
        if fiscal_years:
            must.append(qm.FieldCondition(key="fiscal_year", match=qm.MatchAny(any=fiscal_years)))
        if sections:
            must.append(qm.FieldCondition(key="section", match=qm.MatchAny(any=sections)))
        res = self.client.query_points(
            self.collection,
            query=vector,
            query_filter=qm.Filter(must=must) if must else None,
            limit=limit,
            with_payload=["chunk_id"],
        )
        return [DenseHit(chunk_id=p.payload["chunk_id"], score=float(p.score)) for p in res.points]

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass
