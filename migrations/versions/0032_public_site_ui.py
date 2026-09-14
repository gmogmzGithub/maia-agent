"""Record the first verified public publication time for Listings.

Revision ID: 0032_public_site_ui
Revises: 0031_saved_phone_claim
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0032_public_site_ui"
down_revision: str | None = "0031_saved_phone_claim"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "catalog_listings",
        sa.Column("first_published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_catalog_listings_org_first_published",
        "catalog_listings",
        ["organization_id", "first_published_at"],
        postgresql_where=sa.text("first_published_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_catalog_listings_org_first_published",
        table_name="catalog_listings",
    )
    op.drop_column("catalog_listings", "first_published_at")
