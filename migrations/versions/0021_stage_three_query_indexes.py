"""Add Stage 3 query indexes to already-upgraded installations.

Revision ID: 0021_stage_three_query_indexes
Revises: 0020_authoritative_catalog

These indexes support the organization-scoped absence and open-alert surfaces,
plus authoritative calendar conflict reads. They belong in a new revision:
editing 0018 or 0019 would leave databases already stamped at 0020 without the
indexes and would make their downgrade try to remove objects never created.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_stage_three_query_indexes"
down_revision: str | None = "0020_authoritative_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_advisor_absences_org",
        "advisor_absences",
        ["organization_id", "starts_at"],
    )
    op.create_index(
        "ix_internal_alerts_open",
        "internal_alerts",
        ["organization_id", "created_at"],
        postgresql_where=sa.text("acknowledged_at IS NULL"),
    )
    op.create_index(
        "ix_appointments_calendar",
        "appointments",
        ["calendar_id", "starts_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_appointments_calendar", table_name="appointments")
    op.drop_index("ix_internal_alerts_open", table_name="internal_alerts")
    op.drop_index("ix_advisor_absences_org", table_name="advisor_absences")
