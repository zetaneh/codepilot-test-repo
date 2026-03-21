"""
Test suite for the COD-8 service layer.

Hook name (from spec): test_cod8_service_crud_and_cache_fallback

Covers:
- create / read / update / delete happy paths
- soft-delete awareness (read/update/delete on deleted items → 404)
- Redis cache fallback (simulated by patching _get_redis_client to return None)
- optimistic concurrency control (version mismatch → 409)
- wrong-user access (→ 403)
"""

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_service():
    """Return a fresh Cod8Service with an empty in-memory store."""
    # Re-import the module to reset module-level state (_store, _next_id)
    if "app.services.cod8_service" in sys.modules:
        del sys.modules["app.services.cod8_service"]
    mod = importlib.import_module("app.services.cod8_service")
    return mod.Cod8Service(), mod


# ---------------------------------------------------------------------------
# CRUD happy paths
# ---------------------------------------------------------------------------


class TestCreateCod8Item:
    def test_create_returns_response(self):
        svc, mod = _fresh_service()
        data = mod.Cod8Create(title="Test", description="desc", user_id=1)
        resp = svc.create_cod8_item(data)

        assert resp.id == 1
        assert resp.title == "Test"
        assert resp.description == "desc"
        assert resp.user_id == 1
        assert resp.version == 1
        assert resp.is_deleted is False

    def test_create_increments_id(self):
        svc, mod = _fresh_service()
        data = mod.Cod8Create(title="A", user_id=1)
        r1 = svc.create_cod8_item(data)
        r2 = svc.create_cod8_item(data)
        assert r2.id == r1.id + 1

    def test_create_agent_enrichment(self):
        svc, mod = _fresh_service()
        mock_agent = MagicMock()
        mock_agent.enrich.return_value = "AI enriched"
        svc._agent = mock_agent

        data = mod.Cod8Create(title="EnrichMe", user_id=7)
        resp = svc.create_cod8_item(data)

        mock_agent.enrich.assert_called_once()
        assert resp.ai_summary == "AI enriched"

    def test_create_agent_failure_does_not_raise(self):
        svc, mod = _fresh_service()
        mock_agent = MagicMock()
        mock_agent.enrich.side_effect = RuntimeError("agent down")
        svc._agent = mock_agent

        data = mod.Cod8Create(title="Fallback", user_id=3)
        resp = svc.create_cod8_item(data)  # must not raise
        assert resp.ai_summary is None


class TestGetCod8Item:
    def test_get_existing_item(self):
        svc, mod = _fresh_service()
        created = svc.create_cod8_item(mod.Cod8Create(title="Hello", user_id=2))
        fetched = svc.get_cod8_item(created.id, user_id=2)
        assert fetched.id == created.id
        assert fetched.title == "Hello"

    def test_get_nonexistent_raises_404(self):
        svc, mod = _fresh_service()
        with pytest.raises(HTTPException) as exc_info:
            svc.get_cod8_item(999, user_id=1)
        assert exc_info.value.status_code == 404

    def test_get_deleted_raises_404(self):
        svc, mod = _fresh_service()
        created = svc.create_cod8_item(mod.Cod8Create(title="Gone", user_id=5))
        svc.delete_cod8_item(created.id, user_id=5)

        with pytest.raises(HTTPException) as exc_info:
            svc.get_cod8_item(created.id, user_id=5)
        assert exc_info.value.status_code == 404

    def test_get_wrong_user_raises_403(self):
        svc, mod = _fresh_service()
        created = svc.create_cod8_item(mod.Cod8Create(title="Private", user_id=10))

        with pytest.raises(HTTPException) as exc_info:
            svc.get_cod8_item(created.id, user_id=99)
        assert exc_info.value.status_code == 403


class TestUpdateCod8Item:
    def test_update_happy_path(self):
        svc, mod = _fresh_service()
        created = svc.create_cod8_item(mod.Cod8Create(title="Old", user_id=1))
        updated = svc.update_cod8_item(
            created.id,
            mod.Cod8Update(title="New", version=1),
            user_id=1,
        )
        assert updated.title == "New"
        assert updated.version == 2

    def test_update_version_mismatch_raises_409(self):
        svc, mod = _fresh_service()
        created = svc.create_cod8_item(mod.Cod8Create(title="A", user_id=1))

        with pytest.raises(HTTPException) as exc_info:
            svc.update_cod8_item(
                created.id,
                mod.Cod8Update(title="B", version=99),
                user_id=1,
            )
        assert exc_info.value.status_code == 409

    def test_update_nonexistent_raises_404(self):
        svc, mod = _fresh_service()
        with pytest.raises(HTTPException) as exc_info:
            svc.update_cod8_item(999, mod.Cod8Update(title="X", version=1), user_id=1)
        assert exc_info.value.status_code == 404

    def test_update_deleted_raises_404(self):
        svc, mod = _fresh_service()
        created = svc.create_cod8_item(mod.Cod8Create(title="ToDelete", user_id=1))
        svc.delete_cod8_item(created.id, user_id=1)

        with pytest.raises(HTTPException) as exc_info:
            svc.update_cod8_item(
                created.id, mod.Cod8Update(title="X", version=1), user_id=1
            )
        assert exc_info.value.status_code == 404

    def test_update_wrong_user_raises_403(self):
        svc, mod = _fresh_service()
        created = svc.create_cod8_item(mod.Cod8Create(title="Mine", user_id=1))

        with pytest.raises(HTTPException) as exc_info:
            svc.update_cod8_item(
                created.id, mod.Cod8Update(title="Stolen", version=1), user_id=2
            )
        assert exc_info.value.status_code == 403


class TestDeleteCod8Item:
    def test_delete_happy_path(self):
        svc, mod = _fresh_service()
        created = svc.create_cod8_item(mod.Cod8Create(title="ByeBye", user_id=1))
        svc.delete_cod8_item(created.id, user_id=1)  # must not raise

    def test_delete_nonexistent_raises_404(self):
        svc, mod = _fresh_service()
        with pytest.raises(HTTPException) as exc_info:
            svc.delete_cod8_item(999, user_id=1)
        assert exc_info.value.status_code == 404

    def test_delete_already_deleted_raises_404(self):
        svc, mod = _fresh_service()
        created = svc.create_cod8_item(mod.Cod8Create(title="Once", user_id=1))
        svc.delete_cod8_item(created.id, user_id=1)

        with pytest.raises(HTTPException) as exc_info:
            svc.delete_cod8_item(created.id, user_id=1)
        assert exc_info.value.status_code == 404

    def test_delete_wrong_user_raises_403(self):
        svc, mod = _fresh_service()
        created = svc.create_cod8_item(mod.Cod8Create(title="NotYours", user_id=1))

        with pytest.raises(HTTPException) as exc_info:
            svc.delete_cod8_item(created.id, user_id=2)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Redis cache fallback
# ---------------------------------------------------------------------------


class TestCacheFallback:
    def test_get_falls_back_to_memory_when_redis_unavailable(self):
        """
        When Redis is unavailable (_get_redis_client returns None),
        get_cod8_item must succeed using the in-memory store (no 500).
        """
        svc, mod = _fresh_service()
        created = svc.create_cod8_item(mod.Cod8Create(title="Mem", user_id=3))

        with patch.object(mod, "_get_redis_client", return_value=None):
            fetched = svc.get_cod8_item(created.id, user_id=3)

        assert fetched.id == created.id
        assert fetched.title == "Mem"

    def test_create_does_not_raise_when_redis_unavailable(self):
        svc, mod = _fresh_service()
        with patch.object(mod, "_get_redis_client", return_value=None):
            resp = svc.create_cod8_item(mod.Cod8Create(title="NoCache", user_id=4))
        assert resp.id is not None

    def test_update_does_not_raise_when_redis_unavailable(self):
        svc, mod = _fresh_service()
        created = svc.create_cod8_item(mod.Cod8Create(title="Up", user_id=1))
        with patch.object(mod, "_get_redis_client", return_value=None):
            updated = svc.update_cod8_item(
                created.id, mod.Cod8Update(title="UpNew", version=1), user_id=1
            )
        assert updated.title == "UpNew"

    def test_delete_does_not_raise_when_redis_unavailable(self):
        svc, mod = _fresh_service()
        created = svc.create_cod8_item(mod.Cod8Create(title="Del", user_id=1))
        with patch.object(mod, "_get_redis_client", return_value=None):
            svc.delete_cod8_item(created.id, user_id=1)  # must not raise

    def test_cache_hit_returns_item(self):
        """
        If _read_from_cache returns a valid dict, get_cod8_item should use it
        and not look at the in-memory store.
        """
        svc, mod = _fresh_service()
        import time

        fake_item = {
            "id": 42,
            "title": "Cached",
            "description": None,
            "user_id": 7,
            "version": 3,
            "is_deleted": False,
            "ai_summary": "cached summary",
            "created_at": time.time(),
            "updated_at": time.time(),
        }

        with patch.object(mod, "_read_from_cache", return_value=fake_item), \
             patch.object(mod, "_write_to_cache") as mock_write:
            resp = svc.get_cod8_item(42, user_id=7)

        assert resp.id == 42
        assert resp.title == "Cached"
        assert resp.version == 3
        # No re-write needed on cache hit
        mock_write.assert_not_called()
