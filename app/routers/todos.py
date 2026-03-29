from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from app.models.todo import TodoCreate, TodoUpdate
from app.models.user import User # Import User model
from app.services import todo_service
from app.dependencies import get_current_active_user # Import dependency

router = APIRouter(dependencies=[Depends(get_current_active_user)]) # Protect all routes


@router.get("/")
def list_todos(
    completed: Optional[bool] = None,
    current_user: User = Depends(get_current_active_user)
):
    return todo_service.list_todos(user_id=current_user.id, completed=completed)


@router.get("/{todo_id}")
def get_todo(
    todo_id: int,
    current_user: User = Depends(get_current_active_user)
):
    todo = todo_service.get_todo(todo_id, user_id=current_user.id) # Pass user_id
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found or not owned by user")
    return todo


@router.post("/", status_code=201)
def create_todo(
    data: TodoCreate,
    current_user: User = Depends(get_current_active_user)
):
    return todo_service.create_todo(data, user_id=current_user.id) # Pass user_id


@router.patch("/{todo_id}")
def update_todo(
    todo_id: int,
    data: TodoUpdate,
    current_user: User = Depends(get_current_active_user)
):
    todo = todo_service.update_todo(todo_id, data, user_id=current_user.id) # Pass user_id
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found or not owned by user")
    return todo


@router.delete("/{todo_id}", status_code=204)
def delete_todo(
    todo_id: int,
    current_user: User = Depends(get_current_active_user)
):
    if not todo_service.delete_todo(todo_id, user_id=current_user.id):
        raise HTTPException(status_code=404, detail="Todo not found or not owned by user")
