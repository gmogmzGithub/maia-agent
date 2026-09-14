"""Queue website conversation turns outside the request proxy chain.

Revision ID: 0034_async_website_turns
Revises: 0033_public_site_search
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0034_async_website_turns"
down_revision: str | None = "0033_public_site_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "website_turn_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("conversation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("command_key", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("listing_ids", JSONB(), nullable=False),
        sa.Column("sponsorship_campaign_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="Pending",
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("result", JSONB(), nullable=True),
        sa.Column("error_message", sa.String(length=300), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('Pending', 'Running', 'Complete', 'Failed')",
            name="ck_website_turn_requests_status",
        ),
        sa.CheckConstraint(
            "attempts >= 0", name="ck_website_turn_requests_attempts"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "command_key",
            name="uq_website_turn_requests_org_command",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["website_conversations.organization_id", "website_conversations.id"],
            name="fk_website_turn_requests_org_conversation",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "sponsorship_campaign_id"],
            ["sponsorship_campaigns.organization_id", "sponsorship_campaigns.id"],
            name="fk_website_turn_requests_org_sponsorship",
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    op.create_index(
        "ix_website_turn_requests_claim",
        "website_turn_requests",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_website_turn_requests_claim",
        table_name="website_turn_requests",
    )
    op.drop_table("website_turn_requests")
