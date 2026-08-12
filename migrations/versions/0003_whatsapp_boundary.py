"""Durable WhatsApp Inbox and Outbox (Checkpoint 2, ADR-0005).

Revision ID: 0003_whatsapp_boundary
Revises: 0002_property_ingestion
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_whatsapp_boundary"
down_revision: str | None = "0002_property_ingestion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", UUID, nullable=False),
        sa.Column("wa_id", sa.String(length=32), nullable=False),
        sa.Column("profile_name", sa.String(length=200), nullable=True),
        sa.Column("follow_up_opt_out", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("wa_id"),
    )

    op.create_table(
        "lead_engagement_cycles",
        sa.Column("id", UUID, nullable=False),
        sa.Column("lead_id", UUID, nullable=False),
        sa.Column("started_at", TS, server_default=NOW, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "conversations",
        sa.Column("id", UUID, nullable=False),
        sa.Column("lead_id", UUID, nullable=False),
        sa.Column("cycle_id", UUID, nullable=False),
        sa.Column("phone_number_id", sa.String(length=40), nullable=False),
        sa.Column("property_uuid", UUID, nullable=True),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["cycle_id"], ["lead_engagement_cycles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["property_uuid"], ["properties.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cycle_id"),
    )

    op.create_table(
        "inbox_groups",
        sa.Column("id", UUID, nullable=False),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("claim_token", UUID, nullable=False),
        sa.Column("lease_expires_at", TS, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("turn_started_at", TS, nullable=True),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("closed_at", TS, nullable=True),
        sa.CheckConstraint(
            "status IN ('Processing', 'Settled', 'Failed')", name="ck_inbox_groups_status"
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # At most one active Inbox group per Conversation. Enforced by the database
    # so a second worker cannot open a competing lane (P-028, P-037).
    op.create_index(
        "uq_active_group_per_conversation",
        "inbox_groups",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'Processing'"),
    )

    op.create_table(
        "inbox_messages",
        sa.Column("id", UUID, nullable=False),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("wamid", sa.String(length=200), nullable=False),
        sa.Column("from_wa_id", sa.String(length=32), nullable=False),
        sa.Column("message_type", sa.String(length=40), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("sent_at", TS, nullable=False),
        sa.Column("persisted_at", TS, server_default=NOW, nullable=False),
        sa.Column("raw_message", JSONB, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("group_id", UUID, nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", TS, nullable=True),
        sa.CheckConstraint(
            "status IN ('Pending', 'Processing', 'Processed', 'Failed')",
            name="ck_inbox_messages_status",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["group_id"], ["inbox_groups.id"], name="fk_inbox_message_group"
        ),
        sa.PrimaryKeyConstraint("id"),
        # Meta's message identifier is the duplicate-webhook idempotency key.
        sa.UniqueConstraint("wamid"),
    )
    op.create_index(
        "ix_inbox_messages_lane", "inbox_messages", ["conversation_id", "status", "sent_at"]
    )

    op.create_table(
        "outbox_messages",
        sa.Column("id", UUID, nullable=False),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("inbox_group_id", UUID, nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("to_wa_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("covered_inbox_ids", JSONB, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", TS, nullable=True),
        sa.Column("provider_message_id", sa.String(length=200), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("sent_at", TS, nullable=True),
        sa.CheckConstraint(
            "status IN ('Pending', 'Sending', 'Sent', 'Failed', 'DeliveryUnknown')",
            name="ck_outbox_messages_status",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inbox_group_id"], ["inbox_groups.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_outbox_due", "outbox_messages", ["status", "next_attempt_at"])

    op.create_table(
        "delivery_statuses",
        sa.Column("id", UUID, nullable=False),
        sa.Column("outbox_id", UUID, nullable=True),
        sa.Column("provider_message_id", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("occurred_at", TS, nullable=False),
        sa.Column("raw", JSONB, nullable=False),
        sa.Column("recorded_at", TS, server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["outbox_id"], ["outbox_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_message_id", "status", name="uq_delivery_status_event"
        ),
    )

    # One persistent Sales session per active engagement cycle (P-064).
    op.add_column("agent_sessions", sa.Column("cycle_id", UUID, nullable=True))
    op.create_unique_constraint(
        "uq_agent_sessions_cycle", "agent_sessions", ["cycle_id"]
    )
    op.create_foreign_key(
        "fk_agent_sessions_cycle",
        "agent_sessions",
        "lead_engagement_cycles",
        ["cycle_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_agent_sessions_cycle", "agent_sessions", type_="foreignkey")
    op.drop_constraint("uq_agent_sessions_cycle", "agent_sessions", type_="unique")
    op.drop_column("agent_sessions", "cycle_id")

    op.drop_table("delivery_statuses")
    op.drop_index("ix_outbox_due", table_name="outbox_messages")
    op.drop_table("outbox_messages")
    op.drop_index("ix_inbox_messages_lane", table_name="inbox_messages")
    op.drop_table("inbox_messages")
    op.drop_index("uq_active_group_per_conversation", table_name="inbox_groups")
    op.drop_table("inbox_groups")
    op.drop_table("conversations")
    op.drop_table("lead_engagement_cycles")
    op.drop_table("leads")
