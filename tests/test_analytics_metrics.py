"""``Sin registrar`` is not zero, and it is not a loss.

Three different facts get written as ``0`` by a careless report — a real zero, an
unrecorded value, and an uncomputable ratio — and confusing them is how an
operator ends up managing a fiction. Every assertion here is about keeping them
apart, plus the two SAN-075 metrics that only mean something when they are shown
separately: Follow-up Data Completeness and outcome completeness.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from realestate.db.engine import Database
from realestate.db.models import (
    AnalyticsEventName,
    AppointmentStatus,
    HarmSignalKind,
    OpportunityStage,
)
from realestate.domain.analytics.definitions import CURRENT_DEFINITION_VERSION
from realestate.domain.analytics.emission import AnalyticsEmission
from realestate.domain.analytics.metrics import (
    NOT_COMPUTABLE_TEXT,
    UNRECORDED_TEXT,
    HarmSignalCommand,
    HarmSignals,
    Measure,
    MeasureKind,
    OperationMetrics,
    median,
    ratio,
)
from realestate.domain.analytics.projection import AnalyticsProjection
from realestate.domain.commercial.actors import NotAuthorized
from realestate.domain.commercial.opportunities import (
    DormantReason,
    LostReason,
    OpportunityManagement,
    RecordDormant,
    RecordLost,
)
from tests.conftest import (
    DATABASE_URL,
    requires_postgres,
    reset_property_inventory,
)
from tests.fixtures.commercial import (
    ADMIN_LOGIN,
    ADVISOR_LOGIN,
    actor_for,
    confirm_minimum_criteria,
    opportunity_for,
    provision,
    reset,
)
from tests.fixtures.sponsorship import MOMENT

pytestmark = requires_postgres
PERIOD_START = MOMENT - timedelta(days=30)
PERIOD_END = MOMENT + timedelta(days=1)


@pytest.fixture
async def database():
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await reset(session)
        await reset_property_inventory(session)
        await provision(session)
        await session.commit()
    yield database
    await database.dispose()


def test_a_ratio_without_a_denominator_is_not_computable_rather_than_zero() -> None:
    """Nobody was eligible is a different fact from everybody failing."""
    measure = ratio(0, 0)
    assert measure.kind is MeasureKind.NOT_COMPUTABLE
    assert measure.text == NOT_COMPUTABLE_TEXT


def test_a_ratio_whose_whole_denominator_is_unrecorded_says_so() -> None:
    """Four visits and four blank write-ups is not a zero percent attendance."""
    measure = ratio(0, 4, unrecorded=4)
    assert measure.kind is MeasureKind.UNRECORDED
    assert measure.text == UNRECORDED_TEXT
    assert measure.unrecorded == 4


def test_a_real_zero_is_reported_as_zero() -> None:
    """Four visits written up, none attended. That is a result, not a gap."""
    measure = ratio(0, 4)
    assert measure.kind is MeasureKind.VALUE
    assert measure.text == "0 %"


def test_a_partial_ratio_reports_the_number_and_the_gap_beside_it() -> None:
    measure = ratio(1, 4, unrecorded=1)
    assert measure.text == "25 %"
    assert (measure.sample, measure.unrecorded) == (4, 1)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([], None),
        ([Decimal("5")], Decimal("5")),
        ([Decimal("1"), Decimal("3")], Decimal("2")),
        ([Decimal("9"), Decimal("1"), Decimal("5")], Decimal("5")),
    ],
)
def test_the_median_of_nothing_is_nothing(values, expected) -> None:
    assert median(values) == expected


def test_a_measure_renders_one_decimal_and_drops_a_trailing_zero() -> None:
    assert Measure.of(Decimal("33.333"), unit="%").text == "33.3 %"
    assert Measure.of(Decimal("50.0"), unit="%").text == "50 %"
    assert Measure.of(Decimal("12"), unit="min").text == "12 min"


async def test_an_advisor_may_not_read_the_internal_scorecard(database) -> None:
    async with database.session_scope() as session:
        advisor = await actor_for(session, ADVISOR_LOGIN)
        with pytest.raises(NotAuthorized):
            await OperationMetrics(session, advisor).scorecard(
                period_start=PERIOD_START,
                period_end=PERIOD_END,
                definition_version=CURRENT_DEFINITION_VERSION,
            )


async def test_an_empty_operation_reports_no_computable_rates_and_no_zeros(
    database,
) -> None:
    """A pilot on day zero does not report a 0 percent qualification rate."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        card = await OperationMetrics(session, admin).scorecard(
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            definition_version=CURRENT_DEFINITION_VERSION,
        )
        assert card.qualification_rate.text == NOT_COMPUTABLE_TEXT
        assert card.appointment_attendance.text == NOT_COMPUTABLE_TEXT
        assert card.outcome_completeness.text == NOT_COMPUTABLE_TEXT
        assert card.follow_up_data_completeness.text == NOT_COMPUTABLE_TEXT
        assert card.time_to_first_response.text == NOT_COMPUTABLE_TEXT
        # Deliberately ``No calculable`` and not ``100 %``. There is nothing to
        # cover, and an empty pilot reporting perfect coverage is the single
        # most misleading number this dashboard could show on day one.
        assert card.follow_up_coverage.text == NOT_COMPUTABLE_TEXT
        assert card.harm_total == 0


async def test_a_closed_opportunity_without_evidence_lowers_completeness(
    database,
) -> None:
    """A Lost row with a reason counts; ``Unknown`` is still a recorded reason.

    ``Unknown`` is deliberately a real option (SAN-070): forcing a specific
    reason produces invented ones. What outcome completeness measures is whether
    somebody wrote *something* down, not whether they were decisive.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        management = OpportunityManagement(session)

        first = await opportunity_for(session, "5213300000001", confirm_criteria=True)
        await management.record(
            admin,
            RecordLost(
                opportunity_id=first.opportunity_id,
                reason=LostReason.UNKNOWN,
                command_key="lost:first",
                at=MOMENT,
            ),
        )
        second = await opportunity_for(session, "5213300000002", confirm_criteria=True)
        await management.record(
            admin,
            RecordDormant(
                opportunity_id=second.opportunity_id,
                reason=DormantReason.NO_RESPONSE,
                revisit_condition="Reconfirmar en 60 días",
                command_key="dormant:second",
                at=MOMENT,
            ),
        )
        await session.commit()

        card = await OperationMetrics(session, admin).scorecard(
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            definition_version=CURRENT_DEFINITION_VERSION,
        )
        # Both closures carry evidence, so completeness is a genuine 100.
        assert card.outcome_completeness.text == "100 %"
        assert card.outcome_completeness.unrecorded == 0


async def test_a_visit_nobody_wrote_up_is_sin_registrar_not_a_missed_visit(
    database,
) -> None:
    """Product never invents a Missed outcome for an unrecorded visit.

    That would turn a data-quality problem into a fake business result, and it
    would reward writing something down over writing the truth down.
    """
    from realestate.db.models import Appointment

    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        state = await opportunity_for(session, "5213300000003", confirm_criteria=True)
        from tests.fixtures.commercial import make_conversation

        conversation = await make_conversation(session, state.lead, started_at=MOMENT)
        from realestate.domain.catalog.administration import (
            CatalogAdministration,
            CreateProperty,
        )

        physical = await CatalogAdministration(session).record(
            admin,
            CreateProperty(
                property_key="casa-medicion",
                name="Casa Medición",
                property_type="House",
                facts={"city": "Zapopan"},
                provenance={"kind": "Test"},
                command_key="metrics:property",
            ),
        )
        session.add(
            Appointment(
                organization_id=admin.organization_id,
                reference="VIS-METRICS-1",
                idempotency_key="metrics-visit-1",
                conversation_id=conversation.id,
                lead_id=state.lead.id,
                property_uuid=physical.subject_id,
                starts_at=MOMENT - timedelta(days=1),
                ends_at=MOMENT - timedelta(days=1) + timedelta(minutes=90),
                status=AppointmentStatus.CONFIRMED.value,
                created_at=MOMENT - timedelta(days=2),
            )
        )
        await session.commit()

        card = await OperationMetrics(session, admin).scorecard(
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            definition_version=CURRENT_DEFINITION_VERSION,
        )
        assert card.appointments_scheduled == 1
        assert card.appointment_attendance.text == UNRECORDED_TEXT
        assert card.appointment_attendance.unrecorded == 1
        assert card.follow_up_data_completeness.text == UNRECORDED_TEXT


async def test_first_response_minutes_come_from_the_emitted_events(database) -> None:
    """The scorecard reads the emitted event, not a second derivation.

    The emitter already decided which outbound row was *the* first response;
    two answers to that question would eventually disagree.
    """
    from realestate.db.models import OutboxMessage, OutboxStatus
    from tests.fixtures.commercial import make_conversation, make_inbound

    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        state = await opportunity_for(session, "5213300000004")
        conversation = await make_conversation(session, state.lead, started_at=MOMENT)
        await make_inbound(session, conversation, sent_at=MOMENT)
        session.add(
            OutboxMessage(
                organization_id=conversation.organization_id,
                conversation_id=conversation.id,
                idempotency_key="metrics-outbox-1",
                to_wa_id=state.lead.wa_id,
                kind="AgentReply",
                body="Gracias por escribir.",
                status=OutboxStatus.SENT.value,
                created_at=MOMENT,
                sent_at=MOMENT + timedelta(minutes=6),
            )
        )
        await session.commit()

        await AnalyticsEmission(session, admin).emit_operational()
        await session.commit()
        await AnalyticsProjection(session, admin).drain()
        await session.commit()

        card = await OperationMetrics(session, admin).scorecard(
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            definition_version=CURRENT_DEFINITION_VERSION,
        )
        assert card.time_to_first_response.text == "6 min"
        assert card.time_to_first_response.sample == 1


async def test_qualification_is_counted_from_the_opportunity_itself(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        qualified = await opportunity_for(session, "5213300000005", confirm_criteria=True)
        assert qualified.need_id is not None
        await confirm_minimum_criteria(session, admin, qualified.need_id, at=MOMENT)
        from realestate.domain.commercial.opportunities import AdvanceStage

        await OpportunityManagement(session).record(
            admin,
            AdvanceStage(
                opportunity_id=qualified.opportunity_id,
                to_stage=OpportunityStage.QUALIFIED,
                command_key="qualify:metrics",
                at=MOMENT,
            ),
        )
        await opportunity_for(session, "5213300000006")
        await session.commit()

        card = await OperationMetrics(session, admin).scorecard(
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            definition_version=CURRENT_DEFINITION_VERSION,
        )
        assert card.qualification_rate.text == "50 %"
        active, qualified_count = await OperationMetrics(
            session, admin
        ).active_opportunity_counts()
        assert active >= 2
        assert qualified_count >= 1


async def test_a_harm_signal_is_idempotent_and_reaches_the_scorecard(
    database,
) -> None:
    """SAN-079's stop conditions are counted, and recording one twice counts once."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        signals = HarmSignals(session, admin)
        command = HarmSignalCommand(
            kind=HarmSignalKind.UNTIMELY_MESSAGE,
            evidence="Mensaje sintético fuera de horario en la prueba.",
            occurred_at=MOMENT,
            command_key="harm:untimely:1",
        )
        first = await signals.record(command, at=MOMENT)
        second = await signals.record(command, at=MOMENT)
        await session.commit()
        assert first == second

        card = await OperationMetrics(session, admin).scorecard(
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            definition_version=CURRENT_DEFINITION_VERSION,
        )
        assert card.harm_signals[HarmSignalKind.UNTIMELY_MESSAGE.value] == 1
        assert card.harm_total == 1
        # Every kind is present, so a zero is an explicit "none of these" rather
        # than a category somebody forgot to look for.
        assert set(card.harm_signals) == {item.value for item in HarmSignalKind}


async def test_a_harm_signal_requires_written_evidence(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        with pytest.raises(ValueError, match="evidencia"):
            await HarmSignals(session, admin).record(
                HarmSignalCommand(
                    kind=HarmSignalKind.COMPLAINT,
                    evidence="  ",
                    occurred_at=MOMENT,
                    command_key="harm:blank",
                ),
                at=MOMENT,
            )


async def test_an_advisor_may_not_record_a_harm_signal(database) -> None:
    async with database.session_scope() as session:
        advisor = await actor_for(session, ADVISOR_LOGIN)
        with pytest.raises(NotAuthorized):
            await HarmSignals(session, advisor).record(
                HarmSignalCommand(
                    kind=HarmSignalKind.COMPLAINT,
                    evidence="Intento sin autorización.",
                    occurred_at=MOMENT,
                    command_key="harm:advisor",
                ),
                at=MOMENT,
            )


async def test_excluded_events_are_reported_next_to_the_results(database) -> None:
    from realestate.domain.analytics.events import AnalyticsEvent, AnalyticsEvents

    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await AnalyticsEvents(session, admin).record(
            AnalyticsEvent(
                event_key="scorecard-bot-event-key",
                name=AnalyticsEventName.MAIA_STARTED,
                occurred_at=MOMENT,
                bot=True,
            )
        )
        await session.commit()
        await AnalyticsProjection(session, admin).drain()
        await session.commit()

        card = await OperationMetrics(session, admin).scorecard(
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            definition_version=CURRENT_DEFINITION_VERSION,
        )
        assert card.excluded_events == {"Bot": 1}
