"""The Stage 3 operator surfaces: Spanish, honest, and scoped by role.

What these assertions defend is the operator's ability to tell four things apart
at a glance, because each confusion is a way the operation loses a customer: who
is answering, who is responsible versus who specialises, which visit is actually
Confirmed, and what has been waiting for a human and for how long.

They also defend two things that are easy to break later. Every action is a form
submission with a render-time idempotency key, so no surface needs JavaScript and
a double click replays instead of repeating. And no control claims success before
an authoritative confirmation: the reschedule screen offers only starts the
Advisor's own calendar returned a moment ago.
"""

from __future__ import annotations

import re
import uuid
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, BasicAuth
from sqlalchemy import select

from realestate.app import create_app
from realestate.config import get_settings
from realestate.db.engine import Database
from realestate.db.models import (
    AdvisorAbsence,
    AppointmentAttendance,
    HandlingMode,
    OrganizationMember,
    PropertyExpert,
)
from realestate.domain.commercial.handling import ConversationHandling
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures import commercial, visits

pytestmark = requires_postgres

ADMIN = BasicAuth(commercial.ADMIN_LOGIN, commercial.ADMIN_PASSWORD)
ADVISOR = BasicAuth(commercial.ADVISOR_LOGIN, commercial.ADVISOR_PASSWORD)
OTHER = BasicAuth(
    commercial.SECOND_ADVISOR_LOGIN, commercial.SECOND_ADVISOR_PASSWORD
)

STAGE_THREE_PATHS = (
    "/crm/equipo",
    "/crm/equipo/ausencias",
    "/crm/equipo/especialistas",
    "/crm/agenda",
    "/crm/alertas",
)

# Internal vocabulary that must never reach an operator's screen.
FORBIDDEN_WORDS = (
    r"\bproperty expert\b",
    r"\blead\b",
    r"\blisting\b",
    r"\bhandoff\b",
    r"\bhandling mode\b",
    r"\bappointment\b",
    r"\badvisor\b",
    r"\bbroker\b",
)

_TAGS = re.compile(r"<[^>]+>")
_DROPPED = re.compile(r"<(style|script)\b.*?</\1>", re.DOTALL | re.IGNORECASE)


def visible_text(html: str) -> str:
    return _TAGS.sub(" ", _DROPPED.sub(" ", html))


@pytest.fixture
async def wired(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("WORKER_ENABLED", "false")
    monkeypatch.setenv(
        "DEVELOPER_BASIC_CREDENTIALS_JSON", commercial.credentials_json()
    )
    get_settings.cache_clear()

    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await visits.reset(session)
        built = await visits.build(session, tmp_path / "artifacts")
        await session.commit()

    app = create_app(get_settings())
    app.state.database = database
    app.state.calendars = built.calendars
    app.state.appointment_policy = visits.policy()
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        yield client, database, built
    await database.dispose()
    get_settings.cache_clear()


def local_input(moment) -> str:  # noqa: ANN001
    """A ``datetime-local`` value the surface will read back as this instant.

    The field carries no offset, so Product reads it in the operation's zone.
    Formatting a UTC instant directly would land six hours out and turn a past
    absence into a future one.
    """
    from realestate.api.ui import OPERATION_TIMEZONE

    return moment.astimezone(OPERATION_TIMEZONE).strftime("%Y-%m-%dT%H:%M")


def _another_time(html: str, current) -> str:  # noqa: ANN001
    """An offered start that is not the one the visit already has.

    Compared as instants rather than as strings: the page renders the
    Organization's local offset while PostgreSQL returns UTC, so the same moment
    has two spellings and a string comparison would happily pick it.
    """
    from datetime import datetime

    for value in re.findall(r'<option value="([^"]+)"', html):
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            continue
        if moment != current:
            return value
    raise AssertionError("the reschedule form offered no alternative time")


def nonce(html: str) -> str:
    """One rendered idempotency key, as a form submission would carry it."""
    match = re.search(r'name="clave" value="([0-9a-f]+)"', html)
    assert match, "every mutating form must render an idempotency key"
    return match.group(1)


# -- Shell, language, accessibility ---------------------------------------


@pytest.mark.parametrize("path", STAGE_THREE_PATHS)
async def test_every_surface_requires_authentication(wired, path: str) -> None:
    client, _database, _built = wired
    response = await client.get(path)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Basic"


@pytest.mark.parametrize("path", STAGE_THREE_PATHS)
async def test_every_surface_ships_the_accessible_spanish_shell(
    wired, path: str
) -> None:
    client, _database, _built = wired
    response = await client.get(path, auth=ADMIN)

    assert response.status_code == 200
    assert 'lang="es-MX"' in response.text
    assert 'href="#contenido"' in response.text
    assert "<h1>" in response.text
    # No JavaScript is required for any action on any surface.
    assert "<script" not in response.text


@pytest.mark.parametrize("path", STAGE_THREE_PATHS)
async def test_no_internal_vocabulary_reaches_the_screen(wired, path: str) -> None:
    client, _database, built = wired
    response = await client.get(path, auth=ADMIN)
    text = visible_text(response.text).lower()
    for pattern in FORBIDDEN_WORDS:
        assert not re.search(pattern, text), (path, pattern)


# -- Team -----------------------------------------------------------------


async def test_the_team_surface_says_who_can_receive_work_and_why_not(
    wired,
) -> None:
    client, database, built = wired
    async with database.session_scope() as session:
        member = await session.get(OrganizationMember, built.second_advisor_id)
        assert member is not None
        member.calendar_id = None
        await session.commit()

    response = await client.get("/crm/equipo", auth=ADMIN)

    assert response.status_code == 200
    assert "Falta calendario" in response.text
    assert "Predeterminado" in response.text
    assert "no se pueden confirmar visitas" in response.text
    # The distinction the whole stage rests on, stated on the screen.
    assert "no lo vuelve responsable" in response.text


async def test_an_advisor_sees_the_team_without_the_forms(wired) -> None:
    client, _database, _built = wired
    admin = await client.get("/crm/equipo", auth=ADMIN)
    advisor = await client.get("/crm/equipo", auth=ADVISOR)

    assert advisor.status_code == 200
    assert "Dar de alta a una persona" in admin.text
    assert "Dar de alta a una persona" not in advisor.text
    # Visibility is not the thing being restricted.
    assert commercial.SECOND_ADVISOR_LOGIN in advisor.text


async def test_an_administrator_adds_an_advisor_from_the_surface(wired) -> None:
    client, database, _built = wired
    page = await client.get("/crm/equipo", auth=ADMIN)

    created = await client.post(
        "/crm/equipo/miembros",
        auth=ADMIN,
        data={
            "clave": nonce(page.text),
            "usuario": "nuevo@larevia.test",
            "nombre": "Asesor Nuevo",
            "rol": "RealEstateAdvisor",
            "asesora": "1",
            "calendario": "nuevo@larevia.test",
            "alertas": "9099",
        },
        follow_redirects=True,
    )

    assert created.status_code == 200
    assert "Se dio de alta a la persona." in created.text
    async with database.session_scope() as session:
        member = await session.scalar(
            select(OrganizationMember).where(
                OrganizationMember.login == "nuevo@larevia.test"
            )
        )
    assert member is not None
    assert member.calendar_id == "nuevo@larevia.test"


async def test_an_advisor_cannot_add_a_member(wired) -> None:
    client, database, _built = wired
    page = await client.get("/crm/equipo", auth=ADMIN)

    refused = await client.post(
        "/crm/equipo/miembros",
        auth=ADVISOR,
        data={
            "clave": nonce(page.text),
            "usuario": "colado@larevia.test",
            "nombre": "Colado",
            "rol": "RealEstateAdvisor",
        },
        follow_redirects=True,
    )

    assert "Sólo un administrador" in refused.text
    async with database.session_scope() as session:
        assert (
            await session.scalar(
                select(OrganizationMember).where(
                    OrganizationMember.login == "colado@larevia.test"
                )
            )
            is None
        )


async def test_a_double_submitted_alta_creates_one_member(wired) -> None:
    client, database, _built = wired
    page = await client.get("/crm/equipo", auth=ADMIN)
    payload = {
        "clave": nonce(page.text),
        "usuario": "doble@larevia.test",
        "nombre": "Doble Click",
        "rol": "RealEstateAdvisor",
        "asesora": "1",
    }

    await client.post("/crm/equipo/miembros", auth=ADMIN, data=payload)
    await client.post("/crm/equipo/miembros", auth=ADMIN, data=payload)

    async with database.session_scope() as session:
        rows = list(
            await session.scalars(
                select(OrganizationMember).where(
                    OrganizationMember.login == "doble@larevia.test"
                )
            )
        )
    assert len(rows) == 1


# -- Absences -------------------------------------------------------------


async def test_recording_an_absence_from_the_surface(wired) -> None:
    client, database, built = wired
    page = await client.get("/crm/equipo/ausencias", auth=ADMIN)
    assert "No reasigna sus oportunidades" in page.text

    starts = local_input(visits.now() + timedelta(days=1))
    ends = local_input(visits.now() + timedelta(days=3))
    saved = await client.post(
        "/crm/equipo/ausencias",
        auth=ADMIN,
        data={
            "clave": nonce(page.text),
            "asesor": built.advisor_id.hex,
            "inicio": starts,
            "fin": ends,
            "motivo": "Vacaciones",
        },
        follow_redirects=True,
    )

    assert "Se registró la ausencia." in saved.text
    assert "Programada" in saved.text
    async with database.session_scope() as session:
        rows = list(await session.scalars(select(AdvisorAbsence)))
    assert len(rows) == 1


async def test_an_overlapping_absence_is_refused_in_spanish(wired) -> None:
    client, database, built = wired
    page = await client.get("/crm/equipo/ausencias", auth=ADMIN)
    starts = local_input(visits.now() + timedelta(days=1))
    ends = local_input(visits.now() + timedelta(days=5))
    await client.post(
        "/crm/equipo/ausencias",
        auth=ADMIN,
        data={
            "clave": nonce(page.text),
            "asesor": built.advisor_id.hex,
            "inicio": starts,
            "fin": ends,
        },
    )

    page = await client.get("/crm/equipo/ausencias", auth=ADMIN)
    refused = await client.post(
        "/crm/equipo/ausencias",
        auth=ADMIN,
        data={
            "clave": nonce(page.text),
            "asesor": built.advisor_id.hex,
            "inicio": local_input(visits.now() + timedelta(days=2)),
            "fin": local_input(visits.now() + timedelta(days=7)),
        },
        follow_redirects=True,
    )

    assert "se cruza con estas fechas" in refused.text
    async with database.session_scope() as session:
        rows = list(await session.scalars(select(AdvisorAbsence)))
    assert len(rows) == 1


async def test_an_advisor_cannot_record_an_absence(wired) -> None:
    client, database, built = wired
    page = await client.get("/crm/equipo/ausencias", auth=ADMIN)
    refused = await client.post(
        "/crm/equipo/ausencias",
        auth=ADVISOR,
        data={
            "clave": nonce(page.text),
            "asesor": built.advisor_id.hex,
            "inicio": local_input(visits.now() + timedelta(days=1)),
            "fin": local_input(visits.now() + timedelta(days=2)),
        },
        follow_redirects=True,
    )

    assert "Sólo un administrador" in refused.text
    async with database.session_scope() as session:
        assert list(await session.scalars(select(AdvisorAbsence))) == []


async def test_an_advisor_sees_absences_without_the_controls(wired) -> None:
    client, _database, _built = wired
    advisor = await client.get("/crm/equipo/ausencias", auth=ADVISOR)

    assert advisor.status_code == 200
    assert "Registrar una ausencia" not in advisor.text


# -- Specialists ----------------------------------------------------------


async def test_designating_a_specialist_from_the_surface(wired) -> None:
    client, database, built = wired
    page = await client.get("/crm/equipo/especialistas", auth=ADMIN)
    assert "recibe primero las oportunidades" in page.text

    saved = await client.post(
        f"/crm/equipo/especialistas/{built.property_uuid}",
        auth=ADMIN,
        data={
            "clave": nonce(page.text),
            "asesor": built.second_advisor_id.hex,
            "papel": "Primary",
        },
        follow_redirects=True,
    )

    assert "Se actualizó el especialista" in saved.text
    async with database.session_scope() as session:
        rows = list(
            await session.scalars(
                select(PropertyExpert).where(PropertyExpert.revoked_at.is_(None))
            )
        )
    assert [row.advisor_id for row in rows] == [built.second_advisor_id]


async def test_an_advisor_sees_specialists_without_the_controls(wired) -> None:
    client, _database, _built = wired
    advisor = await client.get("/crm/equipo/especialistas", auth=ADVISOR)

    assert advisor.status_code == 200
    assert "Designar" not in advisor.text


# -- Agenda ---------------------------------------------------------------


async def test_the_agenda_distinguishes_confirmed_from_needing_review(
    wired,
) -> None:
    client, database, built = wired
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-agenda", body="Quiero ver la casa"
        )
        await visits.confirmed_visit(built, session, conversation)

    response = await client.get("/crm/agenda", auth=ADVISOR)

    assert response.status_code == 200
    assert "Confirmada" in response.text
    assert "Sólo una cita" in response.text
    assert built.advisor.display_name in response.text


async def test_an_advisor_sees_only_their_own_agenda(wired) -> None:
    client, database, built = wired
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-mine", body="Quiero ver la casa"
        )
        visit = await visits.confirmed_visit(built, session, conversation)
        reference = visit.reference

    mine = await client.get("/crm/agenda", auth=ADVISOR)
    theirs = await client.get("/crm/agenda", auth=OTHER)

    assert reference in mine.text
    assert reference not in theirs.text
    assert "No hay citas en este periodo." in theirs.text


async def test_recording_a_visit_outcome_from_the_surface(wired) -> None:
    client, database, built = wired
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-outcome", body="Quiero ver la casa"
        )
        visit = await visits.confirmed_visit(built, session, conversation)
        visit.starts_at = visits.now() - timedelta(hours=3)
        visit.ends_at = visits.now() - timedelta(hours=1)
        await session.commit()
        appointment_id = visit.id

    page = await client.get("/crm/agenda", auth=ADVISOR)
    assert "¿Se realizó la visita?" in page.text

    saved = await client.post(
        f"/crm/agenda/{appointment_id}/resultado",
        auth=ADVISOR,
        data={
            "clave": nonce(page.text),
            "asistencia": AppointmentAttendance.ATTENDED.value,
            "notas": "Le gustó la casa.",
        },
        follow_redirects=True,
    )

    assert "Se registró el resultado de la visita." in saved.text
    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, appointment_id)
    assert row is not None
    assert row.attendance == AppointmentAttendance.ATTENDED.value


async def test_the_reschedule_screen_offers_only_authoritative_times(
    wired,
) -> None:
    """No free-text field: a typed time the calendar has since taken would make
    the form look successful before anything said yes."""
    client, database, built = wired
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-resch", body="Quiero ver la casa"
        )
        visit = await visits.confirmed_visit(built, session, conversation)
        appointment_id = visit.id

    page = await client.get(
        f"/crm/agenda/{appointment_id}/reagendar", auth=ADVISOR
    )

    assert page.status_code == 200
    assert "<select" in page.text
    assert 'type="datetime-local"' not in page.text
    assert "Primero se aparta el horario nuevo" in page.text
    assert built.advisor.display_name in page.text


async def test_the_reschedule_screen_refuses_without_an_authoritative_calendar(
    wired,
) -> None:
    client, database, built = wired
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-nocal", body="Quiero ver la casa"
        )
        visit = await visits.confirmed_visit(built, session, conversation)
        appointment_id = visit.id
        member = await session.get(OrganizationMember, built.advisor_id)
        assert member is not None
        member.calendar_id = None
        await session.commit()

    page = await client.get(
        f"/crm/agenda/{appointment_id}/reagendar", auth=ADVISOR
    )

    assert page.status_code == 200
    assert "no tiene calendario configurado" in page.text
    assert "<select" not in page.text or 'name="inicio"' not in page.text


# -- Handling and alerts --------------------------------------------------


async def a_conversation_owned_by_the_advisor(database, built, *, wamid):  # noqa: ANN001, ANN202
    """A conversation the Advisor can actually reach.

    Booking the visit is what makes them the Responsible Advisor, and an Advisor
    only sees Opportunities that are theirs — the Stage 2 visibility rule these
    surfaces inherit rather than relax.
    """
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid=wamid, body="Quiero ver la casa"
        )
        await visits.confirmed_visit(built, session, conversation)
        await session.commit()
        return conversation


async def test_the_conversation_page_names_who_is_answering(wired) -> None:
    client, database, built = wired
    conversation = await a_conversation_owned_by_the_advisor(
        database, built, wamid="w-panel"
    )

    page = await client.get(f"/crm/bandeja/{conversation.id}", auth=ADVISOR)

    assert page.status_code == 200
    assert "Maia está atendiendo" in page.text
    assert "Atender yo esta conversación" in page.text
    # No message box until somebody holds it.
    assert "Responder por WhatsApp" not in page.text


async def test_taking_and_replying_from_the_conversation_page(wired) -> None:
    client, database, built = wired
    conversation = await a_conversation_owned_by_the_advisor(
        database, built, wamid="w-crmreply"
    )

    page = await client.get(f"/crm/bandeja/{conversation.id}", auth=ADVISOR)
    taken = await client.post(
        f"/crm/bandeja/{conversation.id}/atender",
        auth=ADVISOR,
        data={"clave": nonce(page.text)},
        follow_redirects=True,
    )

    assert "Ahora tú atiendes esta conversación" in taken.text
    assert "Responder por WhatsApp" in taken.text
    assert "número oficial de Larevia" in taken.text

    sent = await client.post(
        f"/crm/bandeja/{conversation.id}/responder",
        auth=ADVISOR,
        data={"clave": nonce(taken.text), "mensaje": "Con gusto te apoyo."},
        follow_redirects=True,
    )

    assert "Se envió el mensaje por el canal oficial." in sent.text
    async with database.session_scope() as session:
        staged = [
            row.body
            for row in await session.scalars(select(visits.OutboxMessage))
        ]
    assert "Con gusto te apoyo." in staged


async def test_a_second_advisor_is_told_who_is_answering(wired) -> None:
    client, database, built = wired
    conversation = await a_conversation_owned_by_the_advisor(
        database, built, wamid="w-taken"
    )

    page = await client.get(f"/crm/bandeja/{conversation.id}", auth=ADVISOR)
    await client.post(
        f"/crm/bandeja/{conversation.id}/atender",
        auth=ADVISOR,
        data={"clave": nonce(page.text)},
    )

    # The other Advisor cannot see the Contact at all — the Opportunity is not
    # theirs — which is the stronger version of the same guarantee.
    other = await client.get(f"/crm/bandeja/{conversation.id}", auth=OTHER)
    assert other.status_code == 404

    admin_page = await client.get(f"/crm/bandeja/{conversation.id}", auth=ADMIN)
    assert "Atiende una persona" in admin_page.text
    assert built.advisor.display_name in admin_page.text


async def test_the_alerts_surface_shows_what_is_waiting_and_for_how_long(
    wired,
) -> None:
    client, database, built = wired
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-alerts", body="Quiero ver la casa"
        )
        await visits.confirmed_visit(built, session, conversation)
    async with database.session_scope() as session:
        await visits.inbound(
            session, wamid="w-alerts2", body="quiero hablar con una persona"
        )

    page = await client.get("/crm/alertas", auth=ADMIN)

    assert page.status_code == 200
    assert "Solicitudes de atención humana" in page.text
    assert "A los 15 minutos sin tomarla" in page.text
    assert "no</strong> se " in page.text or "no se reasigna" in page.text
    assert built.advisor.display_name in page.text


async def test_releasing_returns_the_conversation_to_maia(wired) -> None:
    client, database, built = wired
    conversation = await a_conversation_owned_by_the_advisor(
        database, built, wamid="w-rel"
    )

    page = await client.get(f"/crm/bandeja/{conversation.id}", auth=ADVISOR)
    taken = await client.post(
        f"/crm/bandeja/{conversation.id}/atender",
        auth=ADVISOR,
        data={"clave": nonce(page.text)},
        follow_redirects=True,
    )
    released = await client.post(
        f"/crm/bandeja/{conversation.id}/liberar",
        auth=ADVISOR,
        data={"clave": nonce(taken.text), "modo": HandlingMode.MAIA.value},
        follow_redirects=True,
    )

    assert "Liberaste la conversación." in released.text
    async with database.session_scope() as session:
        snapshot = await ConversationHandling(session).snapshot(conversation.id)
    assert snapshot.mode is HandlingMode.MAIA


async def test_a_mutation_without_an_idempotency_key_is_refused(wired) -> None:
    client, _database, built = wired
    response = await client.post(
        "/crm/equipo/miembros",
        auth=ADMIN,
        data={"usuario": "sinclave@larevia.test", "nombre": "Sin Clave"},
    )

    assert response.status_code == 400
    assert "clave de operación" in response.json()["detail"]


# -- The rest of the team controls ----------------------------------------


async def test_updating_a_member_from_the_surface(wired) -> None:
    client, database, built = wired
    page = await client.get("/crm/equipo", auth=ADMIN)

    saved = await client.post(
        f"/crm/equipo/miembros/{built.advisor_id}",
        auth=ADMIN,
        data={
            "clave": nonce(page.text),
            "nombre": "Santiago Larevia",
            "calendario": "santiago@larevia.test",
            "alertas": "9111",
        },
        follow_redirects=True,
    )

    assert "Se guardaron los cambios." in saved.text
    async with database.session_scope() as session:
        member = await session.get(OrganizationMember, built.advisor_id)
    assert member is not None
    assert member.display_name == "Santiago Larevia"
    assert member.calendar_id == "santiago@larevia.test"


async def test_deactivating_and_reactivating_a_member(wired) -> None:
    client, database, built = wired
    page = await client.get("/crm/equipo", auth=ADMIN)
    off = await client.post(
        f"/crm/equipo/miembros/{built.second_advisor_id}/estado",
        auth=ADMIN,
        data={"clave": nonce(page.text), "activo": "0"},
        follow_redirects=True,
    )
    assert "Se actualizó el acceso" in off.text
    assert "Dado de baja" in off.text

    on = await client.post(
        f"/crm/equipo/miembros/{built.second_advisor_id}/estado",
        auth=ADMIN,
        data={"clave": nonce(off.text), "activo": "1"},
        follow_redirects=True,
    )
    assert "Se actualizó el acceso" in on.text
    async with database.session_scope() as session:
        member = await session.get(OrganizationMember, built.second_advisor_id)
    assert member is not None and member.active


async def test_the_last_administrator_refusal_reaches_the_screen(wired) -> None:
    client, database, built = wired
    async with database.session_scope() as session:
        developer = await session.scalar(
            select(OrganizationMember).where(OrganizationMember.login == "developer")
        )
        assert developer is not None
        developer.active = False
        await session.commit()

    page = await client.get("/crm/equipo", auth=ADMIN)
    refused = await client.post(
        f"/crm/equipo/miembros/{built.admin_id}/estado",
        auth=ADMIN,
        data={"clave": nonce(page.text), "activo": "0"},
        follow_redirects=True,
    )

    assert "último administrador activo" in refused.text


async def test_naming_a_new_default_advisor_from_the_surface(wired) -> None:
    client, database, built = wired
    page = await client.get("/crm/equipo", auth=ADMIN)

    saved = await client.post(
        f"/crm/equipo/miembros/{built.second_advisor_id}/predeterminado",
        auth=ADMIN,
        data={"clave": nonce(page.text)},
        follow_redirects=True,
    )

    assert "Se actualizó el asesor predeterminado." in saved.text
    async with database.session_scope() as session:
        rows = list(
            await session.scalars(
                select(OrganizationMember).where(
                    OrganizationMember.is_default_advisor.is_(True)
                )
            )
        )
    assert [row.id for row in rows] == [built.second_advisor_id]


async def test_ending_an_absence_from_the_surface(wired) -> None:
    client, database, built = wired
    page = await client.get("/crm/equipo/ausencias", auth=ADMIN)
    await client.post(
        "/crm/equipo/ausencias",
        auth=ADMIN,
        data={
            "clave": nonce(page.text),
            "asesor": built.advisor_id.hex,
            "inicio": local_input(visits.now() + timedelta(days=1)),
            "fin": local_input(visits.now() + timedelta(days=3)),
        },
    )

    async with database.session_scope() as session:
        absence = await session.scalar(select(AdvisorAbsence))
        assert absence is not None
        absence_id = absence.id

    page = await client.get("/crm/equipo/ausencias", auth=ADMIN)
    ended = await client.post(
        f"/crm/equipo/ausencias/{absence_id}/terminar",
        auth=ADMIN,
        data={"clave": nonce(page.text)},
        follow_redirects=True,
    )

    assert "Se terminó la ausencia." in ended.text
    async with database.session_scope() as session:
        absence = await session.get(AdvisorAbsence, absence_id)
    assert absence is not None and absence.cancelled_at is not None


async def test_a_malformed_absence_date_is_refused_in_spanish(wired) -> None:
    client, _database, built = wired
    page = await client.get("/crm/equipo/ausencias", auth=ADMIN)
    refused = await client.post(
        "/crm/equipo/ausencias",
        auth=ADMIN,
        data={
            "clave": nonce(page.text),
            "asesor": built.advisor_id.hex,
            "inicio": "no es una fecha",
            "fin": "",
        },
        follow_redirects=True,
    )

    assert "Revisa las fechas" in refused.text


async def test_an_absence_without_an_advisor_is_refused(wired) -> None:
    client, _database, _built = wired
    page = await client.get("/crm/equipo/ausencias", auth=ADMIN)
    refused = await client.post(
        "/crm/equipo/ausencias",
        auth=ADMIN,
        data={
            "clave": nonce(page.text),
            "asesor": "no-es-un-id",
            "inicio": local_input(visits.now() + timedelta(days=1)),
            "fin": local_input(visits.now() + timedelta(days=2)),
        },
        follow_redirects=True,
    )

    assert "Elige un asesor." in refused.text


async def test_removing_a_specialist_from_the_surface(wired) -> None:
    client, database, built = wired
    page = await client.get("/crm/equipo/especialistas", auth=ADMIN)
    await client.post(
        f"/crm/equipo/especialistas/{built.property_uuid}",
        auth=ADMIN,
        data={
            "clave": nonce(page.text),
            "asesor": built.advisor_id.hex,
            "papel": "Primary",
        },
    )

    page = await client.get("/crm/equipo/especialistas", auth=ADMIN)
    assert "Quitar a" in page.text
    removed = await client.post(
        f"/crm/equipo/especialistas/{built.property_uuid}/quitar",
        auth=ADMIN,
        data={"clave": nonce(page.text), "asesor": built.advisor_id.hex},
        follow_redirects=True,
    )

    assert "Se actualizó el especialista" in removed.text
    async with database.session_scope() as session:
        live = list(
            await session.scalars(
                select(PropertyExpert).where(PropertyExpert.revoked_at.is_(None))
            )
        )
    assert live == []


async def test_a_specialist_designation_without_an_advisor_is_refused(wired) -> None:
    client, _database, built = wired
    page = await client.get("/crm/equipo/especialistas", auth=ADMIN)
    refused = await client.post(
        f"/crm/equipo/especialistas/{built.property_uuid}",
        auth=ADMIN,
        data={"clave": nonce(page.text), "asesor": "nope", "papel": "Primary"},
        follow_redirects=True,
    )
    assert "Elige un asesor." in refused.text

    refused = await client.post(
        f"/crm/equipo/especialistas/{built.property_uuid}/quitar",
        auth=ADMIN,
        data={"clave": nonce(page.text), "asesor": "nope"},
        follow_redirects=True,
    )
    assert "Elige un asesor." in refused.text


async def test_designating_a_specialist_who_cannot_own_work_is_refused(
    wired,
) -> None:
    client, _database, built = wired
    page = await client.get("/crm/equipo/especialistas", auth=ADMIN)
    refused = await client.post(
        f"/crm/equipo/especialistas/{built.property_uuid}",
        auth=ADMIN,
        data={
            "clave": nonce(page.text),
            "asesor": built.admin_id.hex,
            "papel": "Backup",
        },
        follow_redirects=True,
    )
    assert "no puede recibir oportunidades" in refused.text


# -- Agenda actions -------------------------------------------------------


async def test_rescheduling_from_the_surface(wired) -> None:
    client, database, built = wired
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-uiresch", body="Quiero ver la casa"
        )
        visit = await visits.confirmed_visit(built, session, conversation)
        appointment_id = visit.id
        original_start = visit.starts_at

    page = await client.get(f"/crm/agenda/{appointment_id}/reagendar", auth=ADVISOR)
    later = _another_time(page.text, original_start)

    moved = await client.post(
        f"/crm/agenda/{appointment_id}/reagendar",
        auth=ADVISOR,
        data={"clave": nonce(page.text), "inicio": later},
        follow_redirects=True,
    )

    assert "La cita quedó reagendada." in moved.text
    async with database.session_scope() as session:
        old = await session.get(visits.Appointment, appointment_id)
    assert old is not None
    assert old.rescheduled_to_id is not None


async def test_a_reschedule_with_no_chosen_time_is_refused(wired) -> None:
    client, database, built = wired
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-noopt", body="Quiero ver la casa"
        )
        visit = await visits.confirmed_visit(built, session, conversation)
        appointment_id = visit.id

    page = await client.get(f"/crm/agenda/{appointment_id}/reagendar", auth=ADVISOR)
    refused = await client.post(
        f"/crm/agenda/{appointment_id}/reagendar",
        auth=ADVISOR,
        data={"clave": nonce(page.text), "inicio": "no es una fecha"},
        follow_redirects=True,
    )

    assert "Elige un horario de la lista." in refused.text


async def test_a_reschedule_the_calendar_refuses_says_the_original_stands(
    wired,
) -> None:
    client, database, built = wired
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-uifail", body="Quiero ver la casa"
        )
        visit = await visits.confirmed_visit(built, session, conversation)
        appointment_id = visit.id
        original_start = visit.starts_at

    page = await client.get(f"/crm/agenda/{appointment_id}/reagendar", auth=ADVISOR)
    later = _another_time(page.text, original_start)

    from realestate.channels.google.calendar import CalendarOutcome

    built.calendar.create_outcome = CalendarOutcome.UNKNOWN
    refused = await client.post(
        f"/crm/agenda/{appointment_id}/reagendar",
        auth=ADVISOR,
        data={"clave": nonce(page.text), "inicio": later},
        follow_redirects=True,
    )

    assert "sigue en pie" in refused.text
    async with database.session_scope() as session:
        old = await session.get(visits.Appointment, appointment_id)
    assert old is not None
    assert old.status == "Confirmed"


async def test_cancelling_from_the_surface(wired) -> None:
    client, database, built = wired
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-uicancel", body="Quiero ver la casa"
        )
        visit = await visits.confirmed_visit(built, session, conversation)
        appointment_id = visit.id

    page = await client.get("/crm/agenda", auth=ADVISOR)
    cancelled = await client.post(
        f"/crm/agenda/{appointment_id}/cancelar",
        auth=ADVISOR,
        data={"clave": nonce(page.text)},
        follow_redirects=True,
    )

    assert "La cita quedó cancelada." in cancelled.text
    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, appointment_id)
    assert row is not None and row.status == "Cancelled"


async def test_a_cancellation_the_customer_could_not_be_told_about_says_so(
    wired,
) -> None:
    """The visit is cancelled either way; implying a message that never went out
    would be a lie the operator acts on."""
    client, database, built = wired
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-uinotify", body="Quiero ver la casa"
        )
        visit = await visits.confirmed_visit(built, session, conversation)
        appointment_id = visit.id
        # Age the conversation out of Meta's 24-hour window.
        from realestate.db.models import InboxMessage

        for message in await session.scalars(
            select(InboxMessage).where(
                InboxMessage.conversation_id == conversation.id
            )
        ):
            message.sent_at = message.sent_at - timedelta(hours=30)
            message.persisted_at = message.persisted_at - timedelta(hours=30)
        await session.commit()

    page = await client.get("/crm/agenda", auth=ADVISOR)
    cancelled = await client.post(
        f"/crm/agenda/{appointment_id}/cancelar",
        auth=ADVISOR,
        data={"clave": nonce(page.text)},
        follow_redirects=True,
    )

    assert "no se pudo avisar al cliente" in cancelled.text
    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, appointment_id)
    assert row is not None and row.status == "Cancelled"


async def test_a_visit_that_has_not_happened_cannot_be_closed_from_the_surface(
    wired,
) -> None:
    client, database, built = wired
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-uiearly", body="Quiero ver la casa"
        )
        visit = await visits.confirmed_visit(built, session, conversation)
        appointment_id = visit.id

    page = await client.get("/crm/agenda", auth=ADVISOR)
    refused = await client.post(
        f"/crm/agenda/{appointment_id}/resultado",
        auth=ADVISOR,
        data={
            "clave": nonce(page.text),
            "asistencia": AppointmentAttendance.ATTENDED.value,
        },
        follow_redirects=True,
    )

    assert "todavía no ocurre" in refused.text


async def test_a_missed_visit_can_authorise_a_rescheduling_invitation(wired) -> None:
    client, database, built = wired
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-uimissed", body="Quiero ver la casa"
        )
        visit = await visits.confirmed_visit(built, session, conversation)
        visit.starts_at = visits.now() - timedelta(hours=3)
        visit.ends_at = visits.now() - timedelta(hours=1)
        await session.commit()
        appointment_id = visit.id

    page = await client.get("/crm/agenda", auth=ADVISOR)
    saved = await client.post(
        f"/crm/agenda/{appointment_id}/resultado",
        auth=ADVISOR,
        data={
            "clave": nonce(page.text),
            "asistencia": AppointmentAttendance.MISSED.value,
            "notas": "No llegó.",
            "invitar": "1",
        },
        follow_redirects=True,
    )

    assert "Se registró el resultado" in saved.text
    assert "Reagendado autorizado" in saved.text
    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, appointment_id)
    assert row is not None
    assert row.reschedule_invitation_authorized


async def test_a_pre_stage_three_visit_appears_for_the_administrator(wired) -> None:
    client, database, built = wired
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-uiunowned", body="Quiero ver la casa"
        )
        visit = await visits.confirmed_visit(built, session, conversation)
        visit.advisor_id = None
        visit.calendar_id = None
        await session.commit()
        reference = visit.reference

    page = await client.get("/crm/agenda", auth=ADMIN)

    assert "Citas sin asesor responsable" in page.text
    assert "No se les asignó nadie automáticamente" in page.text
    assert reference in page.text


# -- Handling refusals reach the operator ---------------------------------


async def test_a_reply_the_gate_refuses_explains_what_to_do(wired) -> None:
    client, database, built = wired
    conversation = await a_conversation_owned_by_the_advisor(
        database, built, wamid="w-uidenied"
    )
    async with database.session_scope() as session:
        from realestate.db.models import InboxMessage

        for message in await session.scalars(
            select(InboxMessage).where(
                InboxMessage.conversation_id == conversation.id
            )
        ):
            message.sent_at = message.sent_at - timedelta(hours=30)
            message.persisted_at = message.persisted_at - timedelta(hours=30)
        await session.commit()

    page = await client.get(f"/crm/bandeja/{conversation.id}", auth=ADVISOR)
    taken = await client.post(
        f"/crm/bandeja/{conversation.id}/atender",
        auth=ADVISOR,
        data={"clave": nonce(page.text)},
        follow_redirects=True,
    )
    denied = await client.post(
        f"/crm/bandeja/{conversation.id}/responder",
        auth=ADVISOR,
        data={"clave": nonce(taken.text), "mensaje": "¿Sigues interesado?"},
        follow_redirects=True,
    )

    assert "No se pudo enviar el mensaje" in denied.text
    assert "24 horas" in denied.text


async def test_a_second_advisor_taking_a_held_conversation_is_told_by_name(
    wired,
) -> None:
    client, database, built = wired
    conversation = await a_conversation_owned_by_the_advisor(
        database, built, wamid="w-uiheld"
    )
    page = await client.get(f"/crm/bandeja/{conversation.id}", auth=ADVISOR)
    await client.post(
        f"/crm/bandeja/{conversation.id}/atender",
        auth=ADVISOR,
        data={"clave": nonce(page.text)},
    )

    admin_page = await client.get(f"/crm/bandeja/{conversation.id}", auth=ADMIN)
    # The Administrator may move it, so the refusal is exercised through the
    # holder-mismatch path an Advisor would hit.
    async with database.session_scope() as session:
        from realestate.domain.commercial.handling import (
            AlreadyHandled,
            ConversationHandling,
            TakeHandling,
        )

        with pytest.raises(AlreadyHandled):
            await ConversationHandling(session).take(
                built.second_advisor,
                TakeHandling(
                    conversation_id=conversation.id, command_key="ui-take-race"
                ),
            )
    assert built.advisor.display_name in admin_page.text


async def test_acknowledging_a_pending_request_from_the_conversation(wired) -> None:
    client, database, built = wired
    conversation = await a_conversation_owned_by_the_advisor(
        database, built, wamid="w-uiack"
    )
    async with database.session_scope() as session:
        await visits.inbound(
            session, wamid="w-uiack2", body="¿Y el crédito hipotecario?"
        )

    page = await client.get(f"/crm/bandeja/{conversation.id}", auth=ADVISOR)
    assert "Un cliente está esperando a una persona" in page.text

    request_id = re.search(r'name="solicitud" value="([0-9a-f-]+)"', page.text)
    assert request_id
    acknowledged = await client.post(
        f"/crm/bandeja/{conversation.id}/solicitud",
        auth=ADVISOR,
        data={"clave": nonce(page.text), "solicitud": request_id.group(1)},
        follow_redirects=True,
    )

    assert "Registramos que tú estás atendiendo" in acknowledged.text


async def test_an_unparsable_request_id_is_refused(wired) -> None:
    client, database, built = wired
    conversation = await a_conversation_owned_by_the_advisor(
        database, built, wamid="w-uibad"
    )
    page = await client.get(f"/crm/bandeja/{conversation.id}", auth=ADVISOR)
    refused = await client.post(
        f"/crm/bandeja/{conversation.id}/solicitud",
        auth=ADVISOR,
        data={"clave": nonce(page.text), "solicitud": "nope"},
        follow_redirects=True,
    )
    assert "No encontramos esa solicitud." in refused.text


async def test_dismissing_an_alert_from_the_surface(wired) -> None:
    client, database, built = wired
    async with database.session_scope() as session:
        await visits.inbound(
            session, wamid="w-uialert", body="quiero hablar con alguien"
        )

    page = await client.get("/crm/alertas", auth=ADMIN)
    assert "Marcar visto" in page.text
    alert_id = re.search(r'action="/crm/alertas/([0-9a-f-]+)"', page.text)
    assert alert_id

    dismissed = await client.post(
        f"/crm/alertas/{alert_id.group(1)}",
        auth=ADMIN,
        data={"clave": nonce(page.text)},
        follow_redirects=True,
    )

    assert "Se marcó el aviso como visto." in dismissed.text
    assert "No hay avisos abiertos." in dismissed.text


async def test_releasing_into_awaiting_contact_from_the_surface(wired) -> None:
    client, database, built = wired
    conversation = await a_conversation_owned_by_the_advisor(
        database, built, wamid="w-uiwait"
    )
    page = await client.get(f"/crm/bandeja/{conversation.id}", auth=ADVISOR)
    taken = await client.post(
        f"/crm/bandeja/{conversation.id}/atender",
        auth=ADVISOR,
        data={"clave": nonce(page.text)},
        follow_redirects=True,
    )
    released = await client.post(
        f"/crm/bandeja/{conversation.id}/liberar",
        auth=ADVISOR,
        data={
            "clave": nonce(taken.text),
            "modo": HandlingMode.AWAITING_CONTACT.value,
        },
        follow_redirects=True,
    )

    assert "Liberaste la conversación." in released.text
    assert "En espera del cliente" in released.text
    async with database.session_scope() as session:
        snapshot = await ConversationHandling(session).snapshot(conversation.id)
    assert snapshot.mode is HandlingMode.AWAITING_CONTACT


async def test_an_advisor_cannot_release_a_colleagues_conversation(wired) -> None:
    client, database, built = wired
    conversation = await a_conversation_owned_by_the_advisor(
        database, built, wamid="w-uirel2"
    )
    page = await client.get(f"/crm/bandeja/{conversation.id}", auth=ADVISOR)
    taken = await client.post(
        f"/crm/bandeja/{conversation.id}/atender",
        auth=ADVISOR,
        data={"clave": nonce(page.text)},
        follow_redirects=True,
    )

    refused = await client.post(
        f"/crm/bandeja/{conversation.id}/liberar",
        auth=OTHER,
        data={"clave": nonce(taken.text), "modo": HandlingMode.MAIA.value},
        follow_redirects=True,
    )
    # The other Advisor cannot even see the Contact, which is the stronger form.
    assert refused.status_code == 404


# -- Every refusal reaches the operator as a sentence ---------------------


async def test_an_advisor_cannot_update_a_member_from_the_surface(wired) -> None:
    client, database, built = wired
    page = await client.get("/crm/equipo", auth=ADMIN)
    refused = await client.post(
        f"/crm/equipo/miembros/{built.second_advisor_id}",
        auth=ADVISOR,
        data={"clave": nonce(page.text), "nombre": "Cambiado"},
        follow_redirects=True,
    )

    assert "Sólo un administrador" in refused.text
    async with database.session_scope() as session:
        member = await session.get(OrganizationMember, built.second_advisor_id)
    assert member is not None and member.display_name != "Cambiado"


async def test_naming_a_non_advising_member_as_the_fallback_is_refused(
    wired,
) -> None:
    client, _database, built = wired
    page = await client.get("/crm/equipo", auth=ADMIN)
    refused = await client.post(
        f"/crm/equipo/miembros/{built.admin_id}/predeterminado",
        auth=ADMIN,
        data={"clave": nonce(page.text)},
        follow_redirects=True,
    )

    assert "no puede recibir oportunidades" in refused.text


async def test_ending_an_unknown_absence_is_refused(wired) -> None:
    client, _database, _built = wired
    page = await client.get("/crm/equipo/ausencias", auth=ADMIN)
    refused = await client.post(
        f"/crm/equipo/ausencias/{uuid.uuid4()}/terminar",
        auth=ADMIN,
        data={"clave": nonce(page.text)},
        follow_redirects=True,
    )

    assert "No encontramos esa ausencia." in refused.text


async def test_an_advisor_cannot_remove_a_specialist(wired) -> None:
    client, database, built = wired
    page = await client.get("/crm/equipo/especialistas", auth=ADMIN)
    await client.post(
        f"/crm/equipo/especialistas/{built.property_uuid}",
        auth=ADMIN,
        data={
            "clave": nonce(page.text),
            "asesor": built.advisor_id.hex,
            "papel": "Primary",
        },
    )

    page = await client.get("/crm/equipo/especialistas", auth=ADMIN)
    refused = await client.post(
        f"/crm/equipo/especialistas/{built.property_uuid}/quitar",
        auth=ADVISOR,
        data={"clave": nonce(page.text), "asesor": built.advisor_id.hex},
        follow_redirects=True,
    )

    assert "Sólo un administrador" in refused.text
    async with database.session_scope() as session:
        live = list(
            await session.scalars(
                select(PropertyExpert).where(PropertyExpert.revoked_at.is_(None))
            )
        )
    assert len(live) == 1


async def test_the_absence_list_labels_every_state(wired) -> None:
    client, database, built = wired
    page = await client.get("/crm/equipo/ausencias", auth=ADMIN)
    # One in progress, ended early; one in the future, cancelled.
    await client.post(
        "/crm/equipo/ausencias",
        auth=ADMIN,
        data={
            "clave": nonce(page.text),
            "asesor": built.advisor_id.hex,
            "inicio": local_input(visits.now() - timedelta(hours=2)),
            "fin": local_input(visits.now() + timedelta(days=1)),
        },
    )
    page = await client.get("/crm/equipo/ausencias", auth=ADMIN)
    assert "En curso" in page.text

    async with database.session_scope() as session:
        absence = await session.scalar(select(AdvisorAbsence))
        assert absence is not None
        absence_id = absence.id
    ended = await client.post(
        f"/crm/equipo/ausencias/{absence_id}/terminar",
        auth=ADMIN,
        data={"clave": nonce(page.text)},
        follow_redirects=True,
    )
    assert "Terminada" in ended.text

    page = await client.get("/crm/equipo/ausencias", auth=ADMIN)
    await client.post(
        "/crm/equipo/ausencias",
        auth=ADMIN,
        data={
            "clave": nonce(page.text),
            "asesor": built.second_advisor_id.hex,
            "inicio": local_input(visits.now() + timedelta(days=3)),
            "fin": local_input(visits.now() + timedelta(days=4)),
        },
    )
    async with database.session_scope() as session:
        future = await session.scalar(
            select(AdvisorAbsence).where(
                AdvisorAbsence.advisor_id == built.second_advisor_id
            )
        )
        assert future is not None
        future_id = future.id
    page = await client.get("/crm/equipo/ausencias", auth=ADMIN)
    cancelled = await client.post(
        f"/crm/equipo/ausencias/{future_id}/terminar",
        auth=ADMIN,
        data={"clave": nonce(page.text)},
        follow_redirects=True,
    )
    assert "Cancelada" in cancelled.text


async def test_with_no_active_advisors_both_forms_explain_themselves(wired) -> None:
    client, database, built = wired
    async with database.session_scope() as session:
        for member_id in (built.advisor_id, built.second_advisor_id):
            member = await session.get(OrganizationMember, member_id)
            assert member is not None
            member.active = False
            member.is_default_advisor = False
        await session.commit()

    absences = await client.get("/crm/equipo/ausencias", auth=ADMIN)
    specialists = await client.get("/crm/equipo/especialistas", auth=ADMIN)

    assert "No hay asesores activos" in absences.text
    assert "Da de alta a un asesor primero." in absences.text
    # Nothing to designate with, so the column says so rather than rendering an
    # empty select.
    assert "Designar" not in specialists.text


async def test_the_agenda_names_a_different_conducting_specialist(wired) -> None:
    client, database, built = wired
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-uiconduct", body="Quiero ver la casa"
        )
        from realestate.db.models import PropertyExpertRole
        from realestate.domain.commercial.team import (
            DesignateExpert,
            TeamAdministration,
        )
        from realestate.domain.scheduling.appointments import BookVisit

        await TeamAdministration(session).record(
            built.admin,
            DesignateExpert(
                command_key="ui-conduct-expert",
                property_uuid=built.property_uuid,
                advisor_id=built.second_advisor_id,
                role=PropertyExpertRole.PRIMARY,
            ),
        )
        await session.commit()
        start = await visits.first_slot(
            built, session, advisor_id=built.second_advisor_id
        )
        await built.visits(session).book(
            built.product,
            BookVisit(
                conversation_id=conversation.id,
                property_uuid=built.property_uuid,
                start=start,
                command_key="ui-conduct-book",
                conducting_advisor_id=built.second_advisor_id,
            ),
        )

    page = await client.get("/crm/agenda", auth=ADMIN)

    assert "Conduce la visita:" in page.text
    assert built.second_advisor.display_name in page.text


async def test_another_advisor_cannot_act_on_a_visit_from_the_surface(wired) -> None:
    client, database, built = wired
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-uiscope", body="Quiero ver la casa"
        )
        visit = await visits.confirmed_visit(built, session, conversation)
        visit.starts_at = visits.now() - timedelta(hours=3)
        visit.ends_at = visits.now() - timedelta(hours=1)
        await session.commit()
        appointment_id = visit.id

    page = await client.get("/crm/agenda", auth=ADMIN)
    key_value = nonce(page.text)

    outcome = await client.post(
        f"/crm/agenda/{appointment_id}/resultado",
        auth=OTHER,
        data={
            "clave": key_value,
            "asistencia": AppointmentAttendance.ATTENDED.value,
        },
        follow_redirects=True,
    )
    reschedule_page = await client.get(
        f"/crm/agenda/{appointment_id}/reagendar", auth=OTHER
    )
    reschedule = await client.post(
        f"/crm/agenda/{appointment_id}/reagendar",
        auth=OTHER,
        data={"clave": key_value, "inicio": visits.now().isoformat()},
        follow_redirects=True,
    )
    cancel = await client.post(
        f"/crm/agenda/{appointment_id}/cancelar",
        auth=OTHER,
        data={"clave": key_value},
        follow_redirects=True,
    )

    for response in (outcome, reschedule, cancel):
        assert "No encontramos esa cita." in response.text
    assert "No encontramos esa cita." in reschedule_page.text
    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, appointment_id)
    assert row is not None and row.attendance is None


async def test_replying_without_holding_the_conversation_is_refused(wired) -> None:
    client, database, built = wired
    conversation = await a_conversation_owned_by_the_advisor(
        database, built, wamid="w-uinohold"
    )
    page = await client.get(f"/crm/bandeja/{conversation.id}", auth=ADMIN)
    refused = await client.post(
        f"/crm/bandeja/{conversation.id}/responder",
        auth=ADMIN,
        data={"clave": nonce(page.text), "mensaje": "Hola"},
        follow_redirects=True,
    )

    assert "tienes que tomar la conversación" in refused.text


async def test_acknowledging_an_unknown_request_is_refused(wired) -> None:
    client, database, built = wired
    conversation = await a_conversation_owned_by_the_advisor(
        database, built, wamid="w-uiunknown"
    )
    page = await client.get(f"/crm/bandeja/{conversation.id}", auth=ADVISOR)
    refused = await client.post(
        f"/crm/bandeja/{conversation.id}/solicitud",
        auth=ADVISOR,
        data={"clave": nonce(page.text), "solicitud": str(uuid.uuid4())},
        follow_redirects=True,
    )

    assert "No encontramos esa solicitud de atención." in refused.text


async def test_an_administrator_moves_handling_from_the_surface(wired) -> None:
    """Somebody has to be able to unstick a conversation held by a person who
    went home; an Advisor cannot take it from a colleague."""
    client, database, built = wired
    conversation = await a_conversation_owned_by_the_advisor(
        database, built, wamid="w-uitakerace"
    )
    page = await client.get(f"/crm/bandeja/{conversation.id}", auth=ADVISOR)
    await client.post(
        f"/crm/bandeja/{conversation.id}/atender",
        auth=ADVISOR,
        data={"clave": nonce(page.text)},
    )

    admin_page = await client.get(f"/crm/bandeja/{conversation.id}", auth=ADMIN)
    moved = await client.post(
        f"/crm/bandeja/{conversation.id}/atender",
        auth=ADMIN,
        data={"clave": nonce(admin_page.text)},
        follow_redirects=True,
    )

    assert "Ahora tú atiendes esta conversación" in moved.text
    async with database.session_scope() as session:
        snapshot = await ConversationHandling(session).snapshot(conversation.id)
    assert snapshot.holder_member_id == built.admin_id
