"""The Role binding table: where product authority actually comes from (TC-008).

The plugin forwards a Hermes-supplied ``session_id`` and nothing else. Whether
that session may deactivate a Property, or read an Inactive one, is decided by
the row written here. Two properties matter and neither is visible from a
conversation:

* a binding is an **upsert**, keyed on the cycle or the channel. A reaped
  gateway handle causes a re-attach on almost every turn, so a second row per
  turn would accumulate — and ``hermes_session_id`` is unique, so the second
  write would fail outright.
* a cycle with no session yet resolves to an *empty* durable id rather than to
  nothing. Hermes persists its session row lazily, on the first prompt, so the
  first turn of every cycle takes that path.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from realestate.db.engine import Database
from realestate.db.models import (
    AgentRole,
    AgentSession,
    Conversation,
    Lead,
    LeadEngagementCycle,
)
from realestate.hermes.sessions import (
    bind_channel_session,
    bind_cycle_session,
    bind_role_session,
    bind_session,
    find_role_session,
    session_for_cycle,
)
from tests.conftest import (
    DATABASE_URL,
    larevia_organization_id,
    requires_postgres,
)

pytestmark = requires_postgres


@pytest.fixture
async def database():
    db = Database(DATABASE_URL)
    async with db.session_scope() as session:
        await session.execute(delete(AgentSession))
        await session.execute(delete(Conversation))
        await session.execute(delete(LeadEngagementCycle))
        await session.execute(delete(Lead))
        await session.commit()
    yield db
    await db.dispose()


async def a_cycle(database) -> uuid.UUID:
    async with database.session_scope() as session:
        lead = Lead(
            organization_id=await larevia_organization_id(session),
            wa_id=f"5215550{uuid.uuid4().int % 100000:05d}",
        )
        session.add(lead)
        await session.flush()
        cycle = LeadEngagementCycle(
            lead_id=lead.id, expires_at=datetime.now(tz=UTC) + timedelta(days=30)
        )
        session.add(cycle)
        await session.commit()
        return cycle.id


async def bindings(database) -> list[AgentSession]:
    async with database.session_scope() as session:
        return list((await session.execute(select(AgentSession))).scalars())


# -- Reading a cycle's binding ------------------------------------------------


async def test_a_cycle_with_no_session_yet_resolves_to_an_empty_durable_id(
    database,
) -> None:
    """The first turn of every cycle takes this path; ``_attach`` fills it in."""
    cycle_id = await a_cycle(database)

    async with database.session_scope() as session:
        found = await session_for_cycle(session, cycle_id)

    assert found.hermes_session_id == ""
    assert found.role is AgentRole.SALES
    # No Hermes call happens here: a session created on a throwaway connection
    # would only be reaped with it.
    assert await bindings(database) == []


async def test_a_bound_cycle_resolves_to_its_durable_session(database) -> None:
    cycle_id = await a_cycle(database)
    async with database.session_scope() as session:
        await bind_cycle_session(session, cycle_id=cycle_id, hermes_session_id="durable-1")

    async with database.session_scope() as session:
        found = await session_for_cycle(session, cycle_id)

    assert found.hermes_session_id == "durable-1"
    assert found.role is AgentRole.SALES


# -- Upserting -----------------------------------------------------------------


async def test_re_binding_a_cycle_repoints_the_row_rather_than_adding_one(
    database,
) -> None:
    """A reaped handle re-attaches on nearly every turn; rows must not pile up."""
    cycle_id = await a_cycle(database)

    async with database.session_scope() as session:
        await bind_cycle_session(session, cycle_id=cycle_id, hermes_session_id="durable-1")
        await bind_cycle_session(session, cycle_id=cycle_id, hermes_session_id="durable-2")

    rows = await bindings(database)
    assert len(rows) == 1
    assert rows[0].hermes_session_id == "durable-2"


async def test_re_binding_a_channel_repoints_the_row_rather_than_adding_one(
    database,
) -> None:
    async with database.session_scope() as session:
        await bind_channel_session(
            session,
            role=AgentRole.ADMINISTRATIVE,
            channel_key="telegram:12345",
            hermes_session_id="durable-a",
        )
        await bind_channel_session(
            session,
            role=AgentRole.ADMINISTRATIVE,
            channel_key="telegram:12345",
            hermes_session_id="durable-b",
        )

    rows = await bindings(database)
    assert len(rows) == 1
    assert (rows[0].hermes_session_id, rows[0].channel_key) == (
        "durable-b",
        "telegram:12345",
    )


async def test_a_channel_binding_carries_the_administrative_role(database) -> None:
    async with database.session_scope() as session:
        await bind_channel_session(
            session,
            role=AgentRole.ADMINISTRATIVE,
            channel_key="telegram:12345",
            hermes_session_id="durable-a",
        )

    assert (await bindings(database))[0].role == AgentRole.ADMINISTRATIVE.value


async def test_two_administrators_get_two_separate_sessions(database) -> None:
    """Each Telegram chat has its own Administrative session (ADR-0001)."""
    async with database.session_scope() as session:
        for chat, durable in (("telegram:1", "durable-1"), ("telegram:2", "durable-2")):
            await bind_channel_session(
                session,
                role=AgentRole.ADMINISTRATIVE,
                channel_key=chat,
                hermes_session_id=durable,
            )

    assert len(await bindings(database)) == 2


@pytest.mark.parametrize(
    ("cycle_id", "channel_key"),
    [(None, None), (uuid.uuid4(), "telegram:1")],
)
async def test_a_binding_needs_exactly_one_key(
    database, cycle_id: uuid.UUID | None, channel_key: str | None
) -> None:
    """Neither key means nothing is identified; both means two things are."""
    async with database.session_scope() as session:
        with pytest.raises(ValueError, match="exactly one of cycle_id or channel_key"):
            await bind_session(
                session,
                role=AgentRole.SALES,
                hermes_session_id="durable-1",
                cycle_id=cycle_id,
                channel_key=channel_key,
            )


# -- Finding the most recent session for a Role -------------------------------


async def test_no_session_for_a_role_is_none_not_an_error(database) -> None:
    async with database.session_scope() as session:
        assert await find_role_session(session, AgentRole.ADMINISTRATIVE) is None


async def test_the_most_recently_created_session_for_a_role_wins(database) -> None:
    """The local exercise scripts reattach to the newest session, not the first."""
    async with database.session_scope() as session:
        session.add(
            AgentSession(
                hermes_session_id="older",
                role=AgentRole.SALES.value,
                created_at=datetime.now(tz=UTC) - timedelta(hours=1),
            )
        )
        session.add(
            AgentSession(
                hermes_session_id="newer",
                role=AgentRole.SALES.value,
                created_at=datetime.now(tz=UTC),
            )
        )
        await session.commit()

    async with database.session_scope() as session:
        found = await find_role_session(session, AgentRole.SALES)

    assert found is not None
    assert found.hermes_session_id == "newer"


async def test_a_role_lookup_never_returns_another_roles_session(database) -> None:
    async with database.session_scope() as session:
        session.add(
            AgentSession(hermes_session_id="sales-1", role=AgentRole.SALES.value)
        )
        await session.commit()

    async with database.session_scope() as session:
        assert await find_role_session(session, AgentRole.ADMINISTRATIVE) is None


async def test_an_absent_gateway_handle_reads_as_empty_not_none(database) -> None:
    # The handle is per-connection and normally unset on a stored row; callers
    # treat "" as "attach fresh", and None would break that comparison.
    async with database.session_scope() as session:
        session.add(
            AgentSession(hermes_session_id="sales-1", role=AgentRole.SALES.value)
        )
        await session.commit()

    async with database.session_scope() as session:
        found = await find_role_session(session, AgentRole.SALES)

    assert found is not None
    assert found.gateway_session_id == ""


# -- The cycle-less binding used by the local scripts -------------------------


async def test_a_cycle_less_role_session_is_recorded_once(database) -> None:
    async with database.session_scope() as session:
        await bind_role_session(
            session, role=AgentRole.SALES, hermes_session_id="durable-1"
        )
        # Idempotent: the exercise script binds on every turn, and
        # ``hermes_session_id`` is unique, so a second insert would fail.
        await bind_role_session(
            session, role=AgentRole.SALES, hermes_session_id="durable-1"
        )

    rows = await bindings(database)
    assert [row.hermes_session_id for row in rows] == ["durable-1"]
    assert rows[0].cycle_id is None and rows[0].channel_key is None
