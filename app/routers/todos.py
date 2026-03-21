from fastapi import APIRouter, HTTPException
from typing import Optional
from app.models.todo import TodoCreate, TodoUpdate
from app.services import todo_service

router = APIRouter()


@router.get("/")
def list_todos(user_id: Optional[int] = None, completed: Optional[bool] = None):
    return todo_service.list_todos(user_id=user_id, completed=completed)


@router.get("/{todo_id}")
def get_todo(todo_id: int):
    todo = todo_service.get_todo(todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo


@router.post("/", status_code=201)
def create_todo(data: TodoCreate):
    return todo_service.create_todo(data)


@router.patch("/{todo_id}")
def update_todo(todo_id: int, data: TodoUpdate):
    todo = todo_service.update_todo(todo_id, data)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo


@router.delete("/{todo_id}", status_code=204)
def delete_todo(todo_id: int):
    if not todo_service.delete_todo(todo_id):
        raise HTTPException(status_code=404, detail="Todo not found")
