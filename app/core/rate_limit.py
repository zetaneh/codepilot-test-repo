"""
Async rate-limiting core logic using Redis Lua scripting for atomic operations.
"""
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

_LUA_SCRIPT = """
local key = KEYS[1]
local window = tonumber(ARGV[1])
local current = redis.call('INCR', key)
if current == 1 then
    redis.call('EXPIRE', key, window)
end
local ttl = redis.call('TTL', key)
return {current, ttl}
"""


@dataclass
class RateLimitResult:
    allowed: bool
    current: int
    limit: int
    retry_after: int


async def check_rate_limit(org_id: str, redis_client: Optional[Any]) -> RateLimitResult:
    """
    Check whether the given org_id is within its rate limit using an atomic
    Redis Lua script (INCR + EXPIRE in a single round-trip).

    Reads RATE_LIMIT_MAX_REQUESTS (default 100) and RATE_LIMIT_WINDOW_SECONDS
    (default 60) from environment variables.

    Fails open — returns allowed=True with zeroed counters — when redis_client
    is None or any exception is raised during the Redis call.
    """
    max_requests: int = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "100"))
    window_seconds: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

    if redis_client is None:
        logger.warning(
            "check_rate_limit: redis_client is None for org_id=%s; failing open", org_id
        )
        return RateLimitResult(allowed=True, current=0, limit=max_requests, retry_after=0)

    key: str = f"rate_limit:trigger:{org_id}"

    try:
        result = await redis_client.eval(_LUA_SCRIPT, 1, key, window_seconds)
        count: int = int(result[0])
        ttl: int = int(result[1])
    except Exception as exc:
        logger.error(
            "check_rate_limit: Redis error for org_id=%s key=%s: %s; failing open",
            org_id,
            key,
            exc,
        )
        return RateLimitResult(allowed=True, current=0, limit=max_requests, retry_after=0)

    allowed: bool = count <= max_requests
    retry_after: int = ttl if not allowed else 0

    return RateLimitResult(
        allowed=allowed,
        current=count,
        limit=max_requests,
        retry_after=retry_after,
    )
