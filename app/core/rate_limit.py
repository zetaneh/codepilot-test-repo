"""
Atomic Redis-based rate limiter using a Lua script.

The Lua script atomically increments a counter key and sets the TTL only
when the key is newly created (SETNX-style semantics), ensuring no race
conditions between INCR and EXPIRE.
"""

import logging
from urllib.parse import quote
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lua script
# ---------------------------------------------------------------------------
# KEYS[1] — the rate-limit key
# ARGV[1] — the window TTL in seconds
#
# Returns a two-element array: [current_count, ttl]
#   current_count — value of the counter after this request
#   ttl           — remaining TTL in seconds (-1 means no expiry was set,
#                   which should never happen in normal operation)

RATE_LIMIT_LUA_SCRIPT: str = """
local key   = KEYS[1]
local ttl   = tonumber(ARGV[1])

local current = redis.call('INCR', key)

if current == 1 then
    redis.call('EXPIRE', key, ttl)
end

local remaining_ttl = redis.call('TTL', key)

return {current, remaining_ttl}
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _sanitise_org_id(org_id: Any) -> str:
    """Validate and URL-encode an org_id.

    Raises ValueError for empty / None values.
    """
    if not org_id:
        raise ValueError("org_id must not be empty or None")

    org_id_str: str = str(org_id)
    if not org_id_str.strip():
        raise ValueError("org_id must not be blank")

    # URL-encode any characters that could break Redis key semantics or
    # allow injection (spaces, colons, newlines, etc.).
    return quote(org_id_str, safe="-_")


async def check_rate_limit(
    redis_client: Any,
    org_id: str,
    window: int,
    cap: int,
) -> tuple[bool, int]:
    """Check whether an organisation is within its rate limit.

    Parameters
    ----------
    redis_client:
        An async Redis client (e.g. ``redis.asyncio.Redis``).
    org_id:
        Identifier for the organisation / tenant being rate-limited.
    window:
        Sliding-window size in seconds.  The TTL is set to this value
        the first time the key is created within a window.
    cap:
        Maximum number of requests allowed in the window.

    Returns
    -------
    (allowed, retry_after)
        ``allowed`` is ``True`` when the request is under the cap.
        ``retry_after`` is the number of seconds the caller should wait
        before retrying (0 when the request is allowed).

    Notes
    -----
    * Never raises an unhandled exception — Redis errors are logged at
      ERROR level and the request is *allowed* (fail-open).
    * org_id is validated and URL-encoded before use.
    """
    # --- validate org_id ------------------------------------------------
    try:
        safe_org_id = _sanitise_org_id(org_id)
    except ValueError as exc:
        logger.error("check_rate_limit: invalid org_id=%r — %s", org_id, exc)
        # Fail-open: allow the request but signal 0 retry.
        return True, 0

    key = f"rate_limit:trigger:{safe_org_id}"

    # --- execute Lua script atomically ----------------------------------
    try:
        result = await redis_client.eval(
            RATE_LIMIT_LUA_SCRIPT,
            1,        # number of keys
            key,      # KEYS[1]
            window,   # ARGV[1]
        )

        current_count: int = int(result[0])
        ttl: int = int(result[1])

        if ttl < 0:
            # Safety: if TTL is missing for some reason, use the full window.
            ttl = window

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "check_rate_limit: Redis error for org_id=%r key=%r — %s",
            org_id,
            key,
            exc,
        )
        # Fail-open.
        return True, 0

    # --- decide ---------------------------------------------------------
    if current_count <= cap:
        return True, 0

    # Over the cap — report how long the caller should wait.
    retry_after: int = max(ttl, 1)
    logger.warning(
        "check_rate_limit: rate limit exceeded org_id=%r count=%d cap=%d "
        "retry_after=%ds",
        org_id,
        current_count,
        cap,
        retry_after,
    )
    return False, retry_after
