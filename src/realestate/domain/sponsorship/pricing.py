"""The versioned price catalog, and the reason it can start empty.

ADR-0043 and SAN-062 say the same thing from two directions: do not set the
first price before the pilot has measured traffic. The obvious way to honour
that is to leave prices out of the code — but then somebody types a number into
a form on day one and it becomes the price by accident.

So the catalog is explicit and refuses to publish without evidence. A Draft
version holds proposed numbers; publishing requires a written reference to the
pilot data those numbers came from, and the database enforces it too. Until
somebody publishes, :class:`SponsorshipQuoting` refuses to quote and says why.
The product is honest about not knowing rather than quietly inventing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    PriceCatalogStatus,
    SponsorshipPriceCatalog,
    SponsorshipPriceItem,
)
from realestate.domain.audit import record_audit
from realestate.domain.commercial.actors import (
    Actor,
    CommercialError,
    InvalidTransition,
    NotFound,
)

#: The only sellable packages (ADR-0043). ``Both`` is search and homepage
#: together, priced as its own package rather than as a sum: a bundle discount
#: is a commercial decision, not arithmetic.
PACKAGES: tuple[str, ...] = ("Search", "Homepage", "Both")

#: The surfaces one package delivers on.
PACKAGE_SURFACES: dict[str, tuple[str, ...]] = {
    "Search": ("Search",),
    "Homepage": ("Homepage",),
    "Both": ("Search", "Homepage"),
}

#: The MVP sells one duration. Kept as a constant rather than a free field so a
#: 90-day campaign cannot be sold before anybody has decided what it costs.
DEFAULT_DURATION_DAYS = 30


class PricingUnavailable(CommercialError):
    """No published catalog version, so there is no price to quote."""

    message = (
        "Todavía no hay un catálogo de precios publicado. El primer precio "
        "requiere datos de tráfico del piloto."
    )


class PackageUnpriced(CommercialError):
    """The published version does not price the requested package."""

    message = "El catálogo publicado no incluye ese paquete."


@dataclass(frozen=True)
class PriceLine:
    package: str
    duration_days: int
    amount: Decimal


@dataclass(frozen=True)
class DraftCatalog:
    """A proposed catalog version. Draft prices are never quotable."""

    version: str
    currency: str
    lines: tuple[PriceLine, ...]
    command_key: str


@dataclass(frozen=True)
class PublishCatalog:
    """Publishing one version, with the pilot evidence that justifies it."""

    catalog_id: uuid.UUID
    pilot_evidence: str


@dataclass(frozen=True)
class CatalogView:
    catalog_id: uuid.UUID
    version: str
    status: str
    currency: str
    pilot_evidence: str | None
    published_at: datetime | None
    lines: tuple[PriceLine, ...]

    def amount_for(self, package: str, duration_days: int) -> Decimal | None:
        for line in self.lines:
            if line.package == package and line.duration_days == duration_days:
                return line.amount
        return None


class SponsorshipPricing:
    """Draft, publish, retire and read one Organization's price catalog."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor

    async def draft(self, command: DraftCatalog, *, at: datetime) -> CatalogView:
        self._actor.require_administrator()
        version = command.version.strip()
        if not version:
            raise ValueError("La versión del catálogo requiere un nombre.")
        if not command.lines:
            raise ValueError("El catálogo requiere al menos un paquete con precio.")
        for line in command.lines:
            if line.package not in PACKAGES:
                raise ValueError("El paquete no es válido.")
            if line.amount < 0 or line.duration_days <= 0:
                raise ValueError("El precio y la duración deben ser positivos.")
        existing = await self._session.scalar(
            select(SponsorshipPriceCatalog).where(
                SponsorshipPriceCatalog.organization_id == self._actor.organization_id,
                SponsorshipPriceCatalog.version == version,
            )
        )
        if existing is not None:
            # Idempotent by version rather than by command key: a catalog
            # version is itself the identity somebody names in a quote, so a
            # second draft of the same version has to be the same catalog.
            return await self._view(existing)
        row = SponsorshipPriceCatalog(
            organization_id=self._actor.organization_id,
            version=version,
            status=PriceCatalogStatus.DRAFT.value,
            currency=command.currency,
            created_at=at,
        )
        self._session.add(row)
        await self._session.flush()
        for line in command.lines:
            self._session.add(
                SponsorshipPriceItem(
                    catalog_id=row.id,
                    package=line.package,
                    duration_days=line.duration_days,
                    amount=line.amount,
                )
            )
        await self._session.flush()
        await self._audit("DraftSponsorshipPriceCatalog", row, {"version": version})
        return await self._view(row)

    async def publish(self, command: PublishCatalog, *, at: datetime) -> CatalogView:
        """Publish one version, retiring whichever version was published before.

        Exactly one published version at a time. Two would make "the current
        price" ambiguous, and a quote that preserves its version is only
        reproducible if the version it preserved was unambiguous when issued.
        """
        self._actor.require_administrator()
        evidence = command.pilot_evidence.strip()
        if len(evidence) < 8:
            raise PricingUnavailable(
                "Publicar un precio requiere una referencia escrita a los datos "
                "del piloto que lo justifican."
            )
        row = await self._locked(command.catalog_id)
        if row.status == PriceCatalogStatus.RETIRED.value:
            raise InvalidTransition("Un catálogo retirado no puede publicarse.")
        current = await self._session.scalar(
            select(SponsorshipPriceCatalog).where(
                SponsorshipPriceCatalog.organization_id == self._actor.organization_id,
                SponsorshipPriceCatalog.status == PriceCatalogStatus.PUBLISHED.value,
                SponsorshipPriceCatalog.id != row.id,
            )
        )
        if current is not None:
            current.status = PriceCatalogStatus.RETIRED.value
            current.retired_at = at
        row.status = PriceCatalogStatus.PUBLISHED.value
        row.pilot_evidence = evidence
        row.published_by = self._actor.member_id
        row.published_at = at
        await self._session.flush()
        await self._audit(
            "PublishSponsorshipPriceCatalog",
            row,
            {
                "version": row.version,
                "retired_version": current.version if current else None,
            },
        )
        return await self._view(row)

    async def published(self) -> CatalogView:
        """The current quotable catalog, or a refusal explaining there is none."""
        row = await self._session.scalar(
            select(SponsorshipPriceCatalog).where(
                SponsorshipPriceCatalog.organization_id == self._actor.organization_id,
                SponsorshipPriceCatalog.status == PriceCatalogStatus.PUBLISHED.value,
            )
        )
        if row is None:
            raise PricingUnavailable()
        return await self._view(row)

    async def by_id(self, catalog_id: uuid.UUID) -> CatalogView:
        row = await self._session.get(SponsorshipPriceCatalog, catalog_id)
        if row is None:
            raise NotFound("No encontramos ese catálogo de precios.")
        self._actor.require_same_organization(row.organization_id)
        return await self._view(row)

    async def catalogs(self) -> tuple[CatalogView, ...]:
        rows = await self._session.scalars(
            select(SponsorshipPriceCatalog)
            .where(
                SponsorshipPriceCatalog.organization_id == self._actor.organization_id
            )
            .order_by(SponsorshipPriceCatalog.created_at.desc())
        )
        return tuple([await self._view(row) for row in rows])

    async def _view(self, row: SponsorshipPriceCatalog) -> CatalogView:
        items = await self._session.scalars(
            select(SponsorshipPriceItem)
            .where(SponsorshipPriceItem.catalog_id == row.id)
            .order_by(SponsorshipPriceItem.package, SponsorshipPriceItem.duration_days)
        )
        return CatalogView(
            catalog_id=row.id,
            version=row.version,
            status=row.status,
            currency=row.currency,
            pilot_evidence=row.pilot_evidence,
            published_at=row.published_at,
            lines=tuple(
                PriceLine(item.package, item.duration_days, item.amount)
                for item in items
            ),
        )

    async def _locked(self, catalog_id: uuid.UUID) -> SponsorshipPriceCatalog:
        row = await self._session.scalar(
            select(SponsorshipPriceCatalog)
            .where(SponsorshipPriceCatalog.id == catalog_id)
            .with_for_update()
        )
        if row is None:
            raise NotFound("No encontramos ese catálogo de precios.")
        self._actor.require_same_organization(row.organization_id)
        return row

    async def _audit(
        self, action: str, row: SponsorshipPriceCatalog, details: dict[str, object]
    ) -> None:
        await record_audit(
            self._session,
            actor_type=self._actor.actor_type,
            actor_id=self._actor.label,
            action=action,
            subject_type="SponsorshipPriceCatalog",
            subject_id=str(row.id),
            details=details,
            commit=False,
        )
