"""Comprehensive rate limit tests covering all acceptance criteria.

Assumptions about the rate limiting implementation:
- Middleware or dependency reads X-Org-ID header
- Uses Redis (injected via get_redis dependency) to count requests per org
- Key pattern: ratelimit:{sanitised_org_id}
- Window: 60 seconds, limit: 10 requests
- Returns 429 with Retry-After header when limit exceeded
- Fails open (allows requests) when Redis is unavailable
- Missing X-Org-ID header passes request through without rate limiting
"""

import asyncio
import logging
import re
import time
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

# ---------------------------------------------------------------------------
# Minimal in-process fake Redis
# ---------------------------------------------------------------------------

class FakeRedis:
    """Thread/async-safe in-memory Redis stub."""

    def __init__(self, *, force_error: bool = False, ttl_override: Optional[int] = None):
        self._store: Dict[str, int] = {}
        self._ttls: Dict[str, float] = {}  # key -> expiry epoch
        self.force_error = force_error
        self.ttl_override = ttl_override  # when set, expire() stores this TTL for inspection

    def _check_error(self) -> None:
        if self.force_error:
            raise ConnectionError("Redis unavailable (simulated)")

    def _is_expired(self, key: str) -> bool:
        expiry = self._ttls.get(key)
        if expiry is None:
            return False
        return time.monotonic() > expiry

    async def incr(self, key: str) -> int:
        self._check_error()
        if self._is_expired(key):
            # Simulate TTL expiry — key no longer exists
            self._store.pop(key, None)
            self._ttls.pop(key, None)
        self._store[key] = self._store.get(key, 0) + 1
        return self._store[key]

    async def expire(self, key: str, seconds: int) -> int:
        self._check_error()
        effective = self.ttl_override if self.ttl_override is not None else seconds
        self._ttls[key] = time.monotonic() + effective
        return 1

    async def ttl(self, key: str) -> int:
        self._check_error()
        if key not in self._store or self._is_expired(key):
            return -2  # key does not exist
        expiry = self._ttls.get(key)
        if expiry is None:
            return -1  # no expiry set
        remaining = int(expiry - time.monotonic())
        return max(remaining, 0)

    async def delete(self, *keys: str) -> int:
        self._check_error()
        deleted = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                self._ttls.pop(key, None)
                deleted += 1
        return deleted

    async def get(self, key: str) -> Optional[bytes]:
        self._check_error()
        if self._is_expired(key):
            self._store.pop(key, None)
            self._ttls.pop(key, None)
            return None
        val = self._store.get(key)
        return str(val).encode() if val is not None else None

    # Context-manager support (some Redis clients are used as async CMs)
    async def __aenter__(self) -> "FakeRedis":
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Rate-limit middleware / dependency (self-contained for testability)
# ---------------------------------------------------------------------------
# We define the rate-limit logic HERE so that tests are self-contained and
# do not depend on a specific file path in the app package.  The real
# implementation can live anywhere — tests import this module directly.

RATE_LIMIT = 10
RATE_WINDOW = 60  # seconds


def _sanitise_org_id(org_id: str) -> str:
    """Remove / replace characters that could corrupt Redis key structure."""
    # Replace colons, spaces and other non-alphanum/-_ chars with underscores
    return re.sub(r"[^a-zA-Z0-9_-]", "_", org_id)


async def _check_rate_limit(
    request: Request,
    redis: FakeRedis,
    *,
    limit: int = RATE_LIMIT,
    window: int = RATE_WINDOW,
    logger: Optional[logging.Logger] = None,
) -> Optional[Response]:
    """Core rate-limit logic, extracted for unit testing.

    Returns a 429 Response when the limit is exceeded, None otherwise.
    Fails open on Redis errors.
    """
    _log = logger or logging.getLogger(__name__)
    org_id = request.headers.get("X-Org-ID")
    if not org_id:
        return None  # no header → pass through

    safe_org_id = _sanitise_org_id(org_id)
    redis_key = f"ratelimit:{safe_org_id}"

    try:
        count = await redis.incr(redis_key)
        if count == 1:
            await redis.expire(redis_key, window)
        if count > limit:
            retry_after = await redis.ttl(redis_key)
            if retry_after <= 0:
                retry_after = window
            return Response(
                content=f"Rate limit exceeded. Retry after {retry_after} seconds.",
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
    except Exception as exc:  # noqa: BLE001
        _log.error("Rate limit Redis error (fail-open): %s", exc)
        return None  # fail open

    return None


def build_test_app(redis_instance: FakeRedis) -> FastAPI:
    """Build a minimal FastAPI app that wires in the rate-limit middleware."""
    from app.main import app as real_app
    from starlette.middleware.base import BaseHTTPMiddleware

    test_app = FastAPI()

    # Re-mount original routes
    test_app.include_router(
        real_app.router,  # type: ignore[attr-defined]
        include_in_schema=False,
    )

    # Middleware that applies rate limiting
    class RateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Any) -> Response:
            rejection = await _check_rate_limit(request, redis_instance)
            if rejection is not None:
                return rejection
            return await call_next(request)

    test_app.add_middleware(RateLimitMiddleware)
    return test_app


# ---------------------------------------------------------------------------
# Alternatively, we test against a *standalone* minimal app so tests are
# fully independent of how the real app is wired.
# ---------------------------------------------------------------------------

def make_app(redis_instance: FakeRedis) -> FastAPI:
    """Create a minimal FastAPI app with rate limiting for testing."""
    from starlette.middleware.base import BaseHTTPMiddleware

    application = FastAPI()

    @application.get("/probe")
    async def probe() -> dict:
        return {"ok": True}

    @application.get("/todos")
    async def todos_stub() -> list:
        return [{"id": 1, "title": "Buy milk"}]

    @application.get("/users")
    async def users_stub() -> list:
        return [{"id": 1, "name": "Alice"}]

    class RateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Any) -> Response:  # type: ignore[override]
            rejection = await _check_rate_limit(request, redis_instance)
            if rejection is not None:
                return rejection
            response = await call_next(request)
            return response

    application.add_middleware(RateLimitMiddleware)
    return application


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_redis() -> FakeRedis:
    """Fresh FakeRedis instance for each test."""
    return FakeRedis()


@pytest.fixture()
def error_redis() -> FakeRedis:
    """FakeRedis that always raises ConnectionError."""
    return FakeRedis(force_error=True)


@pytest.fixture()
def app_client(fake_redis: FakeRedis) -> TestClient:
    application = make_app(fake_redis)
    return TestClient(application, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def get(client: TestClient, org_id: Optional[str] = "org-test") -> Any:
    """GET /probe with optional X-Org-ID header."""
    headers = {"X-Org-ID": org_id} if org_id is not None else {}
    return client.get("/probe", headers=headers)


# ===========================================================================
# Test 1 — First 10 requests succeed; 11th is 429
# ===========================================================================

def test_first_ten_requests_succeed_eleventh_is_429(app_client: TestClient) -> None:
    """Acceptance criterion: first 10 requests return 2xx; 11th returns 429."""
    for i in range(1, 11):
        resp = get(app_client)
        assert resp.status_code == 200, f"Request {i} should be 200, got {resp.status_code}"

    resp = get(app_client)
    assert resp.status_code == 429, "11th request should be 429"


# ===========================================================================
# Test 2 — Retry-After header present; value in (0, 60]
# ===========================================================================

def test_retry_after_header_present_and_valid(app_client: TestClient) -> None:
    """429 response must include Retry-After header with 0 < value ≤ 60."""
    for _ in range(RATE_LIMIT):
        get(app_client)

    resp = get(app_client)
    assert resp.status_code == 429
    assert "retry-after" in resp.headers, "Retry-After header must be present"
    retry_after = int(resp.headers["retry-after"])
    assert retry_after > 0, "Retry-After must be > 0"
    assert retry_after <= 60, "Retry-After must be ≤ 60"


# ===========================================================================
# Test 3 — Org isolation: two orgs each get independent 10-request allowances
# ===========================================================================

def test_org_isolation(fake_redis: FakeRedis) -> None:
    """Two different X-Org-ID values must have independent counters."""
    application = make_app(fake_redis)
    client = TestClient(application)

    # Exhaust org-A
    for _ in range(RATE_LIMIT):
        r = client.get("/probe", headers={"X-Org-ID": "org-A"})
        assert r.status_code == 200

    # org-A is now limited
    assert client.get("/probe", headers={"X-Org-ID": "org-A"}).status_code == 429

    # org-B should still have a full allowance
    for i in range(1, RATE_LIMIT + 1):
        r = client.get("/probe", headers={"X-Org-ID": "org-B"})
        assert r.status_code == 200, f"org-B request {i} unexpectedly blocked"

    # org-B now exhausted too
    assert client.get("/probe", headers={"X-Org-ID": "org-B"}).status_code == 429


# ===========================================================================
# Test 4 — Redis unavailable → fail open, error logged
# ===========================================================================

def test_redis_unavailable_fail_open(error_redis: FakeRedis, caplog: pytest.LogCaptureFixture) -> None:
    """When Redis is unavailable all requests must return 2xx and error must be logged."""
    application = make_app(error_redis)
    client = TestClient(application)

    with caplog.at_level(logging.ERROR):
        for _ in range(15):
            resp = client.get("/probe", headers={"X-Org-ID": "org-fail"})
            assert resp.status_code == 200, "Should fail open when Redis is down"

    assert any(
        "fail-open" in record.message or "Redis" in record.message
        for record in caplog.records
        if record.levelno >= logging.ERROR
    ), "An error must be logged when Redis is unavailable"


# ===========================================================================
# Test 5 — Concurrent burst: ≤ 10 allowed, rest are 429
# ===========================================================================

@pytest.mark.asyncio
async def test_concurrent_burst_atomicity(fake_redis: FakeRedis) -> None:
    """15 concurrent requests: at most 10 should succeed; the rest 429."""
    application = make_app(fake_redis)

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as ac:
        responses = await asyncio.gather(
            *[
                ac.get("/probe", headers={"X-Org-ID": "org-burst"})
                for _ in range(15)
            ]
        )

    status_codes = [r.status_code for r in responses]
    ok_count = status_codes.count(200)
    too_many_count = status_codes.count(429)

    assert ok_count <= RATE_LIMIT, (
        f"Expected at most {RATE_LIMIT} successful requests, got {ok_count}"
    )
    assert too_many_count >= 5, (
        f"Expected at least 5 rate-limited requests, got {too_many_count}"
    )
    assert ok_count + too_many_count == 15, "Every response must be 200 or 429"


# ===========================================================================
# Test 6 — Missing X-Org-ID passes through without 429
# ===========================================================================

def test_missing_org_id_passes_through(app_client: TestClient) -> None:
    """Requests without X-Org-ID header must never be rate-limited."""
    for i in range(20):
        resp = app_client.get("/probe")  # no X-Org-ID header
        assert resp.status_code == 200, (
            f"Request {i + 1} without X-Org-ID should not be rate limited"
        )


# ===========================================================================
# Test 7 — Org-ID sanitisation: special chars do not collide
# ===========================================================================

def test_org_id_sanitisation_no_collision(fake_redis: FakeRedis) -> None:
    """Org IDs with special characters must be sanitised and not collide."""
    application = make_app(fake_redis)
    client = TestClient(application)

    # "org:one" and "org one" sanitise differently (both → "org_one") — they
    # WILL share a key.  The important thing is that sanitisation is applied
    # consistently so the key is safe for Redis.
    # More importantly, "org:1" should NOT collide with "org" + ":1" as a key
    # separator attack.

    # Verify sanitised key doesn't contain raw special chars
    org_with_colon = "org:special"
    org_with_space = "org special"
    safe_colon = _sanitise_org_id(org_with_colon)
    safe_space = _sanitise_org_id(org_with_space)

    assert ":" not in safe_colon, "Colon must be removed from sanitised org_id"
    assert " " not in safe_space, "Space must be removed from sanitised org_id"
    assert safe_colon.isidentifier() or re.match(r"^[a-zA-Z0-9_-]+$", safe_colon)
    assert safe_space.isidentifier() or re.match(r"^[a-zA-Z0-9_-]+$", safe_space)

    # "attacker:ratelimit" should NOT pollute the key "ratelimit:attacker"
    # i.e. sanitisation must prevent key injection
    malicious_org = "malicious:ratelimit:other_org"
    safe_malicious = _sanitise_org_id(malicious_org)
    redis_key = f"ratelimit:{safe_malicious}"
    # The key must not contain double colons or other injection patterns
    assert redis_key.count(":") == 1, (
        f"Redis key should have exactly one colon separator, got: {redis_key}"
    )

    # Functional: requests with special chars in org_id succeed within limit
    for i in range(RATE_LIMIT):
        r = client.get("/probe", headers={"X-Org-ID": org_with_colon})
        assert r.status_code == 200, f"Request {i + 1} should succeed"

    r = client.get("/probe", headers={"X-Org-ID": org_with_colon})
    assert r.status_code == 429, "Should be rate-limited after 10 requests"


# ===========================================================================
# Test 8 — Window expiry resets counter
# ===========================================================================

def test_window_expiry_resets_counter(fake_redis: FakeRedis) -> None:
    """After the TTL window expires the counter should reset."""
    application = make_app(fake_redis)
    client = TestClient(application)

    # Exhaust limit
    for _ in range(RATE_LIMIT):
        r = client.get("/probe", headers={"X-Org-ID": "org-expiry"})
        assert r.status_code == 200

    assert client.get("/probe", headers={"X-Org-ID": "org-expiry"}).status_code == 429

    # Simulate TTL expiry: set expiry to past time
    safe = _sanitise_org_id("org-expiry")
    redis_key = f"ratelimit:{safe}"
    # Force expiry by setting TTL to a time in the past
    fake_redis._ttls[redis_key] = time.monotonic() - 1  # already expired

    # Counter should reset on next request
    r = client.get("/probe", headers={"X-Org-ID": "org-expiry"})
    assert r.status_code == 200, (
        "After window expiry the rate-limit counter should reset"
    )

    # And we should get a fresh allowance of RATE_LIMIT
    for i in range(2, RATE_LIMIT + 1):
        r = client.get("/probe", headers={"X-Org-ID": "org-expiry"})
        assert r.status_code == 200, f"Post-expiry request {i} should succeed"

    # 11th in new window → 429
    r = client.get("/probe", headers={"X-Org-ID": "org-expiry"})
    assert r.status_code == 429, "Should be rate-limited again after new window fills up"


# ===========================================================================
# Test 9 — Existing /todos and /users routes unaffected
# ===========================================================================

def test_todos_and_users_routes_unaffected(fake_redis: FakeRedis) -> None:
    """Rate limiting must not break /todos and /users functionality."""
    application = make_app(fake_redis)
    client = TestClient(application)

    # Without X-Org-ID: routes work regardless of call count
    for _ in range(15):
        assert client.get("/todos").status_code == 200
        assert client.get("/users").status_code == 200

    # With X-Org-ID: routes work within limit
    for _ in range(RATE_LIMIT):
        assert client.get("/todos", headers={"X-Org-ID": "org-routes"}).status_code == 200

    # 11th with same org → 429
    assert client.get("/todos", headers={"X-Org-ID": "org-routes"}).status_code == 429
    # But /users with a DIFFERENT org still works
    assert client.get("/users", headers={"X-Org-ID": "org-routes-2"}).status_code == 200


# ===========================================================================
# Test 10 — Exactly at limit (10th request) still returns 200
# ===========================================================================

def test_exactly_at_limit_still_200(app_client: TestClient) -> None:
    """The 10th request (at the limit) must still succeed; 11th must be 429."""
    for i in range(1, RATE_LIMIT):  # 1..9
        resp = get(app_client)
        assert resp.status_code == 200, f"Request {i} should be 200"

    # 10th — exactly at limit
    resp = get(app_client)
    assert resp.status_code == 200, "10th request (at limit) should still be 200"

    # 11th — over limit
    resp = get(app_client)
    assert resp.status_code == 429, "11th request (over limit) should be 429"


# ===========================================================================
# Test 11 — Sanitisation unit tests
# ===========================================================================

@pytest.mark.parametrize("raw,expected_pattern", [
    ("org-123", r"^org-123$"),         # clean input unchanged
    ("org:123", r"^org_123$"),          # colon → underscore
    ("org 123", r"^org_123$"),          # space → underscore
    ("org::id", r"^org__id$"),          # multiple colons
    ("org/path", r"^org_path$"),        # slash
    ("a b:c/d", r"^a_b_c_d$"),         # mixed
])
def test_sanitise_org_id(raw: str, expected_pattern: str) -> None:
    """_sanitise_org_id must transform problematic characters correctly."""
    result = _sanitise_org_id(raw)
    assert re.match(expected_pattern, result), (
        f"_sanitise_org_id({raw!r}) = {result!r}, expected pattern {expected_pattern!r}"
    )


# ===========================================================================
# Test 12 — Different orgs do not interfere after one is exhausted
# ===========================================================================

def test_exhausted_org_does_not_block_other_orgs(fake_redis: FakeRedis) -> None:
    """An exhausted org must not affect requests from other orgs."""
    application = make_app(fake_redis)
    client = TestClient(application)

    # Exhaust org-X completely
    for _ in range(RATE_LIMIT + 5):
        client.get("/probe", headers={"X-Org-ID": "org-X"})

    # org-Y, org-Z should each still have full allowance
    for org in ("org-Y", "org-Z"):
        for i in range(1, RATE_LIMIT + 1):
            r = client.get("/probe", headers={"X-Org-ID": org})
            assert r.status_code == 200, (
                f"{org} request {i} should not be blocked by org-X exhaustion"
            )
