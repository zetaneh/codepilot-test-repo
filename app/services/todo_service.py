"""
In-memory todo store (no DB — easy for agents to extend to real DB).
"""
from datetime import datetime
from typing import Optional
from app.models.todo import Todo, TodoCreate, TodoUpdate

# Fake in-memory store
_todos: dict[int, dict] = {
    1: {"id": 1, "title": "Buy groceries", "description": None, "completed": False, "created_at": datetime.utcnow().isoformat(), "user_id": 1},
    2: {"id": 2, "title": "Write tests", "description": "Add pytest coverage", "completed": False, "created_at": datetime.utcnow().isoformat(), "user_id": 1},
}
_next_id = 3


def list_todos(user_id: Optional[int] = None, completed: Optional[bool] = None) -> list[dict]:
    items = list(_todos.values())
    if user_id is not None:
        items = [t for t in items if t["user_id"] == user_id]
    if completed is not None:
        items = [t for t in items if t["completed"] == completed]
    return items


def get_todo(todo_id: int) -> Optional[dict]:
    return _todos.get(todo_id)


def create_todo(data: TodoCreate) -> dict:
    global _next_id
    todo = {
        "id": _next_id,
        "title": data.title,
        "description": data.description,
        "completed": False,
        "created_at": datetime.utcnow().isoformat(),
        "user_id": data.user_id,
    }
    _todos[_next_id] = todo
    _next_id += 1
    return todo


def update_todo(todo_id: int, data: TodoUpdate) -> Optional[dict]:
    if todo_id not in _todos:
        return None
    todo = _todos[todo_id]
    if data.title is not None:
        todo["title"] = data.title
    if data.description is not None:
        todo["description"] = data.description
    if data.completed is not None:
        todo["completed"] = data.completed
    return todo


def delete_todo(todo_id: int) -> bool:
    if todo_id not in _todos:
        return False
    del _todos[todo_id]
    return True
