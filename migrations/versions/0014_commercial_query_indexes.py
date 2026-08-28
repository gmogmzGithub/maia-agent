"""Indexes for the query shapes the operator surfaces actually run.

Revision ID: 0014_commercial_query_indexes
Revises: 0013_opportunities_and_actions

Three gaps found by reading `EXPLAIN` against the real schema rather than by
guessing from the model definitions.

``opportunities`` had indexes on ``(organization_id, stage)``,
``(responsible_advisor_id, stage)`` and ``(contact_id, created_at)`` — none
including ``last_activity_at``, which is what the dormancy sweep filters on and
what the pipeline surface sorts by on every page load. Both were sequential
scans plus a sort.

``outbound_decisions`` had no index on ``conversation_id`` at all. PostgreSQL
does not index a foreign key on its own, and the Inbox reads the denied
decisions for a conversation on every detail view.

``ix_inbox_messages_retention`` led with ``content_expired_at``, which is NULL
for nearly every row, so it was close to useless. Replaced with a partial index
on exactly the rows the retention sweep looks for — the unexpired ones — which
also shrinks as content expires rather than growing.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_commercial_query_indexes"
down_revision: str | None = "0013_opportunities_and_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The dormancy sweep: WHERE stage IN (...) AND last_activity_at <= cutoff
    # ORDER BY last_activity_at.
    op.create_index(
        "ix_opportunities_activity",
        "opportunities",
        ["stage", "last_activity_at"],
    )
    # The pipeline surface: WHERE organization_id = ? ORDER BY last_activity_at
    # DESC.
    op.create_index(
        "ix_opportunities_org_activity",
        "opportunities",
        ["organization_id", sa.text("last_activity_at DESC")],
    )
    # The Inbox's restriction panel: the denied decisions of one conversation,
    # newest first.
    op.create_index(
        "ix_outbound_decisions_conversation",
        "outbound_decisions",
        ["conversation_id", sa.text("decided_at DESC")],
    )

    op.drop_index("ix_inbox_messages_retention", table_name="inbox_messages")
    op.create_index(
        "ix_inbox_messages_unexpired",
        "inbox_messages",
        ["conversation_id", "sent_at"],
        postgresql_where=sa.text("content_expired_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_inbox_messages_unexpired", table_name="inbox_messages")
    op.create_index(
        "ix_inbox_messages_retention",
        "inbox_messages",
        ["content_expired_at", "sent_at"],
    )
    op.drop_index(
        "ix_outbound_decisions_conversation", table_name="outbound_decisions"
    )
    op.drop_index("ix_opportunities_org_activity", table_name="opportunities")
    op.drop_index("ix_opportunities_activity", table_name="opportunities")
