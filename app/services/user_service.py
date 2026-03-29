"""
In-memory user store.
"""
from typing import Optional
from app.models.user import UserCreate, UserUpdate
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_users: dict[int, dict] = {
    1: {"id": 1, "name": "Alice", "email": "alice@example.com", "is_active": True, "hashed_password": pwd_context.hash("password123")},
    2: {"id": 2, "name": "Bob",   "email": "bob@example.com",   "is_active": True, "hashed_password": pwd_context.hash("password123")},
}
_next_id = 3


def list_users() -> list[dict]:
    return list(_users.values())


def get_user(user_id: int) -> Optional[dict]:
    return _users.get(user_id)


def get_user_by_email(email: str) -> Optional[dict]:
    for user in _users.values():
        if user["email"] == email:
            return user
    return None


def create_user(data: UserCreate) -> dict:
    global _next_id
    hashed_password = pwd_context.hash(data.password)
    user = {"id": _next_id, "name": data.name, "email": data.email, "is_active": True, "hashed_password": hashed_password}
    _users[_next_id] = user
    _next_id += 1
    return user


def update_user(user_id: int, data: UserUpdate) -> Optional[dict]:
    if user_id not in _users:
        return None
    user = _users[user_id]
    if data.name is not None:
        user["name"] = data.name
    if data.email is not None:
        user["email"] = data.email
    if data.is_active is not None:
        user["is_active"] = data.is_active
    return user


def delete_user(user_id: int) -> bool:
    if user_id not in _users:
        return False
    del _users[user_id]
    return True
