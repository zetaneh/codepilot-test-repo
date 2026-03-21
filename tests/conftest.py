"""
Test fixtures and helpers for the Todo API test suite.
"""
import asyncio
from typing import Any, AsyncIterator, Dict, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
httpx = pytest.importorskip("httpx")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeRedis:
    """
    In-memory async Redis mock that supports the minimal interface used by
    the rate-limit middleware:
      - EVAL / EVALSHA (Lua-style sliding-window scripts)
      - GET
      - TTL
      - SET / SETEX
      - INCR / EXPIRE
      - PING
      - close
    """

    def __init__(self) -> None:
        self._store: Dict[str, Any] = {}
        self._ttls: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _is_expired(self, key: str) -> bool:
        import time
        if key in self._ttls:
            if time.monotonic() > self._ttls[key]:
                self._store.pop(key, None)
                self._ttls.pop(key, None)
                return True
        return False

    def _get_raw(self, key: str) -> Optional[Any]:
        if self._is_expired(key):
            return None
        return self._store.get(key)

    # ------------------------------------------------------------------
    # Public async interface
    # ------------------------------------------------------------------
    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> Optional[bytes]:
        value = self._get_raw(key)
        if value is None:
            return None
        return str(value).encode() if not isinstance(value, bytes) else value

    async def set(
        self,
        key: str,
        value: Any,
        ex: Optional[int] = None,
        px: Optional[int] = None,
        nx: bool = False,
    ) -> bool:
        import time
        if nx and self._get_raw(key) is not None:
            return False
        self._store[key] = value
        if ex is not None:
            self._ttls[key] = time.monotonic() + ex
        elif px is not None:
            self._ttls[key] = time.monotonic() + px / 1000.0
        return True

    async def setex(self, key: str, seconds: int, value: Any) -> bool:
        return await self.set(key, value, ex=seconds)

    async def incr(self, key: str) -> int:
        current = self._get_raw(key)
        new_val = int(current) + 1 if current is not None else 1
        self._store[key] = new_val
        return new_val

    async def expire(self, key: str, seconds: int) -> int:
        import time
        if self._get_raw(key) is None:
            return 0
        self._ttls[key] = time.monotonic() + seconds
        return 1

    async def ttl(self, key: str) -> int:
        import time
        if self._is_expired(key):
            return -2
        if key not in self._store:
            return -2
        if key not in self._ttls:
            return -1
        remaining = int(self._ttls[key] - time.monotonic())
        return max(remaining, 0)

    async def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self._store:
                self._store.pop(key, None)
                self._ttls.pop(key, None)
                count += 1
        return count

    async def exists(self, *keys: str) -> int:
        return sum(
            1 for k in keys if self._get_raw(k) is not None
        )

    async def eval(self, script: str, numkeys: int, *args: Any) -> Any:
        """
        Minimal EVAL emulation: implements a token-bucket / fixed-window
        counter pattern commonly used for rate limiting.

        The mock simply increments the first key and returns
        (current_count, ttl_ms) as a two-element list, which mirrors the
        typical response shape of sliding-window Lua scripts.
        """
        import time
        keys = list(args[:numkeys])
        script_args = list(args[numkeys:])

        if not keys:
            return [0, 0]

        key = keys[0]
        limit = int(script_args[0]) if script_args else 100
        window = int(script_args[1]) if len(script_args) > 1 else 60

        current = self._get_raw(key)
        if current is None:
            self._store[key] = 1
            self._ttls[key] = time.monotonic() + window
            current_count = 1
        else:
            current_count = int(current) + 1
            self._store[key] = current_count

        remaining_ms = max(
            int((self._ttls.get(key, time.monotonic()) - time.monotonic()) * 1000),
            0,
        )
        return [current_count, remaining_ms]

    async def evalsha(self, sha: str, numkeys: int, *args: Any) -> Any:
        """Delegate to eval (we don't cache scripts in tests)."""
        # We don't have the original script, so reuse eval with a no-op script.
        # In practice the rate-limit middleware calls evalsha with a known SHA;
        # for tests we just run the same counter logic.
        return await self.eval("", numkeys, *args)

    async def close(self) -> None:
        pass

    # Allow use as async context manager
    async def __aenter__(self) -> "FakeRedis":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()


class UnavailableRedis:
    """A Redis stand-in that raises ConnectionError on every operation."""

    _ERROR_MSG = "Redis unavailable (simulated)"

    async def ping(self) -> bool:
        raise ConnectionError(self._ERROR_MSG)

    async def get(self, *args: Any, **kwargs: Any) -> None:
        raise ConnectionError(self._ERROR_MSG)

    async def set(self, *args: Any, **kwargs: Any) -> None:
        raise ConnectionError(self._ERROR_MSG)

    async def setex(self, *args: Any, **kwargs: Any) -> None:
        raise ConnectionError(self._ERROR_MSG)

    async def incr(self, *args: Any, **kwargs: Any) -> None:
        raise ConnectionError(self._ERROR_MSG)

    async def expire(self, *args: Any, **kwargs: Any) -> None:
        raise ConnectionError(self._ERROR_MSG)

    async def ttl(self, *args: Any, **kwargs: Any) -> None:
        raise ConnectionError(self._ERROR_MSG)

    async def delete(self, *args: Any, **kwargs: Any) -> None:
        raise ConnectionError(self._ERROR_MSG)

    async def exists(self, *args: Any, **kwargs: Any) -> None:
        raise ConnectionError(self._ERROR_MSG)

    async def eval(self, *args: Any, **kwargs: Any) -> None:
        raise ConnectionError(self._ERROR_MSG)

    async def evalsha(self, *args: Any, **kwargs: Any) -> None:
        raise ConnectionError(self._ERROR_MSG)

    async def close(self) -> None:
        pass

    async def __aenter__(self) -> "UnavailableRedis":
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_redis() -> FakeRedis:
    """
    Function-scoped in-memory Redis mock.

    Supports EVAL/EVALSHA, GET, TTL, SET/SETEX, INCR/EXPIRE, PING.
    Each test gets a fresh, empty instance for full isolation.
    """
    return FakeRedis()


@pytest.fixture()
def unavailable_redis() -> UnavailableRedis:
    """
    Function-scoped Redis mock that raises ConnectionError on every call.

    Use this to verify that the middleware / application degrades
    gracefully when Redis is down.
    """
    return UnavailableRedis()


@pytest.fixture()
def test_client():
    """
    Function-scoped synchronous TestClient for the FastAPI app.

    Uses Starlette's built-in TestClient so no running event loop is
    required.  For async tests that need httpx directly, use
    ``async_test_client`` instead.
    """
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        yield client


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

async def make_trigger_request(
    client: Any,
    org_id: str,
    n: int,
) -> list:
    """
    Fire *n* POST requests to ``/api/runs/trigger`` with the
    ``X-Org-ID: <org_id>`` header.

    Works with both:
    - ``httpx.AsyncClient`` (awaits ``client.post``)
    - Starlette ``TestClient`` (calls ``client.post`` synchronously)

    Returns a list of response objects in order.

    Parameters
    ----------
    client:
        An httpx AsyncClient or Starlette TestClient instance.
    org_id:
        The organisation identifier to embed in the request header.
    n:
        Number of requests to fire.
    """
    responses = []
    headers = {"X-Org-ID": org_id}

    for _ in range(n):
        result = client.post("/api/runs/trigger", headers=headers)
        # Support both sync (TestClient) and async (httpx.AsyncClient) clients.
        if asyncio.iscoroutine(result):
            result = await result
        responses.append(result)

    return responses
