"""Semantic evaluation of the Administrative Role (Checkpoint 4, P-016, P-065).

Closes Checkpoint 4's exit condition. Opt-in, like the Sales suite:

    RUN_CONVERSATION_TESTS=1 pytest tests/integration/test_admin_conversation.py

The two properties under test are the ones a wrong answer makes expensive: an
unambiguous instruction must execute and be audited, and an ambiguous one must
*not* mutate anything.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from realestate.config import get_settings
from realestate.db.engine import Database
from realestate.db.models import (
    AgentRole,
    AgentSession,
    AuditEvent,
    Property,
    PropertyStatus,
)
from realestate.domain.properties import ArtifactStore, PropertyService
from realestate.hermes import HermesClient
from realestate.hermes.sessions import RoleSession, submit_prompt
from tests.conftest import requires_hermes, reset_property_inventory
from tests.fixtures import commercial

FIXTURES = Path(__file__).parents[1] / "fixtures"
V1 = (FIXTURES / "casa-roble.md").read_bytes()

pytestmark = [
    pytest.mark.live_provider,
    requires_hermes,
    pytest.mark.skipif(
        os.environ.get("RUN_CONVERSATION_TESTS") != "1",
        reason="needs a model-provider key; set RUN_CONVERSATION_TESTS=1 to run",
    ),
]

CHANNEL_KEY = "test:admin-eval"


def second_property() -> bytes:
    return (
        V1.decode("utf-8")
        .replace("property_id: casa-roble", "property_id: casa-encino")
        .replace("name: Casa Roble", "name: Casa Encino")
        .replace("# Casa Roble", "# Casa Encino")
        .encode("utf-8")
    )


@pytest.fixture
async def admin():
    """A fresh Administrative session over a two-Property inventory.

    Function-scoped: each test needs a session with no prior context, which is
    the whole point of the ambiguity case.
    """
    get_settings.cache_clear()
    settings = get_settings()
    database = Database(settings.database_url)
    artifacts = ArtifactStore(Path(settings.artifact_root))

    async with database.session_scope() as session:
        await reset_property_inventory(session)
        await session.execute(delete(AuditEvent))
        await session.execute(delete(AgentSession))
        await session.commit()
    async with database.session_scope() as session:
        organization = await commercial.organization_id(session)
        service = PropertyService(session, artifacts, organization_id=organization)
        await service.accept_upload("casa-roble.md", V1, actor_id="developer")
        await service.accept_upload(
            "casa-encino.md", second_property(), actor_id="developer"
        )

    client = HermesClient(
        base_url=settings.hermes_base_url,
        session_token=settings.hermes_session_token,
        pinned_version=settings.hermes_pinned_version,
        timeout_seconds=settings.hermes_timeout_seconds,
    )

    async def ask(text: str) -> str:
        async with database.session_scope() as db:
            binding = (
                await db.execute(
                    select(AgentSession).where(AgentSession.channel_key == CHANNEL_KEY)
                )
            ).scalar_one_or_none()
            session = RoleSession(
                gateway_session_id="",
                hermes_session_id=binding.hermes_session_id if binding else "",
                role=AgentRole.ADMINISTRATIVE,
            )

        async def bind(hermes_session_id: str) -> None:
            async with database.session_scope() as db:
                row = (
                    await db.execute(
                        select(AgentSession).where(
                            AgentSession.channel_key == CHANNEL_KEY
                        )
                    )
                ).scalar_one_or_none()
                if row is None:
                    db.add(
                        AgentSession(
                            organization_id=await commercial.organization_id(db),
                            hermes_session_id=hermes_session_id,
                            role=AgentRole.ADMINISTRATIVE.value,
                            channel_key=CHANNEL_KEY,
                        )
                    )
                else:
                    row.hermes_session_id = hermes_session_id
                await db.commit()

        turn = await submit_prompt(
            client, session, text, profile=settings.admin_profile, on_attached=bind
        )
        return turn.text

    yield ask, database
    await client.aclose()
    await database.dispose()


async def status_of(database, key: str) -> str:
    async with database.session_scope() as session:
        prop = (
            await session.execute(select(Property).where(Property.property_key == key))
        ).scalar_one()
        return prop.status


async def transitions(database) -> list[AuditEvent]:
    async with database.session_scope() as session:
        return list(
            (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.action == "PropertyStatusChanged"
                    )
                )
            )
            .scalars()
            .all()
        )


# --- An unambiguous instruction executes -------------------------------------


@pytest.mark.parametrize(
    "instruction",
    [
        "Casa Roble se vendió",
        "Casa Roble se rentó",
        "retira Casa Roble del inventario",
    ],
)
async def test_a_clear_inactivation_executes_immediately(admin, instruction) -> None:
    ask, database = admin

    await ask(instruction)

    assert await status_of(database, "casa-roble") == PropertyStatus.INACTIVE.value
    # The other Property is untouched.
    assert await status_of(database, "casa-encino") == PropertyStatus.ACTIVE.value


async def test_the_transition_is_audited_with_the_trusted_actor(admin) -> None:
    ask, database = admin

    await ask("Casa Roble se vendió")

    events = await transitions(database)
    assert len(events) == 1
    assert events[0].actor_type == "Administrative"
    assert events[0].actor_id == CHANNEL_KEY
    assert events[0].subject_id == "casa-roble"
    assert events[0].details["previous_status"] == "Active"
    assert events[0].details["requested_status"] == "Inactive"


async def test_reactivation_also_works(admin) -> None:
    ask, database = admin
    await ask("Casa Roble se vendió")

    await ask("ok, actívala de nuevo")

    assert await status_of(database, "casa-roble") == PropertyStatus.ACTIVE.value


async def test_repeating_the_current_status_is_reported_as_no_change(admin) -> None:
    ask, database = admin

    reply = await ask("pon Casa Encino como activa")

    lowered = reply.lower()
    assert any(word in lowered for word in ("ya", "sin cambio", "no hubo", "sigue"))
    assert await transitions(database) == []


async def test_an_inactivation_without_a_reason_asks_before_mutating(admin) -> None:
    ask, database = admin

    reply = await ask("desactiva Casa Roble")

    assert "?" in reply, reply
    assert await status_of(database, "casa-roble") == PropertyStatus.ACTIVE.value
    assert await transitions(database) == []


# --- An ambiguous instruction must not mutate ---------------------------------


@pytest.mark.parametrize(
    "instruction",
    ["actívala", "desactiva esa", "cámbiale el estatus a Casa Roble"],
)
async def test_an_ambiguous_instruction_asks_rather_than_guessing(
    admin, instruction
) -> None:
    ask, database = admin

    reply = await ask(instruction)

    # Nothing changed anywhere.
    assert await status_of(database, "casa-roble") == PropertyStatus.ACTIVE.value
    assert await status_of(database, "casa-encino") == PropertyStatus.ACTIVE.value
    assert await transitions(database) == []
    # And it asked.
    assert "?" in reply, reply


async def test_an_unknown_property_is_reported_not_invented(admin) -> None:
    ask, database = admin

    reply = await ask("desactiva Casa Galeno")

    # The behaviour, not the phrasing: nothing changed and no success claimed.
    assert await transitions(database) == []
    lowered = reply.lower()
    assert not any(
        word in lowered for word in ("desactivada", "desactivé", "listo,", "cambió")
    ), reply


# --- The inventory ------------------------------------------------------------


async def test_the_inventory_can_be_listed(admin) -> None:
    ask, _ = admin

    reply = await ask("qué propiedades tenemos?")

    assert "Roble" in reply
    assert "Encino" in reply
