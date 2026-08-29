"""The operating scorecard, with "nobody recorded it" as a first-class answer.

Three different things get written as ``0`` by a careless report, and confusing
them is how an operator ends up managing a fiction:

* a real zero — no appointment was attended;
* an unrecorded value — the visit happened and nobody wrote down what happened;
* an uncomputable ratio — no appointments at all, so attendance has no meaning.

:class:`Measure` keeps them apart, and every number on this scorecard is one.
``Sin registrar`` is never a loss and never a zero (SAN-075): treating a missing
outcome as a negative one turns a data-quality problem into a fake business
result, and rewards writing something down rather than writing the truth down.

Follow-up Coverage itself is not recomputed here. It already has one
authoritative implementation in
:class:`~realestate.domain.commercial.views.CommercialInbox`, and a second query
that agreed with it today would disagree with it eventually.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    ACTIVE_STAGES,
    QUALIFIED_OR_BEYOND,
    AnalyticsDomainEvent,
    AnalyticsEventName,
    Appointment,
    AppointmentStatus,
    HarmSignal,
    HarmSignalKind,
    Opportunity,
    OpportunityStage,
    TrafficClass,
)
from realestate.domain.commercial.actors import Actor
from realestate.domain.commercial.views import CommercialInbox

#: The operator-facing words. Spelled once so a surface cannot invent a
#: synonym that reads like a business result.
UNRECORDED_TEXT = "Sin registrar"
NOT_COMPUTABLE_TEXT = "No calculable"


class MeasureKind(str, enum.Enum):
    """Why a measure reads the way it does."""

    VALUE = "Value"
    #: The subjects exist but their required human-owned field is empty.
    UNRECORDED = "Unrecorded"
    #: There are no subjects, so the ratio has no denominator.
    NOT_COMPUTABLE = "NotComputable"


@dataclass(frozen=True)
class Measure:
    """One reported number, or an explicit statement that there is none."""

    kind: MeasureKind
    value: Decimal | None = None
    unit: str = ""
    #: How many subjects the measure was computed over.
    sample: int = 0
    #: How many subjects had no recorded value. Reported next to the number
    #: rather than folded into it.
    unrecorded: int = 0

    @classmethod
    def of(
        cls,
        value: Decimal,
        *,
        unit: str = "",
        sample: int = 0,
        unrecorded: int = 0,
    ) -> Measure:
        return cls(
            MeasureKind.VALUE,
            value=value,
            unit=unit,
            sample=sample,
            unrecorded=unrecorded,
        )

    @classmethod
    def unrecorded_only(cls, *, sample: int, unit: str = "") -> Measure:
        return cls(MeasureKind.UNRECORDED, unit=unit, sample=sample, unrecorded=sample)

    @classmethod
    def not_computable(cls, *, unit: str = "") -> Measure:
        return cls(MeasureKind.NOT_COMPUTABLE, unit=unit)

    @property
    def text(self) -> str:
        """The Mexican Spanish rendering, including the honest non-answers."""
        if self.kind is MeasureKind.UNRECORDED:
            return UNRECORDED_TEXT
        if self.kind is MeasureKind.NOT_COMPUTABLE or self.value is None:
            return NOT_COMPUTABLE_TEXT
        quantised = self.value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        rendered = f"{quantised.normalize():f}" if quantised % 1 else f"{int(quantised)}"
        return f"{rendered} {self.unit}".strip()


def ratio(numerator: int, denominator: int, *, unrecorded: int = 0) -> Measure:
    """A percentage, or the reason there is not one.

    An empty denominator is ``No calculable`` rather than ``0 %``: nobody was
    eligible, which is a different fact from everybody failing.
    """
    if denominator <= 0:
        return Measure.not_computable(unit="%")
    if unrecorded >= denominator:
        return Measure.unrecorded_only(sample=denominator, unit="%")
    percent = (Decimal(numerator) * 100) / Decimal(denominator)
    return Measure.of(
        percent, unit="%", sample=denominator, unrecorded=unrecorded
    )


def median(values: list[Decimal]) -> Decimal | None:
    """The middle value, or ``None`` when there is nothing to take it of."""
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


@dataclass(frozen=True)
class Scorecard:
    """The pilot scorecard from PROJECT_MEMORY, plus its data-quality half."""

    period_start: datetime
    period_end: datetime
    definition_version: str
    follow_up_coverage: Measure
    coverage_gaps: int
    time_to_first_response: Measure
    qualification_rate: Measure
    appointments_scheduled: int
    appointment_attendance: Measure
    outcome_completeness: Measure
    follow_up_data_completeness: Measure
    harm_signals: dict[str, int] = field(default_factory=dict)
    excluded_events: dict[str, int] = field(default_factory=dict)

    @property
    def harm_total(self) -> int:
        return sum(self.harm_signals.values())


class OperationMetrics:
    """The internal read model behind the BI dashboard.

    Aggregate-only by construction: nothing it returns names a Contact, and
    nothing it returns can be joined back to one.
    """

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor

    async def scorecard(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
        definition_version: str,
    ) -> Scorecard:
        self._actor.require_administrator()
        coverage = await CommercialInbox(self._session).coverage(
            self._actor, now=period_end
        )
        response = await self._time_to_first_response(period_start, period_end)
        qualification = await self._qualification_rate(period_start, period_end)
        scheduled, attendance = await self._appointments(period_start, period_end)
        outcomes = await self._outcome_completeness(period_start, period_end)
        completeness = await self._follow_up_data_completeness(period_start, period_end)
        return Scorecard(
            period_start=period_start,
            period_end=period_end,
            definition_version=definition_version,
            follow_up_coverage=ratio(coverage.covered, coverage.active),
            coverage_gaps=coverage.active - coverage.covered,
            time_to_first_response=response,
            qualification_rate=qualification,
            appointments_scheduled=scheduled,
            appointment_attendance=attendance,
            outcome_completeness=outcomes,
            follow_up_data_completeness=completeness,
            harm_signals=await self._harm_signals(period_start, period_end),
            excluded_events=await self._excluded_events(
                period_start, period_end, definition_version
            ),
        )

    async def _time_to_first_response(
        self, start: datetime, end: datetime
    ) -> Measure:
        """The median minutes to a first reply, from the emitted events.

        Read from the analytics store rather than recomputed over the Inbox: the
        emitter already decided which outbound row was *the* first response, and
        two answers to that question would eventually disagree.
        """
        rows = list(
            await self._session.scalars(
                select(AnalyticsDomainEvent).where(
                    AnalyticsDomainEvent.organization_id
                    == self._actor.organization_id,
                    AnalyticsDomainEvent.event_name
                    == AnalyticsEventName.FIRST_RESPONSE_RECORDED.value,
                    AnalyticsDomainEvent.traffic_class == TrafficClass.VALID.value,
                    AnalyticsDomainEvent.occurred_at >= start,
                    AnalyticsDomainEvent.occurred_at < end,
                )
            )
        )
        minutes = [
            Decimal(str(row.attributes["response_minutes"]))
            for row in rows
            if "response_minutes" in row.attributes
        ]
        middle = median(minutes)
        if middle is None:
            return Measure.not_computable(unit="min")
        return Measure.of(middle, unit="min", sample=len(minutes))

    async def _qualification_rate(self, start: datetime, end: datetime) -> Measure:
        opened = await self._session.scalar(
            select(func.count(Opportunity.id)).where(
                Opportunity.organization_id == self._actor.organization_id,
                Opportunity.created_at >= start,
                Opportunity.created_at < end,
            )
        )
        qualified = await self._session.scalar(
            select(func.count(Opportunity.id)).where(
                Opportunity.organization_id == self._actor.organization_id,
                Opportunity.created_at >= start,
                Opportunity.created_at < end,
                Opportunity.qualified_at.is_not(None),
            )
        )
        return ratio(qualified or 0, opened or 0)

    async def _appointments(
        self, start: datetime, end: datetime
    ) -> tuple[int, Measure]:
        rows = list(
            await self._session.scalars(
                select(Appointment).where(
                    Appointment.organization_id == self._actor.organization_id,
                    Appointment.starts_at >= start,
                    Appointment.starts_at < end,
                    Appointment.status == AppointmentStatus.CONFIRMED.value,
                )
            )
        )
        due = [row for row in rows if row.starts_at < end]
        recorded = [row for row in due if row.attendance is not None]
        attended = [row for row in recorded if row.attendance == "Attended"]
        return len(rows), ratio(
            len(attended), len(due), unrecorded=len(due) - len(recorded)
        )

    async def _outcome_completeness(self, start: datetime, end: datetime) -> Measure:
        """The share of closed Opportunities whose outcome evidence exists.

        Dormant counts as a recorded outcome — it has a reason and a revisit
        condition — while a Lost row with no reason does not. That distinction
        is the whole point: silence is not a loss (SAN-070).
        """
        rows = list(
            await self._session.scalars(
                select(Opportunity).where(
                    Opportunity.organization_id == self._actor.organization_id,
                    Opportunity.closed_at.is_not(None),
                    Opportunity.closed_at >= start,
                    Opportunity.closed_at < end,
                )
            )
        )
        if not rows:
            return Measure.not_computable(unit="%")
        recorded = 0
        for row in rows:
            if row.stage == OpportunityStage.WON.value and row.won_evidence:
                recorded += 1
            elif row.stage == OpportunityStage.LOST.value and row.lost_reason:
                recorded += 1
            elif row.stage == OpportunityStage.DORMANT.value and row.dormant_reason:
                recorded += 1
        return ratio(recorded, len(rows), unrecorded=len(rows) - recorded)

    async def _follow_up_data_completeness(
        self, start: datetime, end: datetime
    ) -> Measure:
        """Appointments and Opportunities whose human-owned fields are filled.

        One number over both populations, because CONTEXT.md defines Follow-up
        Data Completeness that way and because reporting the two separately
        invites reading the flattering one.
        """
        visits = list(
            await self._session.scalars(
                select(Appointment).where(
                    Appointment.organization_id == self._actor.organization_id,
                    Appointment.status == AppointmentStatus.CONFIRMED.value,
                    Appointment.starts_at >= start,
                    Appointment.starts_at < end,
                )
            )
        )
        closed = list(
            await self._session.scalars(
                select(Opportunity).where(
                    Opportunity.organization_id == self._actor.organization_id,
                    Opportunity.closed_at.is_not(None),
                    Opportunity.closed_at >= start,
                    Opportunity.closed_at < end,
                )
            )
        )
        total = len(visits) + len(closed)
        if total == 0:
            return Measure.not_computable(unit="%")
        complete = sum(1 for row in visits if row.attendance is not None)
        complete += sum(
            1
            for row in closed
            if (row.stage == OpportunityStage.WON.value and row.won_evidence)
            or (row.stage == OpportunityStage.LOST.value and row.lost_reason)
            or (row.stage == OpportunityStage.DORMANT.value and row.dormant_reason)
        )
        return ratio(complete, total, unrecorded=total - complete)

    async def _harm_signals(self, start: datetime, end: datetime) -> dict[str, int]:
        rows = await self._session.execute(
            select(HarmSignal.kind, func.count(HarmSignal.id))
            .where(
                HarmSignal.organization_id == self._actor.organization_id,
                HarmSignal.occurred_at >= start,
                HarmSignal.occurred_at < end,
            )
            .group_by(HarmSignal.kind)
        )
        counted = {kind: count for kind, count in rows}
        return {item.value: counted.get(item.value, 0) for item in HarmSignalKind}

    async def _excluded_events(
        self, start: datetime, end: datetime, version: str
    ) -> dict[str, int]:
        rows = await self._session.execute(
            select(
                AnalyticsDomainEvent.traffic_class,
                func.count(AnalyticsDomainEvent.id),
            )
            .where(
                AnalyticsDomainEvent.organization_id == self._actor.organization_id,
                AnalyticsDomainEvent.definition_version == version,
                AnalyticsDomainEvent.occurred_at >= start,
                AnalyticsDomainEvent.occurred_at < end,
                AnalyticsDomainEvent.traffic_class != TrafficClass.VALID.value,
            )
            .group_by(AnalyticsDomainEvent.traffic_class)
        )
        return {traffic_class: count for traffic_class, count in rows}

    async def active_opportunity_counts(self) -> tuple[int, int]:
        """Active and Qualified-or-beyond counts, for the dashboard header."""
        active = await self._session.scalar(
            select(func.count(Opportunity.id)).where(
                Opportunity.organization_id == self._actor.organization_id,
                Opportunity.stage.in_(ACTIVE_STAGES),
            )
        )
        qualified = await self._session.scalar(
            select(func.count(Opportunity.id)).where(
                Opportunity.organization_id == self._actor.organization_id,
                Opportunity.stage.in_(QUALIFIED_OR_BEYOND),
            )
        )
        return active or 0, qualified or 0


@dataclass(frozen=True)
class HarmSignalCommand:
    """One Administrator-recorded pilot harm signal."""

    kind: HarmSignalKind
    evidence: str
    occurred_at: datetime
    command_key: str
    opportunity_id: uuid.UUID | None = None


class HarmSignals:
    """Record the pilot's stop-condition signals idempotently."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor

    async def record(self, command: HarmSignalCommand, *, at: datetime) -> uuid.UUID:
        self._actor.require_administrator()
        evidence = command.evidence.strip()
        if len(evidence) < 4:
            raise ValueError("Una señal de daño requiere evidencia escrita.")
        existing = await self._session.scalar(
            select(HarmSignal).where(
                HarmSignal.organization_id == self._actor.organization_id,
                HarmSignal.command_key == command.command_key,
            )
        )
        if existing is not None:
            return existing.id
        row = HarmSignal(
            organization_id=self._actor.organization_id,
            kind=command.kind.value,
            opportunity_id=command.opportunity_id,
            recorded_by=self._actor.member_id,
            evidence=evidence,
            occurred_at=command.occurred_at,
            recorded_at=at,
            command_key=command.command_key,
        )
        self._session.add(row)
        await self._session.flush()
        return row.id


def default_period(now: datetime, *, days: int = 30) -> tuple[datetime, datetime]:
    """The reporting window the dashboard opens on."""
    return now - timedelta(days=days), now
