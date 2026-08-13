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
from zoneinfo import ZoneInfo

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from realestate.api import plugin as plugin_api
from realestate.api import webhooks as webhook_api
from realestate.api.plugin import SESSION_HEADER
from realestate.app import create_app
from realestate.channels.google.calendar import BusyResult, CalendarOutcome, EventResult
from realestate.channels.whatsapp.client import SendOutcome, SendResult
from realestate.channels.whatsapp.signature import SIGNATURE_HEADER, compute_signature
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
from realestate.domain.availability import Interval, WeeklySchedule
from realestate.domain.properties import ArtifactStore, PropertyService
from realestate.hermes.sessions import TurnResult
from realestate.worker import whatsapp as worker_module
from realestate.worker.broker import BrokerNotifier
from realestate.worker.whatsapp import WhatsAppWorker
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures import webhooks

pytestmark = requires_postgres

FIXTURES = Path(__file__).parent / "fixtures"
CASA_ROBLE = (FIXTURES / "casa-roble.md").read_bytes()
APP_SECRET = "offline-meta-app-secret"
PLUGIN_TOKEN = "offline-plugin-token"
DURABLE_SESSION = "offline-sales-session"
ZONE = ZoneInfo("America/Mexico_City")
SPEC = (
    "mon=09:00-17:00;tue=09:00-17:00;wed=09:00-17:00;thu=09:00-17:00;"
    "fri=09:00-17:00;sat=10:00-17:00;sun=10:00-17:00"
)
SCHEDULE = WeeklySchedule.parse(SPEC, "America/Mexico_City")


class FakeCalendar:
    """A conclusive empty Calendar which records the event Maia creates."""

    def __init__(self) -> None:
        self.created: list[str] = []

    async def busy_between(self, start, end) -> BusyResult:  # noqa: ANN001
        return BusyResult(CalendarOutcome.OK, [])

    async def is_free(self, slot: Interval) -> BusyResult:
        return BusyResult(CalendarOutcome.OK, [])

    async def create_event(
        self, *, slot, summary, description, reference  # noqa: ANN001
    ) -> EventResult:
        self.created.append(reference)
        return EventResult(CalendarOutcome.OK, event_id=f"evt-{reference}")


class FakeWhatsApp:
    """Accepts Product Outbox sends without contacting Meta."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send_text(self, to_wa_id: str, body: str) -> SendResult:
        provider_id = f"wamid.OFFLINE.{len(self.sent) + 1}"
        self.sent.append((to_wa_id, body, provider_id))
        return SendResult(SendOutcome.SENT, provider_message_id=provider_id)


class FakeTelegram:
    """Accepts Broker notices without contacting Telegram."""

    configured = True

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_message(self, chat_id: str, body: str) -> bool:
        self.sent.append((chat_id, body))
        return True


async def _truncate(database: Database) -> None:
    """Reset only the dedicated test database, including future mapped tables."""
    name = make_url(DATABASE_URL).database or ""
    assert name.endswith("_test"), f"refusing to truncate non-test database {name!r}"
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.tables.values())
    async with database.session_scope() as session:
        await session.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
        await session.commit()


async def _age_pending(database: Database) -> None:
    """Move new webhook rows beyond the real reconciliation window."""
    async with database.session_scope() as session:
        rows = (await session.execute(select(InboxMessage))).scalars().all()
        for row in rows:
            if row.status == InboxStatus.PENDING.value:
                row.persisted_at -= timedelta(seconds=10)
                row.next_attempt_at = None
        await session.commit()


async def _post_signed(client: httpx.AsyncClient, payload: dict) -> httpx.Response:
    raw = webhooks.encode(payload)
    return await client.post(
        webhook_api.WEBHOOK_PATH,
        content=raw,
        headers={
            SIGNATURE_HEADER: compute_signature(APP_SECRET, raw),
            "Content-Type": "application/json",
        },
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
    calendar = FakeCalendar()
    whatsapp = FakeWhatsApp()
    telegram = FakeTelegram()
    app.state.database = database
    app.state.artifacts = ArtifactStore(tmp_path / "artifacts")
    app.state.calendar = calendar
    app.state.appointment_policy = AppointmentPolicy(
        schedule=SCHEDULE,
        visit_minutes=90,
        horizon_days=8,
        max_candidates=6,
    )

    async with database.session_scope() as session:
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
        calls = 0

        async def scripted_turn(hermes, role_session, prompt, **kwargs):  # noqa: ANN001
            """Replace only model judgment; exercise its real typed tools."""
            nonlocal calls
            calls += 1
            durable = role_session.hermes_session_id or DURABLE_SESSION
            if not role_session.hermes_session_id:
                await kwargs["on_attached"](durable)
            headers = {
                "Authorization": f"Bearer {PLUGIN_TOKEN}",
                SESSION_HEADER: durable,
            }

            if calls == 1:
                response = await client.post(
                    "/internal/plugin/tools/get_property_information",
                    headers=headers,
                    json={"reference": "Casa Roble"},
                )
                result = response.json()
                assert response.status_code == 200
                assert result["result"] == "found"
                assert result["name"] == "Casa Roble"
                return TurnResult(
                    text=(
                        "Casa Roble está en Zapopan, tiene 4 recámaras y cuesta "
                        "$3,000,000 MXN. ¿Quieres agendar una visita?"
                    ),
                    tools_used=["get_property_information"],
                    hermes_session_id=durable,
                )

            assert calls == 2
            target = datetime.now(tz=ZONE).date() + timedelta(days=2)
            response = await client.post(
                "/internal/plugin/tools/get_available_slots",
                headers=headers,
                json={
                    "reference": "Casa Roble",
                    "date_from": target.isoformat(),
                    "date_to": target.isoformat(),
                },
            )
            slots = response.json()
            assert response.status_code == 200
            assert slots["result"] == "available"
            assert slots["candidates"]

            response = await client.post(
                "/internal/plugin/tools/book_appointment",
                headers=headers,
                json={
                    "reference": "Casa Roble",
                    "start": slots["candidates"][0]["start"],
                    "attendee_name": "Cliente Demo",
                },
            )
            booking = response.json()
            assert response.status_code == 200
            assert booking["result"] == "confirmed"
            return TurnResult(
                text="Hermes draft: la cita quedó lista.",
                tools_used=["get_available_slots", "book_appointment"],
                hermes_session_id=durable,
            )

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

        await _age_pending(database)
        await worker.tick()
        assert len(whatsapp.sent) == 1
        assert "4 recámaras" in whatsapp.sent[0][1]

        second = webhooks.text_message(
            wamid="wamid.OFFLINE.LEAD.2",
            body="Sí, quiero agendar una visita",
        )
        assert (await _post_signed(client, second)).json()["accepted"] == 1
        await _age_pending(database)
        await worker.tick()

        assert len(whatsapp.sent) == 2
        assert "quedó confirmada" in whatsapp.sent[1][1]
        assert "Hermes draft" not in whatsapp.sent[1][1]

        await notifier.tick()
        assert len(telegram.sent) == 1
        assert telegram.sent[0][0] == "offline-admin"
        assert "Nueva visita agendada" in telegram.sent[0][1]
        assert "Casa Roble" in telegram.sent[0][1]

        delivered = webhooks.status_update(
            provider_message_id=whatsapp.sent[1][2], status="delivered"
        )
        response = await _post_signed(client, delivered)
        assert response.json()["statuses"] == 1

    async with database.session_scope() as session:
        inbox = (await session.execute(select(InboxMessage))).scalars().all()
        groups = (await session.execute(select(InboxGroup))).scalars().all()
        outbox = (
            (await session.execute(select(OutboxMessage).order_by(OutboxMessage.created_at)))
            .scalars()
            .all()
        )
        appointments = (await session.execute(select(Appointment))).scalars().all()
        deliveries = (await session.execute(select(DeliveryStatus))).scalars().all()
        sessions = (await session.execute(select(AgentSession))).scalars().all()
        snapshots = (await session.execute(select(AvailabilitySnapshot))).scalars().all()
        audit_actions = (await session.execute(select(AuditEvent.action))).scalars().all()

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
