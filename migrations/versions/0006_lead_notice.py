"""The Lead-facing appointment notice marker (Checkpoint 3).

Revision ID: 0006_lead_notice
Revises: 0005_appointments

The Broker's three notifications already had their bookkeeping columns. The
Lead's single deterministic message did not: without a marker, a confirmation
released on one turn would be released again on the next, because "has the Lead
been told" was not persisted anywhere.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_lead_notice"
down_revision: str | None = "0005_appointments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column("lead_notice_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("appointments", "lead_notice_at")
