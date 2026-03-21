"""Atomic rate-limit logic for per-org request throttling.

Key scheme : rate_limit:trigger:{org_id}
Algorithm  : Lua script — INCR the counter, set EXPIRE only when the key
             is brand-new (count == 1) so the sliding window is never
             inadvertently reset mid-flight.
"""
import logging
from urllib.parse import quote
from typing import Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class RateLimitExceededException(Exception):
    """Raised when an org has exceeded its rate-limit cap."""

    def __init__(self, org_id: str, retry_after: int) -> None:
        self.org_id = org_id
        self.retry_after = retry_after
        super().__init__(
            f"Rate limit exceeded for org '{org_id}'. "
            f"Retry after {retry_after} second(s)."
        )


# ---------------------------------------------------------------------------
# Lua script — atomic INCR + conditional EXPIRE
# ---------------------------------------------------------------------------
#
# Guarantees:
#   * INCR and EXPIRE are executed inside a single Redis round-trip.
#   * EXPIRE is only set when count == 1 (first request in the window),
#     which prevents the window from being reset by concurrent callers.
#   * TTL of the key is returned so the caller knows when the window resets.
#
# KEYS[1] = Redis key
# ARGV[1] = window in seconds
# Returns: {count, ttl}
_RATE_LIMIT_LUA: str = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitise_org_id(org_id: str) -> str:
    """URL-encode *org_id* so special characters cannot affect the Redis key."""
    return quote(str(org_id), safe="")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def check_rate_limit(
    org_id: str,
    redis_client,
    cap: int,
    window: int,
) -> Tuple[bool, int]:
    """Atomically check and increment the rate-limit counter for *org_id*.

    Parameters
    ----------
    org_id:
        Identifier of the organisation (tenant).  Must be a non-empty string.
        Special characters (slashes, colons, Unicode, etc.) are URL-encoded
        before the Redis key is constructed.
    redis_client:
        An async Redis client (e.g. ``redis.asyncio.Redis``).
    cap:
        Maximum number of requests allowed within *window* seconds.
        ``cap=0`` means **no requests are allowed** — every call is denied
        without touching Redis.
    window:
        Duration of the rate-limit window in seconds.

    Returns
    -------
    (True, 0)
        The request is within the cap; the caller may proceed.

    Raises
    ------
    RateLimitExceededException
        When the counter exceeds *cap*.  ``retry_after`` is the remaining TTL
        of the Redis key (seconds until the window resets), floored at 0.
    ValueError
        When *org_id* is missing, not a string, or blank.

    Notes
    -----
    * Redis unavailability is treated as **fail-open**: the function logs an
      ERROR and returns ``(True, 0)`` so that transient outages do not block
      legitimate traffic.
    * Atomicity is guaranteed by a Lua script executed server-side; no
      client-side WATCH/MULTI/EXEC is required.
    """
    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------
    if not isinstance(org_id, str) or not org_id or not org_id.strip():
        raise ValueError(
            f"org_id must be a non-empty string, got: {org_id!r}"
        )

    safe_org_id: str = _sanitise_org_id(org_id)
    redis_key: str = f"rate_limit:trigger:{safe_org_id}"

    # cap=0 → always deny; skip Redis to avoid unnecessary I/O
    if cap == 0:
        logger.warning(
            "Rate-limit cap is 0 for org '%s' — all requests denied.", org_id
        )
        raise RateLimitExceededException(org_id=org_id, retry_after=window)

    # ------------------------------------------------------------------
    # Execute Lua script (atomic INCR + conditional EXPIRE)
    # ------------------------------------------------------------------
    try:
        result = await redis_client.eval(
            _RATE_LIMIT_LUA,
            1,          # number of KEYS
            redis_key,  # KEYS[1]
            window,     # ARGV[1]
        )
        count: int = int(result[0])
        ttl: int = int(result[1])
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Redis error during rate-limit check for org '%s' (key=%s): %s",
            org_id,
            redis_key,
            exc,
        )
        # Fail-open: allow the request rather than blocking on Redis issues
        return True, 0

    # ------------------------------------------------------------------
    # Decision
    # ------------------------------------------------------------------
    if count > cap:
        retry_after: int = max(ttl, 0)
        raise RateLimitExceededException(
            org_id=org_id, retry_after=retry_after
        )

    return True, 0
