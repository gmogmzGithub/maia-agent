"""Turn recorded commercial truth into analytics events, exactly once.

The public funnel arrives from the website as explicit events. The operational
half of the scorecard does not: time to first response, qualification,
appointment milestones, outcomes and harm signals are already facts in the
product tables, and re-deriving them inside every report is how two dashboards
end up disagreeing about the same month.

So this module reads the product tables once and emits an event per fact, with a
key derived from the subject's identity. That derivation is the whole design:
``qualified:<opportunity id>`` cannot be emitted twice no matter how often the
worker runs, restarts, or is replayed, because the second attempt is a duplicate
of the first by construction rather than by luck.

Nothing here reaches a Contact and nothing here writes commercial state. It only
observes what a human or a deterministic rule already decided.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    AnalyticsEventName,
    Appointment,
    AppointmentStatus,
    HarmSignal,
    InboxMessage,
    Opportunity,
    OpportunityStage,
    OutboxMessage,
    OutboxStatus,
)
from realestate.domain.analytics.events import AnalyticsEvent, AnalyticsEvents
from realestate.domain.commercial.actors import Actor

#: How many subjects of each kind one pass reads. Bounded so a backfill is
#: spread over several ticks rather than one very long transaction.
SCAN_LIMIT = 200

#: Outcomes an Opportunity can close with, mapped to the enumerated attribute
#: the taxonomy accepts. ``Dormant`` is included because a paused pursuit with a
#: recorded reason is a known outcome; an empty one is not an outcome at all.
_CLOSING_STAGES = {
    OpportunityStage.WON.value: "Won",
    OpportunityStage.LOST.value: "Lost",
    OpportunityStage.DORMANT.value: "Dormant",
}


@dataclass(frozen=True)
class EmissionReport:
    """How many events one pass added, per kind."""

    first_responses: int = 0
    qualifications: int = 0
    appointments: int = 0
    outcomes: int = 0
    harm_signals: int = 0

    @property
    def total(self) -> int:
        return (
            self.first_responses
            + self.qualifications
            + self.appointments
            + self.outcomes
            + self.harm_signals
        )


class AnalyticsEmission:
    """Emit the operational events the scorecard is computed from."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor
        self._events = AnalyticsEvents(session, actor)

    async def emit_operational(self) -> EmissionReport:
        """Scan the product tables once and emit whatever is not yet emitted.

        No ``at`` argument: every event's timestamp is the moment the fact was
        recorded, not the moment this pass noticed it. A pass that stamped
        "now" would make a backfill look like a burst of activity today.
        """
        return EmissionReport(
            first_responses=await self._first_responses(),
            qualifications=await self._qualifications(),
            appointments=await self._appointments(),
            outcomes=await self._outcomes(),
            harm_signals=await self._harm_signals(),
        )

    async def _first_responses(self) -> int:
        """One event per Conversation that has had a first delivered reply.

        The pairing is the *first* inbound and the *first* sent Outbox row of the
        same Conversation. Deliberately not "the reply that covered that
        message": a reply covering three fragments is still one first response,
        and counting per fragment would make a fast answer to a chatty Contact
        look like three fast answers.
        """
        first_inbound = (
            select(
                InboxMessage.conversation_id.label("conversation_id"),
                func.min(InboxMessage.sent_at).label("first_inbound_at"),
            )
            .group_by(InboxMessage.conversation_id)
            .subquery()
        )
        first_outbound = (
            select(
                OutboxMessage.conversation_id.label("conversation_id"),
                func.min(OutboxMessage.sent_at).label("first_outbound_at"),
            )
            .where(OutboxMessage.status == OutboxStatus.SENT.value)
            .where(OutboxMessage.sent_at.is_not(None))
            .group_by(OutboxMessage.conversation_id)
            .subquery()
        )
        rows = await self._session.execute(
            select(
                first_inbound.c.conversation_id,
                first_inbound.c.first_inbound_at,
                first_outbound.c.first_outbound_at,
            )
            .join(
                first_outbound,
                first_outbound.c.conversation_id == first_inbound.c.conversation_id,
            )
            .where(first_outbound.c.first_outbound_at >= first_inbound.c.first_inbound_at)
            .order_by(first_inbound.c.first_inbound_at)
            .limit(SCAN_LIMIT)
        )
        emitted = 0
        for conversation_id, inbound_at, outbound_at in rows:
            minutes = Decimal(
                (outbound_at - inbound_at).total_seconds()
            ) / Decimal(60)
            recorded = await self._events.record(
                AnalyticsEvent(
                    event_key=f"first-response:{conversation_id}",
                    name=AnalyticsEventName.FIRST_RESPONSE_RECORDED,
                    occurred_at=outbound_at,
                    attributes={
                        "response_minutes": float(
                            minutes.quantize(Decimal("0.01"))
                        )
                    },
                )
            )
            emitted += int(recorded.created)
        return emitted

    async def _qualifications(self) -> int:
        rows = await self._session.scalars(
            select(Opportunity)
            .where(
                Opportunity.organization_id == self._actor.organization_id,
                Opportunity.qualified_at.is_not(None),
            )
            .order_by(Opportunity.qualified_at)
            .limit(SCAN_LIMIT)
        )
        emitted = 0
        for row in rows:
            assert row.qualified_at is not None
            recorded = await self._events.record(
                AnalyticsEvent(
                    event_key=f"qualified:{row.id}",
                    name=AnalyticsEventName.OPPORTUNITY_QUALIFIED,
                    occurred_at=row.qualified_at,
                    subject_value=str(row.contact_id),
                )
            )
            emitted += int(recorded.created)
        return emitted

    async def _appointments(self) -> int:
        """Requested, verified and attended, as three separate milestones.

        A Confirmed appointment is the verified milestone; the request is the row
        existing at all; attendance is only emitted once a human recorded it.
        The third one is the reason ``Sin registrar`` exists: Product will not
        invent a Missed outcome for a visit nobody wrote up.
        """
        rows = await self._session.scalars(
            select(Appointment)
            .where(Appointment.organization_id == self._actor.organization_id)
            .order_by(Appointment.created_at)
            .limit(SCAN_LIMIT)
        )
        emitted = 0
        for row in rows:
            emitted += int(
                (
                    await self._events.record(
                        AnalyticsEvent(
                            event_key=f"appointment-requested:{row.id}",
                            name=AnalyticsEventName.APPOINTMENT_REQUESTED,
                            occurred_at=row.created_at,
                        )
                    )
                ).created
            )
            if row.status == AppointmentStatus.CONFIRMED.value:
                emitted += int(
                    (
                        await self._events.record(
                            AnalyticsEvent(
                                event_key=f"appointment-verified:{row.id}",
                                name=AnalyticsEventName.APPOINTMENT_VERIFIED,
                                occurred_at=row.created_at,
                            )
                        )
                    ).created
                )
            if row.attendance is not None and row.attendance_recorded_at is not None:
                emitted += int(
                    (
                        await self._events.record(
                            AnalyticsEvent(
                                event_key=f"appointment-attended:{row.id}",
                                name=AnalyticsEventName.APPOINTMENT_ATTENDED,
                                occurred_at=row.attendance_recorded_at,
                                attributes={"attendance": row.attendance},
                            )
                        )
                    ).created
                )
        return emitted

    async def _outcomes(self) -> int:
        rows = await self._session.scalars(
            select(Opportunity)
            .where(
                Opportunity.organization_id == self._actor.organization_id,
                Opportunity.closed_at.is_not(None),
                Opportunity.stage.in_(tuple(_CLOSING_STAGES)),
            )
            .order_by(Opportunity.closed_at)
            .limit(SCAN_LIMIT)
        )
        emitted = 0
        for row in rows:
            assert row.closed_at is not None
            recorded = await self._events.record(
                AnalyticsEvent(
                    event_key=f"outcome:{row.id}",
                    name=AnalyticsEventName.OPPORTUNITY_OUTCOME_KNOWN,
                    occurred_at=row.closed_at,
                    subject_value=str(row.contact_id),
                    attributes={"outcome": _CLOSING_STAGES[row.stage]},
                )
            )
            emitted += int(recorded.created)
        return emitted

    async def _harm_signals(self) -> int:
        rows = await self._session.scalars(
            select(HarmSignal)
            .where(HarmSignal.organization_id == self._actor.organization_id)
            .order_by(HarmSignal.occurred_at)
            .limit(SCAN_LIMIT)
        )
        emitted = 0
        for row in rows:
            recorded = await self._events.record(
                AnalyticsEvent(
                    event_key=f"harm:{row.id}",
                    name=AnalyticsEventName.HARM_SIGNAL_RECORDED,
                    occurred_at=row.occurred_at,
                    attributes={"harm_kind": row.kind},
                )
            )
            emitted += int(recorded.created)
        return emitted

    async def emit_sponsored_exposure(
        self,
        *,
        campaign_id: uuid.UUID,
        listing_id: uuid.UUID,
        surface: str,
        position: int,
        session_value: str,
        session_reference: str,
        occurred_at: datetime,
        bot: bool = False,
        internal: bool = False,
    ) -> bool:
        """One Served Impression, keyed so a re-rendered page counts once.

        The key is built from the *pseudonymous* reference, the day and the
        position — the exact granularity the per-session daily cap is expressed
        in. Two separate arguments because the raw value is what gets
        pseudonymised for storage and the reference is what may appear in a
        stored key; passing the raw one into the key would put a browser
        identifier into a column.
        """
        day = occurred_at.date().isoformat()
        recorded = await self._events.record(
            AnalyticsEvent(
                event_key=(
                    f"served:{campaign_id}:{session_reference or 'anon'}"
                    f":{day}:{position}"
                ),
                name=AnalyticsEventName.SPONSORED_SERVED_IMPRESSION,
                occurred_at=occurred_at,
                listing_id=listing_id,
                campaign_id=campaign_id,
                session_value=session_value,
                attributes={"surface": surface, "position": position},
                bot=bot,
                internal=internal,
            )
        )
        return recorded.created
