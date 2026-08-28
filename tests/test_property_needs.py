"""Property Needs: confirmed criteria, Pending interpretations, and staleness.

ADR-0031's rule is that a value Maia inferred is not commercial truth until the
Contact confirms it. The tests below check both halves: a Pending value is
visible and usable in conversation, and it does not satisfy qualification.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from realestate.db.engine import Database
from realestate.db.models import (
    PROPERTY_NEED_STALE_DAYS,
    AuditEvent,
    CriterionSource,
    CriterionState,
    PropertyNeed,
    PropertyNeedCriterion,
    PropertyNeedStatus,
)
from realestate.domain.commercial.actors import Actor, NotFound
from realestate.domain.commercial.needs import (
    ECONOMIC_RANGE,
    HORIZON,
    INTENT,
    SERVICE_AREA,
    CriterionStatement,
    PropertyNeeds,
    criterion_label,
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


async def _need(session):  # noqa: ANN001, ANN202
    contact_id, _ = await commercial.make_contact(session, "5213312345678")
    actor = await commercial.actor_for(session, commercial.ADVISOR_LOGIN)
    need = await PropertyNeeds(session).open(actor, contact_id=contact_id)
    return actor, need


async def test_an_inferred_criterion_is_pending_and_does_not_qualify(wired) -> None:
    async with wired.session_scope() as session:
        actor, need = await _need(session)
        needs = PropertyNeeds(session)

        snapshot = await needs.record(
            actor,
            need.id,
            [
                CriterionStatement.inferred(
                    SERVICE_AREA, "Zapopan norte", evidence="«por el norte»"
                )
            ],
        )

        assert snapshot.pending == {SERVICE_AREA: "Zapopan norte"}
        assert snapshot.confirmed == {}
        assert SERVICE_AREA in snapshot.missing_required
        assert SERVICE_AREA in snapshot.pending_required
        assert snapshot.meets_minimum is False
        # A Pending value does not refresh the confirmation clock.
        assert snapshot.last_confirmed_at is None


async def test_confirming_a_pending_criterion_makes_it_truth(wired) -> None:
    async with wired.session_scope() as session:
        actor, need = await _need(session)
        needs = PropertyNeeds(session)
        await needs.record(
            actor, need.id, [CriterionStatement.inferred(SERVICE_AREA, "Zapopan norte")]
        )

        snapshot = await needs.confirm(actor, need.id, [SERVICE_AREA], now=NOW)

        assert snapshot.confirmed == {SERVICE_AREA: "Zapopan norte"}
        assert snapshot.pending == {}
        assert snapshot.last_confirmed_at == NOW
        # The interpretation is retained, superseded rather than rewritten.
        rows = await needs.history(need.id)
        assert len(rows) == 2
        current = [row for row in rows if row.superseded_at is None]
        superseded = [row for row in rows if row.superseded_at is not None]
        assert [row.state for row in current] == [CriterionState.CONFIRMED.value]
        assert [row.state for row in superseded] == [CriterionState.PENDING.value]
        assert superseded[0].source == CriterionSource.MODEL_INFERRED.value


async def test_confirming_something_that_is_not_pending_is_refused(wired) -> None:
    async with wired.session_scope() as session:
        actor, need = await _need(session)
        with pytest.raises(NotFound, match=criterion_label(HORIZON)):
            await PropertyNeeds(session).confirm(actor, need.id, [HORIZON])


async def test_confirming_an_already_confirmed_criterion_is_refused(wired) -> None:
    """Silently accepting it would report a confirmation that never happened."""
    async with wired.session_scope() as session:
        actor, need = await _need(session)
        needs = PropertyNeeds(session)
        await needs.record(
            actor, need.id, [CriterionStatement.stated(SERVICE_AREA, "Zapopan")]
        )
        with pytest.raises(NotFound):
            await needs.confirm(actor, need.id, [SERVICE_AREA])


async def test_a_new_value_supersedes_the_previous_one(wired) -> None:
    async with wired.session_scope() as session:
        actor, need = await _need(session)
        needs = PropertyNeeds(session)
        await needs.record(
            actor, need.id, [CriterionStatement.inferred(ECONOMIC_RANGE, "3 millones")]
        )
        snapshot = await needs.record(
            actor,
            need.id,
            [CriterionStatement.stated(ECONOMIC_RANGE, "4 a 5 millones MXN")],
        )

        assert snapshot.confirmed == {ECONOMIC_RANGE: "4 a 5 millones MXN"}
        current = await session.scalar(
            select(func.count(PropertyNeedCriterion.id))
            .where(PropertyNeedCriterion.property_need_id == need.id)
            .where(PropertyNeedCriterion.superseded_at.is_(None))
        )
        assert current == 1
        assert len(await needs.history(need.id)) == 2


async def test_a_confirmed_intent_is_denormalised_onto_the_need(wired) -> None:
    async with wired.session_scope() as session:
        actor, need = await _need(session)
        await PropertyNeeds(session).record(
            actor, need.id, [CriterionStatement.stated(INTENT, "Buy")]
        )
        await session.flush()
        stored = await session.get(PropertyNeed, need.id)
        assert stored is not None and stored.transaction_intent == "Buy"


async def test_an_unrecognised_intent_value_is_not_denormalised(wired) -> None:
    async with wired.session_scope() as session:
        actor, need = await _need(session)
        snapshot = await PropertyNeeds(session).record(
            actor, need.id, [CriterionStatement.stated(INTENT, "Comprar una casa")]
        )
        stored = await session.get(PropertyNeed, need.id)
        assert stored is not None and stored.transaction_intent is None
        # The criterion itself is still recorded as the operator wrote it.
        assert snapshot.confirmed[INTENT] == "Comprar una casa"


async def test_the_minimum_is_met_only_when_every_required_value_is_confirmed(
    wired,
) -> None:
    async with wired.session_scope() as session:
        actor, need = await _need(session)
        await commercial.confirm_minimum_criteria(
            session, actor, need.id, omit=(HORIZON,)
        )
        snapshot = await PropertyNeeds(session).snapshot(need.id)
        assert snapshot.missing_required == (HORIZON,)
        assert snapshot.meets_minimum is False

        await commercial.confirm_minimum_criteria(session, actor, need.id)
        snapshot = await PropertyNeeds(session).snapshot(need.id)
        assert snapshot.missing_required == ()
        assert snapshot.meets_minimum is True


async def test_a_need_unconfirmed_for_ninety_days_becomes_stale(wired) -> None:
    async with wired.session_scope() as session:
        actor, need = await _need(session)
        await commercial.confirm_minimum_criteria(session, actor, need.id, at=NOW)
        await session.commit()
        need_id = need.id

    async with wired.session_scope() as session:
        later = NOW + timedelta(days=PROPERTY_NEED_STALE_DAYS, seconds=1)
        marked = await PropertyNeeds(session).refresh_stale(now=later)
        assert marked == 1

        snapshot = await PropertyNeeds(session).snapshot(need_id)
        assert snapshot.status is PropertyNeedStatus.STALE
        assert snapshot.is_stale is True
        # Stale never meets the minimum, whatever it once contained.
        assert snapshot.missing_required == ()
        assert snapshot.meets_minimum is False

        audited = await session.scalar(
            select(func.count(AuditEvent.id))
            .where(AuditEvent.action == "MarkPropertyNeedStale")
            .where(AuditEvent.subject_id == str(need_id))
        )
        assert audited == 1


async def test_a_need_that_was_never_confirmed_also_goes_stale(wired) -> None:
    async with wired.session_scope() as session:
        actor, need = await _need(session)
        stored = await session.get(PropertyNeed, need.id)
        assert stored is not None
        stored.created_at = NOW - timedelta(days=PROPERTY_NEED_STALE_DAYS + 1)
        await session.commit()
        need_id = need.id

    async with wired.session_scope() as session:
        assert await PropertyNeeds(session).refresh_stale(now=NOW) == 1
        assert (await PropertyNeeds(session).snapshot(need_id)).is_stale


async def test_the_staleness_sweep_is_idempotent(wired) -> None:
    async with wired.session_scope() as session:
        actor, need = await _need(session)
        await commercial.confirm_minimum_criteria(session, actor, need.id, at=NOW)
        await session.commit()

    later = NOW + timedelta(days=PROPERTY_NEED_STALE_DAYS + 1)
    async with wired.session_scope() as session:
        assert await PropertyNeeds(session).refresh_stale(now=later) == 1
    async with wired.session_scope() as session:
        assert await PropertyNeeds(session).refresh_stale(now=later) == 0


async def test_a_fresh_need_is_left_alone(wired) -> None:
    async with wired.session_scope() as session:
        actor, need = await _need(session)
        await commercial.confirm_minimum_criteria(session, actor, need.id, at=NOW)
        await session.commit()

    async with wired.session_scope() as session:
        assert await PropertyNeeds(session).refresh_stale(now=NOW + timedelta(days=1)) == 0


async def test_reconfirming_revives_a_stale_need_and_audits_it(wired) -> None:
    async with wired.session_scope() as session:
        actor, need = await _need(session)
        await commercial.confirm_minimum_criteria(session, actor, need.id, at=NOW)
        await session.commit()
        need_id = need.id

    later = NOW + timedelta(days=PROPERTY_NEED_STALE_DAYS + 1)
    async with wired.session_scope() as session:
        await PropertyNeeds(session).refresh_stale(now=later)

    async with wired.session_scope() as session:
        actor = await commercial.actor_for(session, commercial.ADVISOR_LOGIN)
        snapshot = await PropertyNeeds(session).record(
            actor,
            need_id,
            [CriterionStatement.stated(SERVICE_AREA, "Zapopan norte")],
            now=later,
        )
        await session.commit()

        assert snapshot.status is PropertyNeedStatus.ACTIVE
        stored = await session.get(PropertyNeed, need_id)
        assert stored is not None and stored.became_stale_at is None
        audited = await session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.action == "ReconfirmPropertyNeed"
            )
        )
        assert audited == 1


async def test_a_pending_value_does_not_revive_a_stale_need(wired) -> None:
    async with wired.session_scope() as session:
        actor, need = await _need(session)
        await commercial.confirm_minimum_criteria(session, actor, need.id, at=NOW)
        await session.commit()
        need_id = need.id

    later = NOW + timedelta(days=PROPERTY_NEED_STALE_DAYS + 1)
    async with wired.session_scope() as session:
        await PropertyNeeds(session).refresh_stale(now=later)

    async with wired.session_scope() as session:
        actor = await commercial.actor_for(session, commercial.ADVISOR_LOGIN)
        snapshot = await PropertyNeeds(session).record(
            actor,
            need_id,
            [CriterionStatement.inferred(SERVICE_AREA, "Tlaquepaque")],
            now=later,
        )
        assert snapshot.status is PropertyNeedStatus.STALE


async def test_a_need_from_another_organization_is_not_found(wired) -> None:
    async with wired.session_scope() as session:
        _actor, need = await _need(session)
        outsider = Actor.product(uuid.uuid4(), "OtraOrganizacion")
        with pytest.raises(NotFound):
            await PropertyNeeds(session).need(outsider, need.id)


async def test_an_unknown_need_is_not_found(wired) -> None:
    async with wired.session_scope() as session:
        actor = await commercial.actor_for(session, commercial.ADVISOR_LOGIN)
        with pytest.raises(NotFound):
            await PropertyNeeds(session).need(actor, uuid.uuid4())
        with pytest.raises(NotFound):
            await PropertyNeeds(session).snapshot(uuid.uuid4())


async def test_needs_for_a_contact_come_back_newest_first(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        actor = await commercial.actor_for(session, commercial.ADVISOR_LOGIN)
        needs = PropertyNeeds(session)
        first = await needs.open(actor, contact_id=contact_id)
        first.created_at = NOW - timedelta(days=2)
        second = await needs.open(actor, contact_id=contact_id)
        second.created_at = NOW
        await session.flush()

        found = await needs.needs_for_contact(contact_id)
        assert [row.id for row in found] == [second.id, first.id]


def test_every_required_criterion_has_a_spanish_label() -> None:
    from realestate.domain.commercial.needs import CRITERION_LABELS, REQUIRED_CRITERIA

    assert set(REQUIRED_CRITERIA) <= set(CRITERION_LABELS)
    assert criterion_label("otra_cosa") == "Otra cosa"


def test_criterion_statements_carry_their_provenance() -> None:
    assert CriterionStatement.inferred("a", "b").source is CriterionSource.MODEL_INFERRED
    assert CriterionStatement.stated("a", "b").source is CriterionSource.CONTACT_STATED
    assert (
        CriterionStatement.recorded("a", "b").source is CriterionSource.ADVISOR_RECORDED
    )


async def test_recording_criteria_is_audited(wired) -> None:
    """Confirming is the evidence that gates Qualified, so it is in the trail."""
    async with wired.session_scope() as session:
        actor, need = await _need(session)
        await PropertyNeeds(session).record(
            actor,
            need.id,
            [CriterionStatement.stated(SERVICE_AREA, "Zapopan norte")],
        )
        await session.commit()

        event = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "RecordPropertyNeedCriteria"
            )
        )
        assert event is not None
        assert event.subject_id == str(need.id)
        assert event.actor_id == commercial.ADVISOR_LOGIN
        assert event.details["criteria"] == [SERVICE_AREA]
        assert event.details["confirmed"] == [SERVICE_AREA]
        # The value itself is not copied: the audit trail outlives the retention
        # rules for the personal data it would otherwise duplicate.
        assert "Zapopan" not in str(event.details)


async def test_replaying_an_identical_statement_writes_no_new_row(wired) -> None:
    async with wired.session_scope() as session:
        actor, need = await _need(session)
        needs = PropertyNeeds(session)
        statement = CriterionStatement.stated(SERVICE_AREA, "Zapopan norte")

        await needs.record(actor, need.id, [statement])
        await needs.record(actor, need.id, [statement])
        await session.commit()

        rows = await needs.history(need.id)
        # One row, not one superseded by an identical successor.
        assert len(rows) == 1
        assert rows[0].superseded_at is None


async def test_a_changed_provenance_is_a_real_change(wired) -> None:
    """The same value confirmed by the Contact is a different fact."""
    async with wired.session_scope() as session:
        actor, need = await _need(session)
        needs = PropertyNeeds(session)

        await needs.record(
            actor, need.id, [CriterionStatement.inferred(SERVICE_AREA, "Zapopan norte")]
        )
        await needs.record(
            actor, need.id, [CriterionStatement.stated(SERVICE_AREA, "Zapopan norte")]
        )

        rows = await needs.history(need.id)
        assert len(rows) == 2
        assert {row.source for row in rows} == {
            CriterionSource.MODEL_INFERRED.value,
            CriterionSource.CONTACT_STATED.value,
        }


async def test_reconfirming_an_unchanged_value_still_refreshes_the_clock(
    wired,
) -> None:
    """Confirming is an act, not a diff.

    A Contact saying "yes, still that range" revives a Stale need even though
    nothing about the value moved — which is exactly the reconfirmation
    ADR-0026 asks the operation to perform.
    """
    async with wired.session_scope() as session:
        actor, need = await _need(session)
        await commercial.confirm_minimum_criteria(session, actor, need.id, at=NOW)
        await session.commit()
        need_id = need.id

    later = NOW + timedelta(days=PROPERTY_NEED_STALE_DAYS + 1)
    async with wired.session_scope() as session:
        await PropertyNeeds(session).refresh_stale(now=later)

    async with wired.session_scope() as session:
        actor = await commercial.actor_for(session, commercial.ADVISOR_LOGIN)
        needs = PropertyNeeds(session)
        before = len(await needs.history(need_id))

        snapshot = await needs.record(
            actor,
            need_id,
            [
                CriterionStatement.stated(
                    SERVICE_AREA, commercial.CONFIRMED_CRITERIA[SERVICE_AREA]
                )
            ],
            now=later,
        )
        await session.commit()

        assert snapshot.status is PropertyNeedStatus.ACTIVE
        assert snapshot.last_confirmed_at == later
        # No fabricated history for a value that did not move.
        assert len(await needs.history(need_id)) == before
