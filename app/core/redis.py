"""
Async Redis client utility with connection pooling and graceful degradation.
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_redis_client = None

try:
    import redis.asyncio as aioredis
    from redis.asyncio import Redis
    from redis.asyncio.connection import ConnectionPool
    from redis.exceptions import RedisError
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False
    logger.warning("redis package not installed; Redis features disabled")


def _get_redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6379")


def get_redis_client() -> Optional["Redis"]:
    """
    Return an async Redis client using a connection pool, or None if unavailable.

    Reads REDIS_URL from environment. Catches import and connection errors,
    logs them, and returns None so callers can fail open.
    """
    if not _REDIS_AVAILABLE:
        logger.warning("Redis package not available; returning None")
        return None

    url = _get_redis_url()
    try:
        pool = ConnectionPool.from_url(url, max_connections=10, decode_responses=True)
        client = Redis(connection_pool=pool)
        return client
    except Exception as exc:
        logger.error("Failed to create Redis client from %s: %s", url, exc)
        return None


async def redis_health_check() -> bool:
    """
    Ping Redis and return True if reachable, False otherwise.
    """
    if not _REDIS_AVAILABLE:
        return False

    client = get_redis_client()
    if client is None:
        return False

    try:
        await client.ping()
        return True
    except Exception as exc:
        logger.warning("Redis health check failed: %s", exc)
        return False
