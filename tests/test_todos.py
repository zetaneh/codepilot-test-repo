import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services import todo_service # Import todo_service to reset data

# Reset the in-memory store for consistent testing
@pytest.fixture(autouse=True)
def run_around_tests():
    # Before each test, reset the _todos dictionary to a known state
    todo_service._todos = {
        1: {"id": 1, "title": "Buy groceries", "description": None, "completed": False, "created_at": "2023-01-01T00:00:00", "user_id": 1},
        2: {"id": 2, "title": "Write tests", "description": "Add pytest coverage", "completed": False, "created_at": "2023-01-01T00:00:00", "user_id": 1},
        3: {"id": 3, "title": "Walk the dog", "description": None, "completed": False, "created_at": "2023-01-01T00:00:00", "user_id": 2},
    }
    todo_service._next_id = 4
    yield


@pytest.fixture
def authenticated_client_alice():
    # In a real app, you\'d perform a login request to get a token.
    # Here, we\'re using a mock token that our dependency resolver understands.
    headers = {"Authorization": "Bearer mock_token_alice"}
    return TestClient(app, headers=headers)

@pytest.fixture
def authenticated_client_bob():
    headers = {"Authorization": "Bearer mock_token_bob"}
    return TestClient(app, headers=headers)

@pytest.fixture
def unauthenticated_client():
    return TestClient(app)


def test_health(unauthenticated_client):
    r = unauthenticated_client.get("/health")
    assert r.status_code == 200


def test_list_todos(authenticated_client_alice):
    r = authenticated_client_alice.get("/todos/")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) == 2 # Alice has 2 todos
    assert r.json()[0]["user_id"] == 1


def test_list_todos_bob(authenticated_client_bob):
    r = authenticated_client_bob.get("/todos/")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) == 1 # Bob has 1 todo
    assert r.json()[0]["user_id"] == 2


def test_list_todos_unauthenticated(unauthenticated_client):
    r = unauthenticated_client.get("/todos/")
    assert r.status_code == 401


def test_create_todo(authenticated_client_alice):
    r = authenticated_client_alice.post("/todos/", json={"title": "Test task for Alice"})
    assert r.status_code == 201
    data = r.json()
    assert data["title"] == "Test task for Alice"
    assert data["completed"] is False
    assert data["user_id"] == 1 # Should be created for Alice


def test_create_todo_unauthenticated(unauthenticated_client):
    r = unauthenticated_client.post("/todos/", json={"title": "Test task"})
    assert r.status_code == 401


def test_get_todo(authenticated_client_alice):
    r = authenticated_client_alice.get("/todos/1")
    assert r.status_code == 200
    assert r.json()["id"] == 1
    assert r.json()["user_id"] == 1


def test_get_todo_not_found(authenticated_client_alice):
    r = authenticated_client_alice.get("/todos/9999")
    assert r.status_code == 404


def test_get_other_users_todo(authenticated_client_alice):
    # Alice tries to get Bob\'s todo
    r = authenticated_client_alice.get("/todos/3")
    assert r.status_code == 404 # Should not be found for Alice


def test_get_todo_unauthenticated(unauthenticated_client):
    r = unauthenticated_client.get("/todos/1")
    assert r.status_code == 401


def test_update_todo(authenticated_client_alice):
    r = authenticated_client_alice.patch("/todos/1", json={"completed": True})
    assert r.status_code == 200
    assert r.json()["completed"] is True
    assert r.json()["user_id"] == 1


def test_update_other_users_todo(authenticated_client_alice):
    # Alice tries to update Bob\'s todo
    r = authenticated_client_alice.patch("/todos/3", json={"completed": True})
    assert r.status_code == 404


def test_update_todo_unauthenticated(unauthenticated_client):
    r = unauthenticated_client.patch("/todos/1", json={"completed": True})
    assert r.status_code == 401


def test_delete_todo(authenticated_client_alice):
    # create then delete
    r = authenticated_client_alice.post("/todos/", json={"title": "To delete"})
    todo_id = r.json()["id"]
    r = authenticated_client_alice.delete(f"/todos/{todo_id}")
    assert r.status_code == 204

    # Verify it\'s deleted
    r = authenticated_client_alice.get(f"/todos/{todo_id}")
    assert r.status_code == 404


def test_delete_other_users_todo(authenticated_client_alice):
    # Alice tries to delete Bob\'s todo
    r = authenticated_client_alice.delete("/todos/3")
    assert r.status_code == 404


def test_delete_todo_unauthenticated(unauthenticated_client):
    r = unauthenticated_client.delete("/todos/1")
    assert r.status_code == 401
