from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.security import JWTError, TokenType, create_access_token, create_refresh_token, decode_token
from app.crud.crud_user import user as crud_user
from app.db.session import get_db
from app.models.organization import Organization
from app.schemas.token import RefreshRequest, Token, TokenPayload
from app.schemas.user import UserCreate, UserRead

router = APIRouter()


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(user_in: UserCreate, db: AsyncSession = Depends(get_db)) -> Any:
    """Create an account. Open by default for local/dev; disable via
    `ALLOW_OPEN_REGISTRATION=false` once real auth (SSO/invite) is in place."""
    from app.core.config import settings

    if not settings.ALLOW_OPEN_REGISTRATION:
        raise HTTPException(status_code=403, detail="Open registration is disabled")

    existing = await crud_user.get_by_email(db, email=user_in.email)
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    organization_id = None
    if user_in.organization_name:
        org = Organization(name=user_in.organization_name)
        db.add(org)
        await db.commit()
        await db.refresh(org)
        organization_id = org.id

    return await crud_user.create(db, obj_in=user_in, organization_id=organization_id)


@router.post("/login", response_model=Token)
async def login(
    db: AsyncSession = Depends(get_db), form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """OAuth2-compatible password login. `username` is the account email."""
    user = await crud_user.authenticate(db, email=form_data.username, password=form_data.password)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    if not crud_user.is_active(user):
        raise HTTPException(status_code=400, detail="Inactive user")
    return Token(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=Token)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> Any:
    try:
        payload = decode_token(body.refresh_token)
        token_data = TokenPayload(**payload)
    except (JWTError, ValidationError) as exc:
        raise HTTPException(status_code=401, detail="Invalid refresh token") from exc

    if token_data.type != TokenType.REFRESH.value or not token_data.sub:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user = await crud_user.get(db, id=token_data.sub)
    if not user or not crud_user.is_active(user):
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    return Token(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.get("/me", response_model=UserRead)
async def me(current_user: UserRead = Depends(deps.get_current_active_user)) -> Any:
    return current_user
