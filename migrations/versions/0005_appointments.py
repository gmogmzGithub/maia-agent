"""Availability snapshots and appointment booking attempts (Checkpoint 3).

Revision ID: 0005_appointments
Revises: 0004_telegram_administration
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_appointments"
down_revision: str | None = "0004_telegram_administration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "availability_snapshots",
        sa.Column("id", UUID, nullable=False),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("property_uuid", UUID, nullable=False),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("horizon_end", TS, nullable=False),
        sa.Column("time_zone", sa.String(length=60), nullable=False),
        sa.Column("slots", JSONB, nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["property_uuid"], ["properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # At most one current snapshot per Conversation and Property (ADR-0011).
        sa.UniqueConstraint(
            "conversation_id", "property_uuid", name="uq_snapshot_conversation_property"
        ),
    )

    op.create_table(
        "appointments",
        sa.Column("id", UUID, nullable=False),
        sa.Column("reference", sa.String(length=40), nullable=False),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("lead_id", UUID, nullable=False),
        sa.Column("property_uuid", UUID, nullable=False),
        sa.Column("starts_at", TS, nullable=False),
        sa.Column("ends_at", TS, nullable=False),
        sa.Column("attendee_name", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("calendar_event_id", sa.String(length=200), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("resolved_at", TS, nullable=True),
        sa.Column("booked_notice_at", TS, nullable=True),
        sa.Column("reminder_sent_at", TS, nullable=True),
        sa.Column("digest_sent_on", sa.String(length=10), nullable=True),
        sa.CheckConstraint(
            "status IN ('Pending', 'Confirmed', 'Rejected', 'NeedsReview')",
            name="ck_appointments_status",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["property_uuid"], ["properties.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference"),
        # The attempt's identity: one booking per Conversation, Property, start.
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_appointments_upcoming", "appointments", ["status", "starts_at"])


def downgrade() -> None:
    op.drop_index("ix_appointments_upcoming", table_name="appointments")
    op.drop_table("appointments")
    op.drop_table("availability_snapshots")
