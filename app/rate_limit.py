"""
Rate limiting middleware and dependency for the Todo API.

Uses Redis for atomic per-org sliding window counters.
Fails open (allows requests) when Redis is unavailable.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RATE_LIMIT_REQUESTS: int = 10   # max requests per window
RATE_LIMIT_WINDOW: int = 60     # window size in seconds


# ---------------------------------------------------------------------------
# Redis client factory
# ---------------------------------------------------------------------------

def get_redis_client():
    """Return a Redis client instance. Raises on import/connection failure."""
    import redis  # type: ignore

    client = redis.Redis(host="localhost", port=6379, db=0, socket_connect_timeout=1)
    return client


# ---------------------------------------------------------------------------
# Core rate-limit check (atomic via Lua)
# ---------------------------------------------------------------------------

LUA_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local current = redis.call('INCR', key)
if current == 1 then
    redis.call('EXPIRE', key, window)
end
return current
"""


def check_rate_limit(
    org_id: str,
    redis_client,
    limit: int = RATE_LIMIT_REQUESTS,
    window: int = RATE_LIMIT_WINDOW,
) -> dict:
    """
    Atomically increment the request counter for *org_id* and check against
    *limit*.

    Returns a dict with keys:
        - ``allowed``  (bool)  – whether the request is within the limit
        - ``count``    (int)   – current request count
        - ``retry_after`` (int | None) – seconds until window resets (only when
          ``allowed`` is False)

    Raises ``ConnectionError`` if Redis is unavailable (caller decides
    fail-open / fail-closed behaviour).
    """
    key = f"rate_limit:{org_id}"
    current = redis_client.eval(LUA_SCRIPT, 1, key, limit, window)
    current = int(current)

    if current > limit:
        ttl = redis_client.ttl(key)
        retry_after = int(ttl) if ttl and ttl > 0 else window
        return {"allowed": False, "count": current, "retry_after": retry_after}

    return {"allowed": True, "count": current, "retry_after": None}


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

def rate_limit_dependency(
    request: Request,
    redis_client=Depends(get_redis_client),
) -> None:
    """
    FastAPI dependency that enforces per-org rate limiting.

    Reads ``X-Org-ID`` from request headers.  If the header is absent the
    request is allowed through (org_id defaults to ``"anonymous"`` so it
    still counts against a shared bucket).

    Raises ``HTTPException(429)`` when the limit is exceeded.
    Fails open (returns ``None``) when Redis is unavailable.
    """
    org_id: str = request.headers.get("X-Org-ID", "anonymous")

    try:
        result = check_rate_limit(org_id, redis_client)
    except Exception as exc:  # Redis down → fail open
        logger.warning("Rate limit Redis error (fail-open): %s", exc)
        return None

    if not result["allowed"]:
        retry_after = result["retry_after"]
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )

    return None


# ---------------------------------------------------------------------------
# Starlette middleware variant
# ---------------------------------------------------------------------------

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces per-org rate limiting for every request.

    Reads ``X-Org-ID`` header; falls back to ``"anonymous"``.
    Fails open when Redis is unavailable.
    """

    def __init__(self, app, redis_client=None, limit: int = RATE_LIMIT_REQUESTS, window: int = RATE_LIMIT_WINDOW) -> None:
        super().__init__(app)
        self._redis_client = redis_client
        self._limit = limit
        self._window = window

    def _get_redis(self):
        if self._redis_client is not None:
            return self._redis_client
        return get_redis_client()

    async def dispatch(self, request: Request, call_next):
        org_id: str = request.headers.get("X-Org-ID", "anonymous")

        try:
            client = self._get_redis()
            result = check_rate_limit(org_id, client, self._limit, self._window)
        except Exception as exc:
            logger.warning("Rate limit middleware Redis error (fail-open): %s", exc)
            return await call_next(request)

        if not result["allowed"]:
            retry_after = result["retry_after"]
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)
