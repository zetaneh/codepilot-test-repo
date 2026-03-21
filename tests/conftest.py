import time
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


class FakePipeline:
    def __init__(self, redis_store):
        self._store = redis_store
        self._commands = []

    def incr(self, key):
        self._commands.append(("incr", key))
        return self

    def expire(self, key, seconds):
        self._commands.append(("expire", key, seconds))
        return self

    async def execute(self):
        results = []
        for cmd in self._commands:
            if cmd[0] == "incr":
                key = cmd[1]
                self._store["values"][key] = self._store["values"].get(key, 0) + 1
                results.append(self._store["values"][key])
            elif cmd[0] == "expire":
                key, seconds = cmd[1], cmd[2]
                self._store["expiry"][key] = time.time() + seconds
                results.append(True)
        self._commands = []
        return results


class FakeRedis:
    def __init__(self):
        self._values: dict = {}
        self._expiry: dict = {}
        self._store = {"values": self._values, "expiry": self._expiry}

    def _is_expired(self, key: str) -> bool:
        if key in self._expiry:
            if time.time() > self._expiry[key]:
                del self._values[key]
                del self._expiry[key]
                return True
        return False

    async def incr(self, key: str) -> int:
        if self._is_expired(key):
            pass
        self._values[key] = self._values.get(key, 0) + 1
        return self._values[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self._expiry[key] = time.time() + seconds
        return True

    async def ttl(self, key: str) -> int:
        if key not in self._values or self._is_expired(key):
            return -2
        if key not in self._expiry:
            return -1
        remaining = int(self._expiry[key] - time.time())
        return max(remaining, 0)

    def pipeline(self) -> "FakePipeline":
        return FakePipeline(self._store)

    async def eval(self, script: str, numkeys: int, *args) -> list:
        key = args[0]
        window = int(args[1])

        if self._is_expired(key):
            pass

        self._values[key] = self._values.get(key, 0) + 1
        current = self._values[key]

        if current == 1:
            self._expiry[key] = time.time() + window

        if key in self._expiry:
            remaining = int(self._expiry[key] - time.time())
            ttl_val = max(remaining, 0)
        else:
            ttl_val = -1

        return [current, ttl_val]


@pytest.fixture
def fake_redis() -> FakeRedis:
    """In-memory async Redis fixture supporting INCR, EXPIRE, TTL, pipeline, and eval."""
    return FakeRedis()


@pytest.fixture
def app_client():
    """TestClient fixture wrapping the full FastAPI app."""
    from app.main import app
    with TestClient(app) as client:
        yield client


@pytest.fixture
def redis_unavailable():
    """Patches get_redis_client to raise ConnectionError (simulates Redis being down)."""
    with patch(
        "app.core.redis.get_redis_client",
        side_effect=ConnectionError("Redis unavailable"),
    ) as mock:
        yield mock
