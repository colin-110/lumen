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
    # Absent in tokens issued before token versioning existed; treated as 0,
    # which matches the default on every existing row, so tokens outstanding
    # across the deploy keep working rather than logging everyone out.
    ver: int = 0


class RefreshRequest(BaseModel):
    refresh_token: str
