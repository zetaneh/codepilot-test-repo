"""
Test suite for the COD-8 API router.

Verifies:
 - POST /cod8/  → 201 on success, 401/403 on auth failures
 - GET  /cod8/{id} → 200 on success, 404 when missing
 - PATCH /cod8/{id} → 200 on success, 404 when missing, 422 on bad body
 - DELETE /cod8/{id} → 204 on success, 404 when missing
 - Consistent error JSON shape
"""
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from app.api.routes.cod8 import router, _cod8_service


@pytest.fixture(autouse=True)
def _reset_service():
    """Reset the in-memory store before each test."""
    _cod8_service._store.clear()
    _cod8_service._counter = 0
    yield


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


VALID_HEADERS = {"Authorization": "Bearer valid-token"}
INACTIVE_HEADERS = {"Authorization": "Bearer inactive-token"}
DELETED_HEADERS = {"Authorization": "Bearer deleted-token"}
BAD_HEADERS = {"Authorization": "Bearer bad-token"}
NO_HEADERS: dict = {}

CREATE_PAYLOAD = {"name": "Test Item", "description": "A test COD-8 item"}


# ---------------------------------------------------------------------------
# POST /cod8/
# ---------------------------------------------------------------------------


class TestCreateCod8Item:
    def test_create_returns_201(self, client: TestClient) -> None:
        resp = client.post("/cod8/", json=CREATE_PAYLOAD, headers=VALID_HEADERS)
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Test Item"
        assert body["id"] == "1"
        assert body["owner_id"] == "user-1"
        assert body["is_deleted"] is False

    def test_create_no_auth_returns_401(self, client: TestClient) -> None:
        resp = client.post("/cod8/", json=CREATE_PAYLOAD, headers=NO_HEADERS)
        assert resp.status_code == 401
        detail = resp.json()["detail"]
        assert detail["code"] == 401

    def test_create_invalid_token_returns_401(self, client: TestClient) -> None:
        resp = client.post("/cod8/", json=CREATE_PAYLOAD, headers=BAD_HEADERS)
        assert resp.status_code == 401

    def test_create_inactive_user_returns_403(self, client: TestClient) -> None:
        resp = client.post("/cod8/", json=CREATE_PAYLOAD, headers=INACTIVE_HEADERS)
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["code"] == 403

    def test_create_deleted_user_returns_403(self, client: TestClient) -> None:
        resp = client.post("/cod8/", json=CREATE_PAYLOAD, headers=DELETED_HEADERS)
        assert resp.status_code == 403

    def test_create_missing_name_returns_422(self, client: TestClient) -> None:
        resp = client.post("/cod8/", json={"description": "no name"}, headers=VALID_HEADERS)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /cod8/{item_id}
# ---------------------------------------------------------------------------


class TestGetCod8Item:
    def _create_item(self, client: TestClient) -> str:
        resp = client.post("/cod8/", json=CREATE_PAYLOAD, headers=VALID_HEADERS)
        return resp.json()["id"]

    def test_get_existing_returns_200(self, client: TestClient) -> None:
        item_id = self._create_item(client)
        resp = client.get(f"/cod8/{item_id}", headers=VALID_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["id"] == item_id

    def test_get_missing_returns_404(self, client: TestClient) -> None:
        resp = client.get("/cod8/9999", headers=VALID_HEADERS)
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert detail["code"] == 404

    def test_get_no_auth_returns_401(self, client: TestClient) -> None:
        resp = client.get("/cod8/1", headers=NO_HEADERS)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /cod8/{item_id}
# ---------------------------------------------------------------------------


class TestUpdateCod8Item:
    def _create_item(self, client: TestClient) -> str:
        resp = client.post("/cod8/", json=CREATE_PAYLOAD, headers=VALID_HEADERS)
        return resp.json()["id"]

    def test_patch_existing_returns_200(self, client: TestClient) -> None:
        item_id = self._create_item(client)
        resp = client.patch(
            f"/cod8/{item_id}",
            json={"name": "Updated"},
            headers=VALID_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"

    def test_patch_missing_returns_404(self, client: TestClient) -> None:
        resp = client.patch("/cod8/9999", json={"name": "X"}, headers=VALID_HEADERS)
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == 404

    def test_patch_name_too_long_returns_422(self, client: TestClient) -> None:
        item_id = self._create_item(client)
        resp = client.patch(
            f"/cod8/{item_id}",
            json={"name": "A" * 201},
            headers=VALID_HEADERS,
        )
        assert resp.status_code == 422

    def test_patch_no_auth_returns_401(self, client: TestClient) -> None:
        resp = client.patch("/cod8/1", json={"name": "X"}, headers=NO_HEADERS)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /cod8/{item_id}
# ---------------------------------------------------------------------------


class TestDeleteCod8Item:
    def _create_item(self, client: TestClient) -> str:
        resp = client.post("/cod8/", json=CREATE_PAYLOAD, headers=VALID_HEADERS)
        return resp.json()["id"]

    def test_delete_existing_returns_204(self, client: TestClient) -> None:
        item_id = self._create_item(client)
        resp = client.delete(f"/cod8/{item_id}", headers=VALID_HEADERS)
        assert resp.status_code == 204

    def test_delete_missing_returns_404(self, client: TestClient) -> None:
        resp = client.delete("/cod8/9999", headers=VALID_HEADERS)
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == 404

    def test_delete_is_idempotent_soft_delete(self, client: TestClient) -> None:
        """After soft-delete, a second DELETE should return 404."""
        item_id = self._create_item(client)
        client.delete(f"/cod8/{item_id}", headers=VALID_HEADERS)
        resp = client.delete(f"/cod8/{item_id}", headers=VALID_HEADERS)
        assert resp.status_code == 404

    def test_delete_no_auth_returns_401(self, client: TestClient) -> None:
        resp = client.delete("/cod8/1", headers=NO_HEADERS)
        assert resp.status_code == 401

    def test_deleted_item_not_retrievable(self, client: TestClient) -> None:
        """GET after DELETE should return 404."""
        item_id = self._create_item(client)
        client.delete(f"/cod8/{item_id}", headers=VALID_HEADERS)
        resp = client.get(f"/cod8/{item_id}", headers=VALID_HEADERS)
        assert resp.status_code == 404
