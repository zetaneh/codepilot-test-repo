"""
Shared pytest fixtures for the Todo API test suite.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.rate_limit import get_redis_client, RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeRedis:
    """
    In-memory Redis stub that implements the subset of the Redis API used by
    the rate-limit module (INCR / EXPIRE / TTL / eval of the Lua script).

    All state is stored in plain Python dicts so tests remain fully isolated
    without requiring a real Redis server or the ``fakeredis`` package.
    """

    def __init__(self) -> None:
        self._store: dict[str, int] = {}
        self._ttl: dict[str, float] = {}   # absolute expiry timestamp (time.time)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_expired(self, key: str) -> bool:
        import time
        expiry = self._ttl.get(key)
        if expiry is None:
            return False
        return time.time() >= expiry

    def _maybe_expire(self, key: str) -> None:
        if self._is_expired(key):
            self._store.pop(key, None)
            self._ttl.pop(key, None)

    # ------------------------------------------------------------------
    # Redis commands
    # ------------------------------------------------------------------

    def incr(self, key: str) -> int:
        self._maybe_expire(key)
        self._store[key] = self._store.get(key, 0) + 1
        return self._store[key]

    def expire(self, key: str, seconds: int) -> int:
        import time
        self._ttl[key] = time.time() + seconds
        return 1

    def ttl(self, key: str) -> int:
        import time
        self._maybe_expire(key)
        expiry = self._ttl.get(key)
        if expiry is None:
            return -1
        remaining = expiry - time.time()
        return max(0, int(remaining))

    def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                count += 1
            self._ttl.pop(key, None)
        return count

    def eval(self, script: str, numkeys: int, *args) -> int:  # noqa: ARG002
        """
        Minimal Lua-script emulation: executes the INCR + conditional EXPIRE
        logic defined in ``app.rate_limit.LUA_SCRIPT``.
        """
        key = args[0]
        # window = args[2] — not needed; EXPIRE is handled below
        self._maybe_expire(key)
        current = self.incr(key)
        if current == 1:
            window = int(args[2])
            self.expire(key, window)
        return current

    def flushall(self) -> None:
        self._store.clear()
        self._ttl.clear()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_redis() -> FakeRedis:
    """
    A fresh in-memory Redis stub for each test.
    """
    return FakeRedis()


@pytest.fixture()
def redis_down():
    """
    A mock Redis client whose every method raises ``ConnectionError``,
    simulating a Redis outage.
    """
    broken = MagicMock()
    broken.eval.side_effect = ConnectionError("Redis is down")
    broken.incr.side_effect = ConnectionError("Redis is down")
    broken.expire.side_effect = ConnectionError("Redis is down")
    broken.ttl.side_effect = ConnectionError("Redis is down")
    return broken


@pytest.fixture()
def test_client(fake_redis: FakeRedis) -> TestClient:
    """
    FastAPI ``TestClient`` with ``get_redis_client`` overridden to return
    the in-memory ``FakeRedis`` stub.  Each test gets a fresh counter state.
    """
    app.dependency_overrides[get_redis_client] = lambda: fake_redis
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture()
def test_client_redis_down(redis_down) -> TestClient:
    """
    FastAPI ``TestClient`` where Redis is unavailable (fail-open expected).
    """
    app.dependency_overrides[get_redis_client] = lambda: redis_down
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()
