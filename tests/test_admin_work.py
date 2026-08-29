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
from realestate.domain.inbox import InboxService
from realestate.domain.properties import ArtifactStore, PropertyService
from realestate.app import create_app
from realestate.config import get_settings
from tests.conftest import (
    DATABASE_URL,
    env,
    larevia_organization_id,
    requires_postgres,
    reset_property_inventory,
)
from tests.fixtures import commercial, webhooks
from tests.fixtures.stubs import SCHEDULE, StubCalendar

pytestmark = requires_postgres

FIXTURES = Path(__file__).parent / "fixtures"
V1 = (FIXTURES / "casa-roble.md").read_bytes()


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
        # Stage 3 refuses a visit without a Responsible Advisor who has an
        # authoritative calendar, and reconciliation has to happen before the
        # first inbound message because intake assigns as it opens.
        await commercial.provision_bookable_team(session)
        organization = await commercial.organization_id(session)
        await PropertyService(
            session,
            ArtifactStore(tmp_path / "artifacts"),
            organization_id=organization,
        ).accept_upload("casa-roble.md", V1, actor_id="developer")
        message = parse_webhook(
            webhooks.text_message(wamid="w-recovery", body="quiero una cita")
        ).messages[0]
        await InboxService(session).accept(message)

    calendar = StubCalendar()
    schedule = SCHEDULE
    yield database, calendar, schedule
    await database.dispose()


async def appointment(database: Database, *, status: str) -> Appointment:
    async with database.session_scope() as session:
        conversation = (await session.execute(select(Conversation))).scalar_one()
        lead = (await session.execute(select(Lead))).scalar_one()
        prop = (await session.execute(select(Property))).scalar_one()
        start = datetime.now(tz=UTC) + timedelta(days=2)
        row = Appointment(
            organization_id=conversation.organization_id,
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
    calendar.find_result = EventResult(
        CalendarOutcome.OK,
        event_id="evt-1",
        start=row.starts_at,
        end=row.ends_at,
        summary="Visita — Casa Roble — Ana",
    )

    async with database.session_scope() as session:
        result = await AdminWorkService(session, calendar, schedule, day_of_reminder_hour=9).resolve(
            row.reference, "Confirm", Administrator(
                organization_id=row.organization_id,
                actor_id="telegram:1",
                origin_message_id="update:1",
            )
        )

    assert result["result"] == "resolved"
    assert result["outcome"] == "Confirmed"
    assert result["lead_notification"] == "Queued"
    async with database.session_scope() as session:
        saved = await session.get(Appointment, row.id)
        outbox = (await session.execute(select(OutboxMessage))).scalars().all()
        # Selected by what it *is* rather than by position: an unordered
        # ``select`` over the whole audit trail returns rows in whatever order
        # PostgreSQL likes, so "the last one" was only ever the administrator's
        # by luck.
        audit = (
            await session.execute(
                select(AuditEvent)
                .where(
                    AuditEvent.action == "PendingAdminWorkResolutionRequested"
                )
                .where(AuditEvent.subject_id == row.reference)
            )
        ).scalars().all()
    assert saved.status == AppointmentStatus.CONFIRMED.value
    assert saved.resolution_notification_status == LeadNotificationStatus.QUEUED.value
    assert len(outbox) == 1
    assert len(audit) == 1
    assert audit[0].actor_id == "telegram:1"
    assert audit[0].details["origin_message_id"] == "update:1"


async def test_contradictory_or_unavailable_evidence_preserves_needs_review(
    recovery,
) -> None:
    database, calendar, schedule = recovery
    row = await appointment(database, status=AppointmentStatus.NEEDS_REVIEW.value)
    calendar.find_result = EventResult(CalendarOutcome.UNKNOWN, detail="timeout")
    async with database.session_scope() as session:
        ambiguous = await AdminWorkService(session, calendar, schedule, day_of_reminder_hour=9).resolve(
            row.reference, "Confirm", Administrator(organization_id=row.organization_id, actor_id="telegram:1")
        )
    assert ambiguous["result"] == "still_ambiguous"

    calendar.find_result = EventResult(
        CalendarOutcome.OK,
        event_id="evt-wrong",
        start=row.starts_at + timedelta(hours=1),
        end=row.ends_at + timedelta(hours=1),
        summary="Visita — Casa Roble",
    )
    async with database.session_scope() as session:
        conflict = await AdminWorkService(session, calendar, schedule, day_of_reminder_hour=9).resolve(
            row.reference, "Confirm", Administrator(organization_id=row.organization_id, actor_id="telegram:1")
        )
        saved = await session.get(Appointment, row.id)
    assert conflict["result"] == "conflict"
    assert saved.status == AppointmentStatus.NEEDS_REVIEW.value


async def test_admin_resolution_is_idempotent_and_unknown_work_stays_absent(
    recovery,
) -> None:
    """A repeated decision reports durable truth and never replays Calendar."""
    database, calendar, schedule = recovery
    row = await appointment(database, status=AppointmentStatus.CONFIRMED.value)

    async with database.session_scope() as session:
        service = AdminWorkService(session, calendar, schedule, day_of_reminder_hour=9)
        repeated = await service.resolve(
            row.reference, "Confirm", Administrator(organization_id=row.organization_id, actor_id="telegram:1")
        )
        missing = await service.resolve(
            "APT-DOES-NOT-EXIST", "Confirm", Administrator(organization_id=row.organization_id, actor_id="telegram:1")
        )
        invalid = await service.resolve(
            row.reference, "Delete", Administrator(organization_id=row.organization_id, actor_id="telegram:1")
        )

    assert repeated == {
        "result": "already_resolved",
        "reference": row.reference,
        "outcome": AppointmentStatus.CONFIRMED.value,
    }
    assert missing == {"result": "not_found"}
    assert invalid == {"result": "invalid_action"}
    assert calendar.find_reads == 0


async def test_closed_customer_window_creates_manual_notification_work(recovery) -> None:
    database, calendar, schedule = recovery
    row = await appointment(database, status=AppointmentStatus.NEEDS_REVIEW.value)
    async with database.session_scope() as session:
        message = (await session.execute(select(InboxMessage))).scalars().one()
        # Meta measures its window from when the Contact sent the message, so
        # that is what the gate reads (ADR-0045).
        message.sent_at = datetime.now(tz=UTC) - timedelta(hours=25)
        message.persisted_at = datetime.now(tz=UTC) - timedelta(hours=25)
        await session.commit()
    calendar.find_result = EventResult(CalendarOutcome.OK)

    async with database.session_scope() as session:
        result = await AdminWorkService(session, calendar, schedule, day_of_reminder_hour=9).resolve(
            row.reference, "Reject", Administrator(organization_id=row.organization_id, actor_id="telegram:1")
        )
        pending = await AdminWorkService(session, calendar, schedule, day_of_reminder_hour=9).list_pending(row.organization_id)

    assert result["lead_notification"] == "PendingManual"
    assert [item["type"] for item in pending["items"]] == [
        "PendingManualAppointmentNotification"
    ]

    async with database.session_scope() as session:
        service = AdminWorkService(session, calendar, schedule, day_of_reminder_hour=9)
        marked = await service.resolve(
            row.reference, "MarkNotified", Administrator(organization_id=row.organization_id, actor_id="telegram:1")
        )
        repeated = await service.resolve(
            row.reference, "MarkNotified", Administrator(organization_id=row.organization_id, actor_id="telegram:1")
        )
        saved = await session.get(Appointment, row.id)

    assert marked == {"result": "resolved", "reference": row.reference}
    assert repeated == {"result": "conflict"}
    assert saved is not None
    assert saved.resolution_notification_status == LeadNotificationStatus.NOTIFIED.value


async def test_deactivation_opens_review_and_manual_completion_requires_event_absence(
    recovery,
) -> None:
    database, calendar, schedule = recovery
    row = await appointment(database, status=AppointmentStatus.CONFIRMED.value)
    async with database.session_scope() as session:
        changed = await AdministrationService(session).set_property_status(
            "casa-roble",
            "Inactive",
            Administrator(organization_id=row.organization_id, actor_id="telegram:1"),
            "Unspecified",
        )
    assert changed["affected_confirmed_appointments"] == 1

    async with database.session_scope() as session:
        work = await AdminWorkService(session, calendar, schedule, day_of_reminder_hour=9).list_pending(row.organization_id)
        first = await AdminWorkService(session, calendar, schedule, day_of_reminder_hour=9).resolve(
            row.reference, "HandleManually", Administrator(organization_id=row.organization_id, actor_id="telegram:1")
        )
    assert work["items"][0]["type"] == "InactivePropertyAppointmentReview"
    assert first["result"] == "resolved"

    calendar.find_result = EventResult(CalendarOutcome.OK, event_id="still-there")
    async with database.session_scope() as session:
        blocked = await AdminWorkService(session, calendar, schedule, day_of_reminder_hour=9).resolve(
            row.reference, "MarkComplete", Administrator(organization_id=row.organization_id, actor_id="telegram:1")
        )
    assert blocked["result"] == "conflict"

    calendar.find_result = EventResult(CalendarOutcome.OK)
    async with database.session_scope() as session:
        completed = await AdminWorkService(session, calendar, schedule, day_of_reminder_hour=9).resolve(
            row.reference, "MarkComplete", Administrator(organization_id=row.organization_id, actor_id="telegram:1")
        )
        saved = await session.get(Appointment, row.id)
    assert completed["result"] == "resolved"
    assert saved.status == AppointmentStatus.CANCELLED.value
    assert saved.inactive_review_status == InactiveReviewStatus.COMPLETE.value


async def test_restart_recovery_never_reissues_a_calendar_create(recovery) -> None:
    database, calendar, schedule = recovery
    row = await appointment(database, status=AppointmentStatus.PENDING.value)
    async with database.session_scope() as session:
        count = await AdminWorkService(session, calendar, schedule, day_of_reminder_hour=9).recover_pending_attempts()
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
                    organization_id=await larevia_organization_id(session),
                    hermes_session_id="admin-recovery",
                    role=AgentRole.ADMINISTRATIVE.value,
                    channel_key="telegram:1",
                ),
                AgentSession(
                    organization_id=await larevia_organization_id(session),
                    hermes_session_id="sales-recovery", role=AgentRole.SALES.value
                ),
            )
        )
        await session.commit()

    app = create_app(get_settings())
    app.state.database = database
    # A shared stub answers both the calendar port and the directory the
    # scheduling module now takes, which is the honest double for the
    # one-calendar setup these suites are about.
    app.state.calendar = calendar
    app.state.calendars = calendar
    app.state.appointment_policy = AppointmentPolicy(
        schedule=schedule,
        visit_minutes=90,
        horizon_days=8,
        max_candidates=6,
        day_of_reminder_hour=9,
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
