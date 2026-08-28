"""The Stage 3 query indexes reach databases that were already at Stage 4."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.conftest import database_at_revision, requires_postgres

pytestmark = requires_postgres

MIGRATION_DATABASE = "realestate_stage_three_index_migration_test"
PREVIOUS_HEAD = "0020_authoritative_catalog"
HEAD = "0021_stage_three_query_indexes"
INDEXES = (
    "ix_advisor_absences_org",
    "ix_internal_alerts_open",
    "ix_appointments_calendar",
)


@pytest.fixture
def at_previous_head():
    with database_at_revision(MIGRATION_DATABASE, PREVIOUS_HEAD) as harness:
        yield harness


def _index_exists(engine, name: str) -> bool:  # noqa: ANN001
    with engine.begin() as connection:
        return bool(
            connection.execute(
                text("SELECT to_regclass(:name) IS NOT NULL"),
                {"name": f"public.{name}"},
            ).scalar_one()
        )


def test_an_existing_stage_four_database_receives_and_can_remove_the_indexes(
    at_previous_head,
) -> None:
    from alembic import command

    config, engine = at_previous_head
    assert not any(_index_exists(engine, name) for name in INDEXES)

    command.upgrade(config, HEAD)
    assert all(_index_exists(engine, name) for name in INDEXES)

    command.downgrade(config, PREVIOUS_HEAD)
    assert not any(_index_exists(engine, name) for name in INDEXES)

    command.upgrade(config, HEAD)
    assert all(_index_exists(engine, name) for name in INDEXES)
