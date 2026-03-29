from fastapi import APIRouter, HTTPException, Depends
from app.models.user import UserCreate, UserUpdate, User
from app.services import user_service
from app.auth import get_current_active_user

router = APIRouter(dependencies=[Depends(get_current_active_user)])


@router.get("/", response_model=list[User])
def list_users():
    return user_service.list_users()


@router.get("/{user_id}", response_model=User)
def get_user(user_id: int):
    user = user_service.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/{user_id}", response_model=User)
def update_user(user_id: int, data: UserUpdate):
    user = user_service.update_user(user_id, data)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int):
    if not user_service.delete_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")
