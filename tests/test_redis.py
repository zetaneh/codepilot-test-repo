"""
Tests for app/core/redis.py
"""
import importlib
import sys
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper: reset module-level state between tests
# ---------------------------------------------------------------------------

def _reload_redis_module():
    """Force a fresh import of app.core.redis so _redis_pool is None."""
    mod_name = "app.core.redis"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    return importlib.import_module(mod_name)


# ---------------------------------------------------------------------------
# Test: get_redis yields None when Redis is unavailable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_redis_returns_none_when_unavailable():
    """
    When the Redis server is unreachable (ping raises an exception),
    get_redis() should yield None instead of propagating the error.
    """
    redis_mod = _reload_redis_module()

    # Build a fake aioredis module whose from_url returns a client
    # whose ping() raises a connection error
    fake_client = AsyncMock()
    fake_client.ping = AsyncMock(side_effect=ConnectionError("Redis unreachable"))

    fake_aioredis = MagicMock()
    fake_aioredis.from_url = MagicMock(return_value=fake_client)

    with patch.object(redis_mod, "aioredis", fake_aioredis):
        # Reset pool so _get_pool() tries to create a new one
        redis_mod._redis_pool = None

        gen: AsyncGenerator = redis_mod.get_redis()
        result = await gen.__anext__()

        assert result is None, (
            "get_redis() should yield None when connection fails, "
            f"but got {result!r}"
        )

        # Clean up the generator
        try:
            await gen.aclose()
        except StopAsyncIteration:
            pass


@pytest.mark.asyncio
async def test_get_redis_returns_client_when_available():
    """
    When Redis is reachable, get_redis() should yield the client.
    """
    redis_mod = _reload_redis_module()

    fake_client = AsyncMock()
    fake_client.ping = AsyncMock(return_value=True)

    fake_aioredis = MagicMock()
    fake_aioredis.from_url = MagicMock(return_value=fake_client)

    with patch.object(redis_mod, "aioredis", fake_aioredis):
        redis_mod._redis_pool = None

        gen: AsyncGenerator = redis_mod.get_redis()
        result = await gen.__anext__()

        assert result is fake_client

        try:
            await gen.aclose()
        except StopAsyncIteration:
            pass


@pytest.mark.asyncio
async def test_close_redis_resets_pool():
    """
    close_redis() should aclose the pool and reset _redis_pool to None.
    """
    redis_mod = _reload_redis_module()

    fake_client = AsyncMock()
    fake_client.aclose = AsyncMock()
    redis_mod._redis_pool = fake_client

    await redis_mod.close_redis()

    fake_client.aclose.assert_awaited_once()
    assert redis_mod._redis_pool is None


@pytest.mark.asyncio
async def test_close_redis_is_noop_when_pool_is_none():
    """
    close_redis() should not raise when there is no active pool.
    """
    redis_mod = _reload_redis_module()
    redis_mod._redis_pool = None

    # Should complete without error
    await redis_mod.close_redis()

    assert redis_mod._redis_pool is None
