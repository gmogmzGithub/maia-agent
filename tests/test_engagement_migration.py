"""Stage 7 schema is additive, constrained and reversible."""

from __future__ import annotations

from alembic import command
from sqlalchemy import inspect, text

from tests.conftest import database_at_revision, requires_postgres

PREVIOUS_HEAD = "0023_external_inventory"
HEAD = "0024_reactivation_campaigns"
MIGRATION_DATABASE = "realestate_engagement_migration_test"


@requires_postgres
def test_engagement_schema_upgrades_and_downgrades() -> None:
    with database_at_revision(MIGRATION_DATABASE, PREVIOUS_HEAD) as (config, engine):
        command.upgrade(config, HEAD)
        tables = set(inspect(engine).get_table_names())
        assert {
            "approved_message_templates",
            "reactivation_candidates",
            "development_campaigns",
            "campaign_audience_members",
            "marketing_touches",
        } <= tables
        consent_columns = {
            column["name"] for column in inspect(engine).get_columns("consent_records")
        }
        assert {
            "business_name",
            "scope",
            "notice_version",
            "evidence_locator",
            "expires_at",
        } <= consent_columns
        with engine.begin() as connection:
            assert (
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
                == HEAD
            )

        command.downgrade(config, PREVIOUS_HEAD)
        tables = set(inspect(engine).get_table_names())
        assert "development_campaigns" not in tables
        assert "external_listing_candidates" in tables
        consent_columns = {
            column["name"] for column in inspect(engine).get_columns("consent_records")
        }
        assert "notice_version" not in consent_columns
