"""Stage 6 schema is additive, constrained and reversible."""

from __future__ import annotations

from alembic import command
from sqlalchemy import inspect, text

from tests.conftest import database_at_revision, requires_postgres

PREVIOUS_HEAD = "0022_public_site"
HEAD = "0023_external_inventory"
MIGRATION_DATABASE = "realestate_external_inventory_migration_test"


@requires_postgres
def test_external_inventory_schema_upgrades_and_downgrades() -> None:
    with database_at_revision(MIGRATION_DATABASE, PREVIOUS_HEAD) as (config, engine):
        command.upgrade(config, HEAD)
        tables = set(inspect(engine).get_table_names())
        assert {
            "external_listing_candidates",
            "external_offer_candidates",
            "inventory_source_health",
            "listing_revalidations",
        } <= tables
        with engine.begin() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == HEAD

        command.downgrade(config, PREVIOUS_HEAD)
        tables = set(inspect(engine).get_table_names())
        assert "external_listing_candidates" not in tables
        assert "catalog_listings" in tables
