"""Outbound Eligibility Gate: consent, suppression, and recorded decisions.

Revision ID: 0010_outbound_eligibility
Revises: 0009_property_administration

Three new tables plus the follow-up row's provenance (ADR-0045, ADR-0021).

Two choices worth stating. The follow-up day CHECK constraint is dropped rather
than rewritten: the cadence became a versioned pilot hypothesis owned by
``domain/followups.py``, so revising it must not require a migration, and rows
written under the previous hypothesis must stay readable. Existing rows are
backfilled to policy v1 — the days they were actually chosen under — instead of
being relabelled as the new policy.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0010_outbound_eligibility"
down_revision: str | None = "0009_property_administration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "consent_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "lead_id",
            UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "channel", sa.String(length=20), nullable=False, server_default="WhatsApp"
        ),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("state", sa.String(length=12), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("channel = 'WhatsApp'", name="ck_consent_records_channel"),
        sa.CheckConstraint(
            "category IN ('Marketing', 'Utility', 'Service')",
            name="ck_consent_records_category",
        ),
        sa.CheckConstraint(
            "state IN ('Granted', 'Revoked')", name="ck_consent_records_state"
        ),
    )
    op.create_index(
        "ix_consent_records_current",
        "consent_records",
        ["lead_id", "channel", "category", "recorded_at"],
    )

    op.create_table(
        "suppression_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "lead_id",
            UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "channel", sa.String(length=20), nullable=False, server_default="WhatsApp"
        ),
        sa.Column(
            "scope",
            sa.String(length=20),
            nullable=False,
            server_default="BusinessInitiated",
        ),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column(
            "source_inbox_id",
            UUID(as_uuid=True),
            sa.ForeignKey("inbox_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "channel = 'WhatsApp'", name="ck_suppression_records_channel"
        ),
        sa.CheckConstraint(
            "scope IN ('BusinessInitiated', 'All')", name="ck_suppression_records_scope"
        ),
    )
    # One active suppression per Lead and channel: recording the same opt-out
    # twice is a no-op rather than a second row.
    op.create_index(
        "uq_suppression_active",
        "suppression_records",
        ["lead_id", "channel"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "outbound_decisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("initiation", sa.String(length=20), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.String(length=60), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "trigger_inbox_ids",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("template_id", sa.String(length=120), nullable=True),
        sa.Column("template_category", sa.String(length=20), nullable=True),
        sa.Column(
            "service_window_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "outbox_id",
            UUID(as_uuid=True),
            sa.ForeignKey("outbox_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "initiation IN ('Reactive', 'BusinessInitiated')",
            name="ck_outbound_decisions_initiation",
        ),
        sa.CheckConstraint(
            "outcome IN ('Queued', 'Denied')", name="ck_outbound_decisions_outcome"
        ),
        sa.CheckConstraint(
            "(outcome = 'Queued' AND reason IS NULL) OR "
            "(outcome = 'Denied' AND reason IS NOT NULL)",
            name="ck_outbound_decisions_reason",
        ),
    )
    # At most one *allowed* decision per intent key, mirroring the Outbox's own
    # uniqueness. Refusing the same intent twice is history, not a conflict.
    op.create_index(
        "uq_outbound_decision_queued",
        "outbound_decisions",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("outcome = 'Queued'"),
    )
    op.create_index(
        "ix_outbound_decisions_lead", "outbound_decisions", ["lead_id", "decided_at"]
    )

    # -- Indexes for the queries the gate introduced ------------------------
    #
    # These are on pre-existing tables, which is exactly why they are easy to
    # forget: the gate runs on every outbound message and the follow-up sweep
    # runs every poll interval, so an unindexed scan here is paid continuously.
    op.create_index(
        "ix_outbox_conversation_recent",
        "outbox_messages",
        ["conversation_id", sa.text("created_at DESC")],
    )
    # Postgres does not index a foreign key on its own, and the service-window
    # lookup joins inbox_messages -> conversations on exactly this column.
    op.create_index("ix_conversations_lead", "conversations", ["lead_id"])
    # ix_inbox_messages_lane is (conversation_id, status, sent_at): with only an
    # equality on conversation_id, status sits between the key and the sort
    # column, so the planner still sorts. This serves the ordered lookups.
    op.create_index(
        "ix_inbox_messages_recent",
        "inbox_messages",
        ["conversation_id", sa.text("persisted_at DESC")],
    )
    op.create_index(
        "ix_lead_engagement_cycles_active",
        "lead_engagement_cycles",
        ["expires_at", "started_at"],
    )

    # -- lead_followups: provenance and the blocked outcome -----------------
    op.add_column(
        "lead_followups", sa.Column("policy_id", sa.String(length=60), nullable=True)
    )
    op.add_column(
        "lead_followups", sa.Column("policy_version", sa.Integer(), nullable=True)
    )
    op.add_column(
        "lead_followups",
        sa.Column(
            "decision_id",
            UUID(as_uuid=True),
            sa.ForeignKey("outbound_decisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Rows already in the table were chosen by the broker's original 28-day
    # cadence. They are labelled with the policy that actually produced them.
    op.execute(
        "UPDATE lead_followups SET policy_id = 'unanswered-inquiry', "
        "policy_version = 1 WHERE policy_id IS NULL"
    )
    op.alter_column("lead_followups", "policy_id", nullable=False)
    op.alter_column("lead_followups", "policy_version", nullable=False)

    # The cadence is a versioned hypothesis now, not a database invariant.
    op.drop_constraint("ck_lead_followups_day", "lead_followups", type_="check")
    op.drop_constraint("ck_lead_followups_status", "lead_followups", type_="check")
    op.create_check_constraint(
        "ck_lead_followups_status",
        "lead_followups",
        "status IN ('Enqueued', 'Skipped', 'Blocked')",
    )


def downgrade() -> None:
    # A Blocked attempt has no meaning under the old schema and its days may not
    # satisfy the restored CHECK, so the rows this revision could have written
    # are removed rather than silently mislabelled as Enqueued.
    op.execute("DELETE FROM lead_followups WHERE status = 'Blocked'")
    op.execute(
        "DELETE FROM lead_followups WHERE day_number NOT IN "
        "(1, 5, 7, 14, 18, 22, 26, 28)"
    )
    op.drop_constraint("ck_lead_followups_status", "lead_followups", type_="check")
    op.create_check_constraint(
        "ck_lead_followups_status", "lead_followups", "status IN ('Enqueued', 'Skipped')"
    )
    op.create_check_constraint(
        "ck_lead_followups_day",
        "lead_followups",
        "day_number IN (1, 5, 7, 14, 18, 22, 26, 28)",
    )
    op.drop_column("lead_followups", "decision_id")
    op.drop_column("lead_followups", "policy_version")
    op.drop_column("lead_followups", "policy_id")

    op.drop_index(
        "ix_lead_engagement_cycles_active", table_name="lead_engagement_cycles"
    )
    op.drop_index("ix_inbox_messages_recent", table_name="inbox_messages")
    op.drop_index("ix_conversations_lead", table_name="conversations")
    op.drop_index("ix_outbox_conversation_recent", table_name="outbox_messages")
    op.drop_index("ix_outbound_decisions_lead", table_name="outbound_decisions")
    op.drop_index("uq_outbound_decision_queued", table_name="outbound_decisions")
    op.drop_table("outbound_decisions")
    op.drop_index("uq_suppression_active", table_name="suppression_records")
    op.drop_table("suppression_records")
    op.drop_index("ix_consent_records_current", table_name="consent_records")
    op.drop_table("consent_records")
