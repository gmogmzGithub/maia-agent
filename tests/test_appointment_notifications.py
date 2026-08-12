"""What a booking causes afterwards: one message to the Lead, three to the Broker.

Two separate obligations are asserted here, because they fail differently.

The Lead's message is deterministic product text released through the Outbox in
place of the Model's draft, exactly once per outcome. The risk it guards against
is the Model narrating a booking — describing an inconclusive attempt as
confirmed, or quoting a time it did not get from the persisted row.

The Broker's three notifications (amendment 2) are internal Telegram messages.
The risk there is the opposite one: silence. So they are stamped only after
Telegram accepts them, and the tests cover the awkward cases — a visit booked
after the morning digest already went out, and a reminder whose window elapsed
while the process was down.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select

from realestate.channels.whatsapp.client import SendOutcome, SendResult
from realestate.channels.whatsapp.payload import parse_webhook
from realestate.db.engine import Database
from realestate.db.models import (
    AgentSession,
    Appointment,
    AppointmentStatus,
    AvailabilitySnapshot,
    Conversation,
    InboxGroup,
    InboxMessage,
    InboxStatus,
    Lead,
    LeadEngagementCycle,
    OutboxMessage,
    Property,
)
from realestate.domain.appointments import NEEDS_REVIEW_MESSAGE
from realestate.domain.availability import WeeklySchedule
from realestate.domain.inbox import InboxService
from realestate.domain.notifications import (
    BOOKED,
    DIGEST,
    REMINDER,
    BrokerNotificationService,
)
from realestate.domain.properties import ArtifactStore, PropertyService
from realestate.hermes.sessions import TurnResult
from realestate.worker import whatsapp as worker_module
from realestate.worker.broker import BrokerNotifier
from realestate.worker.whatsapp import WhatsAppWorker
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures import webhooks

FIXTURES = Path(__file__).parent / "fixtures"
CASA_ROBLE = (FIXTURES / "casa-roble.md").read_bytes()

pytestmark = requires_postgres

SPEC = (
    "mon=09:00-17:00;tue=09:00-17:00;wed=09:00-17:00;thu=09:00-17:00;"
    "fri=09:00-17:00;sat=10:00-17:00;sun=10:00-17:00"
)
SCHEDULE = WeeklySchedule.parse(SPEC, "America/Mexico_City")
ZONE = ZoneInfo("America/Mexico_City")

DIGEST_HOUR = 8
REMINDER_MINUTES = 90


# --- Fixtures -----------------------------------------------------------------


class StubTelegram:
    """Records every send; ``accepts`` decides whether Telegram takes them."""

    def __init__(self, *, accepts: bool = True) -> None:
        self.sent: list[tuple[str, str]] = []
        self.accepts = accepts
        self.configured = True

    async def send_message(self, chat_id: str, text: str) -> bool:
        self.sent.append((chat_id, text))
        return self.accepts


class StubWhatsApp:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_text(self, to_wa_id: str, body: str) -> SendResult:
        self.sent.append((to_wa_id, body))
        return SendResult(SendOutcome.SENT, provider_message_id=f"wamid.{len(self.sent)}")


@pytest.fixture
async def database(tmp_path: Path):
    db = Database(DATABASE_URL)
    async with db.session_scope() as session:
        for model in (
            Appointment,
            AvailabilitySnapshot,
            OutboxMessage,
            InboxMessage,
            InboxGroup,
            AgentSession,
            Conversation,
            LeadEngagementCycle,
            Lead,
            Property,
        ):
            await session.execute(delete(model))
        await session.commit()

    artifacts = ArtifactStore(tmp_path / "artifacts")
    async with db.session_scope() as session:
        await PropertyService(session, artifacts).accept_upload(
            "casa-roble.md", CASA_ROBLE, actor_id="developer"
        )
    yield db
    await db.dispose()


@pytest.fixture
def stub_hermes(monkeypatch: pytest.MonkeyPatch):
    """A Hermes turn that answers with whatever the test puts in ``reply``."""
    state: dict = {"reply": "Perfecto, ya te agendé la visita. ¡Nos vemos!"}

    async def fake_run_turn(client, session, text, **kwargs):
        durable = session.hermes_session_id
        if not durable:
            durable = f"durable-{uuid.uuid4().hex[:8]}"
            if on_attached := kwargs.get("on_attached"):
                await on_attached(durable)
        return TurnResult(
            text=state["reply"], tools_used=[], injected=[], hermes_session_id=durable
        )

    monkeypatch.setattr(worker_module, "run_turn", fake_run_turn)
    return state


async def a_conversation(database, *, body: str = "hola") -> tuple[Conversation, Lead]:
    """One inbound WhatsApp message, aged past the collection window."""
    message = parse_webhook(
        webhooks.text_message(wamid=f"w-{uuid.uuid4().hex[:8]}", body=body)
    ).messages[0]
    async with database.session_scope() as session:
        await InboxService(session).accept(message)
    async with database.session_scope() as session:
        for row in (await session.execute(select(InboxMessage))).scalars():
            if row.status == InboxStatus.PENDING.value:
                row.persisted_at = row.persisted_at - timedelta(seconds=10)
                row.next_attempt_at = None
        conversation = (await session.execute(select(Conversation))).scalar_one()
        lead = (await session.execute(select(Lead))).scalar_one()
        await session.commit()
        return conversation, lead


async def an_appointment(
    database,
    *,
    starts_at: datetime,
    status: str = AppointmentStatus.CONFIRMED.value,
    attendee_name: str | None = "Juan Pérez",
    reference: str | None = None,
) -> Appointment:
    async with database.session_scope() as session:
        conversation = (await session.execute(select(Conversation))).scalar_one()
        prop = (await session.execute(select(Property))).scalar_one()
        row = Appointment(
            reference=reference or f"APT-{uuid.uuid4().hex[:6].upper()}",
            idempotency_key=f"apt:{uuid.uuid4()}",
            conversation_id=conversation.id,
            lead_id=conversation.lead_id,
            property_uuid=prop.id,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=90),
            attendee_name=attendee_name,
            status=status,
            calendar_event_id="evt-1" if status == AppointmentStatus.CONFIRMED.value else None,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        session.expunge(row)
        return row


def notifications(session) -> BrokerNotificationService:  # noqa: ANN001
    return BrokerNotificationService(
        session,
        SCHEDULE,
        digest_hour=DIGEST_HOUR,
        reminder_minutes=REMINDER_MINUTES,
    )


def build_worker(database, whatsapp) -> WhatsAppWorker:
    return WhatsAppWorker(
        database=database,
        hermes=object(),
        whatsapp=whatsapp,
        sales_profile="sales",
        schedule=SCHEDULE,
    )


def build_notifier(database, telegram, chat_ids=frozenset({"111"})) -> BrokerNotifier:
    return BrokerNotifier(
        database=database,
        telegram=telegram,  # type: ignore[arg-type]
        chat_ids=chat_ids,
        schedule=SCHEDULE,
        digest_hour=DIGEST_HOUR,
        reminder_minutes=REMINDER_MINUTES,
    )


async def reload(database, appointment_id: uuid.UUID) -> Appointment:
    async with database.session_scope() as session:
        return await session.get(Appointment, appointment_id)


# --- What the Lead receives ---------------------------------------------------


async def test_a_confirmed_booking_replaces_the_draft_with_the_confirmation(
    database, stub_hermes
) -> None:
    """The Lead is told about the appointment by the product, not by the Model."""
    await a_conversation(database)
    start = datetime(2026, 8, 14, 13, 0, tzinfo=ZONE)
    await an_appointment(database, starts_at=start)

    whatsapp = StubWhatsApp()
    await build_worker(database, whatsapp).tick()

    assert len(whatsapp.sent) == 1
    _, body = whatsapp.sent[0]
    # Rendered from the persisted row, in the Broker's zone.
    assert body == (
        "Tu cita para visitar Casa Roble quedó confirmada para el 14/08/2026 "
        "a las 13:00. Si necesitas cambiarla, responde a este mensaje."
    )
    # And the Model's own account of the booking never left the process.
    assert stub_hermes["reply"] not in body

    async with database.session_scope() as session:
        outbox = (await session.execute(select(OutboxMessage))).scalar_one()
    assert outbox.kind == "AppointmentConfirmation"


async def test_the_confirmation_is_released_exactly_once(database, stub_hermes) -> None:
    await a_conversation(database)
    appointment = await an_appointment(
        database, starts_at=datetime(2026, 8, 14, 13, 0, tzinfo=ZONE)
    )

    whatsapp = StubWhatsApp()
    worker = build_worker(database, whatsapp)
    await worker.tick()

    # The Lead writes again; that turn is an ordinary reply, not a second
    # confirmation.
    await a_conversation(database, body="gracias!")
    stub_hermes["reply"] = "¡Con gusto! Cualquier cosa aquí estoy."
    await worker.tick()

    assert len(whatsapp.sent) == 2
    assert "quedó confirmada" in whatsapp.sent[0][1]
    assert whatsapp.sent[1][1] == "¡Con gusto! Cualquier cosa aquí estoy."
    assert (await reload(database, appointment.id)).lead_notice_at is not None


async def test_an_inconclusive_booking_is_never_described_as_confirmed(
    database, stub_hermes
) -> None:
    """P-042: the Model may not turn NeedsReview into confirmation language."""
    await a_conversation(database)
    await an_appointment(
        database,
        starts_at=datetime(2026, 8, 14, 13, 0, tzinfo=ZONE),
        status=AppointmentStatus.NEEDS_REVIEW.value,
    )
    stub_hermes["reply"] = "¡Listo! Tu visita quedó agendada para el viernes."

    whatsapp = StubWhatsApp()
    await build_worker(database, whatsapp).tick()

    assert [body for _, body in whatsapp.sent] == [NEEDS_REVIEW_MESSAGE]


async def test_a_notice_whose_visit_already_passed_is_retired_not_released(
    database, stub_hermes
) -> None:
    """Confirming a visit that already started is worse than saying nothing."""
    await a_conversation(database)
    stale = await an_appointment(
        database, starts_at=datetime.now(tz=UTC) - timedelta(hours=2)
    )

    whatsapp = StubWhatsApp()
    await build_worker(database, whatsapp).tick()

    assert [body for _, body in whatsapp.sent] == [stub_hermes["reply"]]
    # Retired, so it cannot displace the reply to every future message either.
    assert (await reload(database, stale.id)).lead_notice_at is not None


async def test_a_pending_attempt_says_nothing_to_the_lead(database, stub_hermes) -> None:
    """An attempt still in flight is not an outcome, so it is not announced."""
    await a_conversation(database)
    await an_appointment(
        database,
        starts_at=datetime(2026, 8, 14, 13, 0, tzinfo=ZONE),
        status=AppointmentStatus.PENDING.value,
    )

    whatsapp = StubWhatsApp()
    await build_worker(database, whatsapp).tick()

    assert [body for _, body in whatsapp.sent] == [stub_hermes["reply"]]


# --- What the Broker receives -------------------------------------------------


async def test_a_booking_notifies_the_broker_immediately_and_once(database) -> None:
    await a_conversation(database)
    appointment = await an_appointment(
        database, starts_at=datetime(2026, 8, 14, 13, 0, tzinfo=ZONE)
    )

    telegram = StubTelegram()
    notifier = build_notifier(database, telegram)
    await notifier.tick()
    await notifier.tick()

    assert len(telegram.sent) == 1
    chat_id, body = telegram.sent[0]
    assert chat_id == "111"
    assert "Nueva visita agendada" in body
    assert "Casa Roble" in body
    assert "viernes 14/08 a las 13:00" in body
    assert "Juan Pérez" in body
    assert f"+{webhooks.LEAD_WA_ID}" in body
    assert appointment.reference in body
    assert (await reload(database, appointment.id)).booked_notice_at is not None


async def test_an_inconclusive_booking_asks_the_broker_to_check_calendar(
    database,
) -> None:
    await a_conversation(database)
    await an_appointment(
        database,
        starts_at=datetime(2026, 8, 14, 13, 0, tzinfo=ZONE),
        status=AppointmentStatus.NEEDS_REVIEW.value,
    )

    telegram = StubTelegram()
    await build_notifier(database, telegram).tick()

    body = telegram.sent[0][1]
    assert "requiere revisión" in body
    assert "Google Calendar" in body
    # It must not read as a booking the Broker can rely on.
    assert "Nueva visita agendada" not in body


async def test_the_morning_digest_lists_the_day_once(database) -> None:
    await a_conversation(database)
    today = datetime.now(tz=ZONE).date()
    first = datetime.combine(today, datetime.min.time(), tzinfo=ZONE).replace(hour=11)
    second = first.replace(hour=15, minute=30)
    await an_appointment(database, starts_at=first, attendee_name="Ana")
    await an_appointment(database, starts_at=second, attendee_name="Beto")

    at_digest_hour = datetime.combine(
        today, datetime.min.time(), tzinfo=ZONE
    ).replace(hour=DIGEST_HOUR)

    async with database.session_scope() as session:
        service = notifications(session)
        # Everything is unsent, so this includes the two immediate notices too.
        due = await service.due(at_digest_hour)
        digests = [n for n in due if n.kind == DIGEST]
        assert len(digests) == 1
        assert "Visitas de hoy" in digests[0].body
        assert "11:00 — Casa Roble — Ana" in digests[0].body
        assert "15:30 — Casa Roble — Beto" in digests[0].body

        await service.mark_sent(digests[0], at_digest_hour)
        assert [n for n in await service.due(at_digest_hour) if n.kind == DIGEST] == []


async def test_the_digest_waits_for_the_digest_hour(database) -> None:
    await a_conversation(database)
    today = datetime.now(tz=ZONE).date()
    midnight = datetime.combine(today, datetime.min.time(), tzinfo=ZONE)
    await an_appointment(database, starts_at=midnight.replace(hour=11))

    async with database.session_scope() as session:
        early = await notifications(session).due(midnight.replace(hour=DIGEST_HOUR - 1))
    assert [n.kind for n in early] == [BOOKED]


async def test_a_visit_booked_after_the_digest_does_not_trigger_a_second_one(
    database,
) -> None:
    """The immediate notice already told the Broker; a digest of one is noise."""
    await a_conversation(database)
    today = datetime.now(tz=ZONE).date()
    midnight = datetime.combine(today, datetime.min.time(), tzinfo=ZONE)
    late_booking = midnight.replace(hour=11)
    booked_at = midnight.replace(hour=10)  # after the 08:00 digest went out
    appointment = await an_appointment(database, starts_at=late_booking)

    async with database.session_scope() as session:
        service = notifications(session)
        immediate = [n for n in await service.due(booked_at) if n.kind == BOOKED]
        await service.mark_sent(immediate[0], booked_at)

    async with database.session_scope() as session:
        again = await notifications(session).due(booked_at)
    assert [n.kind for n in again if n.kind == DIGEST] == []
    assert (await reload(database, appointment.id)).digest_sent_on == today.strftime(
        "%Y-%m-%d"
    )


async def test_a_reminder_fires_inside_the_window_and_only_once(database) -> None:
    await a_conversation(database)
    start = datetime.now(tz=UTC) + timedelta(minutes=60)
    appointment = await an_appointment(database, starts_at=start)

    telegram = StubTelegram()
    notifier = build_notifier(database, telegram)
    await notifier.tick()  # the immediate notice, today's digest, the reminder
    await notifier.tick()

    reminders = [b for _, b in telegram.sent if b.startswith("⏰")]
    assert len(reminders) == 1
    assert "Visita en 59 min" in reminders[0] or "Visita en 60 min" in reminders[0]
    assert (await reload(database, appointment.id)).reminder_sent_at is not None


async def test_a_visit_outside_the_window_is_not_reminded_yet(database) -> None:
    await a_conversation(database)
    start = datetime.now(tz=UTC) + timedelta(minutes=REMINDER_MINUTES + 30)
    await an_appointment(database, starts_at=start)

    async with database.session_scope() as session:
        due = await notifications(session).due()
    assert REMINDER not in [n.kind for n in due]


async def test_a_reminder_whose_visit_started_is_dropped_not_sent_late(
    database,
) -> None:
    """A reminder after the fact is not a reminder. It is retired silently."""
    await a_conversation(database)
    start = datetime.now(tz=UTC) - timedelta(minutes=10)
    appointment = await an_appointment(database, starts_at=start)

    telegram = StubTelegram()
    await build_notifier(database, telegram).tick()

    assert not any(b.startswith("⏰") for _, b in telegram.sent)
    assert (await reload(database, appointment.id)).reminder_sent_at is not None


async def test_a_rejected_telegram_send_leaves_the_notice_owed(database) -> None:
    await a_conversation(database)
    appointment = await an_appointment(
        database, starts_at=datetime(2026, 8, 14, 13, 0, tzinfo=ZONE)
    )

    telegram = StubTelegram(accepts=False)
    notifier = build_notifier(database, telegram)
    await notifier.tick()

    assert len(telegram.sent) == 1
    assert (await reload(database, appointment.id)).booked_notice_at is None

    # And the failure backs the whole tick off rather than retrying every second.
    await notifier.tick()
    assert len(telegram.sent) == 1

    telegram.accepts = True
    notifier._retry_after = None  # the backoff elapsing
    await notifier.tick()
    assert len(telegram.sent) == 2
    assert (await reload(database, appointment.id)).booked_notice_at is not None


async def test_one_unreachable_administrator_does_not_block_the_others(
    database,
) -> None:
    """A bot cannot message someone who never opened a chat with it.

    Requiring every recipient to accept would turn that permanent condition into
    a message to the reachable administrator on every single tick.
    """
    await a_conversation(database)
    appointment = await an_appointment(
        database, starts_at=datetime(2026, 8, 14, 13, 0, tzinfo=ZONE)
    )

    class OneDeadChat(StubTelegram):
        async def send_message(self, chat_id: str, text: str) -> bool:
            self.sent.append((chat_id, text))
            return chat_id != "222"

    telegram = OneDeadChat()
    notifier = build_notifier(database, telegram, chat_ids=frozenset({"111", "222"}))
    await notifier.tick()
    await notifier.tick()

    assert [chat for chat, _ in telegram.sent] == ["111", "222"]
    assert (await reload(database, appointment.id)).booked_notice_at is not None


async def test_nothing_is_sent_without_an_allowlisted_administrator(database) -> None:
    await a_conversation(database)
    await an_appointment(database, starts_at=datetime(2026, 8, 14, 13, 0, tzinfo=ZONE))

    telegram = StubTelegram()
    await build_notifier(database, telegram, chat_ids=frozenset()).tick()

    assert telegram.sent == []


async def test_stamping_a_notice_whose_appointment_vanished_is_a_no_op(
    database,
) -> None:
    """The notice is built in one unit of work and stamped in another after
    Telegram accepts it. If the row went away in between — a Property deleted,
    a cycle cascaded — the stamp must skip it rather than fail the whole batch
    and re-send every notice beside it."""
    from realestate.domain.notifications import BrokerNotice

    await a_conversation(database)
    appointment = await an_appointment(
        database, starts_at=datetime.now(tz=UTC) + timedelta(days=1)
    )

    notice = BrokerNotice(
        kind=BOOKED,
        body="Nueva visita agendada.",
        appointment_ids=[uuid.uuid4(), appointment.id],
    )

    async with database.session_scope() as session:
        await notifications(session).mark_sent(notice)

    # The surviving appointment was still stamped.
    assert (await reload(database, appointment.id)).booked_notice_at is not None
