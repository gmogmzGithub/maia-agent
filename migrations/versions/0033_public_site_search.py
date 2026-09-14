"""Add a dedicated public-site role and idempotent search receipts.

Revision ID: 0033_public_site_search
Revises: 0032_public_site_ui
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0033_public_site_search"
down_revision: str | None = "0032_public_site_ui"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_agent_sessions_role", "agent_sessions", type_="check")
    op.create_check_constraint(
        "ck_agent_sessions_role",
        "agent_sessions",
        "role IN ('Sales', 'Administrative', 'PublicSite')",
    )
    op.create_table(
        "website_search_receipts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("hermes_session_id", sa.String(length=200), nullable=False),
        sa.Column("turn_key", sa.String(length=200), nullable=False),
        sa.Column("criteria", JSONB(), nullable=False),
        sa.Column("listing_ids", JSONB(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("public_url", sa.String(length=1000), nullable=False),
        sa.Column("response", JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "organization_id",
            "turn_key",
            name="uq_website_search_receipts_org_turn",
        ),
    )
    op.create_index(
        "ix_website_search_receipts_session",
        "website_search_receipts",
        ["organization_id", "hermes_session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_website_search_receipts_session",
        table_name="website_search_receipts",
    )
    op.drop_table("website_search_receipts")
    op.drop_constraint("ck_agent_sessions_role", "agent_sessions", type_="check")
    op.create_check_constraint(
        "ck_agent_sessions_role",
        "agent_sessions",
        "role IN ('Sales', 'Administrative')",
    )
