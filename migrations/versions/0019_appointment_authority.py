"""Database arbiters for appointment authority under concurrency.

Revision ID: 0019_appointment_authority
Revises: 0018_human_operation_and_visits

Calendar reads are necessary but cannot serialize two Product workers, and a
provider may take time to reflect a newly created event. PostgreSQL therefore
owns the final no-overlap decision. A separate partial unique index permits one
unrejected successor for an original appointment, so an ambiguous reschedule
cannot be followed by a second competing replacement.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_appointment_authority"
down_revision: str | None = "0018_human_operation_and_visits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE appointments
            ADD CONSTRAINT ex_appointments_calendar_overlap
            EXCLUDE USING gist (
                calendar_id WITH =,
                tstzrange(starts_at, ends_at, '[)') WITH &&
            )
            WHERE (
                calendar_id IS NOT NULL
                AND (
                    status IN ('Pending', 'Confirmed', 'NeedsReview')
                    OR (status = 'Rescheduled' AND calendar_event_id IS NOT NULL)
                )
            )
        """
    )
    op.create_index(
        "uq_appointments_active_reschedule",
        "appointments",
        ["rescheduled_from_id"],
        unique=True,
        postgresql_where=sa.text(
            "rescheduled_from_id IS NOT NULL AND status <> 'Rejected'"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_appointments_active_reschedule", table_name="appointments"
    )
    op.execute(
        "ALTER TABLE appointments "
        "DROP CONSTRAINT ex_appointments_calendar_overlap"
    )
