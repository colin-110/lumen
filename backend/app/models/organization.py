from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.user import User


class Organization(Base, TimestampMixin):
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Unique because the name is how registration resolves an organization.
    # Without the constraint, two people typing the same company name landed
    # in two different tenants and could not see each other's documents —
    # which quietly made org-scoped sharing unreachable in practice.
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="organization")
    documents: Mapped[list["Document"]] = relationship(back_populates="organization")
