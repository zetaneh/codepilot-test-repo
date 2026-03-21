"""Tests for app.core.rate_limit.check_rate_limit."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.rate_limit import (
    RateLimitExceededException,
    check_rate_limit,
    _sanitise_org_id,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_redis(count: int, ttl: int = 30) -> AsyncMock:
    """Return a fake async Redis client whose eval() returns (count, ttl)."""
    client = AsyncMock()
    client.eval = AsyncMock(return_value=[count, ttl])
    return client


# ---------------------------------------------------------------------------
# Sanitisation
# ---------------------------------------------------------------------------


def test_sanitise_org_id_encodes_special_chars() -> None:
    assert _sanitise_org_id("org/foo:bar") == "org%2Ffoo%3Abar"
    assert _sanitise_org_id("org with spaces") == "org%20with%20spaces"
    assert _sanitise_org_id("plain") == "plain"


# ---------------------------------------------------------------------------
# test_check_rate_limit_allows_up_to_cap  (primary hook)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_rate_limit_allows_up_to_cap() -> None:
    """Requests 1 .. cap should all be allowed; cap+1 must be denied."""
    cap = 5
    window = 60
    org_id = "test-org"

    # Simulate sequential increments
    for current_count in range(1, cap + 1):
        redis = _make_redis(count=current_count, ttl=window)
        allowed, retry_after = await check_rate_limit(org_id, redis, cap, window)
        assert allowed is True
        assert retry_after == 0

    # The (cap+1)-th request must raise
    redis = _make_redis(count=cap + 1, ttl=45)
    with pytest.raises(RateLimitExceededException) as exc_info:
        await check_rate_limit(org_id, redis, cap, window)

    assert exc_info.value.org_id == org_id
    assert exc_info.value.retry_after == 45


# ---------------------------------------------------------------------------
# cap=0 — every request denied without touching Redis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cap_zero_always_denies() -> None:
    redis = AsyncMock()
    with pytest.raises(RateLimitExceededException) as exc_info:
        await check_rate_limit("org1", redis, cap=0, window=60)

    assert exc_info.value.retry_after == 60
    redis.eval.assert_not_called()


# ---------------------------------------------------------------------------
# Invalid / missing org_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_org", ["", "   ", None, 42])
async def test_invalid_org_id_raises_value_error(bad_org) -> None:
    redis = AsyncMock()
    with pytest.raises((ValueError, TypeError)):
        await check_rate_limit(bad_org, redis, cap=10, window=60)


# ---------------------------------------------------------------------------
# Special characters in org_id are safely encoded in the Redis key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_special_chars_in_org_id_are_encoded() -> None:
    org_id = "org/name:with special"
    redis = _make_redis(count=1, ttl=60)

    allowed, _ = await check_rate_limit(org_id, redis, cap=5, window=60)
    assert allowed is True

    call_args = redis.eval.call_args
    used_key: str = call_args[0][2]  # positional: script, numkeys, key, window
    assert "/" not in used_key
    assert " " not in used_key
    assert ":" not in used_key.replace("rate_limit:trigger:", "", 1)


# ---------------------------------------------------------------------------
# Redis unavailability → fail-open
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_failure_fails_open() -> None:
    redis = AsyncMock()
    redis.eval = AsyncMock(side_effect=ConnectionError("Redis is down"))

    allowed, retry_after = await check_rate_limit("org1", redis, cap=10, window=60)
    assert allowed is True
    assert retry_after == 0


@pytest.mark.asyncio
async def test_redis_failure_logs_error() -> None:
    redis = AsyncMock()
    redis.eval = AsyncMock(side_effect=OSError("timeout"))

    with patch("app.core.rate_limit.logger") as mock_logger:
        await check_rate_limit("org2", redis, cap=10, window=60)
        mock_logger.error.assert_called_once()


# ---------------------------------------------------------------------------
# retry_after is floored at 0 when TTL is negative (key has no expiry)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_after_floored_at_zero_for_negative_ttl() -> None:
    redis = _make_redis(count=11, ttl=-1)  # TTL=-1 means key exists, no expiry
    with pytest.raises(RateLimitExceededException) as exc_info:
        await check_rate_limit("org1", redis, cap=10, window=60)
    assert exc_info.value.retry_after == 0
