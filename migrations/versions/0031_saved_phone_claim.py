"""Require a bounded phone claim before the first saved Listing.

Revision ID: 0031_saved_phone_claim
Revises: 0030_meta_channels
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0031_saved_phone_claim"
down_revision: str | None = "0030_meta_channels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "saved_collections",
        sa.Column("claimed_phone_number", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_saved_collections_claimed_phone",
        "saved_collections",
        ["organization_id", "claimed_phone_number", "created_at"],
        postgresql_where=sa.text(
            "claimed_phone_number IS NOT NULL AND deleted_at IS NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_saved_collections_claimed_phone", table_name="saved_collections")
    op.drop_column("saved_collections", "claimed_phone_number")
