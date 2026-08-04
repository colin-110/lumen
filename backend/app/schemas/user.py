from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    email: EmailStr


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str | None = Field(None, min_length=1, max_length=100)
    organization_name: str | None = Field(
        None, description="If set, creates a new organization for this user."
    )


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    password: str | None = Field(None, min_length=8, max_length=128)
    full_name: str | None = None
    is_active: bool | None = None


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str | None = None
    is_active: bool
    is_superuser: bool
    organization_id: uuid.UUID | None = None
    created_at: datetime


class UserInDB(UserRead):
    hashed_password: str
