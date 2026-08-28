"""The PostgreSQL engine wrapper (ADR-0006).

Two behaviours here are load-bearing and neither is exercised by a successful
query:

* ``session_scope`` rolls back on the way out. Without it a failed unit of work
  leaves its partial writes visible to the next statement on the same
  connection, and the Inbox's "persist, then acknowledge" ordering stops meaning
  anything.
* ``check_health`` reports rather than raises. It is gathered with the other
  probes on /health, and an escape would take the whole endpoint down —
  including the part that would have told the operator PostgreSQL was the
  problem.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from realestate.db.engine import Database, DatabaseHealth
from realestate.db.models import Lead
from tests.conftest import (
    DATABASE_URL,
    larevia_organization_id,
    requires_postgres,
)


def test_the_health_report_serialises_for_the_health_endpoint() -> None:
    assert DatabaseHealth(ok=True, detail="reachable").as_dict() == {
        "status": "ok",
        "detail": "reachable",
    }
    assert DatabaseHealth(ok=False, detail="down").as_dict() == {
        "status": "unavailable",
        "detail": "down",
    }


async def test_an_unreachable_database_is_reported_not_raised() -> None:
    """Port 9 (discard) is reserved and never speaks the PostgreSQL protocol."""
    database = Database(
        "postgresql+psycopg://realestate:realestate@127.0.0.1:9/realestate"
    )
    try:
        health = await database.check_health()
    finally:
        await database.dispose()

    assert not health.ok
    assert "docker compose up -d db" in health.detail


async def test_a_driver_or_environment_fault_is_reported_not_raised() -> None:
    """A missing greenlet or a bad DSN must reach /health, not crash startup.

    ``SQLAlchemyError`` already has its own branch; this is the one for faults
    that are not SQLAlchemy's at all, which is exactly the class of problem an
    operator has no other way to see.
    """

    class BrokenEngine:
        def connect(self):  # noqa: ANN202
            raise RuntimeError("greenlet_spawn has not been called")

    database = Database(DATABASE_URL)
    database._engine = BrokenEngine()  # type: ignore[assignment]

    health = await database.check_health()

    assert not health.ok
    assert "RuntimeError" in health.detail
    assert "greenlet_spawn" in health.detail


@requires_postgres
async def test_a_reachable_database_is_healthy() -> None:
    database = Database(DATABASE_URL)
    try:
        health = await database.check_health()
    finally:
        await database.dispose()

    assert health.ok
    assert health.detail == "PostgreSQL reachable"


@requires_postgres
async def test_the_engine_is_exposed_for_migrations_and_health() -> None:
    database = Database(DATABASE_URL)
    try:
        async with database.engine.connect() as connection:
            assert (await connection.execute(text("SELECT 1"))).scalar_one() == 1
    finally:
        await database.dispose()


@requires_postgres
async def test_a_failed_unit_of_work_is_rolled_back_on_the_way_out() -> None:
    """The caller commits; an exception must leave nothing behind."""
    database = Database(DATABASE_URL)
    wa_id = "5215559999001"
    try:
        with pytest.raises(RuntimeError, match="halfway"):
            async with database.session_scope() as session:
                session.add(
                    Lead(
                        organization_id=await larevia_organization_id(session),
                        wa_id=wa_id,
                    )
                )
                await session.flush()
                raise RuntimeError("halfway through the unit of work")

        async with database.session_scope() as session:
            found = (
                await session.execute(select(Lead).where(Lead.wa_id == wa_id))
            ).scalar_one_or_none()
        assert found is None
    finally:
        async with database.session_scope() as session:
            await session.execute(
                text("DELETE FROM leads WHERE wa_id = :wa_id"), {"wa_id": wa_id}
            )
            await session.commit()
        await database.dispose()


@requires_postgres
async def test_an_uncommitted_unit_of_work_persists_nothing_either() -> None:
    database = Database(DATABASE_URL)
    wa_id = "5215559999002"
    try:
        async with database.session_scope() as session:
            session.add(
                Lead(
                    organization_id=await larevia_organization_id(session),
                    wa_id=wa_id,
                )
            )
            await session.flush()

        async with database.session_scope() as session:
            found = (
                await session.execute(select(Lead).where(Lead.wa_id == wa_id))
            ).scalar_one_or_none()
        assert found is None
    finally:
        await database.dispose()
