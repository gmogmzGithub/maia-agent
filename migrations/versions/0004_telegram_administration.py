"""Telegram Administrative Channel (Checkpoint 4, P-040, ADR-0001).

Revision ID: 0004_telegram_administration
Revises: 0003_whatsapp_boundary
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_telegram_administration"
down_revision: str | None = "0003_whatsapp_boundary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "admin_messages",
        sa.Column("id", UUID, nullable=False),
        sa.Column("update_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.String(length=40), nullable=False),
        sa.Column("from_user_id", sa.String(length=40), nullable=False),
        sa.Column("from_username", sa.String(length=120), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("authorized", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("received_at", TS, nullable=False),
        sa.Column("persisted_at", TS, server_default=NOW, nullable=False),
        sa.Column("processed_at", TS, nullable=True),
        sa.Column("raw_update", JSONB, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # Telegram's monotonic id: the idempotency key for a re-polled update.
        sa.UniqueConstraint("update_id"),
    )

    op.create_table(
        "channel_cursors",
        sa.Column("channel", sa.String(length=40), nullable=False),
        sa.Column("cursor", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", TS, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("channel"),
    )

    op.add_column(
        "agent_sessions", sa.Column("channel_key", sa.String(length=120), nullable=True)
    )
    op.create_unique_constraint(
        "uq_agent_sessions_channel_key", "agent_sessions", ["channel_key"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_agent_sessions_channel_key", "agent_sessions", type_="unique")
    op.drop_column("agent_sessions", "channel_key")
    op.drop_table("channel_cursors")
    op.drop_table("admin_messages")
