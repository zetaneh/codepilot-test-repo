"""
FastAPI dependency providers.

rate_limit_trigger — enforces a per-org sliding-window rate limit backed by
Redis.  All raw Redis calls are confined to this module so that route handlers
remain free of infrastructure concerns.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

from fastapi import Depends, HTTPException, Request, status

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional Redis integration
# ---------------------------------------------------------------------------
# We import redis lazily so that the application can still start (and tests
# can still run) without a live Redis instance — the dependency falls back to
# an in-process counter in that case.

try:
    import redis as _redis_lib  # type: ignore

    _redis_client: Optional[_redis_lib.Redis] = _redis_lib.Redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
        socket_connect_timeout=1,
    )
except Exception:  # pragma: no cover
    _redis_client = None

# Fallback in-process store used when Redis is unavailable (testing / local).
_in_process_store: dict[str, list[float]] = {}

# Rate-limit configuration (can be overridden via env vars).
_RATE_LIMIT_MAX_CALLS: int = int(os.getenv("RATE_LIMIT_MAX_CALLS", "10"))
_RATE_LIMIT_WINDOW_SECONDS: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))


def _check_rate_limit_in_process(org_id: str) -> bool:
    """Sliding-window rate limiter backed by a plain Python dict.

    Returns *True* when the request is allowed, *False* when the limit has
    been exceeded.
    """
    now = time.monotonic()
    window_start = now - _RATE_LIMIT_WINDOW_SECONDS
    calls = _in_process_store.get(org_id, [])
    # Evict timestamps that fall outside the current window.
    calls = [t for t in calls if t > window_start]
    if len(calls) >= _RATE_LIMIT_MAX_CALLS:
        return False
    calls.append(now)
    _in_process_store[org_id] = calls
    return True


def _check_rate_limit_redis(org_id: str) -> bool:  # pragma: no cover
    """Sliding-window rate limiter backed by Redis sorted sets.

    Returns *True* when the request is allowed, *False* when the limit has
    been exceeded.
    """
    assert _redis_client is not None
    key = f"rate_limit:trigger:{org_id}"
    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW_SECONDS

    pipe = _redis_client.pipeline()
    pipe.zremrangebyscore(key, "-inf", window_start)
    pipe.zcard(key)
    pipe.zadd(key, {str(now): now})
    pipe.expire(key, _RATE_LIMIT_WINDOW_SECONDS + 1)
    results = pipe.execute()

    current_count: int = results[1]  # count *before* adding the new entry
    if current_count >= _RATE_LIMIT_MAX_CALLS:
        # Roll back the zadd we just performed.
        _redis_client.zrem(key, str(now))
        return False
    return True


async def rate_limit_trigger(request: Request) -> None:
    """FastAPI dependency that enforces per-org rate limiting for the trigger
    endpoint.

    The *org_id* is extracted from the JSON request body.  A 429 response is
    returned when the caller has exceeded the allowed call rate.
    """
    try:
        body = await request.json()
        org_id: str = body.get("org_id", "__unknown__")
    except Exception:
        org_id = "__unknown__"

    allowed: bool
    if _redis_client is not None:
        try:
            allowed = _check_rate_limit_redis(org_id)
        except Exception as exc:  # pragma: no cover
            logger.warning("Redis rate-limit check failed, falling back to in-process: %s", exc)
            allowed = _check_rate_limit_in_process(org_id)
    else:
        allowed = _check_rate_limit_in_process(org_id)

    if not allowed:
        logger.warning("Rate limit exceeded for org_id=%s", org_id)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for org '{org_id}'. Please retry later.",
        )
