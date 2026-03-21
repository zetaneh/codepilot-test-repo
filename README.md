# Todo API — CodePilot Test Repo

Simple FastAPI project used as the simulated GitHub repo for CodePilot agent testing.

## Structure

```
app/
  main.py              # FastAPI app, router mounts
  routers/
    todos.py           # CRUD for todos
    users.py           # CRUD for users
  models/
    todo.py            # Todo Pydantic models
    user.py            # User Pydantic models
  services/
    todo_service.py    # In-memory todo store
    user_service.py    # In-memory user store
tests/
  test_todos.py
  test_users.py
```

## Run locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8020
pytest tests/ -v
```

## Open tickets (for agent testing)

- **TODO-001**: Add pagination to `GET /todos/` (page + page_size query params)
- **TODO-002**: Add due_date field to Todo model + filter by overdue
- **TODO-003**: Add `GET /users/{id}/todos` endpoint
- **TODO-004**: Add input validation — title max 200 chars, email format check
- **TODO-005**: Add priority field (LOW/MEDIUM/HIGH) to Todo with filter support
