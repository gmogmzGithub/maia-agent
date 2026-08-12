"""PostgreSQL is the product system of record from Stage 0 (ADR-0006).

Checkpoint 0 defines no business tables, so what is proven here is the
foundation: the configured database is real PostgreSQL, the application can
reach it, and the migration history is applied.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from realestate.db.engine import Database
from tests.conftest import DATABASE_URL, requires_postgres


@requires_postgres
async def test_the_application_can_reach_postgresql() -> None:
    database = Database(DATABASE_URL)
    try:
        health = await database.check_health()
    finally:
        await database.dispose()

    assert health.ok, health.detail


@requires_postgres
async def test_the_backing_store_is_postgresql_not_sqlite() -> None:
    database = Database(DATABASE_URL)
    try:
        async with database.engine.connect() as connection:
            version = (await connection.execute(text("SELECT version()"))).scalar_one()
    finally:
        await database.dispose()

    assert "PostgreSQL" in version


@requires_postgres
async def test_the_database_is_migrated_to_head() -> None:
    """The applied revision must be the newest one in migrations/versions.

    Asserting against the directory rather than a literal keeps this true as
    later checkpoints add revisions, while still failing loudly if someone runs
    the suite against a stale database.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    expected = ScriptDirectory.from_config(config).get_current_head()

    database = Database(DATABASE_URL)
    try:
        async with database.engine.connect() as connection:
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
    finally:
        await database.dispose()

    assert revision == expected
