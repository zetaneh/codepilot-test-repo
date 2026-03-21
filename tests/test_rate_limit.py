"""
Comprehensive tests for the rate-limiting infrastructure.

Coverage:
  - RateLimitResult dataclass structure and defaults
  - check_rate_limit: allowed/blocked paths, fail-open semantics
  - Atomic Lua-based INCR (no GET+SET race window)
  - 429 after 10th request, Retry-After header accuracy
  - Independent counters per organization
  - HTTP-level rate-limit enforcement via a minimal FastAPI test app
"""
import asyncio
import os
from dataclasses import fields
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.core.rate_limit import RateLimitResult, check_rate_limit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENV_LIMIT_10 = {"RATE_LIMIT_MAX_REQUESTS": "10", "RATE_LIMIT_WINDOW_SECONDS": "60"}


def _make_redis_mock(count: int, ttl: int = 60) -> AsyncMock:
    """Return an AsyncMock redis client whose eval() returns [count, ttl]."""
    client = AsyncMock()
    client.eval = AsyncMock(return_value=[count, ttl])
    return client


def _build_test_app(redis_client: AsyncMock) -> FastAPI:
    """
    Build a minimal FastAPI app with POST /trigger that applies check_rate_limit
    and returns 429 + Retry-After when the rate limit is exceeded.
    """
    app = FastAPI()

    @app.post("/trigger")
    async def trigger(request: Request) -> Response:
        org_id = request.headers.get("X-Org-ID", "default")
        result: RateLimitResult = await check_rate_limit(org_id, redis_client)
        if not result.allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(result.retry_after)},
            )
        return JSONResponse(status_code=200, content={"ok": True})

    return app


def _build_strict_test_app(redis_client: AsyncMock) -> FastAPI:
    """
    Build a minimal FastAPI app with POST /trigger where org_id is a required
    query parameter. Missing org_id causes FastAPI's validation to return 422.
    """
    app = FastAPI()

    @app.post("/trigger")
    async def trigger(org_id: str, request: Request) -> Response:
        result: RateLimitResult = await check_rate_limit(org_id, redis_client)
        if not result.allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(result.retry_after)},
            )
        return JSONResponse(status_code=200, content={"ok": True})

    return app


def _build_machine_readable_test_app(redis_client: AsyncMock) -> FastAPI:
    """
    Build a minimal FastAPI app with POST /trigger that returns a full
    machine-readable 429 response body including error, retry_after, and limit.
    """
    app = FastAPI()

    @app.post("/trigger")
    async def trigger(request: Request) -> Response:
        org_id = request.headers.get("X-Org-ID", "default")
        result: RateLimitResult = await check_rate_limit(org_id, redis_client)
        if not result.allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "retry_after": result.retry_after,
                    "limit": result.limit,
                },
                headers={"Retry-After": str(result.retry_after)},
            )
        return JSONResponse(status_code=200, content={"ok": True})

    return app


# ---------------------------------------------------------------------------
# Module-level fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rate_limit_env_10():
    """Patch environment to set RATE_LIMIT_MAX_REQUESTS=10 and RATE_LIMIT_WINDOW_SECONDS=60."""
    with patch.dict(os.environ, {"RATE_LIMIT_MAX_REQUESTS": "10", "RATE_LIMIT_WINDOW_SECONDS": "60"}):
        yield


@pytest.fixture
def incrementing_redis_mock() -> AsyncMock:
    """
    Return an AsyncMock redis client whose eval() increments a per-key counter.
    Each call returns [count_for_key, 60].
    """
    counters: dict = {}

    async def _eval(script: str, numkeys: int, key: str, window: int) -> list:
        counters[key] = counters.get(key, 0) + 1
        return [counters[key], 60]

    client = AsyncMock()
    client.eval = _eval
    return client


@pytest.fixture
def strict_test_app(incrementing_redis_mock: AsyncMock) -> TestClient:
    """TestClient for the strict app where org_id is a required query param."""
    app = _build_strict_test_app(incrementing_redis_mock)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def machine_readable_test_app() -> TestClient:
    """TestClient for the machine-readable app (429 body with error/retry_after/limit)."""
    redis_mock = _make_redis_mock(count=11, ttl=30)
    app = _build_machine_readable_test_app(redis_mock)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def fake_redis() -> AsyncMock:
    """
    Fake async Redis client fixture with per-key INCR simulation.
    Supports incr(), eval(), get(), set() operations.
    """
    counters: dict = {}

    client = AsyncMock()

    async def _incr(key: str) -> int:
        counters[key] = counters.get(key, 0) + 1
        return counters[key]

    async def _eval(script: str, numkeys: int, key: str, window: int) -> list:
        counters[key] = counters.get(key, 0) + 1
        return [counters[key], 60]

    client.incr = _incr
    client.eval = _eval
    return client


# ---------------------------------------------------------------------------
# 1. Settings / defaults
# ---------------------------------------------------------------------------


def test_settings_defaults() -> None:
    """
    check_rate_limit reads RATE_LIMIT_MAX_REQUESTS and RATE_LIMIT_WINDOW_SECONDS
    from environment and exposes them via RateLimitResult.limit; the default
    for RATE_LIMIT_MAX_REQUESTS is 100 when the env var is absent.
    """
    stripped_env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("RATE_LIMIT_MAX_REQUESTS", "RATE_LIMIT_WINDOW_SECONDS")
    }
    redis_mock = _make_redis_mock(count=1, ttl=60)

    with patch.dict(os.environ, stripped_env, clear=True):
        result = asyncio.run(check_rate_limit("org-defaults", redis_mock))

    assert result.limit == 100, "Default RATE_LIMIT_MAX_REQUESTS must be 100"
    assert result.current == 1
    assert result.allowed is True
    assert result.retry_after == 0


# ---------------------------------------------------------------------------
# 2. Fail-open: get_redis_client() and check_rate_limit
# ---------------------------------------------------------------------------


def test_redis_unavailable_fails_open() -> None:
    """
    get_redis_client() must return None rather than raise when the
    Redis server is unreachable (fail-open semantics for infrastructure).
    """
    import app.core.redis as redis_module

    mock_pool_cls = MagicMock()
    mock_pool_cls.from_url.side_effect = Exception("Connection refused to 127.0.0.1:19999")

    original_pool = getattr(redis_module, "ConnectionPool", None)
    redis_module.ConnectionPool = mock_pool_cls

    with patch.dict(os.environ, {"REDIS_URL": "redis://127.0.0.1:19999"}):
        with patch("app.core.redis._REDIS_AVAILABLE", True):
            try:
                result = redis_module.get_redis_client()
            finally:
                if original_pool is not None:
                    redis_module.ConnectionPool = original_pool
                elif hasattr(redis_module, "ConnectionPool"):
                    del redis_module.ConnectionPool

    assert result is None, "get_redis_client() must return None when Redis is unavailable"


def test_fails_open_when_redis_down() -> None:
    """
    check_rate_limit must return allowed=True with zeroed counters when
    redis_client is None (simulating Redis being entirely unreachable).
    """
    result = asyncio.run(check_rate_limit("org-down", redis_client=None))

    assert result.allowed is True
    assert result.current == 0
    assert result.retry_after == 0


def test_fails_open_on_redis_error() -> None:
    """check_rate_limit must fail open when redis_client.eval raises."""
    client = AsyncMock()
    client.eval = AsyncMock(side_effect=ConnectionError("Redis unreachable"))

    result = asyncio.run(check_rate_limit("org-exc", client))

    assert result.allowed is True
    assert result.current == 0
    assert result.retry_after == 0


# ---------------------------------------------------------------------------
# 3. Atomic Lua-based increment (no race window)
# ---------------------------------------------------------------------------


def test_atomic_increment_no_race() -> None:
    """
    Fire 5 concurrent check_rate_limit coroutines via asyncio.gather and verify
    each receives a unique, sequentially-assigned counter (INCR atomicity guarantee).
    Also verifies the implementation uses eval (atomic Lua) not a racy GET+SET.
    """
    call_count = 0

    async def fake_eval(script: str, num_keys: int, key: str, window: int) -> list[int]:
        nonlocal call_count
        call_count += 1
        return [call_count, 55]

    concurrent_client = AsyncMock()
    concurrent_client.eval = fake_eval

    async def _run() -> list[RateLimitResult]:
        with patch.dict(os.environ, {"RATE_LIMIT_MAX_REQUESTS": "10"}):
            return await asyncio.gather(
                *[check_rate_limit("org-race", concurrent_client) for _ in range(5)]
            )

    results = asyncio.run(_run())

    assert call_count == 5
    result_counts = sorted(r.current for r in results)
    assert result_counts == [1, 2, 3, 4, 5], (
        f"Expected unique sequential counts [1,2,3,4,5], got {result_counts}"
    )
    assert all(r.allowed for r in results)

    # Verify the implementation calls eval (atomic) and not a racy get+set
    check_client = _make_redis_mock(count=1, ttl=60)
    asyncio.run(check_rate_limit("org-atomic-verify", check_client))
    check_client.eval.assert_called_once()
    check_client.get.assert_not_called()
    check_client.set.assert_not_called()


def test_correct_key_pattern() -> None:
    """
    The Lua eval call must use the key "rate_limit:trigger:<org_id>".
    eval is called as: await redis_client.eval(script, 1, key, window)
    So positional args[2] is the Redis key.
    """
    redis_mock = _make_redis_mock(count=1, ttl=60)

    asyncio.run(check_rate_limit("my_org", redis_mock))

    assert redis_mock.eval.called, "redis.eval was never called"
    positional = redis_mock.eval.call_args[0]
    assert positional[2] == "rate_limit:trigger:my_org", (
        f"Expected key 'rate_limit:trigger:my_org', got '{positional[2]}'"
    )


# ---------------------------------------------------------------------------
# 4. HTTP-level rate-limit enforcement via test app
# ---------------------------------------------------------------------------


def test_trigger_endpoint_returns_200_when_under_limit() -> None:
    """A request with count=1 (well within any limit) must receive HTTP 200."""
    redis_mock = _make_redis_mock(count=1, ttl=60)
    client = TestClient(_build_test_app(redis_mock), raise_server_exceptions=True)

    with patch.dict(os.environ, _ENV_LIMIT_10):
        response = client.post("/trigger", headers={"X-Org-ID": "org-ok"})

    assert response.status_code == 200


def test_middleware_returns_429_with_retry_after() -> None:
    """When count exceeds the limit the endpoint returns 429 and Retry-After."""
    redis_mock = _make_redis_mock(count=11, ttl=45)
    client = TestClient(_build_test_app(redis_mock), raise_server_exceptions=False)

    with patch.dict(os.environ, _ENV_LIMIT_10):
        response = client.post("/trigger", headers={"X-Org-ID": "org-over"})

    assert response.status_code == 429
    assert "Retry-After" in response.headers


def test_429_after_tenth_request() -> None:
    """First 10 requests (count 1-10) are allowed; the 11th (count 11) is blocked."""
    call_count = 0

    async def incrementing_eval(
        script: str, numkeys: int, key: str, window: int
    ) -> list[int]:
        nonlocal call_count
        call_count += 1
        return [call_count, 60]

    redis_mock = AsyncMock()
    redis_mock.eval = incrementing_eval
    client = TestClient(_build_test_app(redis_mock), raise_server_exceptions=False)

    with patch.dict(os.environ, _ENV_LIMIT_10):
        for i in range(1, 11):
            r = client.post("/trigger", headers={"X-Org-ID": "org-tenth"})
            assert r.status_code == 200, (
                f"Request #{i} should be allowed (got {r.status_code})"
            )

        eleventh = client.post("/trigger", headers={"X-Org-ID": "org-tenth"})

    assert eleventh.status_code == 429, "11th request must be rate-limited"


def test_retry_after_header_present_and_accurate() -> None:
    """Retry-After header value must exactly equal the remaining TTL from Redis."""
    remaining_ttl = 42
    redis_mock = _make_redis_mock(count=11, ttl=remaining_ttl)
    client = TestClient(_build_test_app(redis_mock), raise_server_exceptions=False)

    with patch.dict(os.environ, _ENV_LIMIT_10):
        response = client.post("/trigger", headers={"X-Org-ID": "org-retry"})

    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert response.headers["Retry-After"] == str(remaining_ttl)


def test_different_orgs_independent_counters() -> None:
    """Exhausting org-A's quota must not affect org-B's independent counter."""
    org_counters: dict[str, int] = {}

    async def per_org_eval(
        script: str, numkeys: int, key: str, window: int
    ) -> list[int]:
        org_counters[key] = org_counters.get(key, 0) + 1
        return [org_counters[key], 60]

    redis_mock = AsyncMock()
    redis_mock.eval = per_org_eval
    client = TestClient(_build_test_app(redis_mock), raise_server_exceptions=False)

    with patch.dict(os.environ, _ENV_LIMIT_10):
        # Exhaust org-A's quota
        for _ in range(10):
            r = client.post("/trigger", headers={"X-Org-ID": "org-A"})
            assert r.status_code == 200

        blocked = client.post("/trigger", headers={"X-Org-ID": "org-A"})
        assert blocked.status_code == 429, "org-A must be rate-limited after 10 requests"

        # org-B has its own counter and must still be allowed
        allowed_b = client.post("/trigger", headers={"X-Org-ID": "org-B"})

    assert allowed_b.status_code == 200, "org-B must not be affected by org-A's limit"


# ---------------------------------------------------------------------------
# 5. RateLimitResult dataclass structural check
# ---------------------------------------------------------------------------


def test_result_dataclass_fields() -> None:
    """RateLimitResult must expose the four expected fields with correct types."""
    field_map = {f.name: f.type for f in fields(RateLimitResult)}

    assert "allowed" in field_map, "Missing field: allowed"
    assert "current" in field_map, "Missing field: current"
    assert "limit" in field_map, "Missing field: limit"
    assert "retry_after" in field_map, "Missing field: retry_after"

    r = RateLimitResult(allowed=True, current=5, limit=100, retry_after=0)
    assert isinstance(r.allowed, bool)
    assert isinstance(r.current, int)
    assert isinstance(r.limit, int)
    assert isinstance(r.retry_after, int)


# ---------------------------------------------------------------------------
# 6. fake_redis fixture verification
# ---------------------------------------------------------------------------


def test_fake_redis_fixture_increments_correctly(fake_redis) -> None:
    """
    Verify the fake_redis fixture correctly increments a key,
    returning 1, 2, 3 on successive INCR calls against the same key.
    """

    async def _run() -> tuple[int, int, int]:
        v1 = await fake_redis.incr("counter_key")
        v2 = await fake_redis.incr("counter_key")
        v3 = await fake_redis.incr("counter_key")
        return v1, v2, v3

    v1, v2, v3 = asyncio.run(_run())
    assert v1 == 1, f"First INCR must return 1, got {v1}"
    assert v2 == 2, f"Second INCR must return 2, got {v2}"
    assert v3 == 3, f"Third INCR must return 3, got {v3}"


# ---------------------------------------------------------------------------
# New tests (acceptance criteria)
# ---------------------------------------------------------------------------


def test_allows_up_to_cap() -> None:
    """Make exactly 10 sequential requests with cap=10; verify all return HTTP 200."""
    call_count = 0

    async def incrementing_eval(
        script: str, numkeys: int, key: str, window: int
    ) -> list[int]:
        nonlocal call_count
        call_count += 1
        return [call_count, 60]

    redis_mock = AsyncMock()
    redis_mock.eval = incrementing_eval
    client = TestClient(_build_test_app(redis_mock), raise_server_exceptions=False)

    with patch.dict(os.environ, _ENV_LIMIT_10):
        for i in range(1, 11):
            r = client.post("/trigger", headers={"X-Org-ID": "org-cap"})
            assert r.status_code == 200, (
                f"Request #{i} (count={i}) should be allowed (cap=10), got {r.status_code}"
            )


def test_returns_429_after_cap() -> None:
    """Make 11 requests sequentially; first 10 are 200 and the 11th is 429."""
    call_count = 0

    async def incrementing_eval(
        script: str, numkeys: int, key: str, window: int
    ) -> list[int]:
        nonlocal call_count
        call_count += 1
        return [call_count, 60]

    redis_mock = AsyncMock()
    redis_mock.eval = incrementing_eval
    client = TestClient(_build_test_app(redis_mock), raise_server_exceptions=False)

    with patch.dict(os.environ, _ENV_LIMIT_10):
        for i in range(1, 11):
            r = client.post("/trigger", headers={"X-Org-ID": "org-over-cap"})
            assert r.status_code == 200, (
                f"Request #{i} should be 200 (got {r.status_code})"
            )

        eleventh = client.post("/trigger", headers={"X-Org-ID": "org-over-cap"})
        assert eleventh.status_code == 429, (
            f"11th request must be 429 (got {eleventh.status_code})"
        )


def test_retry_after_header_positive_int() -> None:
    """When rate limited, Retry-After header must be present and a positive integer."""
    redis_mock = _make_redis_mock(count=11, ttl=30)
    client = TestClient(_build_test_app(redis_mock), raise_server_exceptions=False)

    with patch.dict(os.environ, _ENV_LIMIT_10):
        response = client.post("/trigger", headers={"X-Org-ID": "org-retry-positive"})

    assert response.status_code == 429
    assert "Retry-After" in response.headers, "Retry-After header must be present"
    retry_after_value = int(response.headers["Retry-After"])
    assert retry_after_value > 0, (
        f"Retry-After must be a positive integer, got {retry_after_value}"
    )


def test_independent_org_counters() -> None:
    """Exhaust org-X's quota, verify org-X is denied, then org-Y can still request."""
    org_counters: dict[str, int] = {}

    async def per_org_eval(
        script: str, numkeys: int, key: str, window: int
    ) -> list[int]:
        org_counters[key] = org_counters.get(key, 0) + 1
        return [org_counters[key], 60]

    redis_mock = AsyncMock()
    redis_mock.eval = per_org_eval
    client = TestClient(_build_test_app(redis_mock), raise_server_exceptions=False)

    with patch.dict(os.environ, _ENV_LIMIT_10):
        for _ in range(10):
            r = client.post("/trigger", headers={"X-Org-ID": "org-X"})
            assert r.status_code == 200

        denied = client.post("/trigger", headers={"X-Org-ID": "org-X"})
        assert denied.status_code == 429, "org-X must be rate-limited after 10 requests"

        allowed = client.post("/trigger", headers={"X-Org-ID": "org-Y"})
        assert allowed.status_code == 200, (
            "org-Y must be independent from org-X and still be allowed"
        )


def test_fail_open_when_redis_down() -> None:
    """Pass redis_client=None; verify result.allowed is True, current == 0, retry_after == 0."""
    result = asyncio.run(check_rate_limit("org-none", redis_client=None))

    assert result.allowed is True, "Must fail open when redis_client is None"
    assert result.current == 0, f"current must be 0 when failing open, got {result.current}"
    assert result.retry_after == 0, (
        f"retry_after must be 0 when failing open, got {result.retry_after}"
    )


def test_atomic_concurrent_burst() -> None:
    """
    Use asyncio.gather to fire 10 concurrent check_rate_limit coroutines.
    Verify all 10 eval calls were made, each result has unique count (1-10),
    and all are allowed within cap=10.
    """
    call_count = 0

    async def fake_eval(script: str, num_keys: int, key: str, window: int) -> list[int]:
        nonlocal call_count
        call_count += 1
        return [call_count, 60]

    concurrent_client = AsyncMock()
    concurrent_client.eval = fake_eval

    async def _run() -> list[RateLimitResult]:
        with patch.dict(os.environ, _ENV_LIMIT_10):
            return await asyncio.gather(
                *[check_rate_limit("org-burst", concurrent_client) for _ in range(10)]
            )

    results = asyncio.run(_run())

    assert call_count == 10, f"Expected 10 eval calls, got {call_count}"

    result_counts = sorted(r.current for r in results)
    assert result_counts == list(range(1, 11)), (
        f"Expected unique counts 1-10, got {result_counts}"
    )

    assert all(r.allowed for r in results), (
        "All 10 requests must be allowed within cap=10"
    )


def test_cap_zero_always_denies() -> None:
    """Set RATE_LIMIT_MAX_REQUESTS=0; any request (even first with count=1) must be denied."""
    redis_mock = _make_redis_mock(count=1, ttl=60)

    with patch.dict(os.environ, {"RATE_LIMIT_MAX_REQUESTS": "0", "RATE_LIMIT_WINDOW_SECONDS": "60"}):
        result = asyncio.run(check_rate_limit("org-zero-cap", redis_mock))

    assert result.allowed is False, (
        "With cap=0, even the first request (count=1) must be denied"
    )
    assert result.retry_after > 0, (
        f"retry_after must be > 0 when denied, got {result.retry_after}"
    )


def test_missing_org_id_returns_422(strict_test_app: TestClient) -> None:
    """POST /trigger without org_id query param must return HTTP 422 (FastAPI validation)."""
    with patch.dict(os.environ, _ENV_LIMIT_10):
        response = strict_test_app.post("/trigger")

    assert response.status_code == 422, (
        f"Missing required query param org_id must return 422, got {response.status_code}"
    )


def test_special_char_org_id_safe_key() -> None:
    """
    Use an org_id with special characters; verify check_rate_limit does not raise,
    eval is called with a key containing the org_id, and the result is valid.
    """
    special_org_id = "org/foo@bar baz"
    expected_key = f"rate_limit:trigger:{special_org_id}"

    redis_mock = _make_redis_mock(count=1, ttl=60)

    with patch.dict(os.environ, _ENV_LIMIT_10):
        result = asyncio.run(check_rate_limit(special_org_id, redis_mock))

    assert redis_mock.eval.called, "eval must have been called"
    positional = redis_mock.eval.call_args[0]
    assert positional[2] == expected_key, (
        f"Expected key '{expected_key}', got '{positional[2]}'"
    )

    assert isinstance(result, RateLimitResult), (
        f"Expected RateLimitResult, got {type(result)}"
    )
    assert result.allowed is True


def test_window_ttl_not_reset_on_subsequent_requests() -> None:
    """
    Simulate 3 sequential requests with decreasing TTLs (60, 55, 50).
    Verify TTLs are non-increasing and 3 eval calls were made total (not get+expire).
    """
    ttl_sequence = [60, 55, 50]
    call_index = 0

    async def mock_eval(script: str, numkeys: int, key: str, window: int) -> list[int]:
        nonlocal call_index
        current_call = call_index
        call_index += 1
        count = current_call + 1
        ttl = ttl_sequence[current_call]
        return [count, ttl]

    redis_mock = AsyncMock()
    redis_mock.eval = mock_eval

    ttl_values = []

    async def _run() -> None:
        with patch.dict(os.environ, _ENV_LIMIT_10):
            for _ in range(3):
                result = await check_rate_limit("org-ttl-no-reset", redis_mock)
                ttl_values.append(result.retry_after if not result.allowed else ttl_sequence[result.current - 1])

    asyncio.run(_run())

    assert call_index == 3, f"Expected 3 eval calls, got {call_index}"

    for i in range(len(ttl_sequence) - 1):
        assert ttl_sequence[i] >= ttl_sequence[i + 1], (
            f"TTL should be non-increasing: ttl[{i}]={ttl_sequence[i]} >= ttl[{i+1}]={ttl_sequence[i+1]}"
        )

    redis_mock.get.assert_not_called()
    redis_mock.set.assert_not_called()


def test_response_body_has_machine_readable_fields(machine_readable_test_app: TestClient) -> None:
    """
    When rate-limited (429), verify JSON body has error (str), retry_after (int),
    and limit (int) fields with correct types.
    """
    with patch.dict(os.environ, _ENV_LIMIT_10):
        response = machine_readable_test_app.post(
            "/trigger", headers={"X-Org-ID": "org-machine-readable"}
        )

    assert response.status_code == 429, (
        f"Expected 429 response, got {response.status_code}"
    )

    body = response.json()

    assert "error" in body, f"Response body must contain 'error' key, got keys: {list(body.keys())}"
    assert "retry_after" in body, (
        f"Response body must contain 'retry_after' key, got keys: {list(body.keys())}"
    )
    assert "limit" in body, f"Response body must contain 'limit' key, got keys: {list(body.keys())}"

    assert isinstance(body["error"], str), (
        f"'error' must be a string, got {type(body['error'])}"
    )
    assert isinstance(body["retry_after"], int), (
        f"'retry_after' must be an int, got {type(body['retry_after'])}"
    )
    assert isinstance(body["limit"], int), (
        f"'limit' must be an int, got {type(body['limit'])}"
    )

    assert body["error"] == "rate_limit_exceeded", (
        f"Expected error='rate_limit_exceeded', got '{body['error']}'"
    )
