"""WhatsApp-only lead follow-up cadence.

Broker Demo's 28-day Facebook lead process is deterministic product policy. This
module turns the WhatsApp column into Outbox rows; Hermes does not decide who to
follow up with or when.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    Conversation,
    Lead,
    LeadEngagementCycle,
    LeadFollowUp,
    LeadFollowUpStatus,
)
from realestate.domain.outbox import OutboxKind, OutboxService

CADENCE_DAYS: tuple[int, ...] = (1, 5, 7, 14, 18, 22, 26, 28)
CHANNEL = "WhatsApp"


def _now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True)
class DueFollowUp:
    cycle_id: UUID
    conversation_id: UUID
    lead_wa_id: str
    day_number: int
    due_at: datetime


def due_at(cycle: LeadEngagementCycle, day_number: int) -> datetime:
    """Day 1 means the cycle start day; day 5 is four days later."""
    return cycle.started_at + timedelta(days=day_number - 1)


def followup_message(day_number: int) -> str:
    """Lead-facing copy for one WhatsApp follow-up."""
    if day_number == 1:
        return (
            "Hola, sigo pendiente por si quieres más información de la propiedad "
            "o si prefieres que busquemos un horario para visitarla."
        )
    if day_number == 5:
        return (
            "Solo para dar seguimiento: ¿te gustaría que revisemos disponibilidad "
            "para una visita?"
        )
    if day_number == 7:
        return (
            "Sigo atento por si quieres resolver dudas o ver horarios disponibles "
            "para visitar la propiedad."
        )
    if day_number == 14:
        return (
            "Hola, te escribo para dar seguimiento. Si todavía estás buscando, "
            "puedo ayudarte con información o con una visita."
        )
    if day_number == 18:
        return (
            "¿Sigues interesado en revisar opciones? Puedo ayudarte a retomar la "
            "conversación por aquí."
        )
    if day_number == 22:
        return (
            "Doy seguimiento a tu interés. Si quieres, revisamos disponibilidad "
            "para visitar o aclaramos cualquier duda."
        )
    if day_number == 26:
        return (
            "Estamos por cerrar este seguimiento. Si todavía te interesa, dime y "
            "lo retomamos por WhatsApp."
        )
    if day_number == 28:
        return (
            "Último seguimiento por este medio. Si quieres retomar la propiedad "
            "o agendar una visita, aquí sigo pendiente."
        )
    raise ValueError(f"Unsupported follow-up day: {day_number}")


class LeadFollowUpService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue_due(self, now: datetime | None = None, limit: int = 20) -> int:
        moment = now or _now()
        due = await self._due(moment, limit)
        count = 0
        for item in due:
            if await self._enqueue(item):
                count += 1
        return count

    async def _due(self, now: datetime, limit: int) -> list[DueFollowUp]:
        items: list[DueFollowUp] = []
        rows = (
            await self._session.execute(
                select(LeadEngagementCycle, Conversation, Lead)
                .join(Conversation, Conversation.cycle_id == LeadEngagementCycle.id)
                .join(Lead, Lead.id == LeadEngagementCycle.lead_id)
                .where(Lead.follow_up_opt_out.is_(False))
                .where(LeadEngagementCycle.started_at <= now)
                .where(LeadEngagementCycle.expires_at > now)
                .order_by(LeadEngagementCycle.started_at, Conversation.id)
            )
        ).all()
        for cycle, conversation, lead in rows:
            for day_number in CADENCE_DAYS:
                due = due_at(cycle, day_number)
                if due > now:
                    continue
                already = await self._session.scalar(
                    select(
                        exists().where(LeadFollowUp.cycle_id == cycle.id)
                        .where(LeadFollowUp.day_number == day_number)
                        .where(LeadFollowUp.channel == CHANNEL)
                    )
                )
                if already:
                    continue
                items.append(
                    DueFollowUp(
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

    async def _enqueue(self, item: DueFollowUp) -> bool:
        conversation = await self._session.get(Conversation, item.conversation_id)
        if conversation is None:
            return False
        enqueued = await OutboxService(self._session).enqueue(
            conversation=conversation,
            to_wa_id=item.lead_wa_id,
            body=followup_message(item.day_number),
            kind=OutboxKind.LEAD_FOLLOW_UP,
            idempotency_key=f"lead-followup:{item.cycle_id}:{item.day_number}",
            covered_inbox_ids=[],
        )
        row = LeadFollowUp(
            cycle_id=item.cycle_id,
            conversation_id=item.conversation_id,
            day_number=item.day_number,
            channel=CHANNEL,
            due_at=item.due_at,
            status=LeadFollowUpStatus.ENQUEUED.value,
            outbox_id=enqueued.outbox_id,
            enqueued_at=_now(),
        )
        self._session.add(row)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            return False
        return enqueued.created
