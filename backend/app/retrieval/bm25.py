"""BM25 lexical index — guarantees exact matching of financial terms, tags and fiscal periods."""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from rank_bm25 import BM25Okapi

from app.ingest.chunker import index_text
from app.models import Chunk

_TOKEN = re.compile(r"[a-z0-9]+(?:[&'.\-][a-z0-9]+)*")
_STOP = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the this to was were will with "
    "what which who how did does do our we their they them than then there these those".split()
)


def tokenize(text: str) -> list[str]:
    toks = []
    for t in _TOKEN.findall(text.lower()):
        t = t.strip(".'")
        if t and t not in _STOP:
            toks.append(t)
            if "-" in t or "&" in t:  # also index parts: "debt-to-equity" -> debt, equity
                toks.extend(p for p in re.split(r"[-&]", t) if p and p not in _STOP)
    return toks


@dataclass
class LexicalHit:
    chunk_id: str
    score: float


class BM25Index:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.ids = [c.id for c in chunks]
        self.tickers = np.array([c.ticker for c in chunks]) if chunks else np.array([])
        self.years = np.array([c.fiscal_year for c in chunks]) if chunks else np.array([])
        self.sections = np.array([c.section for c in chunks]) if chunks else np.array([])
        corpus = [tokenize(index_text(c)) for c in chunks]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    def __len__(self) -> int:
        return len(self.ids)

    def search(
        self,
        query: str,
        limit: int,
        tickers: list[str] | None = None,
        fiscal_years: list[int] | None = None,
        sections: list[str] | None = None,
    ) -> list[LexicalHit]:
        if self._bm25 is None:
            return []
        q = tokenize(query)
        if not q:
            return []
        scores = self._bm25.get_scores(q)
        mask = np.ones(len(self.ids), dtype=bool)
        if tickers:
            mask &= np.isin(self.tickers, tickers)
        if fiscal_years:
            mask &= np.isin(self.years, fiscal_years)
        if sections:
            mask &= np.isin(self.sections, sections)
        scores = np.where(mask, scores, -np.inf)
        top = np.argsort(-scores)[:limit]
        return [LexicalHit(self.ids[i], float(scores[i])) for i in top if np.isfinite(scores[i]) and scores[i] > 0]
