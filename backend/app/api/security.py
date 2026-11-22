"""API key check and in-memory per-client rate limiting."""

from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request, status

from app.config import get_settings


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = get_settings().app_api_key
    if expected and not (x_api_key and secrets.compare_digest(x_api_key, expected)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or invalid X-API-Key")


class RateLimiter:
    """Sliding-window limiter (per client IP). Use a shared store such as Redis when scaling out."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, request: Request) -> None:
        if self.per_minute <= 0:
            return
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                retry = int(60 - (now - q[0])) + 1
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded", headers={"Retry-After": str(retry)})
            q.append(now)


_limiter: RateLimiter | None = None


def rate_limit(request: Request) -> None:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter(get_settings().rate_limit_per_minute)
    _limiter.check(request)
