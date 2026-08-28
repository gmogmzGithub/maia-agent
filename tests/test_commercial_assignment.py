"""Assignment: preserve, fall back, or make the absence visible.

An Opportunity nobody owns must become work an Administrator can see. The tests
here cover the deterministic rule, its idempotency, the queue that catches the
no-candidate case, and the two ways two callers can collide.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from realestate.db.engine import Database
from realestate.db.models import (
    AssignmentBasis,
    AssignmentQueueEntry,
    AssignmentQueueReason,
    AuditEvent,
    Opportunity,
    OpportunityAssignment,
    OrganizationMember,
)
from realestate.domain.commercial.actors import Actor, NotAuthorized, NotFound
from realestate.domain.commercial.assignment import Assignment
from realestate.domain.commercial.organization import (
    DirectoryPlan,
    OrganizationDirectory,
)
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures import commercial

pytestmark = requires_postgres


@pytest.fixture
async def wired():
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await commercial.reset(session)
        await commercial.provision(session)
    yield database
    await database.dispose()


async def _opportunity(session, wa_id="5213312345678"):  # noqa: ANN001, ANN202
    state = await commercial.opportunity_for(session, wa_id)
    return state.admin, state.opportunity_id


async def test_the_default_advisor_is_the_deterministic_fallback(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _opportunity(session)

        outcome = await Assignment(session).assign(admin, opportunity_id)
        await session.commit()

        assert outcome.queued is False
        assert outcome.created is True
        assert outcome.basis is AssignmentBasis.DEFAULT_ADVISOR
        member = await session.get(OrganizationMember, outcome.advisor_id)
        assert member is not None and member.login == commercial.ADVISOR_LOGIN
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None
        assert opportunity.responsible_advisor_id == outcome.advisor_id
        assert await session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.action == "AssignOpportunity"
            )
        ) == 1


async def test_assigning_twice_preserves_the_existing_advisor(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _opportunity(session)
        assignment = Assignment(session)

        first = await assignment.assign(admin, opportunity_id)
        second = await assignment.assign(admin, opportunity_id)
        await session.commit()

        assert second.advisor_id == first.advisor_id
        assert second.created is False
        assert second.basis is AssignmentBasis.PRESERVED
        periods = await session.scalar(
            select(func.count(OpportunityAssignment.id)).where(
                OpportunityAssignment.opportunity_id == opportunity_id
            )
        )
        assert periods == 1


async def test_no_eligible_advisor_produces_a_queue_entry_not_a_null(wired) -> None:
    async with wired.session_scope() as session:
        # An Organization whose only member administers and does not advise.
        await OrganizationDirectory(session).reconcile(
            DirectoryPlan(
                administrators=(commercial.ADMIN_LOGIN,),
                advisors=(),
                default_advisor=None,
            )
        )
        admin, opportunity_id = await _opportunity(session)

        outcome = await Assignment(session).assign(admin, opportunity_id)
        await session.commit()

        assert outcome.queued is True
        assert outcome.advisor_id is None
        assert outcome.basis is None
        assert outcome.queue_reason is AssignmentQueueReason.NO_ELIGIBLE_ADVISOR
        entry = await session.scalar(
            select(AssignmentQueueEntry).where(
                AssignmentQueueEntry.opportunity_id == opportunity_id
            )
        )
        assert entry is not None and entry.resolved_at is None
        assert "asesor predeterminado" in (entry.detail or "")
        assert await session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.action == "EnqueueForAssignment"
            )
        ) == 1


async def test_an_inactive_default_advisor_is_not_used(wired) -> None:
    """An unusable Advisor would satisfy the column and defeat the promise."""
    async with wired.session_scope() as session:
        admin, opportunity_id = await _opportunity(session)
        member = await session.scalar(
            select(OrganizationMember).where(
                OrganizationMember.login == commercial.ADVISOR_LOGIN
            )
        )
        assert member is not None
        member.active = False
        await session.flush()

        outcome = await Assignment(session).assign(admin, opportunity_id)
        assert outcome.queued is True


async def test_repeated_failures_do_not_stack_up_in_the_queue(wired) -> None:
    async with wired.session_scope() as session:
        await OrganizationDirectory(session).reconcile(
            DirectoryPlan(
                administrators=(commercial.ADMIN_LOGIN,), advisors=(), default_advisor=None
            )
        )
        admin, opportunity_id = await _opportunity(session)
        assignment = Assignment(session)

        await assignment.assign(admin, opportunity_id)
        await assignment.assign(admin, opportunity_id)
        await session.commit()

        entries = await session.scalar(
            select(func.count(AssignmentQueueEntry.id)).where(
                AssignmentQueueEntry.opportunity_id == opportunity_id
            )
        )
        assert entries == 1


async def test_the_queue_is_derived_from_assignment_state(wired) -> None:
    """No drift: the list is the Opportunities with no open assignment."""
    async with wired.session_scope() as session:
        await OrganizationDirectory(session).reconcile(
            DirectoryPlan(
                administrators=(commercial.ADMIN_LOGIN,), advisors=(), default_advisor=None
            )
        )
        admin, first = await _opportunity(session, "5213312345678")
        _admin, second = await _opportunity(session, "5213399990000")
        assignment = Assignment(session)
        await assignment.assign(admin, first)
        # ``second`` was never offered for assignment, so it has no queue entry
        # and yet still needs an Advisor. It must appear anyway.
        await session.commit()

        queue = await assignment.queue(admin)
        ids = {item.opportunity.id for item in queue}
        assert ids == {first, second}
        reasons = {
            item.opportunity.id: item.reason for item in queue
        }
        assert reasons[first] is AssignmentQueueReason.NO_ELIGIBLE_ADVISOR
        assert reasons[second] is None


async def test_assigning_from_the_queue_resolves_the_entry(wired) -> None:
    async with wired.session_scope() as session:
        await OrganizationDirectory(session).reconcile(
            DirectoryPlan(
                administrators=(commercial.ADMIN_LOGIN,), advisors=(), default_advisor=None
            )
        )
        admin, opportunity_id = await _opportunity(session)
        assignment = Assignment(session)
        await assignment.assign(admin, opportunity_id)
        await session.commit()

    async with wired.session_scope() as session:
        members = await commercial.provision(session)
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        outcome = await Assignment(session).assign_manually(
            admin, opportunity_id, members[commercial.ADVISOR_LOGIN]
        )
        await session.commit()

        assert outcome.basis is AssignmentBasis.MANUAL_ADMIN
        entry = await session.scalar(
            select(AssignmentQueueEntry).where(
                AssignmentQueueEntry.opportunity_id == opportunity_id
            )
        )
        assert entry is not None and entry.resolved_at is not None
        assert entry.resolved_by == commercial.ADMIN_LOGIN
        assert await Assignment(session).queue(admin) == []


async def test_manual_reassignment_closes_the_previous_period(wired) -> None:
    async with wired.session_scope() as session:
        members = await commercial.provision(session)
        admin, opportunity_id = await _opportunity(session)
        assignment = Assignment(session)
        first = await assignment.assign(admin, opportunity_id)

        second = await assignment.assign_manually(
            admin, opportunity_id, members[commercial.SECOND_ADVISOR_LOGIN]
        )
        await session.commit()

        assert second.advisor_id != first.advisor_id
        history = await assignment.history(opportunity_id)
        assert len(history) == 2
        open_periods = [row for row in history if row.unassigned_at is None]
        assert len(open_periods) == 1
        assert open_periods[0].advisor_id == second.advisor_id


async def test_manually_assigning_the_same_advisor_is_a_no_op(wired) -> None:
    async with wired.session_scope() as session:
        members = await commercial.provision(session)
        admin, opportunity_id = await _opportunity(session)
        assignment = Assignment(session)
        await assignment.assign(admin, opportunity_id)

        outcome = await assignment.assign_manually(
            admin, opportunity_id, members[commercial.ADVISOR_LOGIN]
        )
        assert outcome.created is False
        assert outcome.basis is AssignmentBasis.PRESERVED
        assert len(await assignment.history(opportunity_id)) == 1


async def test_only_an_administrator_may_assign_or_release(wired) -> None:
    async with wired.session_scope() as session:
        members = await commercial.provision(session)
        admin, opportunity_id = await _opportunity(session)
        await Assignment(session).assign(admin, opportunity_id)
        await session.commit()

    async with wired.session_scope() as session:
        advisor = await commercial.actor_for(session, commercial.ADVISOR_LOGIN)
        assignment = Assignment(session)
        with pytest.raises(NotAuthorized):
            await assignment.assign_manually(
                advisor, opportunity_id, members[commercial.SECOND_ADVISOR_LOGIN]
            )
        with pytest.raises(NotAuthorized):
            await assignment.release(advisor, opportunity_id)
        with pytest.raises(NotAuthorized):
            await assignment.queue(advisor)


async def test_a_member_who_does_not_advise_cannot_be_assigned(wired) -> None:
    async with wired.session_scope() as session:
        members = await commercial.provision(session)
        admin, opportunity_id = await _opportunity(session)
        with pytest.raises(NotAuthorized, match="asesor responsable"):
            await Assignment(session).assign_manually(
                admin, opportunity_id, members[commercial.ADMIN_LOGIN]
            )


async def test_an_unknown_or_inactive_advisor_is_refused(wired) -> None:
    async with wired.session_scope() as session:
        members = await commercial.provision(session)
        admin, opportunity_id = await _opportunity(session)
        assignment = Assignment(session)

        with pytest.raises(NotFound):
            await assignment.assign_manually(admin, opportunity_id, uuid.uuid4())

        member = await session.get(
            OrganizationMember, members[commercial.SECOND_ADVISOR_LOGIN]
        )
        assert member is not None
        member.active = False
        await session.flush()
        with pytest.raises(NotFound):
            await assignment.assign_manually(admin, opportunity_id, member.id)


async def test_releasing_puts_the_work_back_in_the_queue(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _opportunity(session)
        assignment = Assignment(session)
        await assignment.assign(admin, opportunity_id)

        assert await assignment.release(admin, opportunity_id) is True
        await session.commit()

        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None
        assert opportunity.responsible_advisor_id is None
        queue = await assignment.queue(admin)
        assert [item.opportunity.id for item in queue] == [opportunity_id]
        assert "liberó" in (queue[0].detail or "")
        assert await session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.action == "ReleaseOpportunityAssignment"
            )
        ) == 1


async def test_releasing_an_unassigned_opportunity_reports_nothing_to_do(
    wired,
) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _opportunity(session)
        assert await Assignment(session).release(admin, opportunity_id) is False


async def test_a_closed_opportunity_is_not_re_queued_when_released(wired) -> None:
    async with wired.session_scope() as session:
        from realestate.domain.commercial.opportunities import (
            LostReason,
            OpportunityManagement,
            RecordLost,
        )

        admin, opportunity_id = await _opportunity(session)
        assignment = Assignment(session)
        await assignment.assign(admin, opportunity_id)
        await OpportunityManagement(session).record(
            admin,
            RecordLost(
                opportunity_id=opportunity_id,
                reason=LostReason.UNKNOWN,
                command_key="lost:1",
            ),
        )

        assert await assignment.release(admin, opportunity_id) is True
        assert await assignment.queue(admin) == []


async def test_an_opportunity_outside_the_organization_is_not_found(wired) -> None:
    async with wired.session_scope() as session:
        _admin, opportunity_id = await _opportunity(session)
        outsider = Actor.product(uuid.uuid4(), "OtraOrganizacion")
        with pytest.raises(NotFound):
            await Assignment(session).assign(outsider, opportunity_id)
        with pytest.raises(NotFound):
            await Assignment(session).assign(outsider, uuid.uuid4())


async def test_an_empty_queue_is_an_empty_list(wired) -> None:
    async with wired.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        assert await Assignment(session).queue(admin) == []


async def test_two_concurrent_assignments_produce_one_responsible_advisor(
    wired,
) -> None:
    """The row lock serialises; the partial unique index is the final word."""
    async with wired.session_scope() as session:
        admin, opportunity_id = await _opportunity(session)
        await session.commit()

    async def assign() -> uuid.UUID | None:
        async with wired.session_scope() as session:
            actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
            outcome = await Assignment(session).assign(actor, opportunity_id)
            await session.commit()
            return outcome.advisor_id

    first, second = await asyncio.gather(assign(), assign())

    assert first is not None and first == second
    async with wired.session_scope() as session:
        open_periods = await session.scalar(
            select(func.count(OpportunityAssignment.id))
            .where(OpportunityAssignment.opportunity_id == opportunity_id)
            .where(OpportunityAssignment.unassigned_at.is_(None))
        )
        assert open_periods == 1


async def test_losing_the_insert_race_reports_the_winner(wired, monkeypatch) -> None:
    """Forced: another transaction commits between the read and the insert.

    ``asyncio.gather`` above proves the ordinary outcome but cannot guarantee
    the lock is bypassed. Blinding one caller's read is the only reliable way to
    exercise the unique index as the arbiter.
    """
    async with wired.session_scope() as session:
        members = await commercial.provision(session)
        admin, opportunity_id = await _opportunity(session)
        await session.commit()

    # The winner takes the Opportunity in its own transaction first.
    async with wired.session_scope() as session:
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        winner = await Assignment(session).assign_manually(
            actor, opportunity_id, members[commercial.SECOND_ADVISOR_LOGIN]
        )
        await session.commit()

    async with wired.session_scope() as session:
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        assignment = Assignment(session)
        real_open = assignment._open_assignment
        calls = {"n": 0}

        async def blind_first(opportunity_id_):  # noqa: ANN001, ANN202
            calls["n"] += 1
            if calls["n"] == 1:
                return None
            return await real_open(opportunity_id_)

        monkeypatch.setattr(assignment, "_open_assignment", blind_first)

        outcome = await assignment.assign(actor, opportunity_id)
        await session.commit()

        assert outcome.created is False
        assert outcome.basis is AssignmentBasis.PRESERVED
        assert outcome.advisor_id == winner.advisor_id
        open_periods = await session.scalar(
            select(func.count(OpportunityAssignment.id))
            .where(OpportunityAssignment.opportunity_id == opportunity_id)
            .where(OpportunityAssignment.unassigned_at.is_(None))
        )
        assert open_periods == 1


async def test_the_queue_distinguishes_unconfigured_from_inactive(wired) -> None:
    """Two different remedies deserve two different messages.

    "Nobody is configured" needs a login added to the configuration; "the
    configured Advisor is inactive" needs that person reactivated. Collapsing
    them put one sentence in front of two different actions.
    """
    async with wired.session_scope() as session:
        # Nobody designated at all.
        await OrganizationDirectory(session).reconcile(
            DirectoryPlan(
                administrators=(commercial.ADMIN_LOGIN,),
                advisors=(),
                default_advisor=None,
            )
        )
        admin, first = await _opportunity(session, "5213311110000")
        outcome = await Assignment(session).assign(admin, first)
        assert outcome.queue_reason is AssignmentQueueReason.NO_ELIGIBLE_ADVISOR
        await session.commit()

    async with wired.session_scope() as session:
        # Designated, but dado de baja.
        await commercial.provision(session)
        member = await session.scalar(
            select(OrganizationMember).where(
                OrganizationMember.login == commercial.ADVISOR_LOGIN
            )
        )
        assert member is not None
        member.active = False
        await session.flush()

        admin, second = await _opportunity(session, "5213322220000")
        outcome = await Assignment(session).assign(admin, second)
        await session.commit()

        assert outcome.queued is True
        assert outcome.queue_reason is AssignmentQueueReason.DEFAULT_ADVISOR_INACTIVE
        entry = await session.scalar(
            select(AssignmentQueueEntry).where(
                AssignmentQueueEntry.opportunity_id == second
            )
        )
        assert entry is not None
        assert "reactívalo" in (entry.detail or "")


async def test_a_designated_advisor_who_cannot_own_work_cannot_be_stored(
    wired,
) -> None:
    """The schema, not the service layer, makes that state unreachable.

    Which is why ``_default_advisor`` does not re-check ``advises``: a branch
    for a row the database refuses to hold is a branch nothing can reach.
    """
    from sqlalchemy.exc import IntegrityError

    async with wired.session_scope() as session:
        await commercial.provision(session)
        member = await session.scalar(
            select(OrganizationMember).where(
                OrganizationMember.login == commercial.ADVISOR_LOGIN
            )
        )
        assert member is not None
        assert member.is_default_advisor is True

        member.advises = False
        with pytest.raises(IntegrityError, match="advises"):
            await session.flush()
        await session.rollback()
