"""Test configuration: isolate every test run in a temporary data dir with offline, model-free components."""

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="secrag-test-")
os.environ.update(
    {
        "DATA_DIR": _TMP,
        "DATABASE_URL": "",
        "QDRANT_URL": "",
        "EMBEDDING_PROVIDER": "hash",
        "RERANKER_PROVIDER": "none",
        "LLM_PROVIDER": "offline",
        "SEC_USER_AGENT": "SECFilingRAG-tests test@example.com",
        "RATE_LIMIT_PER_MINUTE": "1000",
        "APP_API_KEY": "",
    }
)
