"""Checkpoint 5's bounded Administrative recovery work.

This is intentionally not a task manager. It derives four accepted work types
from Appointment state and accepts a fixed action vocabulary. Hermes interprets
natural language; this module verifies Calendar evidence and owns every state
transition.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.channels.google.calendar import CalendarOutcome, EventResult
from realestate.db.models import (
    Appointment,
    AppointmentStatus,
    Conversation,
    InactiveReviewStatus,
    Lead,
    LeadNotificationStatus,
    OrganizationMember,
    OutboundInitiation,
    Property,
)
from realestate.domain.administration import Administrator
from realestate.domain.appointments import NEEDS_REVIEW_MESSAGE, confirmation_message
from realestate.domain.audit import record_audit
from realestate.domain.availability import WeeklySchedule
from realestate.domain.scheduling.calendars import CalendarDirectory, CalendarPort
from realestate.domain.outbound import (
    Denied,
    OutboundIntent,
    OutboundMessaging,
    Purpose,
)

APPOINTMENT_NEEDS_REVIEW = "AppointmentNeedsReview"
PENDING_MANUAL_NOTIFICATION = "PendingManualAppointmentNotification"
INACTIVE_PROPERTY_REVIEW = "InactivePropertyAppointmentReview"
PENDING_MANUAL_CANCELLATION = "PendingManualCancellation"

CONFIRM = "Confirm"
REJECT = "Reject"
MARK_NOTIFIED = "MarkNotified"
HANDLE_MANUALLY = "HandleManually"
MARK_COMPLETE = "MarkComplete"

ALLOWED_ACTIONS = frozenset(
    {CONFIRM, REJECT, MARK_NOTIFIED, HANDLE_MANUALLY, MARK_COMPLETE}
)

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(tz=UTC)


def rejection_message(
    *, property_name: str, starts_at: datetime, schedule: WeeklySchedule
) -> str:
    local = starts_at.astimezone(schedule.zone)
    return (
        f"No fue posible reservar la visita a {property_name} para el "
        f"{local.strftime('%d/%m/%Y')} a las {local.strftime('%H:%M')}. "
        "Si quieres, puedo mostrarte otros horarios disponibles."
    )


class AdminWorkService:
    """Administrative reconciliation of ambiguous booking attempts.

    Takes a calendar *directory* rather than one calendar: since Stage 3 each
    appointment names the calendar its event was written to, and looking for the
    event somewhere else would report a conclusive absence that is really a
    lookup in the wrong place.
    """

    def __init__(
        self,
        session: AsyncSession,
        calendars: CalendarDirectory,
        schedule: WeeklySchedule,
    ) -> None:
        self._session = session
        self._calendars = calendars
        self._schedule = schedule

    async def _calendar_for(self, row: Appointment) -> CalendarPort | None:
        """The calendar this appointment's event would be on.

        Three cases, in order of how much Product actually knows. The stored
        ``calendar_id`` is where the event was written and is authoritative even
        if the Advisor's configuration changed since. Failing that, the
        Advisor's current calendar. Failing that, the row predates Advisor
        ownership — and a pre-Stage-3 appointment can only have been written to
        the single calendar the operation had, which is now the default
        Advisor's. That is not a guess about where it might be; it is the only
        place it can be.
        """
        if row.calendar_id:
            found = self._calendars.for_calendar_id(row.calendar_id)
            if found is not None:
                return found
        advisor_id = row.conducting_advisor_id or row.advisor_id
        if advisor_id is not None:
            advisor = await self._session.get(OrganizationMember, advisor_id)
            if advisor is not None:
                return self._calendars.for_advisor(advisor)
        legacy: OrganizationMember | None = await self._session.scalar(
            select(OrganizationMember)
            .where(OrganizationMember.organization_id == row.organization_id)
            .where(OrganizationMember.is_default_advisor.is_(True))
            .limit(1)
        )
        if legacy is not None:
            return self._calendars.for_advisor(legacy)
        return None

    async def list_pending(self) -> dict[str, Any]:
        rows = (
            (
                await self._session.execute(
                    select(Appointment).order_by(Appointment.created_at)
                )
            )
            .scalars()
            .all()
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            prop = await self._session.get(Property, row.property_uuid)
            base = {
                "reference": row.reference,
                "property_id": prop.property_key if prop else "unknown",
                "property_name": prop.name if prop else "Unknown property",
                "relevant_at": row.starts_at.astimezone(self._schedule.zone).isoformat(),
            }
            if row.status == AppointmentStatus.NEEDS_REVIEW.value:
                items.append(
                    {
                        **base,
                        "type": APPOINTMENT_NEEDS_REVIEW,
                        "state": AppointmentStatus.NEEDS_REVIEW.value,
                        "allowed_actions": [CONFIRM, REJECT],
                    }
                )
            if (
                row.resolution_notification_status
                == LeadNotificationStatus.PENDING_MANUAL.value
            ):
                items.append(
                    {
                        **base,
                        "type": PENDING_MANUAL_NOTIFICATION,
                        "state": LeadNotificationStatus.PENDING_MANUAL.value,
                        "allowed_actions": [MARK_NOTIFIED],
                    }
                )
            if row.inactive_review_status == InactiveReviewStatus.PENDING.value:
                items.append(
                    {
                        **base,
                        "type": INACTIVE_PROPERTY_REVIEW,
                        "state": InactiveReviewStatus.PENDING.value,
                        "allowed_actions": [HANDLE_MANUALLY],
                    }
                )
            if (
                row.inactive_review_status
                == InactiveReviewStatus.HANDLING_MANUALLY.value
            ):
                items.append(
                    {
                        **base,
                        "type": PENDING_MANUAL_CANCELLATION,
                        "state": InactiveReviewStatus.HANDLING_MANUALLY.value,
                        "allowed_actions": [MARK_COMPLETE],
                    }
                )
        return {"result": "found", "items": items}

    async def resolve(
        self, reference: str, action: str, actor: Administrator
    ) -> dict[str, Any]:
        if action not in ALLOWED_ACTIONS:
            return {"result": "invalid_action"}
        row = (
            await self._session.execute(
                select(Appointment)
                .where(Appointment.reference == reference)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            return {"result": "not_found"}

        if action in (CONFIRM, REJECT):
            result = await self._resolve_booking(row, action)
        elif action == MARK_NOTIFIED:
            result = await self._mark_notified(row)
        elif action == HANDLE_MANUALLY:
            result = await self._handle_manually(row)
        else:
            result = await self._complete_manual_cancellation(row)

        await self._audit(row, actor, action, result)
        return result

    async def recover_pending_attempts(self) -> int:
        """Turn crash-stranded Calendar attempts into visible review work."""
        rows = (
            (
                await self._session.execute(
                    select(Appointment)
                    .where(Appointment.status == AppointmentStatus.PENDING.value)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.status = AppointmentStatus.NEEDS_REVIEW.value
            row.last_error = "Process stopped before the Calendar result was persisted."
            conversation = await self._session.get(Conversation, row.conversation_id)
            lead = await self._session.get(Lead, row.lead_id)
            if conversation is not None and lead is not None:
                # Nobody asked for this notice: recovery decided to send it, so
                # it is business-initiated even though it concerns the Contact's
                # own booking. Outside the service window it is refused, and the
                # appointment simply stays visible as review work.
                notice = await OutboundMessaging(self._session).request(
                    OutboundIntent(
                        conversation=conversation,
                        body=NEEDS_REVIEW_MESSAGE,
                        purpose=Purpose.APPOINTMENT_NEEDS_REVIEW,
                        initiation=OutboundInitiation.BUSINESS_INITIATED,
                        idempotency_key=f"appointment-needs-review:{row.id}",
                    )
                )
                if not isinstance(notice, Denied):
                    row.lead_notice_at = _now()
        if rows:
            await self._session.commit()
        return len(rows)

    async def _resolve_booking(self, row: Appointment, action: str) -> dict[str, Any]:
        if row.status != AppointmentStatus.NEEDS_REVIEW.value:
            if row.status in (
                AppointmentStatus.CONFIRMED.value,
                AppointmentStatus.REJECTED.value,
            ):
                return {
                    "result": "already_resolved",
                    "reference": row.reference,
                    "outcome": row.status,
                }
            return {"result": "conflict", "state": row.status}

        calendar = await self._calendar_for(row)
        if calendar is None:
            return {
                "result": "still_ambiguous",
                "detail": (
                    "La cita no tiene un calendario autoritativo con el que "
                    "verificarla."
                ),
            }
        evidence = await calendar.find_by_reference(row.reference)
        if evidence.outcome is not CalendarOutcome.OK:
            return {"result": "still_ambiguous", "detail": evidence.detail}

        exists = evidence.event_id is not None
        matches = exists and await self._event_matches(row, evidence)
        if action == CONFIRM and not matches:
            return {"result": "conflict" if exists else "still_ambiguous"}
        if action == REJECT and exists:
            return {"result": "conflict"}

        row.status = (
            AppointmentStatus.CONFIRMED.value
            if action == CONFIRM
            else AppointmentStatus.REJECTED.value
        )
        row.calendar_event_id = evidence.event_id if action == CONFIRM else None
        row.resolved_at = _now()
        row.last_error = None
        notification = await self._release_resolution(row)
        await self._session.commit()
        return {
            "result": "resolved",
            "reference": row.reference,
            "outcome": row.status,
            "lead_notification": notification,
        }

    async def _event_matches(self, row: Appointment, evidence: EventResult) -> bool:
        if evidence.start != row.starts_at or evidence.end != row.ends_at:
            return False
        # The deterministic event title includes the persisted Property name.
        # The private appointment reference already binds it uniquely; the
        # title check prevents a manually repurposed event from being accepted.
        prop = await self._session.get(Property, row.property_uuid)
        return prop is not None and prop.name.casefold() in (evidence.summary or "").casefold()

    async def _release_resolution(self, row: Appointment) -> str:
        conversation = await self._session.get(Conversation, row.conversation_id)
        lead = await self._session.get(Lead, row.lead_id)
        prop = await self._session.get(Property, row.property_uuid)
        if conversation is None or lead is None or prop is None:
            row.resolution_notification_status = (
                LeadNotificationStatus.PENDING_MANUAL.value
            )
            return LeadNotificationStatus.PENDING_MANUAL.value

        body = (
            confirmation_message(
                property_name=prop.name,
                starts_at=row.starts_at,
                schedule=self._schedule,
                visit_address=prop.visit_address,
            )
            if row.status == AppointmentStatus.CONFIRMED.value
            else rejection_message(
                property_name=prop.name,
                starts_at=row.starts_at,
                schedule=self._schedule,
            )
        )
        # The Administrator resolved this, not the Contact, so the notice is
        # business-initiated. The gate owns the service-window question that
        # this method used to answer for itself; a refusal becomes the existing
        # manual path rather than a message that silently never arrives.
        outcome = await OutboundMessaging(self._session).request(
            OutboundIntent(
                conversation=conversation,
                body=body,
                purpose=Purpose.APPOINTMENT_RESOLUTION,
                initiation=OutboundInitiation.BUSINESS_INITIATED,
                idempotency_key=f"appointment-resolution:{row.id}:{row.status}",
            )
        )
        if isinstance(outcome, Denied):
            row.resolution_notification_status = (
                LeadNotificationStatus.PENDING_MANUAL.value
            )
            return LeadNotificationStatus.PENDING_MANUAL.value
        row.resolution_notification_status = LeadNotificationStatus.QUEUED.value
        return LeadNotificationStatus.QUEUED.value

    async def _mark_notified(self, row: Appointment) -> dict[str, Any]:
        if (
            row.resolution_notification_status
            != LeadNotificationStatus.PENDING_MANUAL.value
        ):
            return {"result": "conflict"}
        row.resolution_notification_status = LeadNotificationStatus.NOTIFIED.value
        row.resolution_notification_at = _now()
        await self._session.commit()
        return {"result": "resolved", "reference": row.reference}

    async def _handle_manually(self, row: Appointment) -> dict[str, Any]:
        if row.inactive_review_status != InactiveReviewStatus.PENDING.value:
            return {"result": "conflict"}
        row.inactive_review_status = InactiveReviewStatus.HANDLING_MANUALLY.value
        await self._session.commit()
        return {"result": "resolved", "reference": row.reference}

    async def _complete_manual_cancellation(self, row: Appointment) -> dict[str, Any]:
        if (
            row.inactive_review_status
            != InactiveReviewStatus.HANDLING_MANUALLY.value
        ):
            return {"result": "conflict"}
        calendar = await self._calendar_for(row)
        if calendar is None:
            return {"result": "still_ambiguous"}
        evidence = await calendar.find_by_reference(row.reference)
        if evidence.outcome is not CalendarOutcome.OK:
            return {"result": "still_ambiguous", "detail": evidence.detail}
        if evidence.event_id is not None:
            return {"result": "conflict", "detail": "Calendar event still exists"}
        row.inactive_review_status = InactiveReviewStatus.COMPLETE.value
        row.status = AppointmentStatus.CANCELLED.value
        row.cancelled_at = _now()
        await self._session.commit()
        return {"result": "resolved", "reference": row.reference}

    async def _audit(
        self, row: Appointment, actor: Administrator, action: str, result: dict[str, Any]
    ) -> None:
        await record_audit(
            self._session,
            actor_type="Administrative",
            actor_id=actor.actor_id,
            action="PendingAdminWorkResolutionRequested",
            subject_type="Appointment",
            subject_id=row.reference,
            details={
                "action": action,
                "result": result.get("result"),
                "origin_message_id": actor.origin_message_id,
            },
        )
