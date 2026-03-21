from fastapi import APIRouter, HTTPException
from app.models.user import UserCreate, UserUpdate
from app.services import user_service

router = APIRouter()


@router.get("/")
def list_users():
    return user_service.list_users()


@router.get("/{user_id}")
def get_user(user_id: int):
    user = user_service.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/", status_code=201)
def create_user(data: UserCreate):
    return user_service.create_user(data)


@router.patch("/{user_id}")
def update_user(user_id: int, data: UserUpdate):
    user = user_service.update_user(user_id, data)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int):
    if not user_service.delete_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")
