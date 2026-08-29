"""The buyer's read-only door: an expiring link, a revocation, and a PDF.

A sponsorship buyer does not get a CRM account (ADR-0044). What they get is a
link, and that link is the whole authorization: no password, no session, no
navigation into anything else. Which means the link itself has to carry the
protections an account would have provided.

* **Opaque and long.** 32 random bytes, generated with :mod:`secrets`.
* **Digest at rest.** Only ``sha256`` of the token is stored, for the same reason
  a password is not stored: an operator reading the table must not be able to
  open somebody's report.
* **Expiring and revocable.** Both, independently. Expiry is the default
  protection; revocation is the one an Administrator reaches for when a
  negotiation ends badly.
* **Read-only by construction.** The only thing a token resolves to is a report
  scoped to one campaign at the ``Buyer`` audience. There is no route from a
  token to a mutation, and no route from a token to a second campaign.

The PDF presentation lives here too. Both the structured shared page and the PDF
are derived from the same buyer-scoped ``SponsorshipReport``; neither renderer
can reach CRM records or an Administrator-only report.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    ReportAudience,
    SponsorshipCampaign,
    SponsorshipReportLink,
)
from realestate.domain.audit import record_audit
from realestate.domain.commercial.actors import Actor, CommercialError, NotFound
from realestate.domain.sponsorship.labels import (
    NON_CAUSAL_DISCLAIMER,
    SPONSORED_DISCLOSURE,
    SPONSORED_LABEL,
)
from realestate.domain.sponsorship.pdf import Line, Style, render
from realestate.domain.sponsorship.reporting import (
    SponsorshipReport,
    SponsorshipReporting,
)

#: How long a share lasts unless the Administrator asks for less.
DEFAULT_SHARE_DAYS = 14

#: The longest share Product will mint. A link with no practical end is an
#: account with extra steps.
MAX_SHARE_DAYS = 60

#: Bytes of entropy in the token. 32 bytes is 256 bits; the token is the only
#: credential, so it is sized like one.
TOKEN_BYTES = 32


class ShareUnavailable(CommercialError):
    """The link does not resolve to a live share."""

    message = "Este enlace de reporte ya no está disponible."


def digest_of(token: str) -> str:
    """The stored form of one share token."""
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MintedShare:
    """The one moment the raw token exists outside the browser that gets it."""

    link_id: uuid.UUID
    token: str
    campaign_id: uuid.UUID
    expires_at: datetime
    path: str


@dataclass(frozen=True)
class ShareStatus:
    link_id: uuid.UUID
    campaign_id: uuid.UUID
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    last_viewed_at: datetime | None
    views: int

    def live(self, at: datetime) -> bool:
        return self.revoked_at is None and at < self.expires_at


class SponsorshipSharing:
    """Mint, revoke and resolve buyer report links."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor

    async def share(
        self,
        campaign_id: uuid.UUID,
        *,
        at: datetime,
        days: int = DEFAULT_SHARE_DAYS,
        definition_version: str | None = None,
    ) -> MintedShare:
        self._actor.require_administrator()
        if not 0 < days <= MAX_SHARE_DAYS:
            raise ValueError(
                f"La vigencia del enlace debe estar entre 1 y {MAX_SHARE_DAYS} días."
            )
        campaign = await self._session.get(SponsorshipCampaign, campaign_id)
        if campaign is None:
            raise NotFound("No encontramos esa campaña de patrocinio.")
        self._actor.require_same_organization(campaign.organization_id)
        token = secrets.token_urlsafe(TOKEN_BYTES)
        row = SponsorshipReportLink(
            organization_id=campaign.organization_id,
            campaign_id=campaign.id,
            token_digest=digest_of(token),
            definition_version=definition_version or "",
            created_by=self._actor.member_id,
            created_at=at,
            expires_at=at + timedelta(days=days),
        )
        self._session.add(row)
        await self._session.flush()
        await record_audit(
            self._session,
            organization_id=self._actor.organization_id,
            actor_type=self._actor.actor_type,
            actor_id=self._actor.label,
            action="ShareSponsorshipReport",
            subject_type="SponsorshipCampaign",
            subject_id=str(campaign.id),
            details={"expires_at": row.expires_at.isoformat(), "days": days},
            commit=False,
        )
        return MintedShare(
            link_id=row.id,
            token=token,
            campaign_id=campaign.id,
            expires_at=row.expires_at,
            path=f"/reportes/{token}",
        )

    async def revoke(self, link_id: uuid.UUID, *, at: datetime) -> ShareStatus:
        self._actor.require_administrator()
        row = await self._session.scalar(
            select(SponsorshipReportLink)
            .where(SponsorshipReportLink.id == link_id)
            .with_for_update()
        )
        if row is None:
            raise NotFound("No encontramos ese enlace de reporte.")
        self._actor.require_same_organization(row.organization_id)
        if row.revoked_at is None:
            row.revoked_at = at
            await self._session.flush()
            await record_audit(
                self._session,
                organization_id=self._actor.organization_id,
                actor_type=self._actor.actor_type,
                actor_id=self._actor.label,
                action="RevokeSponsorshipReportLink",
                subject_type="SponsorshipCampaign",
                subject_id=str(row.campaign_id),
                details={"link_id": str(row.id)},
                commit=False,
            )
        return _status(row)

    async def shares(self, campaign_id: uuid.UUID) -> tuple[ShareStatus, ...]:
        rows = await self._session.scalars(
            select(SponsorshipReportLink)
            .where(SponsorshipReportLink.campaign_id == campaign_id)
            .order_by(SponsorshipReportLink.created_at.desc())
        )
        return tuple(_status(row) for row in rows)

    async def resolve(self, token: str, *, at: datetime) -> SponsorshipReport:
        """The buyer report behind one token, or a refusal.

        Expiry and revocation give the *same* refusal on purpose. Telling a
        holder that a link existed and was withdrawn discloses a commercial
        relationship to whoever now has the URL.
        """
        row = await self._session.scalar(
            select(SponsorshipReportLink)
            .where(SponsorshipReportLink.token_digest == digest_of(token))
            .with_for_update()
        )
        if row is None or row.revoked_at is not None or at >= row.expires_at:
            raise ShareUnavailable()
        row.views += 1
        row.last_viewed_at = at
        await self._session.flush()
        return await SponsorshipReporting(self._session, self._actor).generate(
            row.campaign_id,
            ReportAudience.BUYER,
            at=at,
            definition_version=row.definition_version or None,
        )


def _status(row: SponsorshipReportLink) -> ShareStatus:
    return ShareStatus(
        link_id=row.id,
        campaign_id=row.campaign_id,
        created_at=row.created_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        last_viewed_at=row.last_viewed_at,
        views=row.views,
    )


def _shown_count(value: int | None) -> str:
    return "Muestra protegida" if value is None else str(value)


def report_lines(report: SponsorshipReport) -> list[Line]:
    """One buyer-scoped report as the PDF's ordered presentation lines.

    The label comes first and the disclaimer last, so a buyer reading only the
    top knows the visibility was paid for and a buyer reading to the bottom has
    seen the non-causal statement. Nothing in this function can emit a Contact,
    a phone number or a message: it reads only aggregate fields off the report,
    and the buyer report has no others.
    """
    steps = {row.step: row for row in report.funnel}

    def count(step: str) -> str:
        value = steps[step].count
        return str(value) if value is not None else "Muestra protegida"

    interest_values = [
        steps[name].count
        for name in ("SavedOrShared", "MaiaStarted", "WhatsAppHandoff")
    ]
    interest = (
        "Muestra protegida"
        if any(value is None for value in interest_values)
        else str(sum(value or 0 for value in interest_values))
    )
    lines: list[Line] = [
        Line(f"Reporte de campaña {SPONSORED_LABEL}", Style.TITLE),
        Line(report.listing_title, Style.HEADING),
        Line(
            f"Periodo: {report.period_start:%d/%m/%Y} a "
            f"{report.period_end:%d/%m/%Y}"
        ),
        Line(f"Superficies: {', '.join(report.surfaces) or 'Sin superficies'}"),
        Line(""),
        Line("Resumen del periodo", Style.HEADING),
        Line(f"Impresiones visibles | {count('SponsoredVisibleImpression')}", Style.METRIC),
        Line(f"Aperturas de publicación | {count('ListingOpened')}", Style.METRIC),
        Line(f"Acciones de interés | {interest}", Style.METRIC),
        Line(f"Solicitudes de cita | {count('AppointmentRequested')}", Style.METRIC),
        Line(""),
        Line("Estado de la campaña", Style.HEADING),
        Line(f"Estado: {report.campaign.status_label}"),
        Line(
            f"Días pagados: {report.campaign.paid_days} | entregados: "
            f"{report.campaign.delivered_days} | restantes: "
            f"{report.campaign.remaining_days}"
        ),
        Line(""),
        Line("Embudo completo", Style.HEADING),
    ]
    for row in report.funnel:
        funnel_count = row.count if row.count is not None else "Muestra protegida"
        lines.append(
            Line(
                f"{row.label}: {funnel_count} "
                f"(paso anterior {row.from_previous.text})"
            )
        )
    lines.extend(
        [
            Line(""),
            Line("Tendencia", Style.HEADING),
            *(
                [
                    Line(
                        f"{point.period_start:%d/%m}: "
                        f"visibles {_shown_count(point.visible_impressions)} | "
                        f"aperturas {_shown_count(point.listing_opens)} | "
                        f"interés {_shown_count(point.interest_actions)}"
                    )
                    for point in report.trend
                ]
                or [Line("Sin actividad registrada en el periodo.")]
            ),
            Line(""),
            Line("Resultados conocidos", Style.HEADING),
            *[
                Line(f"{name}: {count if count is not None else 'Muestra protegida'}")
                for name, count in sorted(report.outcomes.items())
            ],
            Line(f"Completitud de resultados: {report.unrecorded_outcomes.text}"),
            Line(""),
            Line("Economía unitaria", Style.HEADING),
            Line(
                "Precio: "
                + (
                    f"{report.economics.price} {report.economics.currency}"
                    if report.economics.price is not None
                    else "Sin registrar"
                )
            ),
            Line(
                "Costo por impresión visible: "
                f"{report.economics.cost_per_visible_impression.text}"
            ),
            Line(
                "Costo por apertura de publicación: "
                f"{report.economics.cost_per_listing_open.text}"
            ),
            Line(
                "Costo por solicitud de cita: "
                f"{report.economics.cost_per_appointment_request.text}"
            ),
            Line(""),
            Line("Comparables", Style.HEADING),
        ]
    )
    for comparable in report.comparables:
        lines.append(Line(comparable.key.text))
        lines.append(Line(f"  {comparable.text}"))
    lines.extend(
        [
            Line(""),
            Line("Atribución", Style.HEADING),
            Line(
                f"Resultados hasta {report.attribution.view_through_days} días "
                f"después de una exposición: "
                f"{report.attribution.view_through_outcomes if report.attribution.view_through_outcomes is not None else 'Muestra protegida'}"
            ),
            Line(
                f"Resultados hasta {report.attribution.engaged_days} días después "
                "de una interacción: "
                f"{report.attribution.engaged_outcomes if report.attribution.engaged_outcomes is not None else 'Muestra protegida'}"
            ),
        ]
    )
    if report.notes:
        lines.append(Line(""))
        lines.append(Line("Observaciones", Style.HEADING))
        lines.extend(Line(note) for note in report.notes)
    lines.extend(
        [
            Line(""),
            Line("Definiciones", Style.HEADING),
            *[Line(definition) for definition in report.definitions],
            Line(f"Versión aplicada: {report.definition_version}"),
            Line(""),
            Line(SPONSORED_DISCLOSURE),
            Line(NON_CAUSAL_DISCLAIMER, Style.NOTE),
        ]
    )
    return lines


def report_pdf(report: SponsorshipReport) -> bytes:
    """The buyer report as a PDF, built only from buyer-scoped fields."""
    return render(report_lines(report))
