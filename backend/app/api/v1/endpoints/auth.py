from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.config import settings
from app.core.rate_limit import client_ip, enforce_rate_limit
from app.core.security import JWTError, TokenType, create_access_token, create_refresh_token, decode_token
from app.crud.crud_organization import organization as crud_organization
from app.crud.crud_user import user as crud_user
from app.db.session import get_db
from app.schemas.token import RefreshRequest, Token, TokenPayload
from app.schemas.user import UserCreate, UserRead

router = APIRouter()


def _issue_tokens(user_id, token_version: int) -> Token:
    return Token(
        access_token=create_access_token(user_id, token_version),
        refresh_token=create_refresh_token(user_id, token_version),
    )


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(
    request: Request, user_in: UserCreate, db: AsyncSession = Depends(get_db)
) -> Any:
    """Create an account. Open by default for local/dev; disable via
    `ALLOW_OPEN_REGISTRATION=false` once real auth (SSO/invite) is in place.

    Limited by client IP: this endpoint is unauthenticated and creates rows in
    two tables, so without a limit it is an unbounded write primitive.
    """
    await enforce_rate_limit(
        f"register:{client_ip(request)}", settings.RATE_LIMIT_REGISTER_PER_MINUTE
    )

    if not settings.ALLOW_OPEN_REGISTRATION:
        raise HTTPException(status_code=403, detail="Open registration is disabled")

    existing = await crud_user.get_by_email(db, email=user_in.email)
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    organization_id = None
    if user_in.organization_name:
        # Join the existing organization if the name is already taken, rather
        # than minting a second one. Creating unconditionally meant two
        # colleagues who both typed "Acme Corp" ended up in separate tenants
        # and could not see each other's documents — which made org-scoped
        # sharing, the entire point of the organization model, unreachable.
        org = await crud_organization.get_or_create_by_name(db, name=user_in.organization_name)
        organization_id = org.id

    try:
        return await crud_user.create(db, obj_in=user_in, organization_id=organization_id)
    except IntegrityError as exc:
        # Two concurrent registrations for the same email both passed the
        # check above; the unique index is the real arbiter.
        await db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists") from exc


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    db: AsyncSession = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Any:
    """OAuth2-compatible password login. `username` is the account email.

    Limited per IP *and* per account: the IP bucket stops one host spraying
    many accounts, the account bucket stops a distributed attempt against one
    account. Neither is a substitute for the other.
    """
    await enforce_rate_limit(f"login:{client_ip(request)}", settings.RATE_LIMIT_LOGIN_PER_MINUTE)
    await enforce_rate_limit(
        f"login-account:{form_data.username.lower()[:320]}", settings.RATE_LIMIT_LOGIN_PER_MINUTE
    )

    user = await crud_user.authenticate(db, email=form_data.username, password=form_data.password)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    if not crud_user.is_active(user):
        raise HTTPException(status_code=400, detail="Inactive user")
    return _issue_tokens(user.id, user.token_version)


@router.post("/refresh", response_model=Token)
async def refresh(
    request: Request, body: RefreshRequest, db: AsyncSession = Depends(get_db)
) -> Any:
    await enforce_rate_limit(f"refresh:{client_ip(request)}", settings.RATE_LIMIT_LOGIN_PER_MINUTE)

    try:
        payload = decode_token(body.refresh_token)
        token_data = TokenPayload(**payload)
    except (JWTError, ValidationError) as exc:
        raise HTTPException(status_code=401, detail="Invalid refresh token") from exc

    if token_data.type != TokenType.REFRESH.value or not token_data.sub:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    # Parse before querying. Handing a non-UUID string straight to the driver
    # (which the previous version did) pushes a malformed-input error out of
    # the endpoint's control and into asyncpg.
    try:
        user_id = uuid.UUID(token_data.sub)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid refresh token") from exc

    user = await crud_user.get(db, id=user_id)
    if not user or not crud_user.is_active(user):
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if token_data.ver != user.token_version:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    return _issue_tokens(user.id, user.token_version)


@router.get("/me", response_model=UserRead)
async def me(current_user: UserRead = Depends(deps.get_current_active_user)) -> Any:
    return current_user
