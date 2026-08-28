"""Durable idempotency receipts for commercial updates.

Revision ID: 0016_commercial_command_receipts
Revises: 0015_commercial_integrity

Several operator commands update an existing row instead of creating a row
with a naturally unique command key.  This table makes their request keys
transactional, replayable, and payload-bound.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0016_commercial_command_receipts"
down_revision: str | None = "0015_commercial_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "commercial_command_receipts",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("command_key", sa.String(length=200), nullable=False),
        sa.Column("operation", sa.String(length=80), nullable=False),
        sa.Column("subject_type", sa.String(length=80), nullable=False),
        sa.Column("subject_id", sa.String(length=80), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "command_key",
            name="uq_commercial_command_org_key",
        ),
    )
    op.create_index(
        "ix_commercial_command_subject",
        "commercial_command_receipts",
        ["organization_id", "subject_type", "subject_id"],
    )


def downgrade() -> None:
    op.drop_table("commercial_command_receipts")
