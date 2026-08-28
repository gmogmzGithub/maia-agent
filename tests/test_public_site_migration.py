"""Stage 5 public-state schema migration is reversible and complete."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.conftest import database_at_revision, requires_postgres

pytestmark = requires_postgres
MIGRATION_DATABASE = "realestate_public_site_migration_test"
PREVIOUS = "0021_stage_three_query_indexes"
HEAD = "0022_public_site"
TABLES = (
    "saved_collections",
    "saved_collection_items",
    "shared_selections",
    "website_conversations",
    "website_messages",
    "channel_handoffs",
    "public_analytics_events",
)


@pytest.fixture
def at_previous():
    with database_at_revision(MIGRATION_DATABASE, PREVIOUS) as harness:
        yield harness


def scalar(engine, statement: str):  # noqa: ANN001, ANN201
    with engine.begin() as connection:
        return connection.execute(text(statement)).scalar()


def test_upgrade_creates_every_public_authority_table(at_previous) -> None:
    from alembic import command

    config, engine = at_previous
    command.upgrade(config, HEAD)

    assert scalar(engine, "SELECT version_num FROM alembic_version") == HEAD
    for table in TABLES:
        assert scalar(engine, f"SELECT to_regclass('public.{table}')") == table
        assert scalar(engine, f"SELECT count(*) FROM {table}") == 0


def test_downgrade_and_reupgrade_are_reversible(at_previous) -> None:
    from alembic import command

    config, engine = at_previous
    command.upgrade(config, HEAD)
    command.downgrade(config, PREVIOUS)
    for table in TABLES:
        assert scalar(engine, f"SELECT to_regclass('public.{table}')") is None

    command.upgrade(config, HEAD)
    assert scalar(engine, "SELECT version_num FROM alembic_version") == HEAD
    assert all(
        scalar(engine, f"SELECT to_regclass('public.{table}')") == table
        for table in TABLES
    )
