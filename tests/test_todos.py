import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200


def test_list_todos():
    r = client.get("/todos/")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_create_todo():
    r = client.post("/todos/", json={"title": "Test task", "user_id": 1})
    assert r.status_code == 201
    data = r.json()
    assert data["title"] == "Test task"
    assert data["completed"] is False


def test_get_todo():
    r = client.get("/todos/1")
    assert r.status_code == 200


def test_get_todo_not_found():
    r = client.get("/todos/9999")
    assert r.status_code == 404


def test_update_todo():
    r = client.patch("/todos/1", json={"completed": True})
    assert r.status_code == 200
    assert r.json()["completed"] is True


def test_delete_todo():
    # create then delete
    r = client.post("/todos/", json={"title": "To delete", "user_id": 1})
    todo_id = r.json()["id"]
    r = client.delete(f"/todos/{todo_id}")
    assert r.status_code == 204
