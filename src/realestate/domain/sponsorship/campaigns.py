"""The Sponsorship Campaign lifecycle, and what each transition costs.

Draft, Quoted, Reserved, Scheduled, Active, Paused, Completed, Cancelled — the
states ADR-0043 accepts, and no others. Two of the rules here are the ones that
make the product trustworthy rather than merely functional:

**Pausing preserves paid days.** When the source Listing loses authority,
availability, publication or Presentation Readiness, delivery stops and the
undelivered days stay undelivered. A day is consumed by being *delivered*, not
by passing on a calendar, so a buyer whose Listing was withdrawn for a week gets
that week back rather than an apology.

**Nothing here moves money.** ``collection_state`` is somebody's record of what
happened outside Product. There is no invoice, no charge, no auto-renewal, and
completing a campaign does not create a successor.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    AnalyticsEventName,
    AnalyticsOutboxEntry,
    CatalogListing,
    CollectionState,
    SponsorshipCampaign,
    SponsorshipCampaignStatus,
    SponsorshipDeliveryDay,
    SponsorshipQuote,
    SponsorshipQuoteStatus,
)
from realestate.domain.analytics.projection import day_of
from realestate.domain.audit import record_audit
from realestate.domain.commercial.actors import (
    Actor,
    CommercialError,
    InvalidTransition,
    NotFound,
)
from realestate.domain.sponsorship.capacity import SponsorshipCapacity
from realestate.domain.sponsorship.eligibility import (
    SponsoredDecision,
    SponsoredEligibility,
)
from realestate.domain.sponsorship.pricing import (
    DEFAULT_DURATION_DAYS,
    PACKAGES,
    PACKAGE_SURFACES,
)

#: Why one service date did or did not consume a paid day.
DELIVERED = "Delivered"
NO_MEASURED_DELIVERY = "NoMeasuredDelivery"
NOT_ELIGIBLE = "NotEligible"
PAUSED = "Paused"

BUYER_KINDS: tuple[str, ...] = ("Owner", "Developer", "Collaborator")


class CampaignRefused(CommercialError):
    """The campaign cannot take this step yet."""

    message = "La campaña no cumple las condiciones para ese paso."


@dataclass(frozen=True)
class OpenCampaign:
    """A Draft campaign over one eligible source Listing."""

    listing_id: uuid.UUID
    buyer_kind: str
    buyer_label: str
    package: str
    paid_days: int = DEFAULT_DURATION_DAYS
    command_key: str = ""


@dataclass(frozen=True)
class ScheduleCampaign:
    campaign_id: uuid.UUID
    starts_on: datetime


@dataclass(frozen=True)
class RecordCollection:
    campaign_id: uuid.UUID
    state: CollectionState
    reference: str = ""


@dataclass(frozen=True)
class CampaignView:
    campaign_id: uuid.UUID
    listing_id: uuid.UUID
    status: str
    package: str
    surfaces: tuple[str, ...]
    paid_days: int
    delivered_days: int
    remaining_days: int
    starts_on: datetime | None
    collection_state: str
    buyer_label: str
    buyer_kind: str
    paused_reason: str | None

    @property
    def status_label(self) -> str:
        return {
            "Draft": "Borrador",
            "Quoted": "Cotizada",
            "Reserved": "Reservada",
            "Scheduled": "Programada",
            "Active": "Activa",
            "Paused": "Pausada",
            "Completed": "Completada",
            "Cancelled": "Cancelada",
        }.get(self.status, self.status)


@dataclass(frozen=True)
class DailyOutcome:
    """What one daily pass decided for one campaign."""

    campaign_id: uuid.UUID
    status: str
    counted: bool
    reason: str
    decision: SponsoredDecision


def view_of(row: SponsorshipCampaign) -> CampaignView:
    return CampaignView(
        campaign_id=row.id,
        listing_id=row.listing_id,
        status=row.status,
        package=row.package,
        surfaces=PACKAGE_SURFACES.get(row.package, ()),
        paid_days=row.paid_days,
        delivered_days=row.delivered_days,
        remaining_days=max(0, row.paid_days - row.delivered_days),
        starts_on=row.starts_on,
        collection_state=row.collection_state,
        buyer_label=row.buyer_label,
        buyer_kind=row.buyer_kind,
        paused_reason=row.paused_reason,
    )


class SponsorshipCampaigns:
    """Open, clear, schedule, activate, pause, resume, complete and cancel."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor

    async def open(self, command: OpenCampaign, *, at: datetime) -> CampaignView:
        self._actor.require_administrator()
        if command.buyer_kind not in BUYER_KINDS:
            raise ValueError("El tipo de comprador no es válido.")
        if command.package not in PACKAGES:
            raise ValueError("El paquete no es válido.")
        if command.paid_days <= 0:
            raise ValueError("Los días pagados deben ser positivos.")
        label = command.buyer_label.strip()
        if len(label) < 2:
            raise ValueError("La campaña requiere identificar al comprador.")
        listing = await self._session.get(CatalogListing, command.listing_id)
        if listing is None:
            raise NotFound("No encontramos esa publicación.")
        self._actor.require_same_organization(listing.organization_id)
        live = await self._session.scalar(
            select(SponsorshipCampaign).where(
                SponsorshipCampaign.organization_id == self._actor.organization_id,
                SponsorshipCampaign.listing_id == listing.id,
                SponsorshipCampaign.status.notin_(
                    (
                        SponsorshipCampaignStatus.CANCELLED.value,
                        SponsorshipCampaignStatus.COMPLETED.value,
                    )
                ),
            )
        )
        if live is not None:
            raise CampaignRefused(
                "Esa publicación ya tiene una campaña de patrocinio en curso."
            )
        row = SponsorshipCampaign(
            organization_id=self._actor.organization_id,
            listing_id=listing.id,
            buyer_kind=command.buyer_kind,
            buyer_label=label,
            status=SponsorshipCampaignStatus.DRAFT.value,
            package=command.package,
            paid_days=command.paid_days,
            created_at=at,
            updated_at=at,
        )
        self._session.add(row)
        await self._session.flush()
        await self._audit("OpenSponsorshipCampaign", row, {"package": row.package})
        return view_of(row)

    async def record_clearance(
        self, campaign_id: uuid.UUID, evidence: str, *, at: datetime
    ) -> CampaignView:
        """Attach the written commercial validation payment depends on.

        SAN-065 is still Pending, so Product cannot enumerate the defects that
        block accepting money. What it can do is refuse to deliver until a named
        Administrator wrote down that they checked — which is the difference
        between an unanswered question and an assumption.
        """
        self._actor.require_administrator()
        text_value = evidence.strip()
        if len(text_value) < 8:
            raise CampaignRefused(
                "La validación comercial requiere una nota escrita del "
                "administrador (SAN-065)."
            )
        row = await self._locked(campaign_id)
        row.commercial_clearance = text_value
        row.updated_at = at
        await self._session.flush()
        await self._audit("ClearSponsorshipCampaign", row, {"length": len(text_value)})
        return view_of(row)

    async def schedule(
        self, command: ScheduleCampaign, *, at: datetime
    ) -> CampaignView:
        """Move a Reserved campaign to Scheduled with a start date."""
        self._actor.require_administrator()
        row = await self._locked(command.campaign_id)
        if row.status != SponsorshipCampaignStatus.RESERVED.value:
            raise InvalidTransition(
                "Sólo una campaña reservada puede programarse."
            )
        if command.starts_on < day_of(at):
            raise CampaignRefused("La fecha de inicio no puede estar en el pasado.")
        row.status = SponsorshipCampaignStatus.SCHEDULED.value
        row.starts_on = command.starts_on
        row.updated_at = at
        await self._session.flush()
        await self._audit(
            "ScheduleSponsorshipCampaign",
            row,
            {"starts_on": command.starts_on.isoformat()},
        )
        return view_of(row)

    async def activate(self, campaign_id: uuid.UUID, *, at: datetime) -> CampaignView:
        """Begin delivery, refusing when the placement is not eligible now."""
        self._actor.require_administrator()
        row = await self._locked(campaign_id)
        if row.status not in {
            SponsorshipCampaignStatus.SCHEDULED.value,
            SponsorshipCampaignStatus.PAUSED.value,
        }:
            raise InvalidTransition(
                "Sólo una campaña programada o pausada puede activarse."
            )
        decision = await SponsoredEligibility(self._session, self._actor).evaluate(
            row.listing_id, None, at, campaign=row
        )
        blocking = tuple(
            reason
            for reason in decision.reasons
            if "no está programada" not in reason and "no ha iniciado" not in reason
        )
        if blocking:
            raise CampaignRefused(
                "La campaña no puede activarse: " + "; ".join(blocking) + "."
            )
        row.status = SponsorshipCampaignStatus.ACTIVE.value
        row.activated_at = row.activated_at or at
        row.paused_at = None
        row.paused_reason = None
        row.updated_at = at
        await self._session.flush()
        await self._audit("ActivateSponsorshipCampaign", row, {})
        return view_of(row)

    async def pause(
        self, campaign_id: uuid.UUID, reason: str, *, at: datetime
    ) -> CampaignView:
        """Stop delivery and keep the remaining paid days."""
        row = await self._locked(campaign_id)
        if row.status != SponsorshipCampaignStatus.ACTIVE.value:
            raise InvalidTransition("Sólo una campaña activa puede pausarse.")
        row.status = SponsorshipCampaignStatus.PAUSED.value
        row.paused_at = at
        row.paused_reason = reason.strip() or "Sin motivo registrado"
        row.updated_at = at
        await self._session.flush()
        await self._audit(
            "PauseSponsorshipCampaign",
            row,
            {"reason": row.paused_reason, "remaining_days": row.paid_days - row.delivered_days},
        )
        return view_of(row)

    async def cancel(
        self, campaign_id: uuid.UUID, reason: str, *, at: datetime
    ) -> CampaignView:
        self._actor.require_administrator()
        row = await self._locked(campaign_id)
        if row.status == SponsorshipCampaignStatus.CANCELLED.value:
            return view_of(row)
        row.status = SponsorshipCampaignStatus.CANCELLED.value
        row.cancelled_at = at
        row.paused_reason = reason.strip() or None
        row.updated_at = at
        await SponsorshipCapacity(self._session, self._actor).release(row.id, at=at)
        for quote in await self._session.scalars(
            select(SponsorshipQuote).where(
                SponsorshipQuote.campaign_id == row.id,
                SponsorshipQuote.status == SponsorshipQuoteStatus.ISSUED.value,
            )
        ):
            quote.status = SponsorshipQuoteStatus.CANCELLED.value
        await self._session.flush()
        await self._audit("CancelSponsorshipCampaign", row, {"reason": reason})
        return view_of(row)

    async def record_collection(
        self, command: RecordCollection, *, at: datetime
    ) -> CampaignView:
        """Record what somebody observed outside Product. Never a payment."""
        self._actor.require_administrator()
        row = await self._locked(command.campaign_id)
        row.collection_state = command.state.value
        row.collection_reference = command.reference.strip() or None
        row.updated_at = at
        await self._session.flush()
        await self._audit(
            "RecordSponsorshipCollection", row, {"state": row.collection_state}
        )
        return view_of(row)

    async def run_daily(self, *, at: datetime) -> tuple[DailyOutcome, ...]:
        """One pass over every live campaign: check, count, pause, complete.

        The pass is the only writer of ``delivered_days``, and it writes at most
        one delivery day per campaign per service date. That is what makes it
        safe to run on every worker tick and after a restart: the second run of
        a day finds the row and changes nothing.
        """
        service_date = day_of(at)
        eligibility = SponsoredEligibility(self._session, self._actor)
        outcomes: list[DailyOutcome] = []
        rows = list(
            await self._session.scalars(
                select(SponsorshipCampaign)
                .where(
                    SponsorshipCampaign.organization_id == self._actor.organization_id,
                    SponsorshipCampaign.status.in_(
                        (
                            SponsorshipCampaignStatus.SCHEDULED.value,
                            SponsorshipCampaignStatus.ACTIVE.value,
                            SponsorshipCampaignStatus.PAUSED.value,
                        )
                    ),
                )
                .order_by(SponsorshipCampaign.created_at)
                .with_for_update()
            )
        )
        for row in rows:
            decision = await eligibility.evaluate(
                row.listing_id, None, at, campaign=row
            )
            await eligibility.record_daily(row.id, decision, at=at)
            counted, reason = await self._account_for_day(
                row, decision, service_date=service_date, at=at
            )
            outcomes.append(
                DailyOutcome(
                    campaign_id=row.id,
                    status=row.status,
                    counted=counted,
                    reason=reason,
                    decision=decision,
                )
            )
        await self._session.flush()
        return tuple(outcomes)

    async def _account_for_day(
        self,
        row: SponsorshipCampaign,
        decision: SponsoredDecision,
        *,
        service_date: datetime,
        at: datetime,
    ) -> tuple[bool, str]:
        started = row.starts_on is not None and row.starts_on <= at
        deliverable = decision.eligible and started
        if not deliverable:
            if row.status == SponsorshipCampaignStatus.ACTIVE.value and started:
                row.status = SponsorshipCampaignStatus.PAUSED.value
                row.paused_at = at
                row.paused_reason = "; ".join(decision.reasons) or "No elegible"
                row.updated_at = at
                await self._audit(
                    "PauseSponsorshipCampaign",
                    row,
                    {
                        "reason": row.paused_reason,
                        "automatic": True,
                        "remaining_days": row.paid_days - row.delivered_days,
                    },
                )
            return await self._delivery_day(
                row, service_date, counted=False, reason=NOT_ELIGIBLE
            )
        if row.status == SponsorshipCampaignStatus.PAUSED.value:
            # Resumed automatically once the blocking reason is gone. The paused
            # days were never consumed, so resuming does not extend anything.
            row.status = SponsorshipCampaignStatus.ACTIVE.value
            row.paused_at = None
            row.paused_reason = None
            row.updated_at = at
            await self._audit("ResumeSponsorshipCampaign", row, {"automatic": True})
        elif row.status == SponsorshipCampaignStatus.SCHEDULED.value:
            row.status = SponsorshipCampaignStatus.ACTIVE.value
            row.activated_at = row.activated_at or at
            row.updated_at = at
            await self._audit("ActivateSponsorshipCampaign", row, {"automatic": True})
        measured = await self._measured_delivery(row, service_date)
        counted, reason = await self._delivery_day(
            row,
            service_date,
            counted=measured,
            reason=DELIVERED if measured else NO_MEASURED_DELIVERY,
        )
        if counted:
            row.delivered_days += 1
            row.updated_at = at
        if row.delivered_days >= row.paid_days:
            row.status = SponsorshipCampaignStatus.COMPLETED.value
            row.completed_at = at
            row.updated_at = at
            await SponsorshipCapacity(self._session, self._actor).release(row.id, at=at)
            await self._audit(
                "CompleteSponsorshipCampaign",
                row,
                {"delivered_days": row.delivered_days},
            )
        return counted, reason

    async def _measured_delivery(
        self, row: SponsorshipCampaign, service_date: datetime
    ) -> bool:
        """Whether Product recorded an actual paid placement that date."""
        evidence = await self._session.scalar(
            select(AnalyticsOutboxEntry.id)
            .where(
                AnalyticsOutboxEntry.organization_id == row.organization_id,
                AnalyticsOutboxEntry.event_name.in_(
                    (
                        AnalyticsEventName.SPONSORED_SERVED_IMPRESSION.value,
                        AnalyticsEventName.SPONSORED_VISIBLE_IMPRESSION.value,
                    )
                ),
                AnalyticsOutboxEntry.payload["campaign_id"].as_string()
                == str(row.id),
                AnalyticsOutboxEntry.occurred_at >= service_date,
                AnalyticsOutboxEntry.occurred_at < service_date + timedelta(days=1),
            )
            .limit(1)
        )
        return evidence is not None

    async def _delivery_day(
        self,
        row: SponsorshipCampaign,
        service_date: datetime,
        *,
        counted: bool,
        reason: str,
    ) -> tuple[bool, str]:
        existing = await self._session.scalar(
            select(SponsorshipDeliveryDay).where(
                SponsorshipDeliveryDay.campaign_id == row.id,
                SponsorshipDeliveryDay.service_date == service_date,
            )
        )
        if existing is not None:
            if (
                counted
                and not existing.counted
                and existing.reason == NO_MEASURED_DELIVERY
            ):
                existing.counted = True
                existing.reason = reason
                await self._session.flush()
                return True, reason
            return False, existing.reason
        self._session.add(
            SponsorshipDeliveryDay(
                organization_id=row.organization_id,
                campaign_id=row.id,
                service_date=service_date,
                counted=counted,
                reason=reason,
            )
        )
        await self._session.flush()
        return counted, reason

    async def campaigns(
        self, *, statuses: tuple[str, ...] = ()
    ) -> tuple[CampaignView, ...]:
        statement = select(SponsorshipCampaign).where(
            SponsorshipCampaign.organization_id == self._actor.organization_id
        )
        if statuses:
            statement = statement.where(SponsorshipCampaign.status.in_(statuses))
        rows = await self._session.scalars(
            statement.order_by(SponsorshipCampaign.created_at.desc())
        )
        return tuple(view_of(row) for row in rows)

    async def read(self, campaign_id: uuid.UUID) -> SponsorshipCampaign:
        row = await self._session.get(SponsorshipCampaign, campaign_id)
        if row is None:
            raise NotFound("No encontramos esa campaña de patrocinio.")
        self._actor.require_same_organization(row.organization_id)
        return row

    async def delivery_days(
        self, campaign_id: uuid.UUID
    ) -> tuple[SponsorshipDeliveryDay, ...]:
        rows = await self._session.scalars(
            select(SponsorshipDeliveryDay)
            .where(SponsorshipDeliveryDay.campaign_id == campaign_id)
            .order_by(SponsorshipDeliveryDay.service_date)
        )
        return tuple(rows)

    async def _locked(self, campaign_id: uuid.UUID) -> SponsorshipCampaign:
        row = await self._session.scalar(
            select(SponsorshipCampaign)
            .where(SponsorshipCampaign.id == campaign_id)
            .with_for_update()
        )
        if row is None:
            raise NotFound("No encontramos esa campaña de patrocinio.")
        self._actor.require_same_organization(row.organization_id)
        return row

    async def _audit(
        self, action: str, row: SponsorshipCampaign, details: dict[str, object]
    ) -> None:
        await record_audit(
            self._session,
            organization_id=self._actor.organization_id,
            actor_type=self._actor.actor_type,
            actor_id=self._actor.label,
            action=action,
            subject_type="SponsorshipCampaign",
            subject_id=str(row.id),
            details=details,
            commit=False,
        )
