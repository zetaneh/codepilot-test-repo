"""
Redis client module for async connection pool management.

Provides a get_redis() FastAPI dependency that yields a connected
redis.asyncio client, or None if the connection is unavailable (fail-open).
"""

import logging
import os
from typing import AsyncGenerator, Optional

try:
    import redis.asyncio as aioredis
    from redis.asyncio import Redis
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover
    aioredis = None  # type: ignore
    Redis = None  # type: ignore
    RedisError = Exception  # type: ignore

logger = logging.getLogger(__name__)

# Module-level pool, initialised lazily
_redis_pool: Optional["Redis"] = None

REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")


async def _get_pool() -> Optional["Redis"]:
    """Return (or create) the module-level Redis connection pool."""
    global _redis_pool

    if aioredis is None:
        logger.error(
            "redis package is not installed. "
            "Install it with: pip install redis[asyncio]"
        )
        return None

    if _redis_pool is None:
        try:
            _redis_pool = aioredis.from_url(
                REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=2,
            )
            # Ping to verify the connection is reachable
            await _redis_pool.ping()
            logger.info("Redis connection pool initialised at %s", REDIS_URL)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to connect to Redis at %s: %s", REDIS_URL, exc
            )
            _redis_pool = None

    return _redis_pool


async def get_redis() -> AsyncGenerator[Optional["Redis"], None]:
    """
    FastAPI dependency that yields a Redis client.

    If the connection is unavailable the dependency yields None so that
    callers can implement fail-open logic without raising an unhandled
    exception.

    Usage::

        @router.get("/")
        async def my_endpoint(redis=Depends(get_redis)):
            if redis is not None:
                cached = await redis.get("my_key")
    """
    client: Optional["Redis"] = None
    try:
        client = await _get_pool()
        yield client
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected Redis error: %s", exc)
        yield None


async def close_redis() -> None:
    """
    Teardown coroutine — closes the Redis connection pool.

    Call this from your application lifespan shutdown handler.
    """
    global _redis_pool

    if _redis_pool is not None:
        try:
            await _redis_pool.aclose()
            logger.info("Redis connection pool closed.")
        except Exception as exc:  # noqa: BLE001
            logger.error("Error while closing Redis pool: %s", exc)
        finally:
            _redis_pool = None
