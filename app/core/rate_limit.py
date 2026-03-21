"""
Redis-backed rate limiter using an atomic Lua script.

The Lua script atomically increments the per-org counter and sets the TTL
only when the key is first created, avoiding race conditions.
"""
import logging
import time
from typing import Tuple

logger = logging.getLogger(__name__)

# Lua script: atomically INCR the key and conditionally EXPIRE it.
# Returns a two-element array: [current_count, ttl_seconds]
#   - ttl_seconds is the remaining TTL after the INCR (or the window if newly set).
_RATE_LIMIT_LUA_SCRIPT = """
local key    = KEYS[1]
local window = tonumber(ARGV[1])

local count = redis.call('INCR', key)
if count == 1 then
    redis.call('EXPIRE', key, window)
end

local ttl = redis.call('TTL', key)
return {count, ttl}
"""


def _get_settings():
    """Lazy-import settings to avoid circular imports."""
    try:
        from app.core.config import settings  # type: ignore
        return settings
    except ImportError:
        # Fallback defaults used when config module is not present.
        class _DefaultSettings:
            RATE_LIMIT_WINDOW: int = 60   # seconds
            RATE_LIMIT_CAP: int = 100     # max requests per window

        return _DefaultSettings()


async def check_rate_limit(
    org_id: str,
    redis_client,
) -> Tuple[bool, int]:
    """
    Check whether the given organisation is within its rate-limit quota.

    Parameters
    ----------
    org_id:
        The organisation identifier.  If ``None`` or empty the call is
        treated as allowed (fail-open) and a WARNING is emitted.
    redis_client:
        An async Redis client compatible with ``redis.asyncio.Redis``.
        The client must support the ``execute_script`` or
        ``eval`` / ``register_script`` interface.

    Returns
    -------
    (allowed, retry_after)
        ``allowed`` is ``True`` when the request is within quota.
        ``retry_after`` is 0 when allowed, or the number of seconds until
        the current window resets when the request is rejected.
    """
    # --- guard: missing org_id -------------------------------------------
    if not org_id:
        logger.warning(
            "check_rate_limit called with empty or None org_id; "
            "failing open."
        )
        return True, 0

    settings = _get_settings()
    window: int = int(settings.RATE_LIMIT_WINDOW)
    cap: int = int(settings.RATE_LIMIT_CAP)

    redis_key = f"rate_limit:trigger:{org_id}"

    try:
        # Execute the Lua script atomically.
        # redis-py exposes this via ``redis_client.eval(script, numkeys, *keys_and_args)``.
        result = await redis_client.eval(
            _RATE_LIMIT_LUA_SCRIPT,
            1,          # number of keys
            redis_key,  # KEYS[1]
            window,     # ARGV[1]
        )

        current_count: int = int(result[0])
        ttl: int = int(result[1])

        # TTL may be -1 (no expiry set) or -2 (key does not exist) in edge
        # cases; fall back to the full window to be safe.
        if ttl < 0:
            ttl = window

        if current_count <= cap:
            return True, 0
        else:
            return False, ttl

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Rate-limit Redis error for org_id=%r: %s",
            org_id,
            exc,
            exc_info=True,
        )
        # Fail open — do not block requests when Redis is unavailable.
        return True, 0
