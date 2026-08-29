"""Next Actions: one obligation at a time, and a result when it is discharged.

Four states have to be distinguishable for the coverage metric to mean
anything: pending and on time, pending and overdue, completed with a recorded
result, and substituted by a newer obligation. A fifth — cancelled because the
Opportunity stopped being active — keeps closed work out of the overdue report.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from realestate.db.engine import Database
from realestate.db.models import (
    AuditEvent,
    NextAction,
    NextActionKind,
    NextActionOutcome,
    NextActionStatus,
    Opportunity,
    OpportunityStage,
)
from realestate.domain.commercial.actors import (
    Actor,
    InvalidTransition,
    NotAuthorized,
    NotFound,
)
from realestate.domain.commercial.next_actions import (
    CompleteNextAction,
    NextActions,
    ScheduleNextAction,
)
from realestate.domain.commercial.opportunities import (
    AdvanceStage,
    LostReason,
    OpportunityManagement,
    RecordLost,
)
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


async def _assigned(session, wa_id="5213312345678"):  # noqa: ANN001, ANN202
    state = await commercial.opportunity_for(session, wa_id, assign=True)
    return state.admin, state.opportunity_id


async def test_scheduling_owes_one_action_to_the_responsible_advisor(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _assigned(session)

        scheduled = await NextActions(session).schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.CALL,
                due_at=NOW + timedelta(days=1),
                note="Confirmar presupuesto.",
                command_key="action:1",
            ),
        )
        await session.commit()

        assert scheduled.replayed is False
        assert scheduled.superseded_id is None
        action = await session.get(NextAction, scheduled.next_action_id)
        opportunity = await session.get(Opportunity, opportunity_id)
        assert action is not None and opportunity is not None
        assert action.status == NextActionStatus.PENDING.value
        assert action.responsible_member_id == opportunity.responsible_advisor_id
        assert action.created_by == commercial.ADMIN_LOGIN
        assert (
            await session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action == "ScheduleNextAction"
                )
            )
            == 1
        )


async def test_replaying_a_schedule_command_owes_nothing_new(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _assigned(session)
        actions = NextActions(session)
        command = ScheduleNextAction(
            opportunity_id=opportunity_id,
            kind=NextActionKind.CALL,
            due_at=NOW + timedelta(days=1),
            command_key="action:same",
        )
        first = await actions.schedule(admin, command)
        second = await actions.schedule(admin, command)

        assert second.next_action_id == first.next_action_id
        assert second.replayed is True
        assert await session.scalar(select(func.count(NextAction.id))) == 1


async def test_a_new_action_supersedes_the_previous_one(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _assigned(session)
        actions = NextActions(session)
        first = await actions.schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.CALL,
                due_at=NOW + timedelta(days=1),
                command_key="action:1",
            ),
        )
        second = await actions.schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.SCHEDULE_VISIT,
                due_at=NOW + timedelta(days=2),
                command_key="action:2",
            ),
        )
        await session.commit()

        assert second.superseded_id == first.next_action_id
        previous = await session.get(NextAction, first.next_action_id)
        assert previous is not None
        assert previous.status == NextActionStatus.SUPERSEDED.value
        assert previous.superseded_by_id == second.next_action_id
        pending = await actions.pending(opportunity_id)
        assert pending is not None and pending.id == second.next_action_id


async def test_completing_records_the_result(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _assigned(session)
        actions = NextActions(session)
        scheduled = await actions.schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.CALL,
                due_at=NOW + timedelta(days=1),
                command_key="action:1",
            ),
        )

        completed = await actions.complete(
            admin,
            CompleteNextAction(
                next_action_id=scheduled.next_action_id,
                outcome=NextActionOutcome.NO_ANSWER,
                outcome_detail="No contestó dos veces.",
                command_key="complete:1",
                at=NOW,
            ),
        )
        await session.commit()

        assert completed.replayed is False
        action = await session.get(NextAction, scheduled.next_action_id)
        assert action is not None
        assert action.status == NextActionStatus.COMPLETED.value
        assert action.outcome == NextActionOutcome.NO_ANSWER.value
        assert action.completed_at == NOW
        assert await actions.pending(opportunity_id) is None


async def test_completing_twice_with_the_same_result_is_a_replay(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _assigned(session)
        actions = NextActions(session)
        scheduled = await actions.schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.CALL,
                due_at=NOW,
                command_key="action:1",
            ),
        )
        command = CompleteNextAction(
            next_action_id=scheduled.next_action_id,
            outcome=NextActionOutcome.DONE,
            command_key="complete:1",
        )
        await actions.complete(admin, command)
        again = await actions.complete(admin, command)
        assert again.replayed is True


async def test_completing_again_with_a_different_result_is_refused(wired) -> None:
    """Accepting it would overwrite what an Advisor reported."""
    async with wired.session_scope() as session:
        admin, opportunity_id = await _assigned(session)
        actions = NextActions(session)
        scheduled = await actions.schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.CALL,
                due_at=NOW,
                command_key="action:1",
            ),
        )
        await actions.complete(
            admin,
            CompleteNextAction(
                next_action_id=scheduled.next_action_id,
                outcome=NextActionOutcome.DONE,
                command_key="complete:1",
            ),
        )
        with pytest.raises(InvalidTransition, match="clave original"):
            await actions.complete(
                admin,
                CompleteNextAction(
                    next_action_id=scheduled.next_action_id,
                    outcome=NextActionOutcome.NOT_INTERESTED,
                    command_key="complete:2",
                ),
            )


async def test_a_superseded_action_cannot_be_completed(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _assigned(session)
        actions = NextActions(session)
        first = await actions.schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.CALL,
                due_at=NOW,
                command_key="action:1",
            ),
        )
        await actions.schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.SEND_LISTINGS,
                due_at=NOW,
                command_key="action:2",
            ),
        )
        with pytest.raises(InvalidTransition, match="Sustituida"):
            await actions.complete(
                admin,
                CompleteNextAction(
                    next_action_id=first.next_action_id,
                    outcome=NextActionOutcome.DONE,
                    command_key="complete:late",
                ),
            )


async def test_an_overdue_action_is_reported_as_overdue(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _assigned(session)
        actions = NextActions(session)
        scheduled = await actions.schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.CALL,
                due_at=NOW - timedelta(hours=2),
                command_key="action:1",
            ),
        )
        await session.commit()

        action = await session.get(NextAction, scheduled.next_action_id)
        assert action is not None
        assert NextActions.is_overdue(action, now=NOW) is True
        overdue = await actions.due(admin, now=NOW, overdue_only=True)
        assert [row.id for row in overdue] == [scheduled.next_action_id]

        # A completed action is never overdue, however late it was.
        await actions.complete(
            admin,
            CompleteNextAction(
                next_action_id=scheduled.next_action_id,
                outcome=NextActionOutcome.DONE,
                command_key="complete:1",
            ),
        )
        await session.refresh(action)
        assert NextActions.is_overdue(action, now=NOW) is False


async def test_a_future_action_is_not_overdue(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _assigned(session)
        actions = NextActions(session)
        await actions.schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.CALL,
                due_at=NOW + timedelta(days=3),
                command_key="action:1",
            ),
        )
        assert await actions.due(admin, now=NOW, overdue_only=True) == []
        assert len(await actions.due(admin, now=NOW)) == 1


async def test_an_advisor_only_sees_their_own_obligations(wired) -> None:
    async with wired.session_scope() as session:
        members = await commercial.provision(session)
        admin, opportunity_id = await _assigned(session)
        actions = NextActions(session)
        await actions.schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.CALL,
                due_at=NOW,
                command_key="action:1",
            ),
        )
        await session.commit()

    async with wired.session_scope() as session:
        mine = await commercial.actor_for(session, commercial.ADVISOR_LOGIN)
        other = await commercial.actor_for(session, commercial.SECOND_ADVISOR_LOGIN)
        actions = NextActions(session)
        assert len(await actions.due(mine, now=NOW)) == 1
        assert await actions.due(other, now=NOW) == []
        assert members  # the fixture provisioned both advisors


async def test_scheduling_needs_a_responsible_advisor(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, admin, contact_id)

        with pytest.raises(NotAuthorized, match="Asigna un asesor"):
            await NextActions(session).schedule(
                admin,
                ScheduleNextAction(
                    opportunity_id=opportunity_id,
                    kind=NextActionKind.CALL,
                    due_at=NOW,
                    command_key="action:1",
                ),
            )


async def test_an_administrator_may_owe_the_action_to_somebody_else(wired) -> None:
    async with wired.session_scope() as session:
        members = await commercial.provision(session)
        admin, opportunity_id = await _assigned(session)

        scheduled = await NextActions(session).schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.DOCUMENT_REVIEW,
                due_at=NOW,
                responsible_member_id=members[commercial.ADMIN_LOGIN],
                command_key="action:1",
            ),
        )
        action = await session.get(NextAction, scheduled.next_action_id)
        assert action is not None
        assert action.responsible_member_id == members[commercial.ADMIN_LOGIN]


async def test_an_advisor_may_not_owe_the_action_to_a_colleague(wired) -> None:
    async with wired.session_scope() as session:
        members = await commercial.provision(session)
        admin, opportunity_id = await _assigned(session)
        await session.commit()

    async with wired.session_scope() as session:
        advisor = await commercial.actor_for(session, commercial.ADVISOR_LOGIN)
        with pytest.raises(NotAuthorized, match="administrador"):
            await NextActions(session).schedule(
                advisor,
                ScheduleNextAction(
                    opportunity_id=opportunity_id,
                    kind=NextActionKind.CALL,
                    due_at=NOW,
                    responsible_member_id=members[commercial.SECOND_ADVISOR_LOGIN],
                    command_key="action:1",
                ),
            )


async def test_an_unknown_responsible_member_is_refused(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _assigned(session)
        with pytest.raises(NotFound):
            await NextActions(session).schedule(
                admin,
                ScheduleNextAction(
                    opportunity_id=opportunity_id,
                    kind=NextActionKind.CALL,
                    due_at=NOW,
                    responsible_member_id=uuid.uuid4(),
                    command_key="action:1",
                ),
            )


async def test_a_closed_opportunity_owes_nothing(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _assigned(session)
        await OpportunityManagement(session).record(
            admin,
            RecordLost(
                opportunity_id=opportunity_id,
                reason=LostReason.UNKNOWN,
                command_key="lost:1",
            ),
        )
        with pytest.raises(InvalidTransition, match="no está activa"):
            await NextActions(session).schedule(
                admin,
                ScheduleNextAction(
                    opportunity_id=opportunity_id,
                    kind=NextActionKind.CALL,
                    due_at=NOW,
                    command_key="action:1",
                ),
            )


async def test_cancelling_when_nothing_is_pending_reports_nothing(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _assigned(session)
        assert (
            await NextActions(session).cancel_pending(
                admin, opportunity_id, reason="test"
            )
            is None
        )


async def test_an_action_outside_the_actors_reach_is_not_found(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _assigned(session)
        actions = NextActions(session)
        scheduled = await actions.schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.CALL,
                due_at=NOW,
                command_key="action:1",
            ),
        )
        await session.commit()

    async with wired.session_scope() as session:
        actions = NextActions(session)
        with pytest.raises(NotFound):
            await actions.action(
                Actor.product(uuid.uuid4(), "Otra"), scheduled.next_action_id
            )
        with pytest.raises(NotFound):
            await actions.action(
                await commercial.actor_for(session, commercial.SECOND_ADVISOR_LOGIN),
                scheduled.next_action_id,
            )
        with pytest.raises(NotFound):
            await actions.action(
                await commercial.actor_for(session, commercial.ADMIN_LOGIN),
                uuid.uuid4(),
            )


async def test_the_history_keeps_every_state(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _assigned(session)
        actions = NextActions(session)
        first = await actions.schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.CALL,
                due_at=NOW,
                command_key="action:1",
            ),
        )
        second = await actions.schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.SEND_LISTINGS,
                due_at=NOW,
                command_key="action:2",
            ),
        )
        await actions.complete(
            admin,
            CompleteNextAction(
                next_action_id=second.next_action_id,
                outcome=NextActionOutcome.DONE,
                command_key="complete:1",
            ),
        )
        third = await actions.schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.SCHEDULE_VISIT,
                due_at=NOW,
                command_key="action:3",
            ),
        )
        await OpportunityManagement(session).record(
            admin,
            RecordLost(
                opportunity_id=opportunity_id,
                reason=LostReason.UNREACHABLE,
                command_key="lost:1",
            ),
        )
        await session.commit()

        statuses = {row.id: row.status for row in await actions.history(opportunity_id)}
        assert statuses[first.next_action_id] == NextActionStatus.SUPERSEDED.value
        assert statuses[second.next_action_id] == NextActionStatus.COMPLETED.value
        assert statuses[third.next_action_id] == NextActionStatus.CANCELLED.value


async def test_two_concurrent_schedules_leave_exactly_one_pending(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _assigned(session)
        await session.commit()

    async def schedule(key: str) -> uuid.UUID:
        async with wired.session_scope() as session:
            actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
            scheduled = await NextActions(session).schedule(
                actor,
                ScheduleNextAction(
                    opportunity_id=opportunity_id,
                    kind=NextActionKind.CALL,
                    due_at=NOW + timedelta(days=1),
                    command_key=key,
                ),
            )
            await session.commit()
            return scheduled.next_action_id

    await asyncio.gather(schedule("action:a"), schedule("action:b"))

    async with wired.session_scope() as session:
        pending = await session.scalar(
            select(func.count(NextAction.id))
            .where(NextAction.opportunity_id == opportunity_id)
            .where(NextAction.status == NextActionStatus.PENDING.value)
        )
        assert pending == 1
        total = await session.scalar(
            select(func.count(NextAction.id)).where(
                NextAction.opportunity_id == opportunity_id
            )
        )
        assert total == 2


async def test_an_advisor_may_complete_their_own_action(wired) -> None:
    async with wired.session_scope() as session:
        admin, opportunity_id = await _assigned(session)
        scheduled = await NextActions(session).schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.CALL,
                due_at=NOW,
                command_key="action:1",
            ),
        )
        await session.commit()

    async with wired.session_scope() as session:
        advisor = await commercial.actor_for(session, commercial.ADVISOR_LOGIN)
        completed = await NextActions(session).complete(
            advisor,
            CompleteNextAction(
                next_action_id=scheduled.next_action_id,
                outcome=NextActionOutcome.RESCHEDULED,
                command_key="complete:1",
            ),
        )
        await session.commit()
        assert completed.outcome is NextActionOutcome.RESCHEDULED


async def test_a_qualified_opportunity_can_be_worked_end_to_end(wired) -> None:
    """The obligation survives an ordinary stage advance."""
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, admin, contact_id)
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None and opportunity.property_need_id is not None
        await commercial.confirm_minimum_criteria(
            session, admin, opportunity.property_need_id
        )
        management = OpportunityManagement(session)
        await management.record(
            admin,
            AdvanceStage(
                opportunity_id=opportunity_id,
                to_stage=OpportunityStage.QUALIFIED,
                command_key="q:1",
            ),
        )
        actions = NextActions(session)
        scheduled = await actions.schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.SEND_LISTINGS,
                due_at=NOW + timedelta(days=1),
                command_key="action:1",
            ),
        )
        await management.record(
            admin,
            AdvanceStage(
                opportunity_id=opportunity_id,
                to_stage=OpportunityStage.SEARCHING,
                command_key="advance:1",
            ),
        )
        await session.commit()

        pending = await actions.pending(opportunity_id)
        assert pending is not None and pending.id == scheduled.next_action_id
