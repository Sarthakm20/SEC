"""SEC EDGAR HTTP client honoring SEC fair-access rules.

* Descriptive User-Agent with contact information is mandatory (SEC returns 403 otherwise).
* Requests are throttled below the 10 requests/second limit.
* Transient failures (429 / 5xx / network) are retried with exponential backoff.
* Responses are cached on disk so re-ingestion and experiments are reproducible and offline-friendly.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings, get_settings

log = logging.getLogger(__name__)


class SecUserAgentMissing(RuntimeError):
    pass


class _RateLimiter:
    def __init__(self, per_second: float) -> None:
        self.min_interval = 1.0 / max(per_second, 0.1)
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next_allowed - now
            if delay > 0:
                time.sleep(delay)
            self._next_allowed = max(now, self._next_allowed) + self.min_interval


class EdgarClient:
    DATA_BASE = "https://data.sec.gov"
    WWW_BASE = "https://www.sec.gov"

    def __init__(self, settings: Settings | None = None, cache_dir: Path | None = None) -> None:
        self.settings = settings or get_settings()
        ua = self.settings.sec_user_agent.strip()
        if not ua or "@" not in ua:
            raise SecUserAgentMissing(
                "SEC_USER_AGENT must be set to a descriptive name plus contact email, "
                "e.g. 'SECFilingRAG you@example.com' (SEC fair-access policy)."
            )
        self.cache_dir = cache_dir or (self.settings.raw_dir / "http_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._limiter = _RateLimiter(self.settings.sec_max_requests_per_second)
        self._http = httpx.Client(
            headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"},
            timeout=self.settings.sec_timeout_seconds,
            follow_redirects=True,
        )

    # ------------------------------------------------------------------ internals
    def _cache_path(self, url: str, suffix: str) -> Path:
        digest = hashlib.sha256(url.encode()).hexdigest()[:24]
        return self.cache_dir / f"{digest}{suffix}"

    def _get(self, url: str, *, max_attempts: int = 5) -> bytes:
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            self._limiter.wait()
            try:
                resp = self._http.get(url)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
            else:
                if resp.status_code == 200:
                    return resp.content
                if resp.status_code == 403:
                    raise PermissionError(
                        f"SEC returned 403 for {url}. Check SEC_USER_AGENT (needs name + contact email)."
                    )
                if resp.status_code == 404:
                    raise FileNotFoundError(url)
                if resp.status_code not in (429, 500, 502, 503, 504):
                    resp.raise_for_status()
                last_exc = httpx.HTTPStatusError(
                    f"HTTP {resp.status_code}", request=resp.request, response=resp
                )
            backoff = min(2**attempt, 30)
            log.warning("SEC request failed (%s); retrying in %ss: %s", last_exc, backoff, url)
            time.sleep(backoff)
        raise RuntimeError(f"SEC request failed after {max_attempts} attempts: {url}") from last_exc

    def fetch_bytes(self, url: str, *, use_cache: bool = True, suffix: str = ".bin") -> bytes:
        path = self._cache_path(url, suffix)
        if use_cache and path.exists():
            return path.read_bytes()
        data = self._get(url)
        path.write_bytes(data)
        return data

    def fetch_json(self, url: str, *, use_cache: bool = True) -> Any:
        return json.loads(self.fetch_bytes(url, use_cache=use_cache, suffix=".json"))

    # ------------------------------------------------------------------ endpoints
    def submissions(self, cik: int, *, use_cache: bool = True) -> dict[str, Any]:
        return self.fetch_json(f"{self.DATA_BASE}/submissions/CIK{cik:010d}.json", use_cache=use_cache)

    def company_facts(self, cik: int, *, use_cache: bool = True) -> dict[str, Any]:
        return self.fetch_json(
            f"{self.DATA_BASE}/api/xbrl/companyfacts/CIK{cik:010d}.json", use_cache=use_cache
        )

    def company_tickers(self) -> dict[str, Any]:
        return self.fetch_json(f"{self.WWW_BASE}/files/company_tickers.json")

    def filing_document(self, url: str) -> bytes:
        if not url.startswith(self.WWW_BASE + "/Archives/"):
            raise ValueError("Only SEC EDGAR archive URLs may be fetched")
        return self.fetch_bytes(url, suffix=".htm")

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "EdgarClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
