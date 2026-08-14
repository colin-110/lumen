from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.conversation import Conversation
    from app.models.document import Document
    from app.models.organization import Organization


class User(Base, TimestampMixin):
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Bumped to invalidate every token already issued for this user. See the
    # "ver" claim in core/security.py.
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id", ondelete="SET NULL"), nullable=True
    )

    organization: Mapped["Organization | None"] = relationship(back_populates="users")
    documents: Mapped[list["Document"]] = relationship(back_populates="owner")
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
