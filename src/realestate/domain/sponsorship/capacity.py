"""How much may be sold, and the refusal that keeps it from being oversold.

Capacity has two independent ceilings and confusing them is the classic paid-
placement failure. The *delivery* ceiling is what one rendered page may contain:
one sponsored result per six visible results, two on the homepage. The *sales*
ceiling is how many campaigns may hold the same surface over the same days at
all. A product that respects only the first can sell twenty concurrent campaigns
and deliver each of them a twentieth of what the buyer expected.

So a reservation is a row with a date range, taken under a lock, and refused
when the surface is already full for any day in the window. Issuing a quote takes
no reservation: ADR-0043 lets a quote expire after seven days, and an unaccepted
offer that made the surface look sold out would let a stalled negotiation block
a real sale.

The forecast is honest about not knowing. Until the pilot has measured traffic,
``forecast`` reports the sellable slots it can guarantee and says that the
expected exposure per slot is an initial estimate without sufficient history.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    AnalyticsDomainEvent,
    AnalyticsEventName,
    SponsoredSurface,
    SponsorshipCampaign,
    SponsorshipCapacityReservation,
    SponsorshipSurfaceCapacity,
    TrafficClass,
)
from realestate.domain.commercial.actors import Actor, CommercialError
from realestate.domain.sponsorship.labels import INSUFFICIENT_HISTORY
from realestate.domain.sponsorship.pricing import PACKAGE_SURFACES

#: The concurrent campaigns per surface Product assumes until an Administrator
#: sets a number. Deliberately small: with one sponsored slot per six results,
#: two concurrent campaigns already share every position, and a larger default
#: would dilute delivery before anybody chose to.
DEFAULT_CONCURRENT_CAMPAIGNS = 2


class CapacityUnavailable(CommercialError):
    """The requested surface and window are already fully reserved."""

    message = (
        "No hay capacidad disponible para esa superficie en el periodo "
        "solicitado."
    )


@dataclass(frozen=True)
class SurfaceForecast:
    """What one surface can carry over one window."""

    surface: str
    concurrent_campaigns: int
    reserved: int
    available: int
    #: Measured visible impressions per day over the reference period, or
    #: ``None`` when the pilot has not produced enough history.
    measured_daily_visible: int | None

    @property
    def exposure_note(self) -> str:
        if self.measured_daily_visible is None:
            return INSUFFICIENT_HISTORY
        return (
            f"{self.measured_daily_visible} impresiones visibles diarias medidas "
            "en el periodo de referencia"
        )


class SponsorshipCapacity:
    """Forecast, reserve and release sponsored surface capacity."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor

    async def limit(self, surface: str) -> int:
        row = await self._session.scalar(
            select(SponsorshipSurfaceCapacity).where(
                SponsorshipSurfaceCapacity.organization_id
                == self._actor.organization_id,
                SponsorshipSurfaceCapacity.surface == surface,
            )
        )
        return (
            row.concurrent_campaigns
            if row is not None
            else DEFAULT_CONCURRENT_CAMPAIGNS
        )

    async def set_limit(self, surface: str, concurrent: int, *, at: datetime) -> None:
        self._actor.require_administrator()
        if surface not in {item.value for item in SponsoredSurface}:
            raise ValueError("La superficie patrocinada no es válida.")
        if concurrent < 0:
            raise ValueError("La capacidad no puede ser negativa.")
        row = await self._session.scalar(
            select(SponsorshipSurfaceCapacity)
            .where(
                SponsorshipSurfaceCapacity.organization_id
                == self._actor.organization_id,
                SponsorshipSurfaceCapacity.surface == surface,
            )
            .with_for_update()
        )
        if row is None:
            self._session.add(
                SponsorshipSurfaceCapacity(
                    organization_id=self._actor.organization_id,
                    surface=surface,
                    concurrent_campaigns=concurrent,
                    updated_at=at,
                )
            )
        else:
            row.concurrent_campaigns = concurrent
            row.updated_at = at
        await self._session.flush()

    async def peak_reserved(
        self, surface: str, starts_on: datetime, ends_on: datetime
    ) -> int:
        """The largest number of overlapping reservations inside the window.

        The peak, not the total: two consecutive fifteen-day campaigns do not
        compete, and counting them as two would refuse a sale the surface can
        actually deliver.
        """
        rows = list(
            await self._session.scalars(
                select(SponsorshipCapacityReservation).where(
                    SponsorshipCapacityReservation.organization_id
                    == self._actor.organization_id,
                    SponsorshipCapacityReservation.surface == surface,
                    SponsorshipCapacityReservation.released_at.is_(None),
                    SponsorshipCapacityReservation.starts_on < ends_on,
                    SponsorshipCapacityReservation.ends_on > starts_on,
                )
            )
        )
        if not rows:
            return 0
        # Sweep the boundaries. Every overlap change happens at a start or an
        # end, so checking those instants is exact without walking each day.
        boundaries = sorted(
            {max(row.starts_on, starts_on) for row in rows}
            | {starts_on}
        )
        peak = 0
        for moment in boundaries:
            concurrent = sum(
                1 for row in rows if row.starts_on <= moment < row.ends_on
            )
            peak = max(peak, concurrent)
        return peak

    async def forecast(
        self, surface: str, starts_on: datetime, ends_on: datetime
    ) -> SurfaceForecast:
        limit = await self.limit(surface)
        reserved = await self.peak_reserved(surface, starts_on, ends_on)
        return SurfaceForecast(
            surface=surface,
            concurrent_campaigns=limit,
            reserved=reserved,
            available=max(0, limit - reserved),
            measured_daily_visible=await self._measured_daily_visible(surface),
        )

    async def reserve(
        self,
        campaign: SponsorshipCampaign,
        *,
        starts_on: datetime,
        days: int,
        at: datetime,
    ) -> tuple[SurfaceForecast, ...]:
        """Hold every surface the package delivers on, or refuse the whole set.

        All or nothing. A ``Both`` campaign that reserved search and failed on
        the homepage would be a campaign the buyer paid for and Product cannot
        deliver, so the refusal is raised before any row is added.
        """
        ends_on = starts_on + timedelta(days=days)
        surfaces = PACKAGE_SURFACES[campaign.package]
        forecasts: list[SurfaceForecast] = []
        for surface in surfaces:
            # Locked per surface: two concurrent reservations reading the same
            # free slot is exactly how a surface gets oversold.
            await self._lock(surface)
            forecast = await self.forecast(surface, starts_on, ends_on)
            if forecast.available <= 0:
                raise CapacityUnavailable(
                    f"La superficie «{surface}» ya está reservada por completo "
                    "en ese periodo."
                )
            forecasts.append(forecast)
        for surface in surfaces:
            existing = await self._session.scalar(
                select(SponsorshipCapacityReservation).where(
                    SponsorshipCapacityReservation.campaign_id == campaign.id,
                    SponsorshipCapacityReservation.surface == surface,
                )
            )
            if existing is not None:
                existing.starts_on = starts_on
                existing.ends_on = ends_on
                existing.released_at = None
                continue
            self._session.add(
                SponsorshipCapacityReservation(
                    organization_id=self._actor.organization_id,
                    campaign_id=campaign.id,
                    surface=surface,
                    starts_on=starts_on,
                    ends_on=ends_on,
                    created_at=at,
                )
            )
        await self._session.flush()
        return tuple(forecasts)

    async def release(self, campaign_id: uuid.UUID, *, at: datetime) -> int:
        rows = list(
            await self._session.scalars(
                select(SponsorshipCapacityReservation).where(
                    SponsorshipCapacityReservation.campaign_id == campaign_id,
                    SponsorshipCapacityReservation.released_at.is_(None),
                )
            )
        )
        for row in rows:
            row.released_at = at
        await self._session.flush()
        return len(rows)

    async def _lock(self, surface: str) -> None:
        """Serialise reservations for one surface.

        Locks the capacity row, creating it at the default if an Administrator
        never set one — otherwise the first reservation on a surface has nothing
        to lock and two of them can both see it free.
        """
        row = await self._session.scalar(
            select(SponsorshipSurfaceCapacity)
            .where(
                SponsorshipSurfaceCapacity.organization_id
                == self._actor.organization_id,
                SponsorshipSurfaceCapacity.surface == surface,
            )
            .with_for_update()
        )
        if row is None:
            self._session.add(
                SponsorshipSurfaceCapacity(
                    organization_id=self._actor.organization_id,
                    surface=surface,
                    concurrent_campaigns=DEFAULT_CONCURRENT_CAMPAIGNS,
                )
            )
            await self._session.flush()

    async def _measured_daily_visible(self, surface: str) -> int | None:
        """Measured daily Visible Impressions, or ``None`` without history.

        Fewer than seven measured days is ``None`` rather than a small average:
        a forecast built on two days of traffic is a number with a false
        precision, and ADR-0043 would rather say it has no history yet.
        """
        # ``cast(... AS date)`` rather than ``date_trunc('day', ...)``: the latter
        # takes its unit as a bind parameter, which PostgreSQL will not match
        # between the select list and the GROUP BY, and the query fails outright.
        day = cast(AnalyticsDomainEvent.occurred_at, Date)
        rows = await self._session.execute(
            select(day, func.count(AnalyticsDomainEvent.id))
            .where(
                AnalyticsDomainEvent.organization_id == self._actor.organization_id,
                AnalyticsDomainEvent.surface == surface,
                AnalyticsDomainEvent.event_name
                == AnalyticsEventName.SPONSORED_VISIBLE_IMPRESSION.value,
                AnalyticsDomainEvent.traffic_class == TrafficClass.VALID.value,
            )
            .group_by(day)
        )
        counted = [count for _, count in rows]
        if len(counted) < 7:
            return None
        return int(sum(counted) // len(counted))
