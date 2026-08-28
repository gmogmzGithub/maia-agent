"""Complete the commercial handoff for one confirmed Appointment.

Booking and administrative reconciliation reach confirmation through different
paths, but confirmation has one meaning. This module keeps the interface small:
given the authoritative Appointment and Product actor, it creates deterministic
reminders, advances a legally eligible Opportunity, and makes the Responsible
Advisor owe the post-visit record. It never commits, so all three facts land
with the confirmation that called it.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    Appointment,
    NextActionKind,
    Opportunity,
    OpportunityStage,
)
from realestate.domain.availability import WeeklySchedule
from realestate.domain.commercial.actors import Actor
from realestate.domain.scheduling.reminders import AppointmentReminders


class AppointmentHandoff:
    """The single confirmation-to-human-operation transition."""

    def __init__(
        self,
        session: AsyncSession,
        schedule: WeeklySchedule,
        *,
        day_of_reminder_hour: int,
    ) -> None:
        self._session = session
        self._reminders = AppointmentReminders(
            session, schedule, day_of_hour=day_of_reminder_hour
        )

    async def complete(self, actor: Actor, appointment: Appointment) -> None:
        """Complete the handoff idempotently. Never commits."""
        await self._reminders.schedule_for(appointment)
        if appointment.opportunity_id is None:
            return
        opportunity = await self._session.get(
            Opportunity, appointment.opportunity_id
        )
        if opportunity is None:
            return

        from realestate.domain.commercial.next_actions import (
            NextActions,
            ScheduleNextAction,
        )
        from realestate.domain.commercial.opportunities import (
            AdvanceStage,
            OpportunityManagement,
        )

        if opportunity.stage in {
            OpportunityStage.QUALIFIED.value,
            OpportunityStage.SEARCHING.value,
            OpportunityStage.NEGOTIATING.value,
        }:
            await OpportunityManagement(self._session).record(
                actor,
                AdvanceStage(
                    opportunity_id=opportunity.id,
                    to_stage=OpportunityStage.VISITING,
                    reason="AppointmentConfirmed",
                    command_key=f"visit-confirmed:{appointment.id}",
                ),
            )
        await NextActions(self._session).schedule(
            actor,
            ScheduleNextAction(
                opportunity_id=opportunity.id,
                kind=NextActionKind.VISIT_FOLLOW_UP,
                due_at=appointment.ends_at,
                command_key=f"visit-follow-up:{appointment.id}",
                responsible_member_id=appointment.advisor_id,
                note=f"Registrar el resultado de la visita {appointment.reference}.",
            ),
        )
