from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import JWTError, TokenType, decode_token
from app.crud.crud_user import user as crud_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.token import TokenPayload

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login",
    auto_error=False,
)

credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    token: str | None = Depends(reusable_oauth2),
) -> User:
    if not token:
        raise credentials_exception
    try:
        payload = decode_token(token)
        token_data = TokenPayload(**payload)
    except (JWTError, ValidationError) as exc:
        raise credentials_exception from exc

    if token_data.type != TokenType.ACCESS.value or not token_data.sub:
        raise credentials_exception

    try:
        user_id = uuid.UUID(token_data.sub)
    except ValueError as exc:
        raise credentials_exception from exc

    user = await crud_user.get(db, id=user_id)
    if not user:
        raise credentials_exception

    # A JWT is valid until it expires no matter what happened to the account
    # afterwards. `token_version` is the escape hatch: bumping it on the user
    # row invalidates every token already issued for them.
    if token_data.ver != user.token_version:
        raise credentials_exception

    return user


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    if not crud_user.is_active(current_user):
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


async def get_current_active_superuser(
    # Chains off get_current_active_user, not get_current_user: depending on
    # the latter meant a deactivated superuser still passed this check and
    # kept access to /debug/retrieval, which exposes system prompts and raw
    # document text. Being a superuser is an *additional* requirement on top
    # of being active, never a way around it.
    current_user: User = Depends(get_current_active_user),
) -> User:
    if not crud_user.is_superuser(current_user):
        raise HTTPException(status_code=403, detail="Insufficient privileges")
    return current_user


DbSession = AsyncSession
