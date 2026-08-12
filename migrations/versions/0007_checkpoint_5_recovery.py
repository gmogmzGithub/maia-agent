"""Checkpoint 5 recovery and manual-resolution state.

Revision ID: 0007_checkpoint_5_recovery
Revises: 0006_lead_notice
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_checkpoint_5_recovery"
down_revision: str | None = "0006_lead_notice"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_appointments_status", "appointments", type_="check")
    op.create_check_constraint(
        "ck_appointments_status",
        "appointments",
        "status IN ('Pending', 'Confirmed', 'Rejected', 'NeedsReview', 'Cancelled')",
    )
    op.add_column(
        "appointments",
        sa.Column("resolution_notification_status", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "appointments",
        sa.Column("resolution_notification_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "appointments",
        sa.Column("inactive_review_status", sa.String(length=24), nullable=True),
    )
    op.add_column(
        "appointments",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_appointments_resolution_notification",
        "appointments",
        "resolution_notification_status IS NULL OR "
        "resolution_notification_status IN ('Queued', 'PendingManual', 'Notified')",
    )
    op.create_check_constraint(
        "ck_appointments_inactive_review",
        "appointments",
        "inactive_review_status IS NULL OR "
        "inactive_review_status IN ('Pending', 'HandlingManually', 'Complete')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_appointments_inactive_review", "appointments", type_="check"
    )
    op.drop_constraint(
        "ck_appointments_resolution_notification", "appointments", type_="check"
    )
    op.drop_column("appointments", "cancelled_at")
    op.drop_column("appointments", "inactive_review_status")
    op.drop_column("appointments", "resolution_notification_at")
    op.drop_column("appointments", "resolution_notification_status")
    op.drop_constraint("ck_appointments_status", "appointments", type_="check")
    op.create_check_constraint(
        "ck_appointments_status",
        "appointments",
        "status IN ('Pending', 'Confirmed', 'Rejected', 'NeedsReview')",
    )
