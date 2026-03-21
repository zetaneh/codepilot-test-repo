from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class Todo(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    completed: bool = False
    created_at: datetime = None
    user_id: int


class TodoCreate(BaseModel):
    title: str
    description: Optional[str] = None
    user_id: int


class TodoUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    completed: Optional[bool] = None
