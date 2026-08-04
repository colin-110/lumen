from __future__ import annotations

from pydantic import BaseModel


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: str | None = None
    type: str | None = None
    jti: str | None = None
    exp: int | None = None


class RefreshRequest(BaseModel):
    refresh_token: str
