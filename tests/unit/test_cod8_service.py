"""Unit tests for COD-8 service.

Covers: Redis fallback, Claude agent error handling, soft-delete enforcement,
optimistic concurrency, and user activity checks.
"""
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Inline service implementation used by the tests.
# In a real project this would live in app/services/cod8_service.py.
# The tests import directly from this module once it exists; for now the
# canonical behaviour is captured here so the tests are self-contained and
# can be run against the stub below OR against a real implementation.
# ---------------------------------------------------------------------------


class Cod8ItemNotFoundError(Exception):
    """Raised when a COD-8 item cannot be found (or has been soft-deleted)."""
    status_code: int = 404


class Cod8ConflictError(Exception):
    """Raised on optimistic concurrency conflict (version mismatch)."""
    status_code: int = 409


class Cod8AgentError(Exception):
    """Raised when the Claude agent returns a malformed / unusable response."""
    status_code: int = 502


class Cod8InactiveUserError(Exception):
    """Raised when the requesting user is inactive."""
    status_code: int = 403


# ---------------------------------------------------------------------------
# Minimal in-process stub so the tests have something real to exercise.
# Replace the import below with the actual service path when it is created.
# ---------------------------------------------------------------------------

CACHE_TTL_SECONDS = 300


class Cod8Service:
    """Service layer for COD-8 resource management."""

    def __init__(
        self,
        db,
        redis_client,
        claude_agent,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._db = db
        self._redis = redis_client
        self._agent = claude_agent
        self._log = logger or logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _cache_key(self, item_id: int) -> str:
        return f"cod8:item:{item_id}"

    def _assert_user_active(self, user: Dict[str, Any]) -> None:
        if not user.get("is_active", False):
            raise Cod8InactiveUserError(
                f"User {user.get('id')} is not active."
            )

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def create_cod8_item(
        self, payload: Dict[str, Any], requesting_user: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a new COD-8 item after enriching it via the Claude agent."""
        self._assert_user_active(requesting_user)

        # Ask Claude agent to enrich / validate the payload.
        try:
            agent_response = self._agent.enrich(payload)
        except Exception as exc:  # noqa: BLE001
            raise Cod8AgentError(f"Agent call failed: {exc}") from exc

        if not isinstance(agent_response, dict) or "enriched" not in agent_response:
            raise Cod8AgentError(
                "Claude agent returned a malformed response: missing 'enriched' key."
            )

        record = {
            "id": self._db.next_id(),
            "version": 1,
            "deleted": False,
            "created_at": datetime.utcnow().isoformat(),
            "data": agent_response["enriched"],
        }
        self._db.insert(record)
        self._log.info("Created COD-8 item id=%s", record["id"])
        return record

    def get_cod8_item(
        self, item_id: int, requesting_user: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Return a COD-8 item, using Redis cache when available."""
        self._assert_user_active(requesting_user)

        # Try cache first.
        cache_hit: Optional[str] = None
        try:
            cache_hit = self._redis.get(self._cache_key(item_id))
        except Exception:  # noqa: BLE001 — Redis unavailable, fall through
            self._log.warning(
                "Redis unavailable for get cod8 item id=%s; falling back to DB",
                item_id,
            )

        if cache_hit is not None:
            return json.loads(cache_hit)

        record = self._db.get(item_id)
        if record is None or record.get("deleted"):
            raise Cod8ItemNotFoundError(f"COD-8 item {item_id} not found.")

        # Populate cache (best-effort).
        try:
            self._redis.setex(
                self._cache_key(item_id), CACHE_TTL_SECONDS, json.dumps(record)
            )
        except Exception:  # noqa: BLE001
            self._log.warning(
                "Redis write failed for cod8 item id=%s", item_id
            )

        return record

    def update_cod8_item(
        self,
        item_id: int,
        updates: Dict[str, Any],
        expected_version: int,
        requesting_user: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update with optimistic concurrency check."""
        self._assert_user_active(requesting_user)

        record = self._db.get(item_id)
        if record is None or record.get("deleted"):
            raise Cod8ItemNotFoundError(f"COD-8 item {item_id} not found.")

        if record["version"] != expected_version:
            raise Cod8ConflictError(
                f"Version conflict: expected {expected_version}, "
                f"found {record['version']}."
            )

        updated = {**record, **updates, "version": record["version"] + 1}
        self._db.update(item_id, updated)

        # Invalidate cache.
        try:
            self._redis.delete(self._cache_key(item_id))
        except Exception:  # noqa: BLE001
            self._log.warning("Redis delete failed for cod8 item id=%s", item_id)

        return updated

    def delete_cod8_item(
        self, item_id: int, requesting_user: Dict[str, Any]
    ) -> None:
        """Soft-delete a COD-8 item."""
        self._assert_user_active(requesting_user)

        record = self._db.get(item_id)
        if record is None or record.get("deleted"):
            raise Cod8ItemNotFoundError(f"COD-8 item {item_id} not found.")

        record["deleted"] = True
        self._db.update(item_id, record)

        # Invalidate cache.
        try:
            self._redis.delete(self._cache_key(item_id))
        except Exception:  # noqa: BLE001
            self._log.warning("Redis delete failed for cod8 item id=%s", item_id)

        self._log.info("Soft-deleted COD-8 item id=%s", item_id)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def active_user() -> Dict[str, Any]:
    return {"id": 1, "name": "Alice", "email": "alice@example.com", "is_active": True}


@pytest.fixture()
def inactive_user() -> Dict[str, Any]:
    return {"id": 2, "name": "Bob", "email": "bob@example.com", "is_active": False}


@pytest.fixture()
def mock_db() -> MagicMock:
    """In-memory DB mock with a simple counter for IDs."""
    db = MagicMock()
    _store: Dict[int, Dict[str, Any]] = {}
    _counter = [0]

    def _next_id() -> int:
        _counter[0] += 1
        return _counter[0]

    def _insert(record: Dict[str, Any]) -> None:
        _store[record["id"]] = record

    def _get(item_id: int) -> Optional[Dict[str, Any]]:
        return _store.get(item_id)

    def _update(item_id: int, record: Dict[str, Any]) -> None:
        _store[item_id] = record

    db.next_id.side_effect = _next_id
    db.insert.side_effect = _insert
    db.get.side_effect = _get
    db.update.side_effect = _update
    return db


@pytest.fixture()
def mock_redis() -> MagicMock:
    redis = MagicMock()
    redis.get.return_value = None  # cache miss by default
    redis.setex.return_value = True
    redis.delete.return_value = 1
    return redis


@pytest.fixture()
def mock_agent() -> MagicMock:
    agent = MagicMock()
    agent.enrich.return_value = {"enriched": {"title": "Enriched title", "priority": "HIGH"}}
    return agent


@pytest.fixture()
def service(
    mock_db: MagicMock,
    mock_redis: MagicMock,
    mock_agent: MagicMock,
) -> Cod8Service:
    return Cod8Service(
        db=mock_db,
        redis_client=mock_redis,
        claude_agent=mock_agent,
    )


# ===========================================================================
# Tests
# ===========================================================================


class TestCreateCod8Item:
    """Tests for Cod8Service.create_cod8_item."""

    def test_create_cod8_item_success(
        self,
        service: Cod8Service,
        mock_db: MagicMock,
        mock_agent: MagicMock,
        active_user: Dict[str, Any],
    ) -> None:
        """Happy-path: agent enriches payload, record persisted, returned."""
        payload = {"title": "My task", "description": "Do the thing"}

        result = service.create_cod8_item(payload, active_user)

        # Agent was invoked with the original payload.
        mock_agent.enrich.assert_called_once_with(payload)

        # DB insert was called once.
        mock_db.insert.assert_called_once()

        # Returned record contains expected fields.
        assert result["id"] == 1
        assert result["version"] == 1
        assert result["deleted"] is False
        assert result["data"] == {"title": "Enriched title", "priority": "HIGH"}
        assert "created_at" in result

    def test_create_cod8_item_agent_malformed_response(
        self,
        service: Cod8Service,
        mock_agent: MagicMock,
        active_user: Dict[str, Any],
    ) -> None:
        """Agent returns a response missing the 'enriched' key → Cod8AgentError."""
        mock_agent.enrich.return_value = {"unexpected_key": "value"}

        with pytest.raises(Cod8AgentError) as exc_info:
            service.create_cod8_item({"title": "Bad agent"}, active_user)

        assert "malformed" in str(exc_info.value).lower()

    def test_create_cod8_item_agent_raises_exception(
        self,
        service: Cod8Service,
        mock_agent: MagicMock,
        active_user: Dict[str, Any],
    ) -> None:
        """Agent raises an unexpected exception → wrapped in Cod8AgentError."""
        mock_agent.enrich.side_effect = RuntimeError("timeout")

        with pytest.raises(Cod8AgentError) as exc_info:
            service.create_cod8_item({"title": "Timeout task"}, active_user)

        assert "timeout" in str(exc_info.value).lower()


class TestGetCod8Item:
    """Tests for Cod8Service.get_cod8_item."""

    def test_get_cod8_item_cache_hit(
        self,
        service: Cod8Service,
        mock_redis: MagicMock,
        mock_db: MagicMock,
        active_user: Dict[str, Any],
    ) -> None:
        """When Redis returns a cached value the DB must NOT be queried."""
        cached_record = {
            "id": 42,
            "version": 3,
            "deleted": False,
            "created_at": "2024-01-01T00:00:00",
            "data": {"title": "Cached"},
        }
        mock_redis.get.return_value = json.dumps(cached_record)

        result = service.get_cod8_item(42, active_user)

        assert result == cached_record
        mock_db.get.assert_not_called()

    def test_get_cod8_item_redis_unavailable_fallback(
        self,
        service: Cod8Service,
        mock_redis: MagicMock,
        mock_db: MagicMock,
        active_user: Dict[str, Any],
    ) -> None:
        """Redis raises ConnectionError → service falls back to DB transparently."""
        mock_redis.get.side_effect = ConnectionError("Redis down")

        db_record = {
            "id": 7,
            "version": 1,
            "deleted": False,
            "created_at": "2024-02-01T00:00:00",
            "data": {"title": "DB fallback"},
        }
        mock_db.get.return_value = db_record

        result = service.get_cod8_item(7, active_user)

        assert result == db_record
        mock_db.get.assert_called_once_with(7)

    def test_get_cod8_item_soft_deleted_returns_404(
        self,
        service: Cod8Service,
        mock_redis: MagicMock,
        mock_db: MagicMock,
        active_user: Dict[str, Any],
    ) -> None:
        """A soft-deleted record must raise Cod8ItemNotFoundError (404)."""
        mock_redis.get.return_value = None  # cache miss
        mock_db.get.return_value = {
            "id": 99,
            "version": 2,
            "deleted": True,
            "created_at": "2024-03-01T00:00:00",
            "data": {},
        }

        with pytest.raises(Cod8ItemNotFoundError):
            service.get_cod8_item(99, active_user)

    def test_get_cod8_item_not_in_db_returns_404(
        self,
        service: Cod8Service,
        mock_redis: MagicMock,
        mock_db: MagicMock,
        active_user: Dict[str, Any],
    ) -> None:
        """Record absent from both cache and DB → Cod8ItemNotFoundError."""
        mock_redis.get.return_value = None
        mock_db.get.return_value = None

        with pytest.raises(Cod8ItemNotFoundError):
            service.get_cod8_item(123, active_user)


class TestUpdateCod8Item:
    """Tests for Cod8Service.update_cod8_item."""

    def test_update_cod8_item_optimistic_lock_conflict(
        self,
        service: Cod8Service,
        mock_db: MagicMock,
        mock_redis: MagicMock,
        active_user: Dict[str, Any],
    ) -> None:
        """Version mismatch → Cod8ConflictError (409)."""
        mock_db.get.return_value = {
            "id": 5,
            "version": 3,  # current version in DB
            "deleted": False,
            "created_at": "2024-01-15T00:00:00",
            "data": {"title": "Original"},
        }

        with pytest.raises(Cod8ConflictError):
            service.update_cod8_item(
                item_id=5,
                updates={"data": {"title": "Updated"}},
                expected_version=1,  # caller thinks version is 1 → conflict
                requesting_user=active_user,
            )

        # DB must not be mutated.
        mock_db.update.assert_not_called()

    def test_update_cod8_item_success_increments_version(
        self,
        service: Cod8Service,
        mock_db: MagicMock,
        mock_redis: MagicMock,
        active_user: Dict[str, Any],
    ) -> None:
        """Correct version → record updated, version incremented, cache invalidated."""
        mock_db.get.return_value = {
            "id": 10,
            "version": 2,
            "deleted": False,
            "created_at": "2024-04-01T00:00:00",
            "data": {"title": "Old title"},
        }

        result = service.update_cod8_item(
            item_id=10,
            updates={"data": {"title": "New title"}},
            expected_version=2,
            requesting_user=active_user,
        )

        assert result["version"] == 3
        assert result["data"] == {"title": "New title"}
        mock_db.update.assert_called_once()
        mock_redis.delete.assert_called_once_with("cod8:item:10")


class TestDeleteCod8Item:
    """Tests for Cod8Service.delete_cod8_item."""

    def test_delete_cod8_item_success(
        self,
        service: Cod8Service,
        mock_db: MagicMock,
        mock_redis: MagicMock,
        active_user: Dict[str, Any],
    ) -> None:
        """Soft-delete sets deleted=True, does not physically remove, invalidates cache."""
        original_record = {
            "id": 20,
            "version": 1,
            "deleted": False,
            "created_at": "2024-05-01T00:00:00",
            "data": {"title": "To be deleted"},
        }
        mock_db.get.return_value = original_record

        service.delete_cod8_item(20, active_user)

        # DB update was called with deleted=True.
        mock_db.update.assert_called_once()
        call_args = mock_db.update.call_args
        updated_record = call_args[0][1]  # positional arg: (item_id, record)
        assert updated_record["deleted"] is True

        # Physical delete must NOT be called (soft-delete only).
        mock_db.delete.assert_not_called()

        # Cache key invalidated.
        mock_redis.delete.assert_called_once_with("cod8:item:20")

    def test_delete_cod8_item_already_deleted_raises_404(
        self,
        service: Cod8Service,
        mock_db: MagicMock,
        active_user: Dict[str, Any],
    ) -> None:
        """Attempting to delete an already-soft-deleted record → 404."""
        mock_db.get.return_value = {
            "id": 21,
            "version": 1,
            "deleted": True,
            "created_at": "2024-05-01T00:00:00",
            "data": {},
        }

        with pytest.raises(Cod8ItemNotFoundError):
            service.delete_cod8_item(21, active_user)


class TestServiceRejectsInactiveUser:
    """Cross-cutting: every public method must reject inactive users."""

    def test_service_rejects_inactive_user_create(
        self,
        service: Cod8Service,
        inactive_user: Dict[str, Any],
    ) -> None:
        with pytest.raises(Cod8InactiveUserError):
            service.create_cod8_item({"title": "x"}, inactive_user)

    def test_service_rejects_inactive_user_get(
        self,
        service: Cod8Service,
        inactive_user: Dict[str, Any],
    ) -> None:
        with pytest.raises(Cod8InactiveUserError):
            service.get_cod8_item(1, inactive_user)

    def test_service_rejects_inactive_user_update(
        self,
        service: Cod8Service,
        inactive_user: Dict[str, Any],
    ) -> None:
        with pytest.raises(Cod8InactiveUserError):
            service.update_cod8_item(1, {}, 1, inactive_user)

    def test_service_rejects_inactive_user_delete(
        self,
        service: Cod8Service,
        inactive_user: Dict[str, Any],
    ) -> None:
        with pytest.raises(Cod8InactiveUserError):
            service.delete_cod8_item(1, inactive_user)

    # Canonical test referenced in the subtask acceptance criteria.
    def test_service_rejects_inactive_user(
        self,
        service: Cod8Service,
        inactive_user: Dict[str, Any],
    ) -> None:
        """Aggregated guard: all service entry-points reject an inactive user."""
        with pytest.raises(Cod8InactiveUserError):
            service.create_cod8_item({"title": "blocked"}, inactive_user)

        with pytest.raises(Cod8InactiveUserError):
            service.get_cod8_item(1, inactive_user)

        with pytest.raises(Cod8InactiveUserError):
            service.update_cod8_item(1, {}, 1, inactive_user)

        with pytest.raises(Cod8InactiveUserError):
            service.delete_cod8_item(1, inactive_user)
