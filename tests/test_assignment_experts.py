"""The complete deterministic assignment rule, one clause at a time.

Preserve an existing Responsible Advisor; otherwise the Property's present
Property Expert, then its backups in rank order; otherwise the configured
default Advisor; otherwise the Assignment Queue with a reason an Administrator
can act on.

"Present" is the clause with teeth. An absent or deactivated candidate is
skipped at every level, not only at the fallback — a specialist on holiday
receiving new work is exactly the failure Stage 3 removes — and the queue reason
distinguishes "everybody is away" from "nobody is configured", because the two
need different actions.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from realestate.db.models import (
    AssignmentBasis,
    AssignmentQueueReason,
    Opportunity,
    OpportunityAssignment,
    OpportunityKind,
    OpportunityOriginSource,
    OrganizationMember,
    PropertyExpertRole,
)
from realestate.domain.commercial.actors import NotAuthorized
from realestate.domain.commercial.assignment import Assignment
from realestate.domain.commercial.needs import PropertyNeeds
from realestate.domain.commercial.opportunities import (
    OpenOpportunity,
    OpportunityManagement,
    OriginFacts,
)
from realestate.domain.commercial.team import (
    DesignateExpert,
    SetMemberActive,
    StartAbsence,
    TeamAdministration,
)
from tests.conftest import requires_postgres
from tests.fixtures.visits import key
from tests.fixtures import commercial, visits

pytestmark = requires_postgres


async def opportunity_about_the_property(session, built, *, wa_id="5213311110000"):  # noqa: ANN001, ANN202
    """An Opportunity whose preserved origin names the Property.

    That origin is what makes the expert branch reachable: the rule asks what
    this pursuit is about, and attribution is already the record of it.
    """
    contact_id, _lead = await commercial.make_contact(session, wa_id)
    need = await PropertyNeeds(session).open(built.admin, contact_id=contact_id)
    recorded = await OpportunityManagement(session).record(
        built.admin,
        OpenOpportunity(
            contact_id=contact_id,
            kind=OpportunityKind.DEMAND,
            property_need_id=need.id,
            origin=OriginFacts(
                source=OpportunityOriginSource.WHATSAPP_INBOUND,
                channel="WhatsApp",
                property_uuid=built.property_uuid,
            ),
            command_key=key("open"),
        ),
    )
    await session.flush()
    return recorded.opportunity_id


async def designate(session, built, advisor_id, role, rank=0):  # noqa: ANN001, ANN202
    await TeamAdministration(session).record(
        built.admin,
        DesignateExpert(
            command_key=key("expert"),
            property_uuid=built.property_uuid,
            advisor_id=advisor_id,
            role=role,
            rank=rank,
        ),
    )


async def make_absent(session, built, advisor_id) -> None:  # noqa: ANN001
    await TeamAdministration(session).record(
        built.admin,
        StartAbsence(
            command_key=key("absence"),
            advisor_id=advisor_id,
            starts_at=visits.now() - timedelta(hours=1),
            ends_at=visits.now() + timedelta(days=7),
        ),
    )


# -- The rule, clause by clause -------------------------------------------


async def test_a_present_property_expert_receives_the_opportunity(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        opportunity_id = await opportunity_about_the_property(session, built)
        # The second Advisor is the specialist; the first is the default.
        await designate(
            session, built, built.second_advisor_id, PropertyExpertRole.PRIMARY
        )
        outcome = await Assignment(session).assign(built.admin, opportunity_id)
        await session.commit()

    assert outcome.advisor_id == built.second_advisor_id
    assert outcome.basis is AssignmentBasis.PROPERTY_EXPERT
    assert not outcome.queued


async def test_an_absent_expert_hands_over_to_the_backup(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        opportunity_id = await opportunity_about_the_property(session, built)
        await designate(
            session, built, built.second_advisor_id, PropertyExpertRole.PRIMARY
        )
        await designate(
            session, built, built.advisor_id, PropertyExpertRole.BACKUP, rank=1
        )
        await make_absent(session, built, built.second_advisor_id)
        outcome = await Assignment(session).assign(built.admin, opportunity_id)
        await session.commit()

    assert outcome.advisor_id == built.advisor_id
    # Recorded as the backup branch, not as "the specialist took it": the two
    # are different facts about the operation.
    assert outcome.basis is AssignmentBasis.PROPERTY_EXPERT_BACKUP


async def test_a_deactivated_expert_is_skipped(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        opportunity_id = await opportunity_about_the_property(session, built)
        await designate(
            session, built, built.second_advisor_id, PropertyExpertRole.PRIMARY
        )
        await TeamAdministration(session).record(
            built.admin,
            SetMemberActive(
                command_key=key("state"),
                member_id=built.second_advisor_id,
                active=False,
            ),
        )
        outcome = await Assignment(session).assign(built.admin, opportunity_id)
        await session.commit()

    assert outcome.advisor_id == built.advisor_id
    assert outcome.basis is AssignmentBasis.DEFAULT_ADVISOR


async def test_with_no_expert_the_default_advisor_takes_it(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        opportunity_id = await opportunity_about_the_property(session, built)
        outcome = await Assignment(session).assign(built.admin, opportunity_id)
        await session.commit()

    assert outcome.advisor_id == built.advisor_id
    assert outcome.basis is AssignmentBasis.DEFAULT_ADVISOR


async def test_an_absent_default_advisor_sends_it_to_the_queue(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        opportunity_id = await opportunity_about_the_property(session, built)
        await make_absent(session, built, built.advisor_id)
        outcome = await Assignment(session).assign(built.admin, opportunity_id)
        await session.commit()

    assert outcome.queued
    assert outcome.advisor_id is None
    assert outcome.queue_reason is AssignmentQueueReason.EVERY_CANDIDATE_ABSENT


async def test_every_candidate_absent_names_the_absence_as_the_reason(
    operation,
) -> None:
    """The remedy differs from "nobody is configured", so the reason must too."""
    database, built = operation
    async with database.session_scope() as session:
        opportunity_id = await opportunity_about_the_property(session, built)
        await designate(
            session, built, built.second_advisor_id, PropertyExpertRole.PRIMARY
        )
        await make_absent(session, built, built.second_advisor_id)
        await make_absent(session, built, built.advisor_id)
        outcome = await Assignment(session).assign(built.admin, opportunity_id)
        await session.commit()

        queue = await Assignment(session).queue(built.admin)

    assert outcome.queue_reason is AssignmentQueueReason.EVERY_CANDIDATE_ABSENT
    assert [row.opportunity.id for row in queue] == [opportunity_id]
    assert queue[0].detail is not None and "ausentes" in queue[0].detail


async def test_an_existing_responsible_advisor_is_preserved_over_an_expert(
    operation,
) -> None:
    """The first clause beats the second, which is what makes ownership stable."""
    database, built = operation
    async with database.session_scope() as session:
        opportunity_id = await opportunity_about_the_property(session, built)
        first = await Assignment(session).assign(built.admin, opportunity_id)
        await session.commit()

    async with database.session_scope() as session:
        # Somebody else becomes the specialist afterwards.
        await designate(
            session, built, built.second_advisor_id, PropertyExpertRole.PRIMARY
        )
        again = await Assignment(session).assign(built.admin, opportunity_id)
        await session.commit()

    assert first.advisor_id == built.advisor_id
    assert again.advisor_id == built.advisor_id
    assert again.basis is AssignmentBasis.PRESERVED
    assert not again.created


async def test_an_opportunity_with_no_property_never_reaches_the_expert_branch(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        contact_id, _lead = await commercial.make_contact(session, "5213312223333")
        opportunity_id = await commercial.open_opportunity(
            session, built.admin, contact_id
        )
        await designate(
            session, built, built.second_advisor_id, PropertyExpertRole.PRIMARY
        )
        outcome = await Assignment(session).assign(built.admin, opportunity_id)
        await session.commit()

    assert outcome.advisor_id == built.advisor_id
    assert outcome.basis is AssignmentBasis.DEFAULT_ADVISOR


async def test_prospective_assignment_changes_nothing(operation) -> None:
    """Quoting availability must not create a period of responsibility."""
    database, built = operation
    async with database.session_scope() as session:
        opportunity_id = await opportunity_about_the_property(session, built)
        await session.commit()

    async with database.session_scope() as session:
        candidate, why = await Assignment(session).prospective(
            built.admin, opportunity_id
        )
        await session.commit()

    async with database.session_scope() as session:
        opportunity = await session.get(Opportunity, opportunity_id)
        assignments = list(
            await session.scalars(
                select(OpportunityAssignment).where(
                    OpportunityAssignment.opportunity_id == opportunity_id
                )
            )
        )

    assert candidate is not None
    assert candidate.id == built.advisor_id
    assert why is None
    assert opportunity is not None
    assert opportunity.responsible_advisor_id is None
    assert assignments == []


async def test_prospective_assignment_prefers_the_present_expert(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        opportunity_id = await opportunity_about_the_property(session, built)
        await designate(
            session, built, built.second_advisor_id, PropertyExpertRole.PRIMARY
        )
        await session.commit()

    async with database.session_scope() as session:
        candidate, _why = await Assignment(session).prospective(
            built.admin, opportunity_id
        )

    assert candidate is not None
    assert candidate.id == built.second_advisor_id


async def test_an_administrator_cannot_manually_assign_to_an_absent_advisor(
    operation,
) -> None:
    """A declared absence is the operation's own record; a manual override
    contradicting it silently would make the record meaningless."""
    database, built = operation
    async with database.session_scope() as session:
        opportunity_id = await opportunity_about_the_property(session, built)
        await make_absent(session, built, built.second_advisor_id)
        await session.commit()

    async with database.session_scope() as session:
        with pytest.raises(NotAuthorized) as raised:
            await Assignment(session).assign_manually(
                built.admin, opportunity_id, built.second_advisor_id
            )

    assert "ausencia" in str(raised.value)


async def test_an_advisor_cannot_assign_manually(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        opportunity_id = await opportunity_about_the_property(session, built)
        await session.commit()

    async with database.session_scope() as session:
        with pytest.raises(NotAuthorized):
            await Assignment(session).assign_manually(
                built.advisor, opportunity_id, built.advisor_id
            )


async def test_two_concurrent_assignments_produce_one_responsible_advisor(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        opportunity_id = await opportunity_about_the_property(session, built)
        await session.commit()

    async with database.session_scope() as first:
        async with database.session_scope() as second:
            one = await Assignment(first).assign(built.admin, opportunity_id)
            await first.commit()
            two = await Assignment(second).assign(built.admin, opportunity_id)
            await second.commit()

    assert one.advisor_id == two.advisor_id
    async with database.session_scope() as session:
        open_rows = list(
            await session.scalars(
                select(OpportunityAssignment)
                .where(OpportunityAssignment.opportunity_id == opportunity_id)
                .where(OpportunityAssignment.unassigned_at.is_(None))
            )
        )
    assert len(open_rows) == 1


async def test_a_member_who_cannot_own_work_is_never_chosen(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        administrator = await session.get(OrganizationMember, built.admin_id)
        assert administrator is not None
        assert not administrator.advises
        opportunity_id = await opportunity_about_the_property(session, built)
        await designate(session, built, built.advisor_id, PropertyExpertRole.PRIMARY)
        outcome = await Assignment(session).assign(built.admin, opportunity_id)
        await session.commit()

    assert outcome.advisor_id == built.advisor_id
