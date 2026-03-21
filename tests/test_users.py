import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_list_users():
    r = client.get("/users/")
    assert r.status_code == 200
    assert len(r.json()) >= 2


def test_get_user():
    r = client.get("/users/1")
    assert r.status_code == 200
    assert r.json()["name"] == "Alice"


def test_create_user():
    r = client.post("/users/", json={"name": "Charlie", "email": "charlie@example.com"})
    assert r.status_code == 201
    assert r.json()["name"] == "Charlie"


def test_user_not_found():
    r = client.get("/users/9999")
    assert r.status_code == 404
