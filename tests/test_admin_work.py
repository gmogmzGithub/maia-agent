"""Checkpoint 5 business recovery and manual-resolution workflows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import httpx
from httpx import ASGITransport
from sqlalchemy import delete, select

from realestate.channels.google.calendar import CalendarOutcome, EventResult
from realestate.channels.whatsapp.payload import parse_webhook
from realestate.db.engine import Database
from realestate.db.models import (
    AgentRole,
    AgentSession,
    Appointment,
    AppointmentStatus,
    AuditEvent,
    Conversation,
    InboxGroup,
    InactiveReviewStatus,
    InboxMessage,
    Lead,
    LeadEngagementCycle,
    LeadNotificationStatus,
    OutboxMessage,
    Property,
)
from realestate.domain.admin_work import AdminWorkService
from realestate.domain.administration import AdministrationService, Administrator
from realestate.domain.appointments import AppointmentPolicy
from realestate.domain.availability import WeeklySchedule
from realestate.domain.inbox import InboxService
from realestate.domain.properties import ArtifactStore, PropertyService
from realestate.app import create_app
from realestate.config import get_settings
from tests.conftest import DATABASE_URL, env, requires_postgres, reset_property_inventory
from tests.fixtures import webhooks

pytestmark = requires_postgres

FIXTURES = Path(__file__).parent / "fixtures"
V1 = (FIXTURES / "casa-roble.md").read_bytes()
SPEC = (
    "mon=09:00-17:00;tue=09:00-17:00;wed=09:00-17:00;thu=09:00-17:00;"
    "fri=09:00-17:00;sat=10:00-17:00;sun=10:00-17:00"
)


class StubCalendar:
    def __init__(self) -> None:
        self.result = EventResult(CalendarOutcome.OK)

    async def find_by_reference(self, reference: str) -> EventResult:
        return self.result


@pytest.fixture
async def recovery(tmp_path: Path):
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await reset_property_inventory(session)
        for model in (
            OutboxMessage,
            InboxMessage,
            InboxGroup,
            Conversation,
            LeadEngagementCycle,
            Lead,
        ):
            await session.execute(delete(model))
        await session.execute(delete(AuditEvent))
        await session.commit()
        await PropertyService(session, ArtifactStore(tmp_path / "artifacts")).accept_upload(
            "casa-roble.md", V1, actor_id="developer"
        )
        message = parse_webhook(
            webhooks.text_message(wamid="w-recovery", body="quiero una cita")
        ).messages[0]
        await InboxService(session).accept(message)

    calendar = StubCalendar()
    schedule = WeeklySchedule.parse(SPEC, "America/Mexico_City")
    yield database, calendar, schedule
    await database.dispose()


async def appointment(database: Database, *, status: str) -> Appointment:
    async with database.session_scope() as session:
        conversation = (await session.execute(select(Conversation))).scalar_one()
        lead = (await session.execute(select(Lead))).scalar_one()
        prop = (await session.execute(select(Property))).scalar_one()
        start = datetime.now(tz=UTC) + timedelta(days=2)
        row = Appointment(
            reference=f"APT-{status.upper()}",
            idempotency_key=f"apt:test:{status}",
            conversation_id=conversation.id,
            lead_id=lead.id,
            property_uuid=prop.id,
            starts_at=start,
            ends_at=start + timedelta(minutes=90),
            status=status,
        )
        session.add(row)
        await session.commit()
        return row


async def test_matching_calendar_evidence_confirms_and_queues_one_lead_notice(
    recovery,
) -> None:
    database, calendar, schedule = recovery
    row = await appointment(database, status=AppointmentStatus.NEEDS_REVIEW.value)
    calendar.result = EventResult(
        CalendarOutcome.OK,
        event_id="evt-1",
        start=row.starts_at,
        end=row.ends_at,
        summary="Visita — Casa Roble — Ana",
    )

    async with database.session_scope() as session:
        result = await AdminWorkService(session, calendar, schedule).resolve(
            row.reference, "Confirm", Administrator("telegram:1", "update:1")
        )

    assert result["result"] == "resolved"
    assert result["outcome"] == "Confirmed"
    assert result["lead_notification"] == "Queued"
    async with database.session_scope() as session:
        saved = await session.get(Appointment, row.id)
        outbox = (await session.execute(select(OutboxMessage))).scalars().all()
        audit = (await session.execute(select(AuditEvent))).scalars().all()
    assert saved.status == AppointmentStatus.CONFIRMED.value
    assert saved.resolution_notification_status == LeadNotificationStatus.QUEUED.value
    assert len(outbox) == 1
    assert audit[-1].actor_id == "telegram:1"
    assert audit[-1].details["origin_message_id"] == "update:1"


async def test_contradictory_or_unavailable_evidence_preserves_needs_review(
    recovery,
) -> None:
    database, calendar, schedule = recovery
    row = await appointment(database, status=AppointmentStatus.NEEDS_REVIEW.value)
    calendar.result = EventResult(CalendarOutcome.UNKNOWN, detail="timeout")
    async with database.session_scope() as session:
        ambiguous = await AdminWorkService(session, calendar, schedule).resolve(
            row.reference, "Confirm", Administrator("telegram:1")
        )
    assert ambiguous["result"] == "still_ambiguous"

    calendar.result = EventResult(
        CalendarOutcome.OK,
        event_id="evt-wrong",
        start=row.starts_at + timedelta(hours=1),
        end=row.ends_at + timedelta(hours=1),
        summary="Visita — Casa Roble",
    )
    async with database.session_scope() as session:
        conflict = await AdminWorkService(session, calendar, schedule).resolve(
            row.reference, "Confirm", Administrator("telegram:1")
        )
        saved = await session.get(Appointment, row.id)
    assert conflict["result"] == "conflict"
    assert saved.status == AppointmentStatus.NEEDS_REVIEW.value


async def test_closed_customer_window_creates_manual_notification_work(recovery) -> None:
    database, calendar, schedule = recovery
    row = await appointment(database, status=AppointmentStatus.NEEDS_REVIEW.value)
    async with database.session_scope() as session:
        message = (await session.execute(select(InboxMessage))).scalars().one()
        message.persisted_at = datetime.now(tz=UTC) - timedelta(hours=25)
        await session.commit()
    calendar.result = EventResult(CalendarOutcome.OK)

    async with database.session_scope() as session:
        result = await AdminWorkService(session, calendar, schedule).resolve(
            row.reference, "Reject", Administrator("telegram:1")
        )
        pending = await AdminWorkService(session, calendar, schedule).list_pending()

    assert result["lead_notification"] == "PendingManual"
    assert [item["type"] for item in pending["items"]] == [
        "PendingManualAppointmentNotification"
    ]


async def test_deactivation_opens_review_and_manual_completion_requires_event_absence(
    recovery,
) -> None:
    database, calendar, schedule = recovery
    row = await appointment(database, status=AppointmentStatus.CONFIRMED.value)
    async with database.session_scope() as session:
        changed = await AdministrationService(session).set_property_status(
            "casa-roble",
            "Inactive",
            Administrator("telegram:1"),
            "Unspecified",
        )
    assert changed["affected_confirmed_appointments"] == 1

    async with database.session_scope() as session:
        work = await AdminWorkService(session, calendar, schedule).list_pending()
        first = await AdminWorkService(session, calendar, schedule).resolve(
            row.reference, "HandleManually", Administrator("telegram:1")
        )
    assert work["items"][0]["type"] == "InactivePropertyAppointmentReview"
    assert first["result"] == "resolved"

    calendar.result = EventResult(CalendarOutcome.OK, event_id="still-there")
    async with database.session_scope() as session:
        blocked = await AdminWorkService(session, calendar, schedule).resolve(
            row.reference, "MarkComplete", Administrator("telegram:1")
        )
    assert blocked["result"] == "conflict"

    calendar.result = EventResult(CalendarOutcome.OK)
    async with database.session_scope() as session:
        completed = await AdminWorkService(session, calendar, schedule).resolve(
            row.reference, "MarkComplete", Administrator("telegram:1")
        )
        saved = await session.get(Appointment, row.id)
    assert completed["result"] == "resolved"
    assert saved.status == AppointmentStatus.CANCELLED.value
    assert saved.inactive_review_status == InactiveReviewStatus.COMPLETE.value


async def test_restart_recovery_never_reissues_a_calendar_create(recovery) -> None:
    database, calendar, schedule = recovery
    row = await appointment(database, status=AppointmentStatus.PENDING.value)
    async with database.session_scope() as session:
        count = await AdminWorkService(session, calendar, schedule).recover_pending_attempts()
    assert count == 1
    async with database.session_scope() as session:
        saved = await session.get(Appointment, row.id)
        outbox = (await session.execute(select(OutboxMessage))).scalars().all()
    assert saved.status == AppointmentStatus.NEEDS_REVIEW.value
    assert len(outbox) == 1


async def test_plugin_boundary_allows_admin_and_refuses_sales(recovery) -> None:
    database, calendar, schedule = recovery
    row = await appointment(database, status=AppointmentStatus.NEEDS_REVIEW.value)
    async with database.session_scope() as session:
        await session.execute(delete(AgentSession))
        session.add_all(
            (
                AgentSession(
                    hermes_session_id="admin-recovery",
                    role=AgentRole.ADMINISTRATIVE.value,
                    channel_key="telegram:1",
                ),
                AgentSession(
                    hermes_session_id="sales-recovery", role=AgentRole.SALES.value
                ),
            )
        )
        await session.commit()

    app = create_app(get_settings())
    app.state.database = database
    app.state.calendar = calendar
    app.state.appointment_policy = AppointmentPolicy(
        schedule=schedule, visit_minutes=90, horizon_days=8, max_candidates=6
    )
    auth = {"Authorization": f"Bearer {env('PLUGIN_API_TOKEN')}"}
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        listed = await client.post(
            "/internal/plugin/tools/list_pending_admin_work",
            headers={**auth, "X-Hermes-Session-Id": "admin-recovery"},
            json={},
        )
        forbidden = await client.post(
            "/internal/plugin/tools/resolve_pending_admin_work",
            headers={**auth, "X-Hermes-Session-Id": "sales-recovery"},
            json={"reference": row.reference, "action": "Reject"},
        )
        extra = await client.post(
            "/internal/plugin/tools/resolve_pending_admin_work",
            headers={**auth, "X-Hermes-Session-Id": "admin-recovery"},
            json={"reference": row.reference, "action": "Reject", "sql": "DELETE"},
        )

    assert listed.json()["items"][0]["reference"] == row.reference
    assert forbidden.json() == {"result": "forbidden"}
    assert extra.status_code == 422
