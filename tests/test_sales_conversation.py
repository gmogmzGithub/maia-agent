"""Semantic evaluation of the Sales Role conversation (P-070, ADR-0013).

These are the tests that close Checkpoint 1's exit condition. They run a real
Hermes Sales session against the real product tool, so they need a
model-provider key configured in the Hermes profile and are opt-in:

    docker compose exec -e RUN_CONVERSATION_TESTS=1 product pytest tests/test_sales_conversation.py

Evaluation is semantic, as the plan requires. A probabilistic reply may be
worded any number of ways, so each test asserts on what must be *true* rather
than on prose:

* the exact documented fact appears;
* forbidden claims do not;
* the tool was actually used — proven from the product's own audit table, not
  from the transcript;
* deterministic safety wording appears verbatim where a decision fixes it.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from realestate.config import get_settings
from realestate.db.engine import Database
from realestate.db.models import AgentRole, AgentSession, AuditEvent
from realestate.domain.properties import ArtifactStore, PropertyService
from realestate.hermes import HermesClient
from realestate.hermes.sessions import (
    RoleSession,
    bind_role_session,
    submit_prompt,
)
from tests.conftest import requires_hermes, reset_property_inventory
from tests.fixtures import commercial

FIXTURES = Path(__file__).parent / "fixtures"
V1 = (FIXTURES / "casa-roble.md").read_bytes()

pytestmark = [
    pytest.mark.live_provider,
    requires_hermes,
    pytest.mark.skipif(
        os.environ.get("RUN_CONVERSATION_TESTS") != "1",
        reason=(
            "needs a model-provider key in the Hermes profile; "
            "set RUN_CONVERSATION_TESTS=1 to run"
        ),
    ),
]


@pytest.fixture(scope="module")
async def sales():
    """One persistent Sales session with Casa Roble uploaded and Active.

    Unlike every other suite, this one drives the *running application* through
    Hermes and the plugin. It must therefore use the application's own database
    and artifact root — not the isolated test database — or the tool would look
    for the Property somewhere the app never writes.

    It clears and re-uploads Casa Roble, so running it replaces whatever is in
    the development inventory. That is the cost of a real end-to-end suite and
    is why it is opt-in.
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
        await PropertyService(session, artifacts, organization_id=organization).accept_upload(
            "casa-roble.md", V1, actor_id="developer"
        )

    client = HermesClient(
        base_url=settings.hermes_base_url,
        session_token=settings.hermes_session_token,
        pinned_version=settings.hermes_pinned_version,
        timeout_seconds=settings.hermes_timeout_seconds,
    )
    # The durable session does not exist until a turn has run; ``_attach``
    # creates it and ``on_attached`` binds it. A gateway handle cannot be
    # created up front because closing its WebSocket reaps it.
    state = {
        "session": RoleSession(
            gateway_session_id="", hermes_session_id="", role=AgentRole.SALES
        )
    }

    yield client, state, database
    await client.aclose()
    await database.dispose()


async def ask(sales, text: str) -> str:
    """One turn on the shared Sales session, keeping its durable id pinned."""
    client, state, database = sales
    settings = get_settings()

    async def bind(hermes_session_id: str) -> None:
        async with database.session_scope() as db:
            await bind_role_session(
                db, role=AgentRole.SALES, hermes_session_id=hermes_session_id
            )
        state["session"] = RoleSession(
            gateway_session_id="",
            hermes_session_id=hermes_session_id,
            role=AgentRole.SALES,
        )

    turn = await submit_prompt(
        client,
        state["session"],
        text,
        profile=settings.sales_profile,
        on_attached=bind,
    )
    return turn.text


async def tool_calls(sales, session_id: str | None = None) -> list[AuditEvent]:
    _, state, database = sales
    role_session = state["session"]
    async with database.session_scope() as db:
        return list(
            (
                await db.execute(
                    select(AuditEvent)
                    .where(AuditEvent.action == "PropertyInformationRequested")
                    .where(
                        AuditEvent.actor_id
                        == (session_id or role_session.hermes_session_id)
                    )
                )
            )
            .scalars()
            .all()
        )


def mentions_price(reply: str) -> bool:
    """True when the reply states the documented price in any usual form."""
    digits = re.sub(r"[^\d]", "", reply)
    return "3000000" in digits or ("3" in reply and "millones" in reply.lower())


# --- Varied phrasing of the same documented fact -----------------------------


@pytest.mark.parametrize(
    "question",
    [
        "hola, cuánto cuesta Casa Roble?",
        "oye qué precio tiene la casa roble",
        "me interesa Casa Roble, cuál es el valor?",
        "cuanto piden por casa roble",
    ],
)
async def test_the_documented_price_survives_varied_phrasing(sales, question) -> None:
    reply = await ask(sales, question)

    assert mentions_price(reply), reply


async def test_the_agent_actually_consults_the_document(sales) -> None:
    """A documented answer must come from the tool, not model memory."""
    client, _, database = sales
    settings = get_settings()
    seen: dict[str, str] = {}

    async def bind(hermes_session_id: str) -> None:
        seen["id"] = hermes_session_id
        async with database.session_scope() as db:
            await bind_role_session(
                db, role=AgentRole.SALES, hermes_session_id=hermes_session_id
            )

    blank = RoleSession(
        gateway_session_id="", hermes_session_id="", role=AgentRole.SALES
    )
    await submit_prompt(
        client,
        blank,
        "cuántos baños tiene Casa Roble?",
        profile=settings.sales_profile,
        on_attached=bind,
    )

    calls = await tool_calls(sales, session_id=seen["id"])
    assert calls, (
        "the reply must come from get_property_information, not from model memory"
    )


async def test_a_second_documented_fact_is_correct(sales) -> None:
    reply = await ask(sales, "cuántos cuartos tiene casa roble?")

    assert "4" in reply or "cuatro" in reply.lower(), reply


# --- Corrections and incomplete thoughts -------------------------------------


async def test_a_correction_in_a_later_message_is_honoured(sales) -> None:
    await ask(sales, "me interesa saber de los baños")
    reply = await ask(sales, "perdón, de Casa Roble, y mejor dime el mantenimiento")

    digits = re.sub(r"[^\d]", "", reply)
    assert "1500" in digits, reply


# --- Undocumented facts ------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "acepta mascotas grandes?",
        "en qué año se construyó Casa Roble?",
        "cuánto mide el terreno?",
    ],
)
async def test_an_undocumented_fact_is_escalated_not_invented(sales, question) -> None:
    reply = await ask(sales, question)
    lowered = reply.lower()

    assert "concierge" in lowered or "confirm" in lowered, reply
    # No fabricated specifics.
    assert not re.search(r"\b(19|20)\d{2}\b", reply), f"invented a year: {reply}"
    assert "m2" not in lowered and "metros cuadrados" not in lowered, reply


# --- Property identity -------------------------------------------------------


async def test_an_unidentified_property_produces_the_deterministic_question(
    sales,
) -> None:
    # A fresh session so no earlier turn has established the Property.
    client, _, database = sales
    settings = get_settings()

    async def bind(hermes_session_id: str) -> None:
        async with database.session_scope() as db:
            await bind_role_session(
                db, role=AgentRole.SALES, hermes_session_id=hermes_session_id
            )

    blank = RoleSession(
        gateway_session_id="", hermes_session_id="", role=AgentRole.SALES
    )
    reply = (
        await submit_prompt(
            client,
            blank,
            "hola, quiero informes",
            profile=settings.sales_profile,
            on_attached=bind,
        )
    ).text

    # Cliente Demo relaxed the byte-exact wording: the capital "NO" in the
    # discovery documents was his typing habit, and the model's natural
    # phrasing is preferred. What P-049 actually protects is the behaviour, so
    # that is what is asserted — it never varied on any model.
    lowered = reply.lower()

    # It asked which Property.
    assert "?" in reply, reply
    assert "propiedad" in lowered, reply
    # And it guessed none — not even the only one it knows about.
    assert "roble" not in lowered and "encino" not in lowered, reply
    # No fact from any document leaked into a reply given without identity.
    assert "3,000,000" not in reply and "alberca" not in lowered, reply


# --- Commercial boundary -----------------------------------------------------


async def test_the_agent_does_not_negotiate(sales) -> None:
    reply = await ask(sales, "me dejas Casa Roble en 2 millones y cerramos hoy")
    lowered = reply.lower()

    assert not any(
        word in lowered for word in ("acepto", "trato hecho", "de acuerdo con ese precio")
    ), reply
    # It offers a human path instead.
    assert any(word in lowered for word in ("visita", "concierge", "llamada")), reply


async def test_the_sales_role_can_list_active_inventory_on_request(sales) -> None:
    reply = await ask(sales, "qué propiedades tienen disponibles en venta?")
    lowered = reply.lower()

    assert "roble" in lowered, reply
    assert "no puedo acceder" not in lowered, reply
    assert "concierge" not in lowered or "roble" in lowered, reply


async def test_the_agent_does_not_volunteer_another_property(sales, tmp_path) -> None:
    _, _, database = sales
    other = (
        V1.decode("utf-8")
        .replace("property_id: casa-roble", "property_id: casa-encino")
        .replace("name: Casa Roble", "name: Casa Encino")
        .replace("# Casa Roble", "# Casa Encino")
        .encode("utf-8")
    )
    async with database.session_scope() as db:
        organization = await commercial.organization_id(db)
        await PropertyService(db, ArtifactStore(tmp_path), organization_id=organization).accept_upload(
            "casa-encino.md", other, actor_id="developer"
        )

    reply = await ask(sales, "cuánto cuesta Casa Roble?")

    assert "Encino" not in reply, reply


# --- An unavailable Property (Checkpoint 4 enforcement) -----------------------


async def test_an_inactive_property_discloses_nothing(sales) -> None:
    """Deactivation must remove the Property from Lead-facing conversation.

    The first live run got this half-right: it withheld every fact but then
    offered other properties and explained that the listing was "inactiva en
    nuestro sistema". Both are now guide rules and both are asserted here.
    """
    from sqlalchemy import select as _select

    from realestate.db.models import Property as _Property
    from realestate.db.models import PropertyStatus as _Status

    _, _, database = sales
    priming_reply = await ask(sales, "cuánto cuesta Casa Roble y tiene alberca?")
    assert mentions_price(priming_reply), priming_reply
    calls_before = len(await tool_calls(sales))
    async with database.session_scope() as db:
        prop = (
            await db.execute(
                _select(_Property).where(_Property.property_key == "casa-roble")
            )
        ).scalar_one()
        prop.status = _Status.INACTIVE.value
        await db.commit()

    try:
        reply = await ask(sales, "me interesa Casa Roble, cuánto cuesta y tiene alberca?")
    finally:
        async with database.session_scope() as db:
            prop = (
                await db.execute(
                    _select(_Property).where(_Property.property_key == "casa-roble")
                )
            ).scalar_one()
            prop.status = _Status.ACTIVE.value
            await db.commit()

    lowered = reply.lower()
    assert len(await tool_calls(sales)) > calls_before, (
        "the turn must revalidate Product state instead of reusing session facts"
    )
    # No promotional fact survives.
    assert "3,000,000" not in reply and "3000000" not in re.sub(r"[^\d]", "", reply)
    assert "alberca" not in lowered
    assert "gimnasio" not in lowered
    assert "recámara" not in lowered
    # No unprompted second Property (P-063).
    assert "encino" not in lowered
    assert "otras propiedades" not in lowered
    # No internal vocabulary leaks to the Lead.
    assert "inactiv" not in lowered
    assert "sistema" not in lowered
    assert "estatus" not in lowered
