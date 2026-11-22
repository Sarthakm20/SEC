"""Central configuration. Every knob is an env var (see .env.example) so experiments are reproducible."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# quiet third-party model-hub noise (symlink warnings on Windows, progress bars in server logs)
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent

# Calibrated on the MAIN gold set only (the held-out set is never used for tuning):
#   MiniLM-L6: -2.0 (original benchmark tuning).
#   bge-reranker-base (2026-11-22): top-1 score of the 14 main-set narrative questions ranged -4.26 … 6.46
#   (all had a relevant passage); 18 off-topic probes (recipes, sports, weather × 3 companies) scored
#   -10.19 … -3.68. -4.5 keeps every relevant case and rejects 17/18 off-topic probes.
RERANKER_SUFFICIENCY_THRESHOLDS: dict[str, float] = {
    "Xenova/ms-marco-MiniLM-L-6-v2": -2.0,
    "BAAI/bge-reranker-base": -4.5,
}
DEFAULT_SUFFICIENCY_THRESHOLD = -2.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- SEC EDGAR -------------------------------------------------------------------------------
    # SEC fair-access policy: identify yourself with a descriptive User-Agent containing a contact.
    sec_user_agent: str = Field(default="", description="e.g. 'MyApp admin@example.com'")
    sec_max_requests_per_second: float = 8.0  # SEC limit is 10 req/s; stay under it.
    sec_timeout_seconds: float = 30.0

    # --- Initial scope (Recommendations §9.1) -------------------------------------------------------
    default_tickers: list[str] = ["AAPL", "MSFT", "NVDA"]
    default_fiscal_years: list[int] = [2023, 2024, 2025]

    # --- Storage ---------------------------------------------------------------------------------
    data_dir: Path = BACKEND_DIR / "data"
    database_url: str = ""  # empty -> sqlite file under data_dir; docker-compose sets PostgreSQL
    qdrant_url: str = ""  # empty -> embedded Qdrant under data_dir; docker-compose sets the server
    qdrant_collection: str = "sec_chunks"
    qdrant_path: str = ""  # empty -> <data_dir>/qdrant (embedded mode allows one process per path)

    # --- Retrieval -------------------------------------------------------------------------------
    embedding_provider: str = "fastembed"  # fastembed | openai | hash (tests only)
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_provider: str = "fastembed"  # fastembed | cohere | none
    reranker_model: str = "BAAI/bge-reranker-base"  # upgrade from ms-marco-MiniLM-L-6-v2 for higher semantic accuracy on financial footnotes
    retrieval_candidates: int = 25  # per retriever, before fusion (tune on benchmark)
    rerank_top_n: int = 6  # evidence passages handed to synthesis (tune on benchmark)
    rerank_candidates: int = 15  # fused candidates scored by the cross-encoder (CPU cost ~ linear)
    rerank_max_chars: int = 1200  # passage prefix scored by the cross-encoder
    rrf_k: int = 60
    chunk_target_tokens: int = 350
    chunk_overlap_tokens: int = 50
    # Cross-encoder logits are on a different scale for each model, so the "is any passage relevant enough?"
    # threshold is calibrated per reranker (RERANKER_SUFFICIENCY_THRESHOLDS); set this env var to override.
    min_rerank_score_for_sufficiency: float | None = None

    # --- LLM -------------------------------------------------------------------------------------
    llm_provider: str = "auto"  # auto | anthropic | openai | gemini | ollama | offline
    llm_model: str = ""  # empty -> provider default
    llm_effort: str = "medium"  # Anthropic output_config.effort
    llm_max_tokens: int = 4000
    llm_timeout_seconds: float = 120.0
    llm_min_interval_seconds: float | None = None  # pacing between calls; None -> provider default (gemini 6 s)
    llm_rate_limit_retries: int = 3  # per-minute 429 retries (waits for the server-suggested delay)
    ollama_base_url: str = "http://localhost:11434/v1"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    cohere_api_key: str = ""

    # --- API / security ----------------------------------------------------------------------------
    app_api_key: str = ""  # if set, required in X-API-Key header for /api/* (except health)
    rate_limit_per_minute: int = 60
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    max_question_chars: int = 1000

    # --- Agentic loop ----------------------------------------------------------------------------
    max_retrieval_iterations: int = 2

    @property
    def sufficiency_threshold(self) -> float:
        if self.min_rerank_score_for_sufficiency is not None:
            return self.min_rerank_score_for_sufficiency
        return RERANKER_SUFFICIENCY_THRESHOLDS.get(self.reranker_model, DEFAULT_SUFFICIENCY_THRESHOLD)

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{(self.data_dir / 'secrag.db').as_posix()}"

    @property
    def raw_dir(self) -> Path:
        p = self.data_dir / "raw"
        p.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache
def get_settings() -> Settings:
    return Settings()
