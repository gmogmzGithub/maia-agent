"""After the appointment, Maia keeps logistics and nothing else (ADR-0037).

The classification is a whitelist, and that direction is the whole design. A
message is Maia's only if it clearly matches Appointment Logistics or is a bare
pleasantry; everything else — commercial questions, questions about the visit,
and anything unrecognised — goes to the Advisor. The opposite default would have
Maia negotiating a price after the handoff, which the ADR forbids.

The boundary is the *Confirmed* appointment. Before it, Maia is working toward
one and answers everything she is allowed to. After a cancellation with no other
confirmed visit, she is working toward one again.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from realestate.db.models import (
    HandlingMode,
    HandoffSource,
    HumanHandoffRequest,
)
from realestate.domain.commercial.handling import ConversationHandling
from realestate.domain.commercial.routing import (
    InboundRouting,
    PostHandoffRoute,
    classify_post_handoff,
)
from realestate.domain.scheduling.appointments import CancelVisit, VisitCancelled
from tests.conftest import requires_postgres
from tests.fixtures import visits

pytestmark = requires_postgres


# -- The classification ---------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "Quiero cancelar la visita",
        "¿Podemos reagendar para el sábado?",
        "necesito cambiar la cita",
        "¿A qué hora es la visita?",
        "¿Cuál es la dirección?",
        "Ya no puedo ir mañana",
        "Voy a llegar tarde unos minutos",
        "Confirmo la cita",
    ],
)
def test_appointment_logistics_stays_with_maia(message: str) -> None:
    assert classify_post_handoff(message) is PostHandoffRoute.LOGISTICS


@pytest.mark.parametrize(
    "message",
    [
        "gracias",
        "Muchas gracias!",
        "Ok",
        "perfecto",
        "Listo",
    ],
)
def test_a_bare_pleasantry_stays_with_maia(message: str) -> None:
    """Otherwise every "gracias" after a confirmed visit alerts an Advisor and
    the alert list stops being read."""
    assert classify_post_handoff(message) is PostHandoffRoute.COURTESY


@pytest.mark.parametrize(
    "message",
    [
        "¿Aceptan una oferta de 3.8 millones?",
        "¿Qué documentos necesito para el crédito?",
        "¿La casa tiene problemas de humedad?",
        "Quiero hacer una oferta",
        "algo raro que nadie previó",
        "",
        None,
    ],
)
def test_commercial_and_ambiguous_messages_go_to_the_advisor(
    message: str | None,
) -> None:
    assert classify_post_handoff(message) is PostHandoffRoute.ADVISOR


def test_a_pleasantry_with_a_question_attached_is_not_a_pleasantry() -> None:
    """The courtesy list matches the whole message, which is what makes it safe."""
    assert (
        classify_post_handoff("gracias, pero tengo una duda del precio")
        is PostHandoffRoute.ADVISOR
    )


# -- Applied to a real conversation ---------------------------------------


async def test_before_a_confirmed_visit_nothing_is_routed_away_from_maia(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-pre", body="¿Aceptan una oferta más baja?"
        )

    async with database.session_scope() as session:
        snapshot = await ConversationHandling(session).snapshot(conversation.id)
        requests = list(await session.scalars(select(HumanHandoffRequest)))

    assert snapshot.mode is HandlingMode.MAIA
    assert requests == []


async def test_a_commercial_question_after_the_visit_goes_to_the_advisor(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-post", body="Quiero ver la casa"
        )
        await visits.confirmed_visit(built, session, conversation)

    async with database.session_scope() as session:
        await visits.inbound(
            session,
            wamid="w-post2",
            body="¿Qué documentos necesito para el crédito?",
        )

    async with database.session_scope() as session:
        snapshot = await ConversationHandling(session).snapshot(conversation.id)
        request_row = await session.scalar(select(HumanHandoffRequest))

    assert snapshot.mode is HandlingMode.HUMAN
    assert snapshot.holder_member_id == built.advisor_id
    assert not snapshot.maia_may_reply
    assert request_row is not None
    assert request_row.source == HandoffSource.POST_HANDOFF_ROUTING.value


async def test_a_logistics_message_after_the_visit_stays_with_maia(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-log", body="Quiero ver la casa"
        )
        await visits.confirmed_visit(built, session, conversation)

    async with database.session_scope() as session:
        await visits.inbound(
            session, wamid="w-log2", body="¿Podemos reagendar para el sábado?"
        )

    async with database.session_scope() as session:
        snapshot = await ConversationHandling(session).snapshot(conversation.id)
        requests = list(await session.scalars(select(HumanHandoffRequest)))

    assert snapshot.mode is HandlingMode.MAIA
    assert snapshot.maia_may_reply
    assert requests == []


async def test_after_the_only_visit_is_cancelled_maia_leads_again(
    operation,
) -> None:
    """Cancelling does not close the pursuit, so somebody has to keep working it
    — and Maia asking once about another time is exactly that (ADR-0037)."""
    database, built = operation
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-again", body="Quiero ver la casa"
        )
        visit = await visits.confirmed_visit(built, session, conversation)
        visit_id = visit.id

    async with database.session_scope() as session:
        cancelled = await built.visits(session).cancel(
            built.product,
            CancelVisit(appointment_id=visit_id, command_key="cancel-again"),
        )
    assert isinstance(cancelled, VisitCancelled)

    async with database.session_scope() as session:
        in_force = await InboundRouting(session).handoff_in_force(conversation.id)

    assert not in_force
    async with database.session_scope() as session:
        await visits.inbound(
            session, wamid="w-again2", body="¿Aceptan una oferta más baja?"
        )
    async with database.session_scope() as session:
        snapshot = await ConversationHandling(session).snapshot(conversation.id)
        requests = list(await session.scalars(select(HumanHandoffRequest)))

    assert snapshot.mode is HandlingMode.MAIA
    assert requests == []


async def test_the_handoff_stays_in_force_after_the_visit_has_happened(
    operation,
) -> None:
    """The Advisor owns the relationship from the confirmation onward, not only
    until the visit."""
    database, built = operation
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-after", body="Quiero ver la casa"
        )
        visit = await visits.confirmed_visit(built, session, conversation)
        visit.starts_at = visits.now() - timedelta(days=1)
        visit.ends_at = visits.now() - timedelta(days=1) + timedelta(minutes=90)
        await session.commit()

    async with database.session_scope() as session:
        in_force = await InboundRouting(session).handoff_in_force(conversation.id)

    assert in_force


async def test_a_second_post_appointment_question_does_not_alert_twice(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-twice", body="Quiero ver la casa"
        )
        await visits.confirmed_visit(built, session, conversation)

    for index, body in enumerate(
        ("¿Y el crédito?", "¿Me pueden dar un descuento?"), start=1
    ):
        async with database.session_scope() as session:
            await visits.inbound(session, wamid=f"w-twice-{index}", body=body)

    async with database.session_scope() as session:
        requests = list(await session.scalars(select(HumanHandoffRequest)))
        from realestate.db.models import InternalAlert

        alerts = list(await session.scalars(select(InternalAlert)))

    assert len(requests) == 1
    assert len([alert for alert in alerts if "atención humana" in alert.title]) == 1
