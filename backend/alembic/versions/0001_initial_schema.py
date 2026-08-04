"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_organization_name", "organization", ["name"])

    op.create_table(
        "user",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("email", name="uq_user_email"),
    )
    op.create_index("ix_user_email", "user", ["email"])
    op.create_index("ix_user_full_name", "user", ["full_name"])

    op.create_table(
        "document",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("file_type", sa.String(length=128), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING", "PROCESSING", "COMPLETED", "FAILED", name="document_status", native_enum=False
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_document_filename", "document", ["filename"])
    op.create_index("ix_document_status", "document", ["status"])
    op.create_index("ix_document_owner_id", "document", ["owner_id"])
    op.create_index("ix_document_organization_id", "document", ["organization_id"])

    op.create_table(
        "conversation",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False, server_default="New conversation"),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_conversation_user_id", "conversation", ["user_id"])

    op.create_table(
        "message",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversation.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.Enum("USER", "ASSISTANT", "SYSTEM", name="message_role", native_enum=False),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("cached", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_message_conversation_created", "message", ["conversation_id", "created_at"])


def downgrade() -> None:
    op.drop_table("message")
    op.drop_table("conversation")
    op.drop_table("document")
    op.drop_table("user")
    op.drop_table("organization")
