"""
Async Redis client singleton using redis-py (asyncio).

Lazily initialises a connection pool from the REDIS_URL environment variable.
Does NOT connect at import time.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

_redis_client: Optional[aioredis.Redis] = None


async def get_redis() -> Optional[aioredis.Redis]:
    """Return the shared async Redis client, creating it on first call.

    Returns:
        A connected ``redis.asyncio.Redis`` instance, or ``None`` if the
        connection could not be established.
    """
    global _redis_client

    if _redis_client is not None:
        return _redis_client

    try:
        client: aioredis.Redis = aioredis.from_url(
            REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        # Verify the connection is actually reachable.
        await client.ping()
        _redis_client = client
        logger.info("Redis connection established: %s", REDIS_URL)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to connect to Redis at %s: %s", REDIS_URL, exc)
        return None

    return _redis_client


async def close_redis() -> None:
    """Close the shared Redis client and reset the singleton."""
    global _redis_client

    if _redis_client is not None:
        try:
            await _redis_client.aclose()
            logger.info("Redis connection closed.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error while closing Redis connection: %s", exc)
        finally:
            _redis_client = None
