"""unique organization names, token versioning, conversation activity index

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-12

Three changes, all of them fixing something that was silently wrong:

* `organization.name` gains a unique constraint. Registration used to create
  a brand new organization for every signup, so two colleagues typing the same
  company name landed in different tenants. Registration now resolves an
  existing organization by name, which only makes sense if the name is unique.
  Pre-existing duplicates are merged into the oldest row before the constraint
  goes on, so the upgrade doesn't fail on live data.

* `user.token_version` supports revoking already-issued JWTs (deactivation,
  password change). Defaults to 0 so tokens outstanding across the deploy
  keep working.

* An index on `(user_id, updated_at desc)` for the conversation sidebar, which
  orders by exactly that and previously had only `user_id`.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- merge duplicate organizations before enforcing uniqueness ---------
    # Keep the oldest row for each name and repoint everything at it. Done in
    # SQL rather than Python so it stays a single transaction and needs no
    # application code to run the migration.
    op.execute(
        """
        WITH canonical AS (
            SELECT DISTINCT ON (name) name, id
            FROM organization
            ORDER BY name, created_at ASC, id ASC
        ),
        remap AS (
            SELECT o.id AS old_id, c.id AS new_id
            FROM organization o
            JOIN canonical c ON c.name = o.name
            WHERE o.id <> c.id
        )
        UPDATE "user" u
        SET organization_id = r.new_id
        FROM remap r
        WHERE u.organization_id = r.old_id
        """
    )
    op.execute(
        """
        WITH canonical AS (
            SELECT DISTINCT ON (name) name, id
            FROM organization
            ORDER BY name, created_at ASC, id ASC
        ),
        remap AS (
            SELECT o.id AS old_id, c.id AS new_id
            FROM organization o
            JOIN canonical c ON c.name = o.name
            WHERE o.id <> c.id
        )
        UPDATE document d
        SET organization_id = r.new_id
        FROM remap r
        WHERE d.organization_id = r.old_id
        """
    )
    op.execute(
        """
        DELETE FROM organization o
        USING (
            SELECT DISTINCT ON (name) name, id
            FROM organization
            ORDER BY name, created_at ASC, id ASC
        ) c
        WHERE o.name = c.name AND o.id <> c.id
        """
    )
    op.create_unique_constraint("uq_organization_name", "organization", ["name"])

    # --- token revocation support -----------------------------------------
    op.add_column(
        "user",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )

    # --- sidebar ordering --------------------------------------------------
    op.create_index(
        "ix_conversation_user_updated",
        "conversation",
        ["user_id", sa.text("updated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_user_updated", table_name="conversation")
    op.drop_column("user", "token_version")
    op.drop_constraint("uq_organization_name", "organization", type_="unique")
    # The merged duplicate organizations are not recoverable; that is inherent
    # to the merge, not an oversight.
