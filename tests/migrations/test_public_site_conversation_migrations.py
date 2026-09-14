"""The public-search and asynchronous-turn schema upgrades are reversible."""

from __future__ import annotations

from datetime import UTC, datetime
import uuid

from alembic import command
from sqlalchemy import text

from tests.conftest import database_at_revision, requires_postgres

pytestmark = requires_postgres

PREVIOUS_HEAD = "0032_public_site_ui"
ASYNC_HEAD = "0034_async_website_turns"
HEAD = "0035_anonymous_close"
MIGRATION_DATABASE = "realestate_public_site_conversation_migration_test"


def test_public_search_and_async_turn_tables_upgrade_and_downgrade_together() -> None:
    with database_at_revision(MIGRATION_DATABASE, PREVIOUS_HEAD) as (config, engine):
        command.upgrade(config, HEAD)

        with engine.begin() as connection:
            tables = connection.execute(
                text(
                    "SELECT to_regclass('public.website_search_receipts'), "
                    "to_regclass('public.website_turn_requests')"
                )
            ).one()
            role_constraint = connection.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_agent_sessions_role'"
                )
            ).scalar_one()
            turn_foreign_keys = set(
                connection.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid = 'website_turn_requests'::regclass "
                        "AND contype = 'f'"
                    )
                ).scalars()
            )
            indexes = set(
                connection.execute(
                    text(
                        "SELECT indexname FROM pg_indexes WHERE indexname IN "
                        "('ix_website_search_receipts_session', "
                        "'ix_website_turn_requests_claim')"
                    )
                ).scalars()
            )

        assert tables == ("website_search_receipts", "website_turn_requests")
        assert "PublicSite" in role_constraint
        assert turn_foreign_keys >= {
            "fk_website_turn_requests_org_conversation",
            "fk_website_turn_requests_org_sponsorship",
        }
        assert indexes == {
            "ix_website_search_receipts_session",
            "ix_website_turn_requests_claim",
        }

        command.downgrade(config, PREVIOUS_HEAD)

        with engine.begin() as connection:
            tables_after = connection.execute(
                text(
                    "SELECT to_regclass('public.website_search_receipts'), "
                    "to_regclass('public.website_turn_requests')"
                )
            ).one()
            role_constraint_after = connection.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_agent_sessions_role'"
                )
            ).scalar_one()

        assert tables_after == (None, None)
        assert "PublicSite" not in role_constraint_after


def test_anonymous_conversation_can_reach_a_terminal_closed_state() -> None:
    with database_at_revision(MIGRATION_DATABASE, ASYNC_HEAD) as (config, engine):
        conversation_id = uuid.uuid4()
        at = datetime(2026, 9, 13, 20, 0, tzinfo=UTC)
        with engine.begin() as connection:
            organization_id = connection.execute(
                text("SELECT id FROM organizations WHERE slug = 'larevia'")
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO website_conversations "
                    "(id, organization_id, access_token_hash, listing_context, "
                    "status, created_at, last_activity_at) VALUES "
                    "(:id, :organization_id, :token_hash, '[]'::jsonb, "
                    "'Open', :at, :at)"
                ),
                {
                    "id": conversation_id,
                    "organization_id": organization_id,
                    "token_hash": uuid.uuid4().hex + uuid.uuid4().hex,
                    "at": at,
                },
            )

        command.upgrade(config, HEAD)

        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE website_conversations SET status = 'Closed' "
                    "WHERE id = :id"
                ),
                {"id": conversation_id},
            )
            state = connection.execute(
                text("SELECT status FROM website_conversations WHERE id = :id"),
                {"id": conversation_id},
            ).scalar_one()

        assert state == "Closed"

        # A rollback keeps the terminal row valid without reopening continuity.
        command.downgrade(config, ASYNC_HEAD)

        with engine.begin() as connection:
            state_after = connection.execute(
                text("SELECT status FROM website_conversations WHERE id = :id"),
                {"id": conversation_id},
            ).scalar_one()

        assert state_after == "Closed"
