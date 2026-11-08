"""document content hash for duplicate-upload detection

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-08

Uploading the same file twice used to store a second object, parse and embed
it again, index a second copy of every chunk (so the same passage could fill
several top-k slots) and wipe the tenant's semantic cache. The upload endpoint
now hashes the bytes and returns the existing document on a match.

Existing rows keep a NULL hash: backfilling would mean downloading every
stored object, and the cost of not doing so is only that the first re-upload
of a pre-existing file is not recognised.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document", sa.Column("content_hash", sa.String(length=64), nullable=True))
    op.create_index("ix_document_content_hash", "document", ["content_hash"])


def downgrade() -> None:
    op.drop_index("ix_document_content_hash", table_name="document")
    op.drop_column("document", "content_hash")
