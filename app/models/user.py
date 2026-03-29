from pydantic import BaseModel, EmailStr
from typing import Optional


class User(BaseModel):
    id: int
    name: str
    email: str
    is_active: bool = True


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = None
