"""
COD-8 Service Layer

Provides business logic for COD-8 items with:
- Redis caching with TTL and graceful fallback to in-memory store
- Soft-delete awareness
- Optimistic concurrency control via version field
- AI enrichment via Cod8Agent
"""

import json
import logging
import os
import time
from typing import Any, Dict, Optional

from fastapi import HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

COD8_REDIS_TTL_SECONDS: int = int(os.getenv("COD8_REDIS_TTL_SECONDS", "300"))

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class Cod8Create(BaseModel):
    """Payload for creating a COD-8 item."""

    title: str
    description: Optional[str] = None
    user_id: int


class Cod8Update(BaseModel):
    """Payload for updating a COD-8 item (supports optimistic locking)."""

    title: Optional[str] = None
    description: Optional[str] = None
    version: int  # Required for optimistic concurrency control


class Cod8Response(BaseModel):
    """Response model for COD-8 items."""

    id: int
    title: str
    description: Optional[str] = None
    user_id: int
    version: int
    is_deleted: bool
    ai_summary: Optional[str] = None
    created_at: float
    updated_at: float


# ---------------------------------------------------------------------------
# Minimal Cod8Agent stub (resolved at import time to avoid hard dependency)
# ---------------------------------------------------------------------------


class _DefaultCod8Agent:
    """Fallback agent used when no external Cod8Agent is registered."""

    def enrich(self, data: Dict[str, Any]) -> Optional[str]:
        """Return a minimal AI summary."""
        return f"AI summary for: {data.get('title', '')}"


try:
    from app.agents.cod8_agent import Cod8Agent as _Cod8Agent  # type: ignore
except ImportError:
    _Cod8Agent = _DefaultCod8Agent  # type: ignore


# ---------------------------------------------------------------------------
# Redis helper (graceful fallback)
# ---------------------------------------------------------------------------


def _get_redis_client() -> Optional[Any]:
    """Return a Redis client or None if Redis is unavailable."""
    try:
        import redis  # type: ignore

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        client = redis.Redis.from_url(redis_url, socket_connect_timeout=1)
        client.ping()  # verify connectivity
        return client
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis unavailable, falling back to in-memory store: %s", exc)
        return None


# ---------------------------------------------------------------------------
# In-memory store (used when Redis is unavailable or as the source of truth)
# ---------------------------------------------------------------------------

_store: Dict[int, Dict[str, Any]] = {}
_next_id: int = 1


def _next_item_id() -> int:
    global _next_id
    item_id = _next_id
    _next_id += 1
    return item_id


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _cache_key(item_id: int) -> str:
    return f"cod8:item:{item_id}"


def _read_from_cache(item_id: int) -> Optional[Dict[str, Any]]:
    """Attempt to read item from Redis; return None on any failure."""
    client = _get_redis_client()
    if client is None:
        return None
    try:
        raw = client.get(_cache_key(item_id))
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cache read failed for item %d: %s", item_id, exc)
        return None


def _write_to_cache(item: Dict[str, Any]) -> None:
    """Attempt to write item to Redis; silently ignore failures."""
    client = _get_redis_client()
    if client is None:
        return
    try:
        client.setex(
            _cache_key(item["id"]),
            COD8_REDIS_TTL_SECONDS,
            json.dumps(item),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cache write failed for item %d: %s", item.get("id"), exc)


def _invalidate_cache(item_id: int) -> None:
    """Remove an item from the Redis cache; silently ignore failures."""
    client = _get_redis_client()
    if client is None:
        return
    try:
        client.delete(_cache_key(item_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cache invalidation failed for item %d: %s", item_id, exc)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _dict_to_response(item: Dict[str, Any]) -> Cod8Response:
    return Cod8Response(
        id=item["id"],
        title=item["title"],
        description=item.get("description"),
        user_id=item["user_id"],
        version=item["version"],
        is_deleted=item["is_deleted"],
        ai_summary=item.get("ai_summary"),
        created_at=item["created_at"],
        updated_at=item["updated_at"],
    )


# ---------------------------------------------------------------------------
# Cod8Service
# ---------------------------------------------------------------------------


class Cod8Service:
    """Service layer for COD-8 item operations."""

    def __init__(self) -> None:
        self._agent = _Cod8Agent()

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_cod8_item(self, data: Cod8Create) -> Cod8Response:
        """Create a new COD-8 item, enrich it via AI, and cache the result.

        Args:
            data: Creation payload.

        Returns:
            The newly created Cod8Response.
        """
        now = time.time()
        item_id = _next_item_id()

        # AI enrichment — failure must not block the creation
        ai_summary: Optional[str] = None
        try:
            ai_summary = self._agent.enrich({"title": data.title, "description": data.description})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cod8Agent enrichment failed for new item: %s", exc)

        item: Dict[str, Any] = {
            "id": item_id,
            "title": data.title,
            "description": data.description,
            "user_id": data.user_id,
            "version": 1,
            "is_deleted": False,
            "ai_summary": ai_summary,
            "created_at": now,
            "updated_at": now,
        }

        _store[item_id] = item
        _write_to_cache(item)

        logger.info("Created COD-8 item id=%d for user_id=%d", item_id, data.user_id)
        return _dict_to_response(item)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_cod8_item(self, item_id: int, user_id: int) -> Cod8Response:
        """Retrieve a COD-8 item by ID, using Redis cache with fallback.

        Args:
            item_id: Primary key of the item.
            user_id: ID of the requesting user (ownership validation).

        Returns:
            The found Cod8Response.

        Raises:
            HTTPException 404: If the item does not exist or is soft-deleted.
            HTTPException 403: If the item belongs to a different user.
        """
        # 1. Try Redis cache first
        cached = _read_from_cache(item_id)
        if cached is not None:
            logger.debug("Cache hit for COD-8 item id=%d", item_id)
            item = cached
        else:
            # 2. Fall back to in-memory store
            logger.debug("Cache miss for COD-8 item id=%d, reading from store", item_id)
            item = _store.get(item_id)

        if item is None:
            raise HTTPException(status_code=404, detail=f"COD-8 item {item_id} not found")

        if item["is_deleted"]:
            raise HTTPException(
                status_code=404,
                detail=f"COD-8 item {item_id} has been deleted",
            )

        if item["user_id"] != user_id:
            raise HTTPException(
                status_code=403,
                detail="Access denied: item belongs to a different user",
            )

        # Refresh cache if we had a miss
        if cached is None:
            _write_to_cache(item)

        return _dict_to_response(item)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update_cod8_item(
        self, item_id: int, data: Cod8Update, user_id: int
    ) -> Cod8Response:
        """Update a COD-8 item with optimistic concurrency control.

        The caller must supply the current ``version`` in *data*. If the stored
        version does not match, an HTTP 409 Conflict is raised.

        Args:
            item_id: Primary key of the item to update.
            data: Update payload including the expected version.
            user_id: ID of the requesting user.

        Returns:
            The updated Cod8Response.

        Raises:
            HTTPException 404: If the item does not exist or is soft-deleted.
            HTTPException 403: If the item belongs to a different user.
            HTTPException 409: If the version does not match (optimistic lock conflict).
        """
        item = _store.get(item_id)

        if item is None:
            raise HTTPException(status_code=404, detail=f"COD-8 item {item_id} not found")

        if item["is_deleted"]:
            raise HTTPException(
                status_code=404,
                detail=f"COD-8 item {item_id} has been deleted",
            )

        if item["user_id"] != user_id:
            raise HTTPException(
                status_code=403,
                detail="Access denied: item belongs to a different user",
            )

        # Optimistic concurrency check
        if item["version"] != data.version:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Version conflict: expected {item['version']}, "
                    f"got {data.version}. Fetch the latest version and retry."
                ),
            )

        # Apply updates
        if data.title is not None:
            item["title"] = data.title
        if data.description is not None:
            item["description"] = data.description

        item["version"] += 1
        item["updated_at"] = time.time()

        _store[item_id] = item
        _invalidate_cache(item_id)
        _write_to_cache(item)

        logger.info(
            "Updated COD-8 item id=%d to version=%d for user_id=%d",
            item_id,
            item["version"],
            user_id,
        )
        return _dict_to_response(item)

    # ------------------------------------------------------------------
    # Delete (soft)
    # ------------------------------------------------------------------

    def delete_cod8_item(self, item_id: int, user_id: int) -> None:
        """Soft-delete a COD-8 item.

        The item record is retained in the store with ``is_deleted=True``;
        subsequent reads will return 404.

        Args:
            item_id: Primary key of the item to delete.
            user_id: ID of the requesting user.

        Raises:
            HTTPException 404: If the item does not exist or is already deleted.
            HTTPException 403: If the item belongs to a different user.
        """
        item = _store.get(item_id)

        if item is None:
            raise HTTPException(status_code=404, detail=f"COD-8 item {item_id} not found")

        if item["is_deleted"]:
            raise HTTPException(
                status_code=404,
                detail=f"COD-8 item {item_id} has already been deleted",
            )

        if item["user_id"] != user_id:
            raise HTTPException(
                status_code=403,
                detail="Access denied: item belongs to a different user",
            )

        item["is_deleted"] = True
        item["updated_at"] = time.time()
        _store[item_id] = item
        _invalidate_cache(item_id)

        logger.info("Soft-deleted COD-8 item id=%d for user_id=%d", item_id, user_id)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

cod8_service = Cod8Service()
