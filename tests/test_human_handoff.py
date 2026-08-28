"""A request for a human cannot disappear (ADR-0029).

The alert is immediate, the escalation is exactly fifteen minutes, and neither
of them reassigns anything. The escalation is the part worth attacking: it is
stamped in the same transaction as the alert it raises, so a restart mid-window
re-derives the same due set and a restart afterwards finds nothing due. This
suite drives the clock rather than waiting, and re-runs the pass repeatedly to
show that "exactly once" is a property of the data and not of the process
staying alive.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from realestate.db.engine import Database
from realestate.db.models import (
    AuditEvent,
    HandlingMode,
    HandoffSource,
    HandoffStatus,
    HumanHandoffRequest,
    InternalAlert,
    InternalAlertKind,
    InternalAlertStatus,
    Opportunity,
)
from realestate.domain.commercial.assignment import Assignment
from realestate.domain.commercial.handling import ConversationHandling, TakeHandling
from realestate.domain.commercial.handoff import (
    ESCALATION_DELAY,
    HUMAN_HANDOFF_ACKNOWLEDGEMENT,
    AcknowledgeHandoff,
    HumanHandoff,
    RequestHumanHandling,
)
from realestate.domain.commercial.routing import (
    InboundRouting,
    detect_human_request,
)
from realestate.domain.commercial.team import StartAbsence, TeamAdministration
from realestate.domain.internal_alerts import InternalAlerts
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures.visits import key
from tests.fixtures import commercial, visits
from tests.fixtures.stubs import SCHEDULE, StubTelegram

pytestmark = requires_postgres


# -- Recognising the request ----------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "quiero hablar con una persona",
        "¿Puedo HABLAR CON ALGUIEN?",
        "prefiero hablar con una persona, gracias",
        "me pueden llamar por favor",
        "eres un bot?",
    ],
)
def test_an_explicit_request_for_a_person_is_recognised(message: str) -> None:
    """Deterministic Product policy, not model judgement: a paraphrase the list
    misses is covered by the typed tool, never by a guess."""
    assert detect_human_request(message) is not None


@pytest.mark.parametrize(
    "message",
    [
        "quiero ver la casa el sábado",
        "¿cuánto cuesta?",
        "hola",
        "",
    ],
)
def test_an_ordinary_message_is_not_a_request_for_a_person(message: str) -> None:
    assert detect_human_request(message) is None


# -- The immediate alert --------------------------------------------------


async def test_asking_for_a_person_pauses_maia_and_alerts_the_advisor(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        # Assign the Opportunity first so there is a Responsible Advisor to
        # alert; an unassigned pursuit is the Administrator's case below.
        conversation = await visits.inbound(
            session, wamid="w-ask", body="Quiero ver la casa"
        )
        await visits.confirmed_visit(built, session, conversation)

    async with database.session_scope() as session:
        await visits.inbound(
            session, wamid="w-ask2", body="Mejor quiero hablar con una persona"
        )

    async with database.session_scope() as session:
        request_row = await session.scalar(
            select(HumanHandoffRequest).where(
                HumanHandoffRequest.conversation_id == conversation.id
            )
        )
        snapshot = await ConversationHandling(session).snapshot(conversation.id)
        alerts = list(
            await session.scalars(
                select(InternalAlert).where(
                    InternalAlert.kind
                    == InternalAlertKind.HUMAN_HANDOFF_REQUESTED.value
                )
            )
        )

    assert request_row is not None
    assert request_row.source == HandoffSource.CONTACT_REQUEST.value
    assert request_row.status == HandoffStatus.PENDING.value
    assert request_row.advisor_id == built.advisor_id
    assert request_row.advisor_alert_at is not None
    # Fifteen minutes, from the request rather than from now.
    assert request_row.escalate_at - request_row.requested_at == ESCALATION_DELAY
    # Maia stops leading the conversation the moment the request lands.
    assert snapshot.mode is HandlingMode.HUMAN
    assert snapshot.holder_member_id == built.advisor_id
    assert not snapshot.maia_may_reply
    assert len(alerts) == 1
    assert alerts[0].recipient_member_id == built.advisor_id


async def test_the_acknowledgement_copy_promises_effort_not_a_deadline(
    operation,
) -> None:
    """PROJECT_MEMORY's exact sentence, owned by Product so no model run can
    turn a warm handoff into a service-level commitment."""
    assert "le avisaré al asesor" in HUMAN_HANDOFF_ACKNOWLEDGEMENT
    assert "No puedo confirmar su disponibilidad" in HUMAN_HANDOFF_ACKNOWLEDGEMENT
    for forbidden in ("minutos garantizados", "en 5 minutos", "de inmediato te"):
        assert forbidden not in HUMAN_HANDOFF_ACKNOWLEDGEMENT


async def test_three_requests_in_a_row_are_one_unmet_request(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-thrice", body="quiero hablar con alguien"
        )
    for index, body in enumerate(
        ("hola? quiero hablar con alguien", "me pueden llamar"), start=1
    ):
        async with database.session_scope() as session:
            await visits.inbound(session, wamid=f"w-thrice-{index}", body=body)

    async with database.session_scope() as session:
        rows = list(
            await session.scalars(
                select(HumanHandoffRequest).where(
                    HumanHandoffRequest.conversation_id == conversation.id
                )
            )
        )
        alerts = list(
            await session.scalars(
                select(InternalAlert).where(
                    InternalAlert.kind
                    == InternalAlertKind.HUMAN_HANDOFF_REQUESTED.value
                )
            )
        )

    assert len(rows) == 1
    assert len(alerts) == 1


async def test_with_nobody_responsible_the_conversation_needs_admin_review(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-noone", body="quiero hablar con un asesor"
        )

    async with database.session_scope() as session:
        request_row = await session.scalar(
            select(HumanHandoffRequest).where(
                HumanHandoffRequest.conversation_id == conversation.id
            )
        )
        snapshot = await ConversationHandling(session).snapshot(conversation.id)
        alerts = list(await session.scalars(select(InternalAlert)))

    assert request_row is not None
    assert request_row.advisor_id is None
    assert snapshot.mode is HandlingMode.ADMIN_REVIEW
    assert not snapshot.maia_may_reply
    # Addressed to every Administrator rather than to a person who does not
    # exist.
    assert [alert.recipient_member_id for alert in alerts] == [None]


async def test_an_absent_advisor_does_not_receive_the_alert_and_keeps_the_work(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-absent", body="Quiero ver la casa"
        )
        visit = await visits.confirmed_visit(built, session, conversation)
        opportunity_id = visit.opportunity_id

    async with database.session_scope() as session:
        await TeamAdministration(session).record(
            built.admin,
            StartAbsence(
                command_key=key("absence"),
                advisor_id=built.advisor_id,
                starts_at=visits.now() - timedelta(minutes=5),
                ends_at=visits.now() + timedelta(days=2),
            ),
        )
        await session.commit()

    async with database.session_scope() as session:
        await visits.inbound(
            session, wamid="w-absent2", body="quiero hablar con una persona"
        )

    async with database.session_scope() as session:
        request_row = await session.scalar(
            select(HumanHandoffRequest).where(
                HumanHandoffRequest.conversation_id == conversation.id
            )
        )
        opportunity = await session.get(Opportunity, opportunity_id)
        snapshot = await ConversationHandling(session).snapshot(conversation.id)

    assert request_row is not None
    # Alerting only somebody who cannot answer would be the silent failure.
    assert request_row.advisor_id is None
    assert snapshot.mode is HandlingMode.ADMIN_REVIEW
    # And still no reassignment: the Opportunity is the Advisor's.
    assert opportunity is not None
    assert opportunity.responsible_advisor_id == built.advisor_id


# -- The fifteen-minute escalation ----------------------------------------


async def test_nothing_escalates_before_fifteen_minutes(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        await visits.inbound(
            session, wamid="w-early", body="quiero hablar con alguien"
        )

    async with database.session_scope() as session:
        escalated = await HumanHandoff(session).escalate_due(
            visits.now() + timedelta(minutes=14)
        )
        rows = list(await session.scalars(select(HumanHandoffRequest)))

    assert escalated == 0
    assert rows[0].admin_alert_at is None


async def test_after_fifteen_minutes_the_administrator_is_alerted_once(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-esc", body="Quiero ver la casa"
        )
        await visits.confirmed_visit(built, session, conversation)
    async with database.session_scope() as session:
        await visits.inbound(
            session, wamid="w-esc2", body="quiero hablar con una persona"
        )

    later = visits.now() + ESCALATION_DELAY + timedelta(minutes=1)
    counts = []
    for _ in range(3):
        async with database.session_scope() as session:
            counts.append(await HumanHandoff(session).escalate_due(later))

    async with database.session_scope() as session:
        escalation_alerts = list(
            await session.scalars(
                select(InternalAlert).where(
                    InternalAlert.kind
                    == InternalAlertKind.HUMAN_HANDOFF_ESCALATED.value
                )
            )
        )
        request_row = await session.scalar(select(HumanHandoffRequest))
        audits = list(
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "EscalateHumanHandling"
                )
            )
        )

    assert counts == [1, 0, 0]
    assert len(escalation_alerts) == 1
    assert escalation_alerts[0].recipient_member_id is None
    assert "NO se reasignó" in escalation_alerts[0].body
    assert request_row is not None and request_row.admin_alert_at is not None
    assert len(audits) == 1
    assert audits[0].details["reassigned_opportunity"] is False


async def test_the_escalation_survives_a_restart(operation) -> None:
    """The deadline is stored, not held in a timer.

    Simulated by throwing away every in-memory object between passes: a fresh
    process re-derives the due set from the row and reaches the same answer.
    """
    database, built = operation
    async with database.session_scope() as session:
        await visits.inbound(
            session, wamid="w-restart", body="quiero hablar con alguien"
        )

    later = visits.now() + ESCALATION_DELAY + timedelta(seconds=30)

    # "Before the restart": the pass runs but the process dies before the
    # commit, which is modelled by rolling the session back.
    async with database.session_scope() as session:
        rows = list(
            await session.scalars(
                select(HumanHandoffRequest).where(
                    HumanHandoffRequest.escalate_at <= later
                )
            )
        )
        assert len(rows) == 1
        await session.rollback()

    # A brand new engine, as a restarted process would have.
    restarted = Database(DATABASE_URL)
    try:
        async with restarted.session_scope() as session:
            first = await HumanHandoff(session).escalate_due(later)
        async with restarted.session_scope() as session:
            second = await HumanHandoff(session).escalate_due(later)
    finally:
        await restarted.dispose()

    assert (first, second) == (1, 0)


async def test_taking_the_conversation_acknowledges_the_request(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-ack", body="quiero hablar con alguien"
        )
        opportunity = await session.scalar(select(Opportunity))
        assert opportunity is not None
        await Assignment(session).assign(built.admin, opportunity.id)
        await session.commit()

    async with database.session_scope() as session:
        await ConversationHandling(session).take(
            built.advisor,
            TakeHandling(conversation_id=conversation.id, command_key=key("take")),
        )
        await session.commit()

    later = visits.now() + ESCALATION_DELAY + timedelta(minutes=1)
    async with database.session_scope() as session:
        escalated = await HumanHandoff(session).escalate_due(later)
        request_row = await session.scalar(select(HumanHandoffRequest))

    # Requiring a second button would have the Administrator escalating a
    # request somebody is already answering.
    assert request_row is not None
    assert request_row.status == HandoffStatus.ACKNOWLEDGED.value
    assert request_row.resolved_by == built.advisor_id
    assert escalated == 0


async def test_acknowledging_without_taking_the_conversation_is_allowed(
    operation,
) -> None:
    """An Administrator routing it by phone should not have to claim WhatsApp."""
    database, built = operation
    async with database.session_scope() as session:
        await visits.inbound(session, wamid="w-ack2", body="me pueden llamar")

    async with database.session_scope() as session:
        request_row = await session.scalar(select(HumanHandoffRequest))
        assert request_row is not None
        await HumanHandoff(session).acknowledge(
            built.admin,
            AcknowledgeHandoff(request_id=request_row.id, command_key=key("ack")),
        )
        await session.commit()

    async with database.session_scope() as session:
        request_row = await session.scalar(select(HumanHandoffRequest))
        snapshot = await ConversationHandling(session).snapshot(
            request_row.conversation_id  # type: ignore[union-attr]
        )

    assert request_row is not None
    assert request_row.status == HandoffStatus.ACKNOWLEDGED.value
    # Handling authority did not silently move to the Administrator.
    assert snapshot.holder_member_id != built.admin_id


async def test_an_advisor_cannot_acknowledge_somebody_elses_request(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-mine", body="Quiero ver la casa"
        )
        await visits.confirmed_visit(built, session, conversation)
    async with database.session_scope() as session:
        await visits.inbound(
            session, wamid="w-mine2", body="quiero hablar con una persona"
        )

    async with database.session_scope() as session:
        request_row = await session.scalar(select(HumanHandoffRequest))
        assert request_row is not None
        from realestate.domain.commercial.actors import NotFound

        with pytest.raises(NotFound):
            await HumanHandoff(session).acknowledge(
                built.second_advisor,
                AcknowledgeHandoff(
                    request_id=request_row.id, command_key=key("ack")
                ),
            )


async def test_an_advisor_sees_only_their_own_pending_requests(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-scope", body="Quiero ver la casa"
        )
        await visits.confirmed_visit(built, session, conversation)
    async with database.session_scope() as session:
        await visits.inbound(
            session, wamid="w-scope2", body="quiero hablar con una persona"
        )

    async with database.session_scope() as session:
        handoff = HumanHandoff(session)
        mine = await handoff.pending(built.advisor)
        theirs = await handoff.pending(built.second_advisor)
        everything = await handoff.pending(built.admin)

    assert len(mine) == 1
    assert theirs == []
    assert len(everything) == 1


# -- Delivering the alert -------------------------------------------------


async def test_an_alert_reaches_the_configured_advisor_channel(operation) -> None:
    database, built = operation
    from realestate.worker.operations import OperationsWorker

    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-deliver", body="Quiero ver la casa"
        )
        await visits.confirmed_visit(built, session, conversation)
    async with database.session_scope() as session:
        await visits.inbound(
            session, wamid="w-deliver2", body="quiero hablar con una persona"
        )

    telegram = StubTelegram()
    worker = OperationsWorker(
        database=database,
        telegram=telegram,  # type: ignore[arg-type]
        schedule=SCHEDULE,
        day_of_reminder_hour=9,
        administrator_chat_ids=frozenset({"admin-chat"}),
    )
    await worker.tick()

    assert [notice.chat_id for notice in telegram.sent] == [
        commercial.ADVISOR_CHAT_ID
    ]
    assert "pidió hablar con una persona" in telegram.sent[0].body
    async with database.session_scope() as session:
        alert = await session.scalar(select(InternalAlert))
    assert alert is not None and alert.status == InternalAlertStatus.SENT.value


async def test_an_alert_with_no_channel_stays_visible_as_undeliverable(
    operation,
) -> None:
    """A missing configuration value must not make a request disappear."""
    database, built = operation
    from realestate.worker.operations import OperationsWorker

    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-nochan", body="Quiero ver la casa"
        )
        await visits.confirmed_visit(built, session, conversation)
        member = await session.get(visits.OrganizationMember, built.advisor_id)
        assert member is not None
        member.telegram_chat_id = None
        await session.commit()
    async with database.session_scope() as session:
        await visits.inbound(
            session, wamid="w-nochan2", body="quiero hablar con una persona"
        )

    telegram = StubTelegram()
    await OperationsWorker(
        database=database,
        telegram=telegram,  # type: ignore[arg-type]
        schedule=SCHEDULE,
        day_of_reminder_hour=9,
        administrator_chat_ids=frozenset(),
    ).tick()

    assert telegram.sent == []
    async with database.session_scope() as session:
        alert = await session.scalar(
            select(InternalAlert).where(
                InternalAlert.kind == InternalAlertKind.HUMAN_HANDOFF_REQUESTED.value
            )
        )
        notice = await session.scalar(
            select(InternalAlert).where(
                InternalAlert.kind == InternalAlertKind.ALERT_UNDELIVERABLE.value
            )
        )
        visible = await InternalAlerts(session).open_for(built.admin)

    assert alert is not None
    assert alert.status == InternalAlertStatus.UNDELIVERABLE.value
    # Still on the Administrator's screen, which is the point.
    assert alert.id in {row.id for row in visible}

    # ADR-0049's other half: the Administrators are told it could not be
    # delivered, rather than the failure living only in a log line.
    assert notice is not None
    assert notice.recipient_member_id is None
    assert notice.subject_id == str(alert.id)
    assert alert.title in notice.body
    assert notice.id in {row.id for row in visible}


async def test_an_undeliverable_broadcast_does_not_alert_about_itself(
    operation,
) -> None:
    """Otherwise the notice about a notice would never terminate.

    An undeliverable broadcast means no Administrator has a channel at all, so
    there is nobody left to tell. The CRM row is the answer in that case.
    """
    database, built = operation
    async with database.session_scope() as session:
        alerts = InternalAlerts(session)
        raised = await alerts.raise_alert(
            built.product,
            kind=InternalAlertKind.HUMAN_HANDOFF_ESCALATED,
            subject_type="Conversation",
            subject_id="broadcast",
            title="Solicitud sin tomar",
            body="Nadie la ha tomado.",
            dedupe_key="broadcast-undeliverable",
            recipient_member_id=None,
        )
        await session.commit()
        await alerts.mark_undeliverable(raised.id, "Sin canal.")

    async with database.session_scope() as session:
        kinds = list(
            await session.scalars(
                select(InternalAlert.kind).where(
                    InternalAlert.kind
                    == InternalAlertKind.ALERT_UNDELIVERABLE.value
                )
            )
        )
    assert kinds == []


async def test_a_delivered_alert_is_not_sent_twice(operation) -> None:
    database, built = operation
    from realestate.worker.operations import OperationsWorker

    async with database.session_scope() as session:
        await visits.inbound(
            session, wamid="w-once", body="quiero hablar con alguien"
        )

    telegram = StubTelegram()
    worker = OperationsWorker(
        database=database,
        telegram=telegram,  # type: ignore[arg-type]
        schedule=SCHEDULE,
        day_of_reminder_hour=9,
        administrator_chat_ids=frozenset({"admin-chat"}),
    )
    await worker.tick()
    await worker.tick()

    assert len(telegram.sent) == 1


async def test_maia_may_request_a_handoff_for_a_phrasing_the_list_misses(
    operation,
) -> None:
    """The typed tool and the deterministic detector reach the same module, so a
    request is recorded once either way."""
    database, built = operation
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-tool", body="¿me ayudan con algo delicado?"
        )
        await session.commit()

    async with database.session_scope() as session:
        recorded = await HumanHandoff(session).request(
            built.product,
            RequestHumanHandling(
                conversation=conversation,
                source=HandoffSource.CONTACT_REQUEST,
                detail="Pidió apoyo humano en otras palabras.",
            ),
        )
        await session.commit()

    assert recorded.created
    async with database.session_scope() as session:
        rows = list(await session.scalars(select(HumanHandoffRequest)))
        snapshot = await ConversationHandling(session).snapshot(conversation.id)
    assert len(rows) == 1
    assert not snapshot.maia_may_reply


async def test_routing_reports_what_it_did(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await visits.inbound(session, wamid="w-report", body="Hola")
        inbox_id = await session.scalar(
            select(visits.InboxMessage.id).where(
                visits.InboxMessage.conversation_id == conversation.id
            )
        )
        decision = await InboundRouting(session).route(
            lead=await session.get(visits.Lead, conversation.lead_id),  # type: ignore[arg-type]
            conversation=conversation,
            inbox_id=inbox_id,  # type: ignore[arg-type]
            text="quiero hablar con una persona",
        )
        await session.commit()

    assert decision.handed_off
    assert decision.reason == "ContactRequestedHuman"


# -- Closing a request without a human having answered -------------------


async def test_an_administrator_may_cancel_an_unmet_request_with_a_reason(
    operation,
) -> None:
    """The one path that makes an unmet request disappear, so it is attributable."""
    database, built = operation
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-cancel", body="quiero hablar con alguien"
        )

    async with database.session_scope() as session:
        cancelled = await HumanHandoff(session).cancel(
            built.admin, conversation.id, reason="El cliente ya se resolvió con Maia"
        )
        await session.commit()

    assert cancelled
    async with database.session_scope() as session:
        row = await session.scalar(select(HumanHandoffRequest))
        audits = list(
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "CancelHumanHandling"
                )
            )
        )
    assert row is not None
    assert row.status == HandoffStatus.CANCELLED.value
    assert row.resolved_at is not None
    assert audits and "ya se resolvió" in audits[0].details["reason"]


async def test_an_advisor_cannot_cancel_an_unmet_request(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-cancel2", body="quiero hablar con alguien"
        )

    async with database.session_scope() as session:
        from realestate.domain.commercial.actors import NotAuthorized

        with pytest.raises(NotAuthorized):
            await HumanHandoff(session).cancel(
                built.advisor, conversation.id, reason="no"
            )


async def test_cancelling_with_nothing_open_changes_nothing(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await visits.inbound(session, wamid="w-none", body="Hola")

    async with database.session_scope() as session:
        assert not await HumanHandoff(session).cancel(
            built.admin, conversation.id, reason="nada"
        )


async def test_an_acknowledged_request_reports_itself_unchanged(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        await visits.inbound(session, wamid="w-ack3", body="me pueden llamar")

    async with database.session_scope() as session:
        row = await session.scalar(select(HumanHandoffRequest))
        assert row is not None
        handoff = HumanHandoff(session)
        first = await handoff.acknowledge(
            built.admin,
            AcknowledgeHandoff(request_id=row.id, command_key=key("ack")),
        )
        second = await handoff.acknowledge(
            built.admin,
            AcknowledgeHandoff(request_id=row.id, command_key=key("ack")),
        )
        await session.commit()

    assert first.request_id == second.request_id
    assert not second.created


async def test_acknowledging_an_unknown_request_reads_as_absent(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        from realestate.domain.commercial.actors import NotFound

        with pytest.raises(NotFound):
            await HumanHandoff(session).acknowledge(
                built.admin,
                AcknowledgeHandoff(request_id=uuid.uuid4(), command_key=key("ack")),
            )


async def test_product_cannot_acknowledge_a_request(operation) -> None:
    """Only a person can say they are on it."""
    database, built = operation
    async with database.session_scope() as session:
        await visits.inbound(session, wamid="w-prod", body="me pueden llamar")

    async with database.session_scope() as session:
        row = await session.scalar(select(HumanHandoffRequest))
        assert row is not None
        from realestate.domain.commercial.actors import NotAuthorized

        with pytest.raises(NotAuthorized):
            await HumanHandoff(session).acknowledge(
                built.product,
                AcknowledgeHandoff(request_id=row.id, command_key=key("ack")),
            )


# -- The alert list an operator reads -------------------------------------


async def test_an_advisor_sees_only_alerts_addressed_to_them(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-scoped", body="Quiero ver la casa"
        )
        await visits.confirmed_visit(built, session, conversation)
    async with database.session_scope() as session:
        await visits.inbound(
            session, wamid="w-scoped2", body="quiero hablar con una persona"
        )

    async with database.session_scope() as session:
        alerts = InternalAlerts(session)
        mine = await alerts.open_for(built.advisor)
        theirs = await alerts.open_for(built.second_advisor)
        everything = await alerts.open_for(built.admin)

    assert len(mine) == 1
    assert theirs == []
    assert len(everything) >= 1


async def test_acknowledging_an_alert_removes_it_from_the_list(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        await visits.inbound(
            session, wamid="w-dismiss", body="quiero hablar con alguien"
        )

    async with database.session_scope() as session:
        alerts = InternalAlerts(session)
        open_now = await alerts.open_for(built.admin)
        assert open_now
        assert await alerts.acknowledge(built.admin, open_now[0].id)
        # Twice is a no-op rather than an error.
        assert not await alerts.acknowledge(built.admin, open_now[0].id)
        await session.commit()

    async with database.session_scope() as session:
        assert await InternalAlerts(session).open_for(built.admin) == []


async def test_an_advisor_cannot_dismiss_somebody_elses_alert(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-notmine", body="Quiero ver la casa"
        )
        await visits.confirmed_visit(built, session, conversation)
    async with database.session_scope() as session:
        await visits.inbound(
            session, wamid="w-notmine2", body="quiero hablar con una persona"
        )

    async with database.session_scope() as session:
        alerts = InternalAlerts(session)
        mine = await alerts.open_for(built.advisor)
        assert mine
        assert not await alerts.acknowledge(built.second_advisor, mine[0].id)
        assert not await alerts.acknowledge(built.admin, uuid.uuid4())


async def test_a_failed_delivery_is_retried_and_eventually_gives_up(
    operation,
) -> None:
    """A Telegram outage must not lose the alert, and must not retry forever."""
    database, built = operation
    from realestate.db.models import InternalAlertStatus as Status
    from realestate.worker.operations import OperationsWorker

    async with database.session_scope() as session:
        await visits.inbound(
            session, wamid="w-outage", body="quiero hablar con alguien"
        )

    class RefusingTelegram:
        def __init__(self) -> None:
            self.attempts = 0

        async def send_message(self, chat_id: str, text: str) -> bool:
            self.attempts += 1
            return False

    telegram = RefusingTelegram()
    worker = OperationsWorker(
        database=database,
        telegram=telegram,  # type: ignore[arg-type]
        schedule=SCHEDULE,
        day_of_reminder_hour=9,
        administrator_chat_ids=frozenset({"admin-chat"}),
    )
    for _ in range(6):
        await worker.tick()

    async with database.session_scope() as session:
        alert = await session.scalar(select(InternalAlert))
    assert alert is not None
    assert alert.status == Status.FAILED.value
    assert alert.last_error and "Telegram" in alert.last_error
    assert telegram.attempts >= 5


async def test_a_repeated_alert_key_returns_the_existing_alert(operation) -> None:
    """Idempotent creation is what lets a caller stamp "already alerted" in the
    same transaction without checking first."""
    database, built = operation
    from realestate.db.models import InternalAlertKind as Kind

    async with database.session_scope() as session:
        alerts = InternalAlerts(session)
        first = await alerts.raise_alert(
            built.admin,
            kind=Kind.ABSENCE_REVIEW,
            subject_type="OrganizationMember",
            subject_id=str(built.advisor_id),
            title="Uno",
            body="cuerpo",
            dedupe_key="same-key",
            recipient_member_id=None,
        )
        second = await alerts.raise_alert(
            built.admin,
            kind=Kind.ABSENCE_REVIEW,
            subject_type="OrganizationMember",
            subject_id=str(built.advisor_id),
            title="Dos",
            body="otro cuerpo",
            dedupe_key="same-key",
            recipient_member_id=None,
        )
        await session.commit()

    assert first.id == second.id
    assert second.title == "Uno"
