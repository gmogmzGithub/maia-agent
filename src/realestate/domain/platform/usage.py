"""What the platform counts about each Organization.

Usage, not billing. Nothing here is priced and no row becomes an invoice: the
packaging shape exists so the platform can answer "how much of this are they
actually using" before anybody decides what to charge, and so a customer asking
"why were we refused" gets a number rather than an opinion (ADR-0053).

The pass is **recomputed, never incremented**, for the reason the analytics
projection already gives: a restarted worker repeats a pass, and a counter that a
repeated pass increments is a counter nobody can trust. Every metric is a query
over rows that already exist, so replaying the pass from an empty table rebuilds
the identical store.

The grain is a calendar month in UTC. Monthly because the packaging shape is
monthly and a daily grain would imply a precision these counts do not have — an
Organization's WhatsApp conversation is a Meta billing concept with its own
24-hour window, and Product is counting its own Conversations rather than
reproducing Meta's arithmetic. That difference is stated on the surface that
reports it.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from realestate.db.models import (
    Appointment,
    AppointmentStatus,
    CatalogListing,
    Conversation,
    InboxMessage,
    ListingPublicationState,
    OrganizationMember,
    OrganizationSecretReference,
    OrganizationUsagePeriod,
    OutboxMessage,
    OutboxStatus,
    SecretReferenceState,
    UsageMetric,
)
from realestate.domain.clock import utc_now
from realestate.domain.platform.registry import (
    all_organizations,
    operating_organization_ids,
)

logger = logging.getLogger(__name__)

#: How often recomputing is worth it. Usage is a management number, not an
#: operational one: nobody is waiting on it, and an hourly refresh keeps the
#: platform surface useful without putting eight aggregate scans on the loop
#: every minute.
USAGE_INTERVAL_SECONDS = 3600.0

UNITS: dict[UsageMetric, str] = {
    UsageMetric.ACTIVE_ADVISORS: "asesores",
    UsageMetric.WHATSAPP_CONVERSATIONS: "conversaciones",
    UsageMetric.INBOUND_MESSAGES: "mensajes",
    UsageMetric.OUTBOUND_MESSAGES: "mensajes",
    UsageMetric.MODEL_TURNS: "turnos",
    UsageMetric.ACTIVE_INTEGRATIONS: "integraciones",
    UsageMetric.PUBLISHED_LISTINGS: "publicaciones",
    UsageMetric.CONFIRMED_APPOINTMENTS: "citas",
}

METRIC_LABELS: dict[UsageMetric, str] = {
    UsageMetric.ACTIVE_ADVISORS: "Asesores activos",
    UsageMetric.WHATSAPP_CONVERSATIONS: "Conversaciones de WhatsApp iniciadas",
    UsageMetric.INBOUND_MESSAGES: "Mensajes recibidos",
    UsageMetric.OUTBOUND_MESSAGES: "Mensajes enviados",
    UsageMetric.MODEL_TURNS: "Turnos del modelo",
    UsageMetric.ACTIVE_INTEGRATIONS: "Integraciones con credencial vigente",
    UsageMetric.PUBLISHED_LISTINGS: "Propiedades publicadas",
    UsageMetric.CONFIRMED_APPOINTMENTS: "Citas confirmadas",
}


def month_start(moment: datetime) -> datetime:
    """The first instant of *moment*'s month, in UTC.

    One definition, used by the pass that writes and by every read: a month
    boundary computed twice is a month boundary that eventually disagrees.
    """
    aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    utc = aware.astimezone(UTC)
    return utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_month(start: datetime) -> datetime:
    return (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )


@dataclass(frozen=True)
class UsageReading:
    """One measured quantity, ready to render."""

    metric: UsageMetric
    label: str
    quantity: int
    unit: str
    period_start: datetime


@dataclass(frozen=True)
class OrganizationUsage:
    """One Organization's month."""

    organization_id: uuid.UUID
    slug: str
    display_name: str
    period_start: datetime
    readings: tuple[UsageReading, ...] = field(default_factory=tuple)

    def of(self, metric: UsageMetric) -> UsageReading | None:
        return next((item for item in self.readings if item.metric is metric), None)


@dataclass(frozen=True)
class UsageRefresh:
    """What one pass recomputed."""

    organizations: int = 0
    cells: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.cells)


async def monthly_quantity(
    session: AsyncSession,
    organization_id: uuid.UUID,
    metric: UsageMetric,
    *,
    at: datetime,
) -> int:
    """One stored quantity for the month containing *at*, or zero.

    Read from the projection rather than recomputed, because this is called on
    the entitlement path: putting an aggregate scan in front of every outbound
    message would trade a management number for latency a customer feels. The
    consequence is that a ceiling is enforced against the last refresh, which the
    surface that reports it says out loud.
    """
    found = await session.scalar(
        select(OrganizationUsagePeriod.quantity)
        .where(OrganizationUsagePeriod.organization_id == organization_id)
        .where(OrganizationUsagePeriod.metric == metric.value)
        .where(OrganizationUsagePeriod.period_start == month_start(at))
    )
    return int(found or 0)


class PlatformUsage:
    """Recompute and read what the platform counts.

    Hides: the month arithmetic, the eight measurements, and the idempotent
    upsert that makes a repeated pass harmless.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def refresh(self, *, at: datetime | None = None) -> UsageRefresh:
        """Recompute the current month for every operating Organization.

        Does not commit: the caller owns the transaction, which is what lets the
        worker fold this into the same pass as the rest of its work.
        """
        moment = at or utc_now()
        start = month_start(moment)
        end = next_month(start)
        # The identifiers alone: the pass names no Organization in its output,
        # so the slug and display name would be columns fetched to be dropped.
        identifiers = await operating_organization_ids(self._session)
        if not identifiers:
            return UsageRefresh(organizations=0, cells=0)

        measured = await self._measure(identifiers, start, end)
        stored = await self._stored(identifiers, start)
        cells = 0
        for organization_id in identifiers:
            for metric in UsageMetric:
                self._apply(
                    stored,
                    organization_id=organization_id,
                    metric=metric,
                    start=start,
                    quantity=measured[metric].get(organization_id, 0),
                    refreshed_at=moment,
                )
                cells += 1
        await self._session.flush()
        return UsageRefresh(organizations=len(identifiers), cells=cells)

    async def read(
        self, organization_id: uuid.UUID, *, at: datetime | None = None
    ) -> OrganizationUsage:
        """One Organization's stored month, in declaration order."""
        moment = at or utc_now()
        start = month_start(moment)
        rows = {
            row.metric: row
            for row in await self._session.scalars(
                select(OrganizationUsagePeriod)
                .where(OrganizationUsagePeriod.organization_id == organization_id)
                .where(OrganizationUsagePeriod.period_start == start)
            )
        }
        # ``all_organizations`` rather than the operating ones: a suspended
        # Organization's last month is exactly what somebody looks at while
        # deciding whether to resume it.
        summary = next(
            (
                item
                for item in await all_organizations(self._session)
                if item.organization_id == organization_id
            ),
            None,
        )
        return OrganizationUsage(
            organization_id=organization_id,
            slug=summary.slug if summary else "",
            display_name=summary.display_name if summary else "",
            period_start=start,
            readings=tuple(
                UsageReading(
                    metric=metric,
                    label=METRIC_LABELS[metric],
                    quantity=int(rows[metric.value].quantity)
                    if metric.value in rows
                    else 0,
                    unit=UNITS[metric],
                    period_start=start,
                )
                for metric in UsageMetric
            ),
        )

    async def _counts(
        self, query: Select[tuple[uuid.UUID, int]]
    ) -> dict[uuid.UUID, int]:
        """One grouped count, as ``organization_id -> quantity``.

        Absent means zero: a grouped count returns no row for an Organization
        with nothing to count, and the caller supplies the zero rather than this
        having to know which Organizations were asked about.
        """
        rows = await self._session.execute(query)
        return {organization_id: int(total) for organization_id, total in rows}

    async def _measure(
        self, identifiers: list[uuid.UUID], start: datetime, end: datetime
    ) -> dict[UsageMetric, dict[uuid.UUID, int]]:
        """The eight counts, each one grouped query covering every Organization.

        Grouped rather than asked once per Organization: this is eight aggregate
        scans per pass however many Organizations are operating, where the
        per-Organization form was eight times as many queries as there are
        tenants. The same reasoning the inventory counts already follow — "one
        grouped query rather than once per row".

        Point-in-time counts (Advisors, integrations, published Listings) are
        deliberately *current* rather than as-of the month's end: they answer
        "what is this Organization operating with", which is the question the
        seat ceiling and the integration inventory are about.
        """

        def grouped(
            column: InstrumentedAttribute[uuid.UUID], counted: ColumnElement[Any]
        ) -> Select[tuple[uuid.UUID, int]]:
            return (
                select(column, counted).where(column.in_(identifiers)).group_by(column)
            )

        return {
            UsageMetric.ACTIVE_ADVISORS: await self._counts(
                grouped(
                    OrganizationMember.organization_id,
                    func.count(OrganizationMember.id),
                )
                .where(OrganizationMember.active.is_(True))
                .where(OrganizationMember.advises.is_(True))
            ),
            UsageMetric.WHATSAPP_CONVERSATIONS: await self._counts(
                grouped(Conversation.organization_id, func.count(Conversation.id))
                .where(Conversation.created_at >= start)
                .where(Conversation.created_at < end)
            ),
            UsageMetric.INBOUND_MESSAGES: await self._counts(
                grouped(InboxMessage.organization_id, func.count(InboxMessage.id))
                .where(InboxMessage.persisted_at >= start)
                .where(InboxMessage.persisted_at < end)
            ),
            UsageMetric.OUTBOUND_MESSAGES: await self._counts(
                grouped(OutboxMessage.organization_id, func.count(OutboxMessage.id))
                .where(OutboxMessage.status == OutboxStatus.SENT.value)
                .where(OutboxMessage.created_at >= start)
                .where(OutboxMessage.created_at < end)
            ),
            # A model turn is one settled Inbox group: the group is the unit
            # Hermes is asked about, so counting messages would over-report a
            # customer who writes in fragments — which is most of them.
            UsageMetric.MODEL_TURNS: await self._counts(
                grouped(
                    InboxMessage.organization_id,
                    func.count(func.distinct(InboxMessage.group_id)),
                )
                .where(InboxMessage.group_id.is_not(None))
                .where(InboxMessage.persisted_at >= start)
                .where(InboxMessage.persisted_at < end)
            ),
            UsageMetric.ACTIVE_INTEGRATIONS: await self._counts(
                grouped(
                    OrganizationSecretReference.organization_id,
                    func.count(func.distinct(OrganizationSecretReference.provider)),
                ).where(
                    OrganizationSecretReference.state
                    == SecretReferenceState.ACTIVE.value
                )
            ),
            UsageMetric.PUBLISHED_LISTINGS: await self._counts(
                grouped(
                    CatalogListing.organization_id, func.count(CatalogListing.id)
                ).where(
                    CatalogListing.publication_state
                    == ListingPublicationState.PUBLISHED.value
                )
            ),
            UsageMetric.CONFIRMED_APPOINTMENTS: await self._counts(
                grouped(Appointment.organization_id, func.count(Appointment.id))
                .where(Appointment.status == AppointmentStatus.CONFIRMED.value)
                .where(Appointment.starts_at >= start)
                .where(Appointment.starts_at < end)
            ),
        }

    async def _stored(
        self, identifiers: list[uuid.UUID], start: datetime
    ) -> dict[tuple[uuid.UUID, str], OrganizationUsagePeriod]:
        """This month's existing rows for these Organizations, locked for update.

        One locked select for the whole pass rather than one per cell. The lock
        covers exactly the rows the pass is about to assign, which is what stops
        two overlapping refreshes from interleaving a stale quantity.
        """
        rows = await self._session.scalars(
            select(OrganizationUsagePeriod)
            .where(OrganizationUsagePeriod.organization_id.in_(identifiers))
            .where(OrganizationUsagePeriod.period_start == start)
            .with_for_update()
        )
        return {(row.organization_id, row.metric): row for row in rows}

    def _apply(
        self,
        stored: dict[tuple[uuid.UUID, str], OrganizationUsagePeriod],
        *,
        organization_id: uuid.UUID,
        metric: UsageMetric,
        start: datetime,
        quantity: int,
        refreshed_at: datetime,
    ) -> None:
        row = stored.get((organization_id, metric.value))
        if row is None:
            self._session.add(
                OrganizationUsagePeriod(
                    organization_id=organization_id,
                    metric=metric.value,
                    period_start=start,
                    quantity=quantity,
                    unit=UNITS[metric],
                    refreshed_at=refreshed_at,
                )
            )
            return
        # Assigned, never incremented. See the module docstring.
        row.quantity = quantity
        row.unit = UNITS[metric]
        row.refreshed_at = refreshed_at
