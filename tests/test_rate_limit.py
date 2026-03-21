"""
Tests for the async rate-limit core logic in app.core.rate_limit.

Note: pytest-asyncio is NOT available in this environment. All async tests are
driven by asyncio.run() inside regular synchronous def test functions.
"""
import asyncio
import os
from dataclasses import fields
from unittest.mock import AsyncMock, patch

from app.core.rate_limit import RateLimitResult, check_rate_limit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_redis_mock(count: int, ttl: int) -> AsyncMock:
    """Return an AsyncMock redis client whose eval() returns [count, ttl]."""
    client = AsyncMock()
    client.eval = AsyncMock(return_value=[count, ttl])
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_allows_when_under_limit() -> None:
    """Eval returns count=1, ttl=60 — request is well within the limit."""
    redis = _make_redis_mock(count=1, ttl=60)

    result = asyncio.run(check_rate_limit("org1", redis))

    assert result.allowed is True
    assert result.current == 1
    assert result.retry_after == 0


def test_blocks_when_limit_exceeded() -> None:
    """With RATE_LIMIT_MAX_REQUESTS=5 and count=6 the request must be blocked."""
    redis = _make_redis_mock(count=6, ttl=30)

    with patch.dict(os.environ, {"RATE_LIMIT_MAX_REQUESTS": "5"}):
        result = asyncio.run(check_rate_limit("org2", redis))

    assert result.allowed is False
    assert result.retry_after == 30
    assert result.limit == 5


def test_fails_open_when_redis_is_none() -> None:
    """Passing redis_client=None must fail open (allowed=True)."""
    result = asyncio.run(check_rate_limit("org3", None))

    assert result.allowed is True
    assert result.current == 0
    assert result.retry_after == 0


def test_fails_open_on_redis_error() -> None:
    """If redis.eval raises ConnectionError, the function must fail open."""
    client = AsyncMock()
    client.eval = AsyncMock(side_effect=ConnectionError("Redis unreachable"))

    result = asyncio.run(check_rate_limit("org4", client))

    assert result.allowed is True
    assert result.current == 0
    assert result.retry_after == 0


def test_correct_key_pattern() -> None:
    """
    The Lua eval call must use the key "rate_limit:trigger:my_org".

    eval is called as: await redis_client.eval(script, 1, key, window)
    So call_args.args == (script, 1, key, window) and the key is at index 2.
    """
    redis = _make_redis_mock(count=1, ttl=60)

    asyncio.run(check_rate_limit("my_org", redis))

    assert redis.eval.called, "redis.eval was never called"
    call_args = redis.eval.call_args
    positional = call_args[0]  # tuple of positional arguments
    assert positional[2] == "rate_limit:trigger:my_org", (
        f"Expected key 'rate_limit:trigger:my_org', got '{positional[2]}'"
    )


def test_atomic_increment_no_race() -> None:
    """
    Fire 5 concurrent check_rate_limit calls via asyncio.gather and verify
    that each call received a unique, sequentially-assigned counter value
    (simulating the atomicity guarantee of the Lua INCR script).
    """
    call_count = 0
    counters: list[int] = []

    async def fake_eval(script: str, num_keys: int, key: str, window: int) -> list[int]:
        nonlocal call_count
        call_count += 1
        counters.append(call_count)
        return [call_count, 55]

    client = AsyncMock()
    client.eval = fake_eval  # replace with real coroutine function

    async def _run() -> list[RateLimitResult]:
        with patch.dict(os.environ, {"RATE_LIMIT_MAX_REQUESTS": "10"}):
            return await asyncio.gather(
                *[check_rate_limit("org_race", client) for _ in range(5)]
            )

    results = asyncio.run(_run())

    assert call_count == 5, f"Expected 5 eval calls, got {call_count}"

    result_counts = sorted(r.current for r in results)
    assert result_counts == [1, 2, 3, 4, 5], (
        f"Expected unique sequential counts [1,2,3,4,5], got {result_counts}"
    )

    for result in results:
        assert result.allowed is True, (
            f"All requests should be allowed with limit=10, but got allowed=False "
            f"for current={result.current}"
        )


def test_result_dataclass_fields() -> None:
    """RateLimitResult must expose the four expected fields with correct types."""
    field_map = {f.name: f.type for f in fields(RateLimitResult)}

    assert "allowed" in field_map, "Missing field: allowed"
    assert "current" in field_map, "Missing field: current"
    assert "limit" in field_map, "Missing field: limit"
    assert "retry_after" in field_map, "Missing field: retry_after"

    # Verify the dataclass can be instantiated and field values are correct types.
    r = RateLimitResult(allowed=True, current=5, limit=100, retry_after=0)
    assert isinstance(r.allowed, bool)
    assert isinstance(r.current, int)
    assert isinstance(r.limit, int)
    assert isinstance(r.retry_after, int)
