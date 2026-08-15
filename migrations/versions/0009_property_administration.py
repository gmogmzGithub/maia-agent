"""Manual property administration and private visit address.

Revision ID: 0009_property_administration
Revises: 0008_lead_followups
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_property_administration"
down_revision: str | None = "0008_lead_followups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "properties", sa.Column("inactive_reason", sa.String(length=40), nullable=True)
    )
    op.add_column("properties", sa.Column("visit_address", sa.Text(), nullable=True))
    op.execute(
        "UPDATE properties SET inactive_reason = 'Unspecified' "
        "WHERE status = 'Inactive'"
    )
    op.create_check_constraint(
        "ck_properties_inactive_reason",
        "properties",
        "(status = 'Active' AND inactive_reason IS NULL) OR "
        "(status = 'Inactive' AND inactive_reason IN "
        "('Sold', 'Rented', 'Reserved', 'TemporarilyUnavailable', "
        "'Withdrawn', 'Unspecified'))",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_properties_inactive_reason", "properties", type_="check"
    )
    op.drop_column("properties", "visit_address")
    op.drop_column("properties", "inactive_reason")
