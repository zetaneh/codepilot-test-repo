from datetime import datetime
from typing import Optional
from app.models.todo import Todo, TodoCreate, TodoUpdate

# Fake in-memory store
_todos: dict[int, dict] = {
    1: {"id": 1, "title": "Buy groceries", "description": None, "completed": False, "created_at": datetime.utcnow().isoformat(), "user_id": 1},
    2: {"id": 2, "title": "Write tests", "description": "Add pytest coverage", "completed": False, "created_at": datetime.utcnow().isoformat(), "user_id": 1},
    3: {"id": 3, "title": "Walk the dog", "description": None, "completed": False, "created_at": datetime.utcnow().isoformat(), "user_id": 2}, # Add a todo for another user
}
_next_id = 4 # Update next_id


def list_todos(user_id: int, completed: Optional[bool] = None) -> list[dict]: # user_id is now required
    items = list(_todos.values())
    items = [t for t in items if t["user_id"] == user_id] # Filter by user_id
    if completed is not None:
        items = [t for t in items if t["completed"] == completed]
    return items


def get_todo(todo_id: int, user_id: int) -> Optional[dict]: # Add user_id
    todo = _todos.get(todo_id)
    if todo and todo["user_id"] == user_id: # Check ownership
        return todo
    return None


def create_todo(data: TodoCreate, user_id: int) -> dict: # Add user_id
    global _next_id
    todo = {
        "id": _next_id,
        "title": data.title,
        "description": data.description,
        "completed": False,
        "created_at": datetime.utcnow().isoformat(),
        "user_id": user_id, # Use passed user_id
    }
    _todos[_next_id] = todo
    _next_id += 1
    return todo


def update_todo(todo_id: int, data: TodoUpdate, user_id: int) -> Optional[dict]: # Add user_id
    if todo_id not in _todos:
        return None
    todo = _todos[todo_id]
    if todo["user_id"] != user_id: # Check ownership
        return None
    if data.title is not None:
        todo["title"] = data.title
    if data.description is not None:
        todo["description"] = data.description
    if data.completed is not None:
        todo["completed"] = data.completed
    return todo


def delete_todo(todo_id: int, user_id: int) -> bool: # Add user_id
    if todo_id not in _todos:
        return False
    todo = _todos[todo_id]
    if todo["user_id"] != user_id: # Check ownership
        return False
    del _todos[todo_id]
    return True
