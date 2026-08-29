"""Opportunity stages: what may follow what, and what each outcome must prove.

The stage model is where a CRM usually rots. Two properties keep it honest here:
the legal-transition table is explicit rather than derived from an ordering, and
a terminal outcome cannot be reached without the evidence it requires — Lost
needs a reason, Dormant needs a revisit condition, Won needs an Administrator
and accepted operational evidence.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from realestate.db.engine import Database
from realestate.db.models import (
    ACTIVE_STAGES,
    AuditEvent,
    CommercialTransaction,
    NextActionKind,
    NextActionStatus,
    Opportunity,
    OpportunityExceptionReason,
    OpportunityKind,
    OpportunityOriginSource,
    OpportunityStage,
    OpportunityStageTransition,
)
from realestate.domain.commercial.actors import (
    Actor,
    InvalidTransition,
    MissingEvidence,
    NotAuthorized,
    NotFound,
    QualificationIncomplete,
)
from realestate.domain.commercial.needs import HORIZON, PropertyNeeds
from realestate.domain.commercial.next_actions import NextActions, ScheduleNextAction
from realestate.domain.commercial.opportunities import (
    ALLOWED_TRANSITIONS,
    STAGE_LABELS,
    AdvanceStage,
    DormantReason,
    LostReason,
    OpenOpportunity,
    OpportunityManagement,
    OriginFacts,
    RecordDormant,
    RecordLost,
    RecordWon,
    WonEvidence,
)
from realestate.domain.commercial.transactions import RecordTransaction, Transactions
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures import commercial

pytestmark = requires_postgres

NOW = commercial.now()


@pytest.fixture
async def wired():
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await commercial.reset(session)
        await commercial.provision(session)
    yield database
    await database.dispose()


async def _qualified_opportunity(session, *, wa_id="5213312345678"):  # noqa: ANN001, ANN202
    """An Opportunity with the minimum criteria confirmed, ready to qualify."""
    state = await commercial.opportunity_for(session, wa_id, confirm_criteria=True)
    return state.admin, state.opportunity_id


# -- Structure -------------------------------------------------------------


def test_every_stage_appears_in_the_transition_table_and_has_a_label() -> None:
    stages = {stage.value for stage in OpportunityStage}
    assert set(ALLOWED_TRANSITIONS) == stages
    assert set(STAGE_LABELS) == stages
    for targets in ALLOWED_TRANSITIONS.values():
        assert targets <= stages


def test_won_and_lost_are_terminal() -> None:
    assert ALLOWED_TRANSITIONS[OpportunityStage.WON.value] == frozenset()
    assert ALLOWED_TRANSITIONS[OpportunityStage.LOST.value] == frozenset()


def test_nothing_reaches_the_working_stages_without_being_qualified() -> None:
    """Searching, Visiting and Negotiating are only reachable past Qualified."""
    unqualified = (OpportunityStage.NEW.value, OpportunityStage.IN_CONVERSATION.value)
    working = {
        OpportunityStage.SEARCHING.value,
        OpportunityStage.VISITING.value,
        OpportunityStage.NEGOTIATING.value,
    }
    for stage in unqualified:
        assert not (ALLOWED_TRANSITIONS[stage] & working)


# -- Opening ---------------------------------------------------------------


async def test_opening_records_the_stage_the_origin_and_the_audit(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(
            session, actor, contact_id, command_key="open:one"
        )
        await session.commit()

        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None
        assert opportunity.stage == OpportunityStage.NEW.value
        assert opportunity.organization_id == actor.organization_id
        assert opportunity.qualified_at is None

        management = OpportunityManagement(session)
        origin = await management.origin(opportunity_id)
        assert origin is not None
        assert origin.source == OpportunityOriginSource.WHATSAPP_INBOUND.value
        transitions = await management.transitions(opportunity_id)
        assert [row.to_stage for row in transitions] == [OpportunityStage.NEW.value]
        assert transitions[0].from_stage is None
        assert (
            await session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action == "OpenOpportunity"
                )
            )
            == 1
        )


async def test_replaying_an_open_command_opens_nothing_new(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        management = OpportunityManagement(session)
        command = OpenOpportunity(
            contact_id=contact_id,
            kind=OpportunityKind.DEMAND,
            origin=OriginFacts(source=OpportunityOriginSource.ADVISOR_ENTRY),
            command_key="open:same",
        )
        first = await management.record(actor, command)
        second = await management.record(actor, command)

        assert second.opportunity_id == first.opportunity_id
        assert second.replayed is True
        assert second.created is False
        assert await session.scalar(select(func.count(Opportunity.id))) == 1


async def test_a_listing_acquisition_is_its_own_kind(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(
            session, actor, contact_id, kind=OpportunityKind.LISTING_ACQUISITION
        )
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None
        assert opportunity.kind == OpportunityKind.LISTING_ACQUISITION.value


async def test_the_first_attribution_survives_later_interactions(wired) -> None:
    """ADR-0023: a newer channel is an interaction, never a new origin."""
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        management = OpportunityManagement(session)
        opened = await management.record(
            actor,
            OpenOpportunity(
                contact_id=contact_id,
                kind=OpportunityKind.DEMAND,
                origin=OriginFacts(
                    source=OpportunityOriginSource.CAMPAIGN,
                    channel="WhatsApp",
                    campaign="lanzamiento-agosto",
                ),
                command_key="open:campaign",
            ),
        )
        await management.record(
            actor,
            AdvanceStage(
                opportunity_id=opened.opportunity_id,
                to_stage=OpportunityStage.IN_CONVERSATION,
                command_key="advance:later",
            ),
        )
        await session.commit()

        origin = await management.origin(opened.opportunity_id)
        assert origin is not None
        assert origin.source == OpportunityOriginSource.CAMPAIGN.value
        assert origin.campaign == "lanzamiento-agosto"
        assert (
            await session.scalar(
                select(func.count()).select_from(
                    select(OpportunityStageTransition.id).subquery()
                )
            )
            == 2
        )


# -- Legal and illegal transitions ----------------------------------------


async def test_a_new_opportunity_may_enter_conversation(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, actor, contact_id)

        result = await OpportunityManagement(session).record(
            actor,
            AdvanceStage(
                opportunity_id=opportunity_id,
                to_stage=OpportunityStage.IN_CONVERSATION,
                command_key="advance:conv",
            ),
        )
        assert result.stage is OpportunityStage.IN_CONVERSATION


async def test_skipping_qualification_is_refused(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, actor, contact_id)

        with pytest.raises(InvalidTransition, match="Nueva"):
            await OpportunityManagement(session).record(
                actor,
                AdvanceStage(
                    opportunity_id=opportunity_id,
                    to_stage=OpportunityStage.SEARCHING,
                    command_key="advance:skip",
                ),
            )


async def test_moving_to_the_stage_it_is_already_in_is_refused(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, actor, contact_id)

        with pytest.raises(InvalidTransition, match="ya está"):
            await OpportunityManagement(session).record(
                actor,
                AdvanceStage(
                    opportunity_id=opportunity_id,
                    to_stage=OpportunityStage.NEW,
                    command_key="advance:same",
                ),
            )


async def test_a_terminal_outcome_needs_its_own_command(wired) -> None:
    """A generic advance cannot carry the evidence an outcome requires."""
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, actor, contact_id)

        for stage in (
            OpportunityStage.WON,
            OpportunityStage.LOST,
            OpportunityStage.DORMANT,
        ):
            with pytest.raises(InvalidTransition, match="comando específico"):
                await OpportunityManagement(session).record(
                    actor,
                    AdvanceStage(
                        opportunity_id=opportunity_id,
                        to_stage=stage,
                        command_key=f"advance:{stage.value}",
                    ),
                )


async def test_a_won_opportunity_cannot_move_again(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _qualified_opportunity(session)
        management = OpportunityManagement(session)
        await management.record(
            admin,
            AdvanceStage(
                opportunity_id=opportunity_id,
                to_stage=OpportunityStage.QUALIFIED,
                command_key="q:1",
            ),
        )
        await management.record(
            admin,
            RecordWon(
                opportunity_id=opportunity_id,
                evidence=WonEvidence.SIGNED_RENTAL_AGREEMENT,
                evidence_detail="Contrato de arrendamiento firmado.",
                command_key="won:1",
            ),
        )
        with pytest.raises(InvalidTransition):
            await management.record(
                admin,
                RecordLost(
                    opportunity_id=opportunity_id,
                    reason=LostReason.UNKNOWN,
                    command_key="lost:after-won",
                ),
            )


# -- Qualification ---------------------------------------------------------


async def test_qualifying_without_confirmed_criteria_is_refused(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, actor, contact_id)

        with pytest.raises(QualificationIncomplete, match="Faltan criterios"):
            await OpportunityManagement(session).record(
                actor,
                AdvanceStage(
                    opportunity_id=opportunity_id,
                    to_stage=OpportunityStage.QUALIFIED,
                    command_key="q:missing",
                ),
            )


async def test_pending_interpretations_do_not_qualify_and_say_so(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, actor, contact_id)
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None and opportunity.property_need_id is not None
        await commercial.confirm_minimum_criteria(
            session, actor, opportunity.property_need_id, omit=(HORIZON,)
        )
        from realestate.domain.commercial.needs import CriterionStatement

        await PropertyNeeds(session).record(
            actor,
            opportunity.property_need_id,
            [CriterionStatement.inferred(HORIZON, "quizá este año")],
        )

        with pytest.raises(QualificationIncomplete) as raised:
            await OpportunityManagement(session).record(
                actor,
                AdvanceStage(
                    opportunity_id=opportunity_id,
                    to_stage=OpportunityStage.QUALIFIED,
                    command_key="q:pending",
                ),
            )
        assert "Horizonte aproximado" in raised.value.message
        assert "sin confirmar" in raised.value.message


async def test_qualifying_without_a_need_is_refused(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(
            session, actor, contact_id, with_need=False
        )

        with pytest.raises(QualificationIncomplete, match="Registra la necesidad"):
            await OpportunityManagement(session).record(
                actor,
                AdvanceStage(
                    opportunity_id=opportunity_id,
                    to_stage=OpportunityStage.QUALIFIED,
                    command_key="q:no-need",
                ),
            )


async def test_a_stale_need_must_be_reconfirmed_before_qualifying(wired) -> None:
    from datetime import timedelta

    from realestate.db.models import PROPERTY_NEED_STALE_DAYS

    async with wired.session_scope() as session:
        admin, opportunity_id = await _qualified_opportunity(session)
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None and opportunity.property_need_id is not None
        need_id = opportunity.property_need_id
        await session.commit()

    async with wired.session_scope() as session:
        await PropertyNeeds(session).refresh_stale(
            now=commercial.now() + timedelta(days=PROPERTY_NEED_STALE_DAYS + 1)
        )

    async with wired.session_scope() as session:
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        with pytest.raises(QualificationIncomplete, match="90 días"):
            await OpportunityManagement(session).record(
                actor,
                AdvanceStage(
                    opportunity_id=opportunity_id,
                    to_stage=OpportunityStage.QUALIFIED,
                    command_key="q:stale",
                ),
            )
        assert need_id is not None


async def test_qualification_needs_a_verified_contact_path(wired) -> None:
    """A Contact nobody can legitimately reach is not a Qualified Opportunity."""
    async with wired.session_scope() as session:
        from realestate.db.models import ChannelIdentityTrust, ContactChannelIdentity

        admin, opportunity_id = await _qualified_opportunity(session)
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None
        identity = await session.scalar(
            select(ContactChannelIdentity).where(
                ContactChannelIdentity.contact_id == opportunity.contact_id
            )
        )
        assert identity is not None
        identity.trust = ChannelIdentityTrust.ASSERTED.value
        await session.flush()

        with pytest.raises(QualificationIncomplete, match="vía de contacto"):
            await OpportunityManagement(session).record(
                admin,
                AdvanceStage(
                    opportunity_id=opportunity_id,
                    to_stage=OpportunityStage.QUALIFIED,
                    command_key="q:untrusted",
                ),
            )


async def test_qualifying_stamps_the_moment_and_assigns_an_advisor(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _qualified_opportunity(session)

        result = await OpportunityManagement(session).record(
            admin,
            AdvanceStage(
                opportunity_id=opportunity_id,
                to_stage=OpportunityStage.QUALIFIED,
                command_key="q:ok",
                at=NOW,
            ),
        )
        await session.commit()

        assert result.stage is OpportunityStage.QUALIFIED
        assert result.queued_for_assignment is False
        assert result.responsible_advisor_id is not None
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None
        assert opportunity.qualified_at == NOW
        assert opportunity.responsible_advisor_id == result.responsible_advisor_id


async def test_advancing_past_qualified_keeps_the_original_qualified_stamp(
    wired,
) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _qualified_opportunity(session)
        management = OpportunityManagement(session)
        await management.record(
            admin,
            AdvanceStage(
                opportunity_id=opportunity_id,
                to_stage=OpportunityStage.QUALIFIED,
                command_key="q:1",
                at=NOW,
            ),
        )
        await management.record(
            admin,
            AdvanceStage(
                opportunity_id=opportunity_id,
                to_stage=OpportunityStage.SEARCHING,
                command_key="q:2",
            ),
        )
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None and opportunity.qualified_at == NOW


# -- Outcomes --------------------------------------------------------------


async def test_lost_requires_a_reason_and_records_it(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, actor, contact_id)

        await OpportunityManagement(session).record(
            actor,
            RecordLost(
                opportunity_id=opportunity_id,
                reason=LostReason.BOUGHT_ELSEWHERE,
                detail="Compró en otro fraccionamiento.",
                command_key="lost:1",
                at=NOW,
            ),
        )
        await session.commit()

        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None
        assert opportunity.stage == OpportunityStage.LOST.value
        assert opportunity.lost_reason == LostReason.BOUGHT_ELSEWHERE.value
        assert opportunity.closed_at == NOW


async def test_unknown_is_an_explicit_allowed_lost_reason(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, actor, contact_id)
        await OpportunityManagement(session).record(
            actor,
            RecordLost(
                opportunity_id=opportunity_id,
                reason=LostReason.UNKNOWN,
                command_key="lost:unknown",
            ),
        )
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None
        assert opportunity.lost_reason == "Unknown"


async def test_dormant_requires_a_revisit_condition_and_is_not_lost(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, actor, contact_id)
        management = OpportunityManagement(session)

        with pytest.raises(MissingEvidence, match="condición"):
            await management.record(
                actor,
                RecordDormant(
                    opportunity_id=opportunity_id,
                    reason=DormantReason.NO_RESPONSE,
                    revisit_condition="   ",
                    command_key="dormant:blank",
                ),
            )

        await management.record(
            actor,
            RecordDormant(
                opportunity_id=opportunity_id,
                reason=DormantReason.AWAITING_NEW_INVENTORY,
                revisit_condition="Cuando entre inventario en Zapopan norte.",
                command_key="dormant:ok",
            ),
        )
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None
        assert opportunity.stage == OpportunityStage.DORMANT.value
        assert opportunity.lost_reason is None
        # Dormant is paused, not concluded.
        assert opportunity.closed_at is None
        assert (
            opportunity.dormant_revisit_condition
            == "Cuando entre inventario en Zapopan norte."
        )


async def test_a_dormant_opportunity_can_be_reactivated(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, actor, contact_id)
        management = OpportunityManagement(session)
        await management.record(
            actor,
            RecordDormant(
                opportunity_id=opportunity_id,
                reason=DormantReason.NO_RESPONSE,
                revisit_condition="Si vuelve a escribir.",
                command_key="dormant:1",
            ),
        )

        result = await management.record(
            actor,
            AdvanceStage(
                opportunity_id=opportunity_id,
                to_stage=OpportunityStage.IN_CONVERSATION,
                reason="Reactivation",
                command_key="reactivate:1",
            ),
        )
        assert result.stage is OpportunityStage.IN_CONVERSATION
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None
        assert opportunity.dormant_reason is None
        assert opportunity.dormant_revisit_condition is None
        # The pause is still legible in the history.
        history = await management.transitions(opportunity_id)
        assert any(row.to_stage == OpportunityStage.DORMANT.value for row in history)


async def test_only_an_administrator_may_mark_won(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _qualified_opportunity(session)
        management = OpportunityManagement(session)
        await management.record(
            admin,
            AdvanceStage(
                opportunity_id=opportunity_id,
                to_stage=OpportunityStage.QUALIFIED,
                command_key="q:1",
            ),
        )
        await session.commit()

    async with wired.session_scope() as session:
        advisor = await commercial.actor_for(session, commercial.ADVISOR_LOGIN)
        with pytest.raises(NotAuthorized, match="administrador"):
            await OpportunityManagement(session).record(
                advisor,
                RecordWon(
                    opportunity_id=opportunity_id,
                    evidence=WonEvidence.COMPLETED_SALE,
                    evidence_detail="Dice que ya se cerró.",
                    command_key="won:advisor",
                ),
            )


async def test_product_itself_may_not_mark_won(wired) -> None:
    """ADR-0032 reserves the win for a human who accepted evidence."""
    async with wired.session_scope() as session:
        admin, opportunity_id = await _qualified_opportunity(session)
        management = OpportunityManagement(session)
        await management.record(
            admin,
            AdvanceStage(
                opportunity_id=opportunity_id,
                to_stage=OpportunityStage.QUALIFIED,
                command_key="q:1",
            ),
        )
        product = await commercial.product_actor(session)
        with pytest.raises(NotAuthorized):
            await management.record(
                product,
                RecordWon(
                    opportunity_id=opportunity_id,
                    evidence=WonEvidence.COMPLETED_SALE,
                    evidence_detail="Inferido de la conversación.",
                    command_key="won:product",
                ),
            )


async def test_won_requires_described_evidence(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _qualified_opportunity(session)
        management = OpportunityManagement(session)
        await management.record(
            admin,
            AdvanceStage(
                opportunity_id=opportunity_id,
                to_stage=OpportunityStage.QUALIFIED,
                command_key="q:1",
            ),
        )
        with pytest.raises(MissingEvidence, match="evidencia"):
            await management.record(
                admin,
                RecordWon(
                    opportunity_id=opportunity_id,
                    evidence=WonEvidence.SIGNED_RENTAL_AGREEMENT,
                    evidence_detail="  ",
                    command_key="won:blank",
                ),
            )


async def test_a_visit_is_not_enough_to_win(wired) -> None:
    """The vocabulary itself excludes visits, offers and reservations."""
    accepted = {evidence.value for evidence in WonEvidence}
    assert accepted == {
        "CompletedSale",
        "SignedRentalAgreement",
        "AcceptedBindingPresale",
    }
    for excluded in ("VisitCompleted", "OfferAccepted", "Reservation"):
        assert excluded not in accepted
    async with wired.session_scope() as session:
        assert session is not None


async def test_won_records_who_accepted_the_evidence(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _qualified_opportunity(session)
        management = OpportunityManagement(session)
        await management.record(
            admin,
            AdvanceStage(
                opportunity_id=opportunity_id,
                to_stage=OpportunityStage.QUALIFIED,
                command_key="q:1",
            ),
        )
        await management.record(
            admin,
            RecordWon(
                opportunity_id=opportunity_id,
                evidence=WonEvidence.ACCEPTED_BINDING_PRESALE,
                evidence_detail="Contrato de preventa aceptado, folio 8891.",
                command_key="won:1",
                at=NOW,
            ),
        )
        await session.commit()

        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None
        assert opportunity.stage == OpportunityStage.WON.value
        assert opportunity.won_recorded_by == admin.member_id
        assert opportunity.won_evidence_detail.startswith("Contrato de preventa")
        assert opportunity.closed_at == NOW
        transaction = await session.scalar(
            select(CommercialTransaction).where(
                CommercialTransaction.opportunity_id == opportunity_id
            )
        )
        assert transaction is not None
        assert transaction.contact_id == opportunity.contact_id
        assert transaction.evidence == WonEvidence.ACCEPTED_BINDING_PRESALE.value
        assert transaction.accepted_by == admin.member_id
        assert transaction.completed_at == NOW


async def test_a_pipeline_stage_cannot_create_a_transaction_directly(wired) -> None:
    """Transaction is a concluded deal, not a convenient Opportunity alias."""
    async with wired.session_scope() as session:
        admin, opportunity_id = await _qualified_opportunity(session)
        with pytest.raises(InvalidTransition, match="oportunidad ganada"):
            await Transactions(session).record(
                admin,
                RecordTransaction(
                    opportunity_id=opportunity_id,
                    evidence=WonEvidence.COMPLETED_SALE.value,
                    evidence_detail="Todavía no hay cierre aceptado.",
                    completed_at=NOW,
                    command_key="transaction:premature",
                ),
            )


# -- Closing side effects --------------------------------------------------


async def test_concluding_cancels_the_pending_next_action(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _qualified_opportunity(session)
        management = OpportunityManagement(session)
        await management.record(
            admin,
            AdvanceStage(
                opportunity_id=opportunity_id,
                to_stage=OpportunityStage.QUALIFIED,
                command_key="q:1",
            ),
        )
        scheduled = await NextActions(session).schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.CALL,
                due_at=NOW,
                command_key="action:1",
            ),
        )
        await management.record(
            admin,
            RecordLost(
                opportunity_id=opportunity_id,
                reason=LostReason.NOT_INTERESTED,
                command_key="lost:1",
            ),
        )
        await session.commit()

        from realestate.db.models import NextAction

        action = await session.get(NextAction, scheduled.next_action_id)
        assert action is not None
        assert action.status == NextActionStatus.CANCELLED.value
        assert await NextActions(session).pending(opportunity_id) is None


async def test_concluding_clears_an_open_exception(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, admin, contact_id)
        management = OpportunityManagement(session)
        await management.record_exception(
            admin,
            opportunity_id,
            reason=OpportunityExceptionReason.AWAITING_CONTACT,
            detail="Quedó de avisar.",
            command_key="exc:1",
        )
        assert await management.open_exception(opportunity_id) is not None

        await management.record(
            admin,
            RecordDormant(
                opportunity_id=opportunity_id,
                reason=DormantReason.NO_RESPONSE,
                revisit_condition="Si responde.",
                command_key="dormant:1",
            ),
        )
        assert await management.open_exception(opportunity_id) is None


# -- Exceptions ------------------------------------------------------------


async def test_an_exception_is_recorded_audited_and_singular(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, admin, contact_id)
        management = OpportunityManagement(session)

        first = await management.record_exception(
            admin,
            opportunity_id,
            reason=OpportunityExceptionReason.AWAITING_CONTACT,
            detail="Quedó de avisar.",
            command_key="exc:1",
        )
        replayed = await management.record_exception(
            admin,
            opportunity_id,
            reason=OpportunityExceptionReason.AWAITING_CONTACT,
            detail="Quedó de avisar.",
            command_key="exc:1",
        )
        assert replayed.id == first.id

        replaced = await management.record_exception(
            admin,
            opportunity_id,
            reason=OpportunityExceptionReason.ADMIN_REVIEW,
            detail="Necesita revisión.",
            command_key="exc:2",
        )
        await session.commit()

        assert replaced.id != first.id
        open_now = await management.open_exception(opportunity_id)
        assert open_now is not None and open_now.id == replaced.id
        assert (
            await session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action == "RecordOpportunityException"
                )
            )
            == 2
        )


async def test_clearing_an_absent_exception_reports_nothing_to_clear(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, admin, contact_id)
        management = OpportunityManagement(session)

        assert await management.clear_exception(admin, opportunity_id) is False
        await management.record_exception(
            admin,
            opportunity_id,
            reason=OpportunityExceptionReason.DO_NOT_CONTACT,
            detail=None,
            command_key="exc:1",
        )
        assert await management.clear_exception(admin, opportunity_id) is True
        assert await management.open_exception(opportunity_id) is None


# -- Reads and scoping -----------------------------------------------------


async def test_an_unknown_opportunity_is_not_found(wired) -> None:
    async with wired.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        with pytest.raises(NotFound):
            await OpportunityManagement(session).opportunity(admin, uuid.uuid4())


async def test_another_organizations_opportunity_is_not_found(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, admin, contact_id)
        outsider = Actor.product(uuid.uuid4(), "OtraOrganizacion")
        with pytest.raises(NotFound):
            await OpportunityManagement(session).opportunity(outsider, opportunity_id)


async def test_an_active_demand_opportunity_is_reused_not_duplicated(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, admin, contact_id)
        management = OpportunityManagement(session)

        found = await management.open_demand_for_contact(contact_id)
        assert found is not None and found.id == opportunity_id


async def test_a_dormant_opportunity_is_not_offered_as_the_active_one(wired) -> None:
    """A message from a paused Contact is a human decision, not a reactivation."""
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, admin, contact_id)
        management = OpportunityManagement(session)
        await management.record(
            admin,
            RecordDormant(
                opportunity_id=opportunity_id,
                reason=DormantReason.NO_RESPONSE,
                revisit_condition="Si responde.",
                command_key="dormant:1",
            ),
        )
        assert await management.open_demand_for_contact(contact_id) is None
        assert OpportunityStage.DORMANT.value not in ACTIVE_STAGES


async def test_noting_an_interaction_never_moves_the_stage(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, admin, contact_id)
        management = OpportunityManagement(session)
        from datetime import timedelta

        later = commercial.now() + timedelta(hours=3)
        await management.note_interaction(opportunity_id, at=later)
        await management.note_interaction(opportunity_id, at=later - timedelta(hours=2))
        await management.note_interaction(uuid.uuid4())
        await session.flush()

        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None
        assert opportunity.stage == OpportunityStage.NEW.value
        assert opportunity.last_activity_at == later
