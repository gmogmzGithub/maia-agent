"""What Product decides about an inbound message before Maia ever sees it.

Two deterministic decisions, both Product policy and neither model judgement.

**"Quiero hablar con una persona."** Recognised on the exact folded text, the
same way an opt-out is (ADR-0045). Product does not need a model to notice that
somebody asked for a human, and making that recognition probabilistic would mean
a paraphrase could silently cost the operation a lead. Maia can *also* raise a
handoff through a typed tool for the phrasings this list does not cover; both
end in the same module, so the request is recorded once either way.

**Where a post-appointment message goes.** ADR-0037 ends Maia's commercial role
at the confirmed appointment: from then on she may handle Appointment Logistics
and nothing else, commercial or visit questions go to the Advisor, and
*ambiguity goes to the Advisor*. That last clause is why this is a whitelist
rather than a blacklist. A message is Maia's only if it clearly matches
logistics; everything else, including anything unrecognised, becomes a human
handoff. The failure mode of the opposite default is Maia negotiating a price
after the handoff, which is exactly what the ADR forbids.

The markers are Mexican Spanish as customers actually write it, folded through
:func:`~realestate.domain.text.fold_phrase` so accents, punctuation and casing
do not matter. They are substring matches on purpose: a Contact writes "oye,
podemos cambiar la cita al sábado?", not a command.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    Appointment,
    AppointmentStatus,
    Conversation,
    HandoffSource,
    Lead,
)
from realestate.domain.commercial.actors import Actor
from realestate.domain.commercial.handling import ConversationHandling
from realestate.domain.commercial.handoff import HumanHandoff, RequestHumanHandling
from realestate.domain.text import fold_phrase

logger = logging.getLogger(__name__)


class PostHandoffRoute(str, Enum):
    """Who answers a message that arrived after the Appointment Handoff."""

    #: Confirming, reminding, rescheduling or cancelling — Maia's bounded work.
    LOGISTICS = "Logistics"
    #: A bare pleasantry. Maia may answer it; it asks for nothing.
    COURTESY = "Courtesy"
    #: Commercial, about the visit itself, or simply unclear.
    ADVISOR = "Advisor"


#: Routes Maia may still answer after the handoff.
MAIA_KEEPS: frozenset[PostHandoffRoute] = frozenset(
    {PostHandoffRoute.LOGISTICS, PostHandoffRoute.COURTESY}
)


#: Phrases that make a post-appointment message Appointment Logistics.
#: Deliberately narrow. Anything not here goes to the Advisor, so a marker added
#: carelessly hands commercial work back to Maia.
LOGISTICS_MARKERS: tuple[str, ...] = (
    "cancelar",
    "cancela",
    "cancelacion",
    "reagendar",
    "reagenda",
    "reprogramar",
    "cambiar la cita",
    "cambiar mi cita",
    "cambiar la visita",
    "mover la cita",
    "mover la visita",
    "otro horario",
    "otra hora",
    "otro dia",
    "confirmar la cita",
    "confirmo la cita",
    "sigue en pie",
    "a que hora es",
    "a que hora quedamos",
    "a que hora era",
    "cual es la direccion",
    "donde es la visita",
    "donde queda",
    "ya no puedo",
    "no voy a poder",
    "no podre",
    "llegare tarde",
    "voy a llegar tarde",
)

#: Messages that are *only* a pleasantry. Matched on the whole folded message
#: rather than as substrings, which is the whole reason they are safe: "gracias"
#: routes to Maia, while "gracias, pero tengo una duda del precio" does not.
#: Without this, every "ok" after a confirmed visit would alert an Advisor and
#: the alert list would stop being read.
COURTESY_MESSAGES: frozenset[str] = frozenset(
    {
        "gracias",
        "muchas gracias",
        "mil gracias",
        "gracias gracias",
        "ok",
        "okey",
        "oki",
        "va",
        "vale",
        "sale",
        "perfecto",
        "excelente",
        "listo",
        "de acuerdo",
        "muy bien",
        "buenisimo",
        "genial",
        "si",
        "claro",
        "esta bien",
        "nos vemos",
        "hasta luego",
        "buenas noches",
        "buen dia",
    }
)

#: Phrases that are an explicit request for a person. Same discipline as the
#: opt-out list: exact folded substrings, no inference.
HUMAN_REQUEST_MARKERS: tuple[str, ...] = (
    "hablar con una persona",
    "hablar con alguien",
    "hablar con un humano",
    "hablar con un asesor",
    "hablar con el asesor",
    "hablar con un agente",
    "quiero un asesor",
    "necesito un asesor",
    "me puede llamar",
    "me pueden llamar",
    "puedo hablar con",
    "atencion humana",
    "eres un bot",
    "eres una maquina",
    "no quiero hablar con un bot",
    "prefiero hablar con una persona",
)


def detect_human_request(text: str | None) -> str | None:
    """The marker a Contact used to ask for a person, or ``None``."""
    if not text:
        return None
    folded = fold_phrase(text)
    for marker in HUMAN_REQUEST_MARKERS:
        if marker in folded:
            return marker
    return None


def classify_post_handoff(text: str | None) -> PostHandoffRoute:
    """Where a post-Appointment-Handoff message goes.

    Ambiguity — including an empty or non-text message — goes to the Advisor.
    """
    if not text:
        return PostHandoffRoute.ADVISOR
    folded = fold_phrase(text)
    for marker in LOGISTICS_MARKERS:
        if marker in folded:
            return PostHandoffRoute.LOGISTICS
    if folded in COURTESY_MESSAGES:
        return PostHandoffRoute.COURTESY
    return PostHandoffRoute.ADVISOR


@dataclass(frozen=True)
class RoutingDecision:
    """What Product did with one inbound message besides persisting it."""

    #: True when a human handoff was requested as a result.
    handed_off: bool
    reason: str | None = None
    request_id: uuid.UUID | None = None
    post_handoff_route: PostHandoffRoute | None = None


class InboundRouting:
    """The inbound-decision module.

    Hides: the marker lists, whether an Appointment Handoff is in force, the
    Maia-resumes rule after the Contact answers, and the handoff request itself.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def route(
        self,
        *,
        lead: Lead,
        conversation: Conversation,
        inbox_id: uuid.UUID,
        text: str | None,
    ) -> RoutingDecision:
        """Decide and apply. Never commits.

        Runs inside the transaction that persists the message, like the opt-out
        rule above it: a handoff request that outlived the message asking for it
        would be a record of something that never durably happened.
        """
        actor = Actor.product(lead.organization_id, "InboundRouting")
        handling = ConversationHandling(self._session)
        handoff = HumanHandoff(self._session)

        # The Contact answering ends an explicit wait. Done first, because the
        # rules below may immediately pause Maia again for a better reason.
        await handling.note_inbound(actor, conversation)

        marker = detect_human_request(text)
        if marker is not None:
            recorded = await handoff.request(
                actor,
                RequestHumanHandling(
                    conversation=conversation,
                    source=HandoffSource.CONTACT_REQUEST,
                    trigger_inbox_id=inbox_id,
                ),
            )
            logger.info(
                "Conversation %s asked for a human (marker=%r)",
                conversation.id,
                marker,
            )
            return RoutingDecision(
                handed_off=True,
                reason="ContactRequestedHuman",
                request_id=recorded.request_id,
            )

        if not await self.handoff_in_force(conversation.id):
            return RoutingDecision(handed_off=False)

        route = classify_post_handoff(text)
        if route in MAIA_KEEPS:
            # Maia keeps the bounded logistics work — the one thing ADR-0037
            # leaves her after the handoff — and a bare pleasantry, which asks
            # for nothing and would otherwise generate an alert per "gracias".
            return RoutingDecision(handed_off=False, post_handoff_route=route)

        recorded = await handoff.request(
            actor,
            RequestHumanHandling(
                conversation=conversation,
                source=HandoffSource.POST_HANDOFF_ROUTING,
                trigger_inbox_id=inbox_id,
                detail=(
                    "El mensaje llegó después de una cita confirmada y no es "
                    "logística de cita."
                ),
            ),
        )
        logger.info(
            "Routing a post-appointment message on %s to the Advisor",
            conversation.id,
        )
        return RoutingDecision(
            handed_off=True,
            reason="PostAppointmentQuestion",
            request_id=recorded.request_id,
            post_handoff_route=route,
        )

    async def handoff_in_force(self, conversation_id: uuid.UUID) -> bool:
        """Whether this Conversation has passed the Appointment Handoff.

        A Confirmed appointment is the boundary (ADR-0037), and it stays in
        force after the visit: the Advisor owns the relationship from then on.
        A Conversation whose only appointments were cancelled is *not* past the
        boundary — Maia legitimately asks once about another time, and taking
        her commercial role away would leave nobody working the lead.
        """
        found = await self._session.scalar(
            select(Appointment.id)
            .where(Appointment.conversation_id == conversation_id)
            .where(Appointment.status == AppointmentStatus.CONFIRMED.value)
            .limit(1)
        )
        return found is not None
