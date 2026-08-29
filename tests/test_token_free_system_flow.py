"""Credential-free vertical proof of the Lead-to-Broker booking path.

This test deliberately keeps the Product boundary real: a signed Meta-shaped
webhook is persisted, the WhatsApp worker binds a Sales session, Hermes-style
tool calls cross the authenticated ASGI plugin API, appointment policy writes
PostgreSQL, the Outbox releases deterministic copy, a delivery callback is
reconciled, and the Broker notifier emits Telegram text.

Only the four external transports are fakes: model inference, Meta delivery,
Google Calendar, and Telegram delivery. No provider credential is read or
required, so CI can run this scenario on every change.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import Select, select, text
from sqlalchemy.engine import make_url

from realestate.api import plugin as plugin_api
from realestate.api import webhooks as webhook_api
from realestate.api.plugin import SESSION_HEADER
from realestate.app import create_app
from realestate.config import Settings
from realestate.db.engine import Base, Database
from realestate.db.models import (
    AgentSession,
    Appointment,
    AppointmentStatus,
    AuditEvent,
    AvailabilitySnapshot,
    DeliveryStatus,
    InboxGroup,
    InboxGroupStatus,
    InboxMessage,
    InboxStatus,
    OutboxMessage,
    OutboxStatus,
)
from realestate.domain.appointments import AppointmentPolicy
from realestate.domain.properties import ArtifactStore, PropertyService
from realestate.hermes.sessions import TurnResult
from realestate.worker import whatsapp as worker_module
from realestate.worker.broker import BrokerNotifier
from realestate.worker.whatsapp import WhatsAppWorker
from tests.conftest import DATABASE_URL, age_pending_inbox, requires_postgres
from tests.fixtures import commercial, webhooks
from tests.fixtures.stubs import (
    SCHEDULE,
    ZONE,
    StubCalendar,
    StubTelegram,
    StubWhatsApp,
)

pytestmark = requires_postgres

FIXTURES = Path(__file__).parent / "fixtures"
CASA_ROBLE = (FIXTURES / "casa-roble.md").read_bytes()
APP_SECRET = "offline-meta-app-secret"
PLUGIN_TOKEN = "offline-plugin-token"
DURABLE_SESSION = "offline-sales-session"


# The Organization and its members are created by migration and configuration,
# not by this scenario. Truncating them would leave every later test in the
# session without the Organization that all commercial data belongs to
# (ADR-0019), so they are named as preserved rather than discovered by accident.
# ``measurement_definitions`` joins them for the same reason: migration 0025
# seeds the versioned counting rules, and a scenario that truncated them would
# leave every later analytics test unable to resolve its own definition version.
PRESERVED_TABLES = frozenset(
    {"organizations", "organization_members", "measurement_definitions"}
)


async def _truncate(database: Database) -> None:
    """Reset only the dedicated test database, including future mapped tables."""
    name = make_url(DATABASE_URL).database or ""
    assert name.endswith("_test"), f"refusing to truncate non-test database {name!r}"
    # Schema-qualified: the pseudonymous analytics tables live in their own
    # PostgreSQL schema since Stage 8, and a bare name would resolve against
    # ``public`` and fail rather than truncating them.
    tables = ", ".join(
        f'"{table.schema}"."{table.name}"' if table.schema else f'"{table.name}"'
        for table in Base.metadata.tables.values()
        if table.name not in PRESERVED_TABLES
    )
    async with database.session_scope() as session:
        await session.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
        await session.commit()


async def _post_signed(client: httpx.AsyncClient, payload: dict) -> httpx.Response:
    """This suite's webhook path and app secret, bound to the shared signer."""
    return await webhooks.post_signed(
        client, webhook_api.WEBHOOK_PATH, payload, APP_SECRET
    )


async def _tool(
    client: httpx.AsyncClient, headers: dict[str, str], name: str, payload: dict
) -> dict:
    """Call one typed Product tool the way the Hermes plugin would."""
    response = await client.post(
        f"/internal/plugin/tools/{name}", headers=headers, json=payload
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _rows(session, statement: Select) -> list:  # noqa: ANN001
    return list((await session.execute(statement)).scalars().all())


async def _answer_property_question(client: httpx.AsyncClient, headers) -> TurnResult:  # noqa: ANN001
    """Turn one: the Model consults the document before quoting it."""
    result = await _tool(
        client, headers, "get_property_information", {"reference": "Casa Roble"}
    )
    assert result["result"] == "found"
    assert result["name"] == "Casa Roble"
    return TurnResult(
        text=(
            "**Casa Roble** está en Zapopan, tiene **4 recámaras** y cuesta "
            "$3,000,000 MXN. ¿Quieres agendar una visita?"
        ),
        tools_used=["get_property_information"],
    )


async def _book_a_visit(client: httpx.AsyncClient, headers) -> TurnResult:  # noqa: ANN001
    """Turn two: the Model reads availability, then books through Product."""
    target = datetime.now(tz=ZONE).date() + timedelta(days=2)
    slots = await _tool(
        client,
        headers,
        "get_available_slots",
        {
            "reference": "Casa Roble",
            "date_from": target.isoformat(),
            "date_to": target.isoformat(),
        },
    )
    assert slots["result"] == "available"
    assert slots["candidates"]

    booking = await _tool(
        client,
        headers,
        "book_appointment",
        {
            "reference": "Casa Roble",
            "start": slots["candidates"][0]["start"],
            "attendee_name": "Cliente Demo",
        },
    )
    assert booking["result"] == "confirmed"
    return TurnResult(
        text="Hermes draft: la cita quedó lista.",
        tools_used=["get_available_slots", "book_appointment"],
    )


@pytest.fixture
async def database():
    database = Database(DATABASE_URL)
    await _truncate(database)
    try:
        yield database
    finally:
        await _truncate(database)
        await database.dispose()


async def test_whatsapp_lead_booking_reaches_telegram_without_provider_tokens(
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        DATABASE_URL=DATABASE_URL,
        HERMES_DASHBOARD_SESSION_TOKEN="offline-hermes-token",
        PLUGIN_API_TOKEN=PLUGIN_TOKEN,
        META_APP_SECRET=APP_SECRET,
        META_VERIFY_TOKEN="offline-verify-token",
        META_ACCESS_TOKEN="",
        META_PHONE_NUMBER_ID="",
        ANTHROPIC_API_KEY="",
        GOOGLE_CALENDAR_CREDENTIALS="",
        GOOGLE_CALENDAR_ID="",
        TELEGRAM_BOT_TOKEN="",
        TELEGRAM_ADMIN_IDS="",
        ARTIFACT_ROOT=str(tmp_path / "artifacts"),
        WORKER_ENABLED=False,
    )
    monkeypatch.setattr(webhook_api, "get_settings", lambda: settings)
    monkeypatch.setattr(plugin_api, "get_settings", lambda: settings)

    app = create_app(settings)
    calendar = StubCalendar()
    whatsapp = StubWhatsApp()
    telegram = StubTelegram()
    app.state.database = database
    app.state.artifacts = ArtifactStore(tmp_path / "artifacts")
    # A shared stub answers both the calendar port and the directory the
    # scheduling module now takes, which is the honest double for the
    # one-calendar setup these suites are about.
    app.state.calendar = calendar
    app.state.calendars = calendar
    app.state.appointment_policy = AppointmentPolicy(
        schedule=SCHEDULE,
        visit_minutes=90,
        horizon_days=8,
        max_candidates=6,
        day_of_reminder_hour=9,
    )

    async with database.session_scope() as session:
        # A team that can actually receive a visit. Stage 3 refuses to quote
        # availability or confirm an appointment without a Responsible Advisor
        # who has an authoritative calendar, so the vertical scenario has to
        # provision one before the first message arrives.
        await commercial.provision_bookable_team(session)
        await PropertyService(session, app.state.artifacts).accept_upload(
            "casa-roble.md", CASA_ROBLE, actor_id="offline-developer"
        )

    worker = WhatsAppWorker(
        database=database,
        hermes=object(),  # type: ignore[arg-type]
        whatsapp=whatsapp,  # type: ignore[arg-type]
        sales_profile="sales",
        schedule=SCHEDULE,
    )
    notifier = BrokerNotifier(
        database=database,
        telegram=telegram,  # type: ignore[arg-type]
        chat_ids=frozenset({"offline-admin"}),
        schedule=SCHEDULE,
        digest_hour=8,
        reminder_minutes=90,
    )

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        # Each scripted turn replaces only the Model's judgment; the tools it
        # calls are the real authenticated Product tools. Exhausting the script
        # is a clearer failure than an unexpected extra turn silently passing.
        turns = iter((_answer_property_question, _book_a_visit))

        async def scripted_turn(hermes, role_session, prompt, **kwargs):  # noqa: ANN001
            durable = role_session.hermes_session_id or DURABLE_SESSION
            if not role_session.hermes_session_id:
                await kwargs["on_attached"](durable)
            headers = {
                "Authorization": f"Bearer {PLUGIN_TOKEN}",
                SESSION_HEADER: durable,
            }
            result = await next(turns)(client, headers)
            result.hermes_session_id = durable
            return result

        monkeypatch.setattr(worker_module, "run_turn", scripted_turn)

        first = webhooks.text_message(
            wamid="wamid.OFFLINE.LEAD.1",
            body="Hola, vi Casa Roble. Me interesa saber más info",
        )
        response = await _post_signed(client, first)
        assert response.json() == {
            "result": "ok",
            "accepted": 1,
            "duplicates": 0,
            "statuses": 0,
        }
        duplicate = await _post_signed(client, first)
        assert duplicate.json()["duplicates"] == 1

        await age_pending_inbox(database)
        await worker.tick()
        assert len(whatsapp.sent) == 1
        assert "*Casa Roble*" in whatsapp.sent[0].body
        assert "*4 recámaras*" in whatsapp.sent[0].body
        assert "**" not in whatsapp.sent[0].body

        second = webhooks.text_message(
            wamid="wamid.OFFLINE.LEAD.2",
            body="Sí, quiero agendar una visita",
        )
        assert (await _post_signed(client, second)).json()["accepted"] == 1
        await age_pending_inbox(database)
        await worker.tick()

        assert len(whatsapp.sent) == 2
        confirmation = whatsapp.sent[1]
        assert "quedó confirmada" in confirmation.body
        assert "Hermes draft" not in confirmation.body

        await notifier.tick()
        assert len(telegram.sent) == 1
        assert telegram.sent[0].chat_id == "offline-admin"
        assert "Nueva visita agendada" in telegram.sent[0].body
        assert "Casa Roble" in telegram.sent[0].body

        delivered = webhooks.status_update(
            provider_message_id=confirmation.provider_message_id, status="delivered"
        )
        response = await _post_signed(client, delivered)
        assert response.json()["statuses"] == 1

    async with database.session_scope() as session:
        inbox = await _rows(session, select(InboxMessage))
        groups = await _rows(session, select(InboxGroup))
        outbox = await _rows(session, select(OutboxMessage).order_by(OutboxMessage.created_at))
        appointments = await _rows(session, select(Appointment))
        deliveries = await _rows(session, select(DeliveryStatus))
        sessions = await _rows(session, select(AgentSession))
        snapshots = await _rows(session, select(AvailabilitySnapshot))
        audit_actions = await _rows(session, select(AuditEvent.action))

        assert [row.status for row in inbox] == [
            InboxStatus.PROCESSED.value,
            InboxStatus.PROCESSED.value,
        ]
        assert all(row.status == InboxGroupStatus.SETTLED.value for row in groups)
        assert [row.kind for row in outbox] == ["AgentReply", "AppointmentConfirmation"]
        assert all(row.status == OutboxStatus.SENT.value for row in outbox)
        assert len(appointments) == 1
        appointment = appointments[0]
        assert appointment.status == AppointmentStatus.CONFIRMED.value
        assert appointment.calendar_event_id == f"evt-{appointment.reference}"
        assert appointment.lead_notice_at is not None
        assert appointment.booked_notice_at is not None
        assert len(deliveries) == 1
        assert deliveries[0].outbox_id == outbox[1].id
        assert deliveries[0].status == "delivered"
        assert [row.hermes_session_id for row in sessions] == [DURABLE_SESSION]
        assert len(snapshots) == 1
        assert "PropertyInformationRequested" in audit_actions

    assert calendar.created == [appointments[0].reference]
