"""Add the redacted, bounded operational trace ledger.

Revision ID: 0032_operational_trace_ledger
Revises: 0031_saved_phone_claim
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0032_operational_trace_ledger"
down_revision: str | None = "0031_saved_phone_claim"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "inbox_messages",
        sa.Column("interaction_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_inbox_messages_interaction",
        "inbox_messages",
        ["organization_id", "interaction_id"],
        postgresql_where=sa.text("interaction_id IS NOT NULL"),
    )
    op.create_table(
        "operational_trace_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("interaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_trace_handle", sa.String(length=32), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_name", sa.String(length=100), nullable=False),
        sa.Column("stage", sa.String(length=60), nullable=False),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=12), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_type", sa.String(length=100), nullable=True),
        sa.Column("error_fingerprint", sa.String(length=32), nullable=True),
        sa.CheckConstraint("expires_at >= occurred_at", name="ck_trace_events_expiry"),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_trace_events_duration"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_trace_events_interaction",
        "operational_trace_events",
        ["organization_id", "interaction_id", "occurred_at"],
    )
    op.create_index(
        "ix_trace_events_customer",
        "operational_trace_events",
        ["organization_id", "customer_trace_handle", "occurred_at"],
    )
    op.create_index("ix_trace_events_expiry", "operational_trace_events", ["expires_at"])


def downgrade() -> None:
    op.drop_table("operational_trace_events")
    op.drop_index("ix_inbox_messages_interaction", table_name="inbox_messages")
    op.drop_column("inbox_messages", "interaction_id")
