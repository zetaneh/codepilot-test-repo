from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from enum import Enum


class Cod8Status(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Cod8(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    status: Cod8Status = Cod8Status.PENDING
    owner_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_deleted: bool = False


class Cod8Create(BaseModel):
    title: str
    description: Optional[str] = None
    status: Cod8Status = Cod8Status.PENDING
    owner_id: int


class Cod8Update(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[Cod8Status] = None
    is_deleted: Optional[bool] = None
