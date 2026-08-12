"""WhatsApp-only 28-day lead follow-up cadence.

Revision ID: 0008_lead_followups
Revises: 0007_checkpoint_5_recovery
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_lead_followups"
down_revision: str | None = "0007_checkpoint_5_recovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "lead_followups",
        sa.Column("id", UUID, nullable=False),
        sa.Column("cycle_id", UUID, nullable=False),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("day_number", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False, server_default="WhatsApp"),
        sa.Column("due_at", TS, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="Enqueued"),
        sa.Column("outbox_id", UUID, nullable=True),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("enqueued_at", TS, nullable=True),
        sa.CheckConstraint(
            "day_number IN (1, 5, 7, 14, 18, 22, 26, 28)",
            name="ck_lead_followups_day",
        ),
        sa.CheckConstraint("channel = 'WhatsApp'", name="ck_lead_followups_channel"),
        sa.CheckConstraint(
            "status IN ('Enqueued', 'Skipped')", name="ck_lead_followups_status"
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cycle_id"], ["lead_engagement_cycles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["outbox_id"], ["outbox_messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "cycle_id", "day_number", "channel", name="uq_lead_followup_cycle_day"
        ),
    )
    op.create_index("ix_lead_followups_due", "lead_followups", ["status", "due_at"])

    # Do not send catch-up messages to leads that already existed before this
    # feature was enabled. New cycles after this migration receive the cadence.
    op.execute(
        """
        INSERT INTO lead_followups (
            id, cycle_id, conversation_id, day_number, channel, due_at, status,
            created_at
        )
        SELECT
            gen_random_uuid(),
            c.id,
            conv.id,
            d.day_number,
            'WhatsApp',
            c.started_at + ((d.day_number - 1) * interval '1 day'),
            'Skipped',
            now()
        FROM lead_engagement_cycles c
        JOIN conversations conv ON conv.cycle_id = c.id
        CROSS JOIN (VALUES (1), (5), (7), (14), (18), (22), (26), (28)) AS d(day_number)
        ON CONFLICT (cycle_id, day_number, channel) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_lead_followups_due", table_name="lead_followups")
    op.drop_table("lead_followups")
