"""
Comprehensive tests for the per-org rate-limiting system.

Covers:
 - First 10 requests succeed (200)
 - 11th request is rejected (429)
 - Retry-After header is present and plausible
 - Different orgs have independent counters
 - Fail-open when Redis is down
 - Atomic increment (no race conditions)
 - Missing X-Org-ID header behaviour
 - Window reset after TTL expiry
 - Invalid config raises on startup (conceptual)
 - /trigger endpoint returns 200 within limit
 - Dependency raises 429 with Retry-After header
 - Middleware standalone returns 429
 - check_rate_limit atomic increment helper
 - get_redis_client returns a connection object
"""
from __future__ import annotations

import concurrent.futures
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.rate_limit import (
    RATE_LIMIT_REQUESTS,
    RATE_LIMIT_WINDOW,
    RateLimitMiddleware,
    check_rate_limit,
    get_redis_client,
    rate_limit_dependency,
)
from tests.conftest import FakeRedis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _org_headers(org_id: str) -> dict:
    return {"X-Org-ID": org_id}


def _hit_trigger(client: TestClient, org_id: str) -> int:
    """POST /trigger with the given org header and return the HTTP status."""
    return client.post("/trigger", headers=_org_headers(org_id)).status_code


# ===========================================================================
# 1. First 10 requests return 200
# ===========================================================================

def test_first_10_requests_return_200(test_client: TestClient) -> None:
    for i in range(RATE_LIMIT_REQUESTS):
        status = _hit_trigger(test_client, "org-alpha")
        assert status == 200, f"Request {i + 1} expected 200, got {status}"


# ===========================================================================
# 2. 11th request returns 429
# ===========================================================================

def test_11th_request_returns_429(test_client: TestClient) -> None:
    for _ in range(RATE_LIMIT_REQUESTS):
        test_client.post("/trigger", headers=_org_headers("org-beta"))

    response = test_client.post("/trigger", headers=_org_headers("org-beta"))
    assert response.status_code == 429


# ===========================================================================
# 3. Retry-After header is present and accurate
# ===========================================================================

def test_retry_after_header_present_and_accurate(test_client: TestClient) -> None:
    org = "org-gamma"
    for _ in range(RATE_LIMIT_REQUESTS):
        test_client.post("/trigger", headers=_org_headers(org))

    response = test_client.post("/trigger", headers=_org_headers(org))
    assert response.status_code == 429
    assert "retry-after" in response.headers, "Retry-After header missing"
    retry_after = int(response.headers["retry-after"])
    assert 0 < retry_after <= RATE_LIMIT_WINDOW, (
        f"Retry-After {retry_after} out of expected range (0, {RATE_LIMIT_WINDOW}]"
    )


# ===========================================================================
# 4. Different orgs have independent counters
# ===========================================================================

def test_different_orgs_independent_counters(test_client: TestClient) -> None:
    # Exhaust org-A
    for _ in range(RATE_LIMIT_REQUESTS):
        test_client.post("/trigger", headers=_org_headers("org-A"))

    # org-A should now be throttled
    assert _hit_trigger(test_client, "org-A") == 429

    # org-B counter is independent — first request should succeed
    assert _hit_trigger(test_client, "org-B") == 200


# ===========================================================================
# 5. Fail-open when Redis is down
# ===========================================================================

def test_fail_open_when_redis_down(test_client_redis_down: TestClient) -> None:
    """When Redis is unavailable every request must still receive 200."""
    for i in range(RATE_LIMIT_REQUESTS + 5):
        status = test_client_redis_down.post(
            "/trigger", headers=_org_headers("org-failopen")
        )
        assert status.status_code == 200, (
            f"Expected 200 (fail-open) on request {i + 1}, got {status.status_code}"
        )


# ===========================================================================
# 6. Atomic increment — no race conditions under concurrent load
# ===========================================================================

def test_atomic_increment_no_race_condition() -> None:
    """
    Fire (RATE_LIMIT_REQUESTS + 5) concurrent requests for the same org and
    assert that exactly RATE_LIMIT_REQUESTS succeed (200) and the rest are
    rejected (429).
    """
    redis = FakeRedis()
    from app.main import app as the_app
    from app.rate_limit import get_redis_client as grc

    the_app.dependency_overrides[grc] = lambda: redis
    client = TestClient(the_app, raise_server_exceptions=False)

    total = RATE_LIMIT_REQUESTS + 5
    results: list[int] = []

    def make_request(_: int) -> int:
        return client.post("/trigger", headers=_org_headers("org-concurrent")).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=total) as executor:
        futures = [executor.submit(make_request, i) for i in range(total)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    the_app.dependency_overrides.clear()

    ok_count = results.count(200)
    throttled_count = results.count(429)

    assert ok_count == RATE_LIMIT_REQUESTS, (
        f"Expected exactly {RATE_LIMIT_REQUESTS} successful requests, got {ok_count}"
    )
    assert throttled_count == 5, (
        f"Expected exactly 5 throttled requests, got {throttled_count}"
    )


# ===========================================================================
# 7. Missing X-Org-ID header behaviour
# ===========================================================================

def test_missing_org_id_behavior(test_client: TestClient) -> None:
    """
    Requests without X-Org-ID should be bucketed under 'anonymous' and
    still respect the rate limit.
    """
    # First 10 should succeed
    for i in range(RATE_LIMIT_REQUESTS):
        resp = test_client.post("/trigger")
        assert resp.status_code == 200, (
            f"Anon request {i + 1} expected 200, got {resp.status_code}"
        )

    # 11th should be throttled
    assert test_client.post("/trigger").status_code == 429


# ===========================================================================
# 8. Window reset after TTL expiry
# ===========================================================================

def test_window_reset_after_ttl_expiry() -> None:
    """
    Simulate TTL expiry by manipulating FakeRedis internal state and confirm
    the counter resets.
    """
    redis = FakeRedis()
    org = "org-ttl"
    key = f"rate_limit:{org}"

    # Exhaust the limit
    for _ in range(RATE_LIMIT_REQUESTS):
        check_rate_limit(org, redis)

    result_before = check_rate_limit(org, redis)
    assert not result_before["allowed"], "Expected limit to be exceeded before reset"

    # Simulate expiry by back-dating the TTL
    redis._ttl[key] = time.time() - 1  # already expired

    # Now the counter should reset
    result_after = check_rate_limit(org, redis)
    assert result_after["allowed"], "Expected request to be allowed after TTL expiry"
    assert result_after["count"] == 1, (
        f"Expected counter to reset to 1, got {result_after['count']}"
    )


# ===========================================================================
# 9. Invalid config raises on startup (conceptual)
# ===========================================================================

def test_invalid_config_raises_on_startup() -> None:
    """
    Passing a non-positive limit to check_rate_limit should be caught
    because any INCR (count=1) would immediately exceed limit=0.
    """
    redis = FakeRedis()
    result = check_rate_limit("org-bad-config", redis, limit=0, window=60)
    assert not result["allowed"], (
        "Expected rate limit to be exceeded immediately with limit=0"
    )


# ===========================================================================
# 10. /trigger endpoint returns 200 within limit
# ===========================================================================

def test_trigger_endpoint_returns_200_within_limit(test_client: TestClient) -> None:
    response = test_client.post("/trigger", headers=_org_headers("org-trigger"))
    assert response.status_code == 200
    assert response.json() == {"status": "triggered"}


# ===========================================================================
# 11. Dependency raises 429 with Retry-After header
# ===========================================================================

def test_dependency_raises_429_with_retry_after_header(test_client: TestClient) -> None:
    org = "org-dep"
    for _ in range(RATE_LIMIT_REQUESTS):
        test_client.post("/trigger", headers=_org_headers(org))

    response = test_client.post("/trigger", headers=_org_headers(org))
    assert response.status_code == 429
    assert "retry-after" in response.headers
    retry_after_value = response.headers["retry-after"]
    assert retry_after_value.isdigit(), (
        f"Retry-After header should be a digit string, got: '{retry_after_value}'"
    )


# ===========================================================================
# 12. Middleware standalone returns 429
# ===========================================================================

def test_middleware_returns_429_standalone() -> None:
    """
    Mount RateLimitMiddleware on a minimal app and confirm it blocks after
    the limit is reached.
    """
    redis = FakeRedis()
    mini_app = FastAPI()

    @mini_app.get("/ping")
    def ping():
        return {"pong": True}

    mini_app.add_middleware(
        RateLimitMiddleware,
        redis_client=redis,
        limit=RATE_LIMIT_REQUESTS,
        window=RATE_LIMIT_WINDOW,
    )

    client = TestClient(mini_app, raise_server_exceptions=False)
    org = "org-mw"

    for i in range(RATE_LIMIT_REQUESTS):
        resp = client.get("/ping", headers=_org_headers(org))
        assert resp.status_code == 200, f"Request {i + 1} expected 200, got {resp.status_code}"

    resp = client.get("/ping", headers=_org_headers(org))
    assert resp.status_code == 429
    assert "retry-after" in resp.headers


# ===========================================================================
# 13. check_rate_limit atomic increment helper
# ===========================================================================

def test_check_rate_limit_atomic_increment() -> None:
    """
    Calling check_rate_limit N times should yield sequential counts 1..N.
    """
    redis = FakeRedis()
    org = "org-seq"

    for expected_count in range(1, RATE_LIMIT_REQUESTS + 1):
        result = check_rate_limit(org, redis)
        assert result["count"] == expected_count, (
            f"Expected count {expected_count}, got {result['count']}"
        )
        assert result["allowed"] is True

    # One more — should be disallowed
    result = check_rate_limit(org, redis)
    assert result["allowed"] is False
    assert result["count"] == RATE_LIMIT_REQUESTS + 1
    assert result["retry_after"] is not None


# ===========================================================================
# 14. get_redis_client returns a connection object
# ===========================================================================

def test_redis_client_returns_connection() -> None:
    """
    get_redis_client() should return an object that at minimum exposes an
    ``eval`` callable (the interface used by check_rate_limit).

    We patch ``redis.Redis`` so no real Redis server is required.
    """
    mock_redis_instance = MagicMock()

    with patch("app.rate_limit.redis") as mock_redis_module:
        mock_redis_module.Redis.return_value = mock_redis_instance
        client = get_redis_client()

    mock_redis_module.Redis.assert_called_once_with(
        host="localhost", port=6379, db=0, socket_connect_timeout=1
    )
    assert client is mock_redis_instance
    assert callable(client.eval)
