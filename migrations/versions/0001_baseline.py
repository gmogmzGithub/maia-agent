"""Checkpoint 0 baseline: establish the migration history.

Deliberately empty. The implementation plan requires building only the database
records the current checkpoint needs, and Checkpoint 0 needs none. This revision
exists so `alembic upgrade head` is a real, provable step from the first
documented command sequence onward.

Revision ID: 0001_baseline
Revises:
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
