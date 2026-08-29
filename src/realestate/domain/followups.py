"""The unanswered-inquiry follow-up policy.

Follow-up is deterministic Product work: Hermes never decides who to write to
or when. What changed with ADR-0021 is that the *cadence* is no longer treated
as truth. It is a named, versioned pilot hypothesis, it produces an attempt
rather than a message, and every attempt has to be authorised by the Outbound
Eligibility Gate (ADR-0045) before anything can reach a Contact.

Today that gate refuses all of them: proactive marketing needs a recorded
marketing consent and an approved WhatsApp template, and Product has neither.
That is the intended state, not a gap to route around. The attempts are still
recorded, with the reason they were blocked, so the operation can see what the
policy *would* have sent once consent and templates exist.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    ConsentCategory,
    Conversation,
    Lead,
    LeadEngagementCycle,
    LeadFollowUp,
    LeadFollowUpStatus,
    OutboundInitiation,
)
from realestate.domain.outbound import Denied, OutboundIntent, OutboundMessaging, Purpose

# The cadence is a hypothesis under test, so it is named and versioned rather
# than hard-coded as product truth (ADR-0021).
#
# v1 was the broker's own 28-day Facebook process: days 1, 5, 7, 14, 18, 22, 26
# and 28, sent regardless of whether the Contact had answered. No evidence was
# found for that intensity in Mexican real estate over WhatsApp, and it treated
# silence as permission.
#
# v2 is the conservative starting hypothesis: an immediate useful answer, then
# attempts on days 1, 3, 7, 14 and 28 *when contact is permitted*. Any reply
# ends it. Whether these are the right days is exactly what the pilot has to
# measure; SAN-025 will revise them, and revising them must not require a
# schema change.
FOLLOW_UP_POLICY_ID = "unanswered-inquiry"
FOLLOW_UP_POLICY_VERSION = 2


@dataclass(frozen=True)
class FollowUpDay:
    """One attempt in the cadence: when, what it says, and what carries it."""

    day: int
    body: str
    #: Every day of this cadence necessarily falls outside the 24-hour service
    #: window — the window runs from the Contact's last message and day 1 is
    #: already a day later — so a template is structural here, not a fallback.
    #: Naming it now defines the provider contract. It does not activate the
    #: sequence: ADR-0021's Opportunity/Next Action and Dormant states must also
    #: exist and the policy must be explicitly enabled after operational review.
    template_id: str


def _day(day: int, body: str) -> FollowUpDay:
    return FollowUpDay(
        day=day,
        body=body,
        template_id=f"larevia_seguimiento_dia_{day}_v{FOLLOW_UP_POLICY_VERSION}",
    )


# One table, so revising the hypothesis is one edit rather than three
# coordinated ones with a runtime error as the only feedback for missing any.
#
# Each day says something the previous one did not. "Solo dando seguimiento"
# with nothing new in it is the kind of message that earns a block, so a day
# without its own reason to exist does not belong in the cadence.
POLICY: tuple[FollowUpDay, ...] = (
    _day(
        1,
        "Hola, quedé pendiente de tu mensaje. Si quieres, te comparto más "
        "detalles de la propiedad o vemos un horario para visitarla.",
    ),
    _day(
        3,
        "¿Te ayudo a resolver alguna duda de la propiedad? También puedo "
        "revisar qué horarios hay disponibles para que la conozcas.",
    ),
    _day(
        7,
        "Sigo a tus órdenes. Si te sirve, puedo apartarte un horario de "
        "visita esta semana o la siguiente.",
    ),
    _day(
        14,
        "Hola, ¿sigues buscando? Si cambió lo que necesitas, dime y lo "
        "tomo en cuenta para lo que tenemos disponible.",
    ),
    _day(
        28,
        "Con este cierro el seguimiento por ahora para no incomodarte. "
        "Cuando quieras retomarlo, aquí sigo.",
    ),
)

_BY_DAY: dict[int, FollowUpDay] = {entry.day: entry for entry in POLICY}
CADENCE_DAYS: tuple[int, ...] = tuple(entry.day for entry in POLICY)
CHANNEL = "WhatsApp"

logger = logging.getLogger(__name__)


def scheduled_day(day_number: int) -> FollowUpDay:
    """The policy entry for one cadence day."""
    try:
        return _BY_DAY[day_number]
    except KeyError:
        raise ValueError(f"Unsupported follow-up day: {day_number}") from None


def followup_message(day_number: int) -> str:
    """Contact-facing copy for one follow-up attempt under the current policy."""
    return scheduled_day(day_number).body


def followup_template_id(day_number: int) -> str:
    """The WhatsApp template this attempt would use, named per policy version."""
    return scheduled_day(day_number).template_id


def _now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True)
class DueFollowUp:
    """One cadence day that has come due for one engagement cycle."""

    #: Whose cycle it is. Carried on the item rather than looked up when the
    #: attempt row is written, so a sweep that spans Organizations cannot file
    #: one brokerage's follow-up under another's (ADR-0050).
    organization_id: UUID
    cycle_id: UUID
    conversation_id: UUID
    lead_wa_id: str
    day_number: int
    due_at: datetime


def due_at(cycle: LeadEngagementCycle, day_number: int) -> datetime:
    """Day N falls N days after the inquiry arrived.

    Under v1 day 1 fell on the cycle's own start instant, so the first
    follow-up competed with the answer to the message that opened the cycle.
    The immediate response is the answer; day 1 is the day after.
    """
    return cycle.started_at + timedelta(days=day_number)


@dataclass(frozen=True)
class FollowUpRun:
    """What one pass of the policy actually did."""

    enqueued: int
    blocked: int


class LeadFollowUpService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue_due(
        self, now: datetime | None = None, limit: int = 20
    ) -> FollowUpRun:
        moment = now or _now()
        recorded = [
            status
            for item in await self._due(moment, limit)
            if (status := await self._attempt(item, moment)) is not None
        ]
        return FollowUpRun(
            enqueued=recorded.count(LeadFollowUpStatus.ENQUEUED),
            blocked=recorded.count(LeadFollowUpStatus.BLOCKED),
        )

    async def _due(self, now: datetime, limit: int) -> list[DueFollowUp]:
        """Cadence days that have come due and have no attempt recorded yet.

        Two queries, not one per (cycle, day). The steady state under the
        current policy is that every due day already has a ``Blocked`` row, so
        a per-pair ``EXISTS`` would walk the whole cross-product every tick and
        find nothing — the worst case would be the normal case.
        """
        rows = (
            await self._session.execute(
                select(LeadEngagementCycle, Conversation, Lead)
                .join(Conversation, Conversation.cycle_id == LeadEngagementCycle.id)
                .join(Lead, Lead.id == LeadEngagementCycle.lead_id)
                # A legacy per-Lead flag, superseded by SuppressionRecord and
                # kept only so an existing opt-out is not quietly ignored.
                .where(Lead.follow_up_opt_out.is_(False))
                .where(LeadEngagementCycle.started_at <= now)
                .where(LeadEngagementCycle.expires_at > now)
                .order_by(LeadEngagementCycle.started_at, Conversation.id)
            )
        ).all()
        if not rows:
            return []

        recorded = set(
            (
                await self._session.execute(
                    select(LeadFollowUp.cycle_id, LeadFollowUp.day_number)
                    .where(LeadFollowUp.channel == CHANNEL)
                    .where(
                        LeadFollowUp.cycle_id.in_([cycle.id for cycle, _, _ in rows])
                    )
                )
            ).all()
        )

        items: list[DueFollowUp] = []
        for cycle, conversation, lead in rows:
            for day_number in CADENCE_DAYS:
                due = due_at(cycle, day_number)
                if due > now or (cycle.id, day_number) in recorded:
                    continue
                items.append(
                    DueFollowUp(
                        organization_id=cycle.organization_id,
                        cycle_id=cycle.id,
                        conversation_id=conversation.id,
                        lead_wa_id=lead.wa_id,
                        day_number=day_number,
                        due_at=due,
                    )
                )
                if len(items) >= limit:
                    return items
        return items

    async def _attempt(
        self, item: DueFollowUp, now: datetime
    ) -> LeadFollowUpStatus | None:
        """Run one due attempt through the gate and record what happened.

        Returns the recorded status, or ``None`` when there was nothing to
        attempt or another worker got there first.

        The eligibility decision, the ``LeadFollowUp`` row and the Outbox row
        commit together. Any partial outcome would be a lie: a queued message
        no decision authorised, or a day recorded as handled that never was.
        """
        conversation = await self._session.get(Conversation, item.conversation_id)
        if conversation is None:
            return None

        outcome = await OutboundMessaging(self._session).request(
            OutboundIntent(
                conversation=conversation,
                body=followup_message(item.day_number),
                purpose=Purpose.LEAD_FOLLOW_UP,
                # The operation reaching out on a schedule. Nothing the Contact
                # sent asked for this message, and the gate is told so plainly.
                initiation=OutboundInitiation.BUSINESS_INITIATED,
                idempotency_key=f"lead-followup:{item.cycle_id}:{item.day_number}",
                requested_at=now,
                template_id=followup_template_id(item.day_number),
                template_category=ConsentCategory.MARKETING,
            )
        )

        # Narrowed exactly once. Reading ``outbox_id`` off a refusal, or
        # ``reason`` off an approval, is a type error rather than a convention
        # somebody has to remember.
        if isinstance(outcome, Denied):
            row = self._row(item, outcome.decision_id, LeadFollowUpStatus.BLOCKED)
        else:
            row = self._row(
                item,
                outcome.decision_id,
                LeadFollowUpStatus.ENQUEUED,
                outbox_id=outcome.outbox_id,
                enqueued_at=now,
            )

        self._session.add(row)
        try:
            await self._session.commit()
        except IntegrityError:
            # Another worker recorded this cycle/day first. Its decision and
            # row stand; this transaction contributed nothing.
            await self._session.rollback()
            return None
        return LeadFollowUpStatus(row.status)

    @staticmethod
    def _row(
        item: DueFollowUp,
        decision_id: UUID,
        status: LeadFollowUpStatus,
        *,
        outbox_id: UUID | None = None,
        enqueued_at: datetime | None = None,
    ) -> LeadFollowUp:
        """One attempt row, however it turned out."""
        return LeadFollowUp(
            organization_id=item.organization_id,
            cycle_id=item.cycle_id,
            conversation_id=item.conversation_id,
            day_number=item.day_number,
            channel=CHANNEL,
            policy_id=FOLLOW_UP_POLICY_ID,
            policy_version=FOLLOW_UP_POLICY_VERSION,
            due_at=item.due_at,
            status=status.value,
            outbox_id=outbox_id,
            decision_id=decision_id,
            enqueued_at=enqueued_at,
        )
