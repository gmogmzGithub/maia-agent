"""Allow an anonymous website conversation to end without inventing a Contact.

Revision ID: 0035_anonymous_close
Revises: 0034_async_website_turns
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0035_anonymous_close"
down_revision: str | None = "0034_async_website_turns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EXPANDED = (
    "(verified_contact_id IS NULL AND status IN "
    "('Open', 'HandoffPending', 'Closed')) OR "
    "(verified_contact_id IS NOT NULL AND status IN ('Verified', 'Closed'))"
)
_PREVIOUS = (
    "(verified_contact_id IS NULL AND status IN ('Open', 'HandoffPending')) OR "
    "(verified_contact_id IS NOT NULL AND status IN ('Verified', 'Closed'))"
)


def upgrade() -> None:
    op.drop_constraint(
        "ck_website_conversations_verified_contact",
        "website_conversations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_website_conversations_verified_contact",
        "website_conversations",
        _EXPANDED,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_website_conversations_verified_contact",
        "website_conversations",
        type_="check",
    )
    # Keep already-closed anonymous rows terminal during a rollback. PostgreSQL
    # still enforces a NOT VALID check for new or changed rows; only the rows
    # legitimately closed while this revision was active remain grandfathered.
    op.execute(
        "ALTER TABLE website_conversations ADD CONSTRAINT "
        "ck_website_conversations_verified_contact CHECK "
        f"({_PREVIOUS}) NOT VALID"
    )
