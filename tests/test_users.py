import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.user import UserCreate

client = TestClient(app)


@pytest.fixture(scope="module")
def authenticated_client():
    # Register a new user
    test_user_email = "testuser@example.com"
    test_user_password = "testpassword"
    register_data = {"name": "Test User", "email": test_user_email, "password": test_user_password}
    response = client.post("/register", json=register_data)
    assert response.status_code == 201

    # Log in to get a token
    login_data = {"username": test_user_email, "password": test_user_password}
    response = client.post("/token", data=login_data)
    assert response.status_code == 200
    token = response.json()["access_token"]

    # Create a client with the authorization header
    auth_client = TestClient(app)
    auth_client.headers.update({"Authorization": f"Bearer {token}"})
    return auth_client


def test_list_users(authenticated_client):
    r = authenticated_client.get("/users/")
    assert r.status_code == 200
    assert len(r.json()) >= 2


def test_get_user(authenticated_client):
    # Assuming user with ID 1 exists from initial data
    r = authenticated_client.get("/users/1")
    assert r.status_code == 200
    assert r.json()["name"] == "Alice"


def test_user_not_found(authenticated_client):
    r = authenticated_client.get("/users/9999")
    assert r.status_code == 404


def test_update_user(authenticated_client):
    # Assuming user with ID 1 exists from initial data
    update_data = {"name": "Alicia", "is_active": False}
    r = authenticated_client.patch("/users/1", json=update_data)
    assert r.status_code == 200
    assert r.json()["name"] == "Alicia"
    assert r.json()["is_active"] is False


def test_delete_user(authenticated_client):
    # First, create a user to delete (using the register endpoint)
    delete_user_email = "deleteme@example.com"
    delete_user_password = "deletepass"
    register_data = {"name": "Delete Me", "email": delete_user_email, "password": delete_user_password}
    response = client.post("/register", json=register_data)
    assert response.status_code == 201
    user_id_to_delete = response.json()["id"]

    r = authenticated_client.delete(f"/users/{user_id_to_delete}")
    assert r.status_code == 204

    # Verify user is deleted
    r = authenticated_client.get(f"/users/{user_id_to_delete}")
    assert r.status_code == 404
