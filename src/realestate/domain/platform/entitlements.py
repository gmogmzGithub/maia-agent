"""What an Organization is entitled to do, and the refusal when it is not.

Two things this module deliberately is *not*.

It is not billing. Nothing here has a price, produces an invoice or moves money.
The commercial shape PROJECT_MEMORY describes — a base organization fee, tiers by
Advisor count, paid onboarding, optional integration add-ons — exists here as
*structure* only, because the structure is what the product has to enforce and the
prices are a decision nobody has taken. Building charging on top of this would be
a separate, explicitly authorised piece of work (ADR-0053).

It is not a feature-flag system. A flag answers "is this code path on"; an
entitlement answers "did this customer buy this, and can I show them why they
were refused". That is why every row carries a source, a note and an author, why
history is append-only, and why the refusal is a sentence rather than a boolean.

The evaluation is deliberately strict in one direction. An Organization with **no
recorded entitlement** for a capability is refused, not permitted. A permissive
default would mean that adding a new capability silently grants it to every
existing customer, and that the difference between "we sold this" and "nobody has
thought about it yet" disappears at exactly the moment somebody asks.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    Capability,
    EntitlementSource,
    EntitlementState,
    OrganizationEntitlement,
    OrganizationMember,
)
from realestate.domain.audit import record_audit
from realestate.domain.clock import utc_now
from realestate.domain.commercial.actors import Actor, CommercialError
from realestate.domain.platform.authority import PlatformOperator, require_reason

logger = logging.getLogger(__name__)

#: The name of the one package Stage 9 has. A second package is a commercial
#: decision, not a code change: this constant and the tier table below are the
#: whole of the packaging model.
MANAGED_BASE = "ManagedBase"

#: Capabilities that carry a ceiling rather than a yes/no. Kept as a set because
#: the alternative — inferring it from whether ``limit_value`` happens to be set
#: — would make a limit somebody forgot to record look like an unlimited one.
BOUNDED = frozenset(
    {
        Capability.ADVISOR_SEATS,
        Capability.MONTHLY_WHATSAPP_CONVERSATIONS,
    }
)


@dataclass(frozen=True)
class Tier:
    """One Advisor-count tier. Seats and the conversation allowance, no price.

    Named after what the Organization is rather than after a price point,
    because the names have to survive the pricing decision that has not been
    taken. ``advisor_seats`` is the ceiling the tier includes; exceeding it is a
    refusal with an upgrade path, not an overage charge.
    """

    name: str
    advisor_seats: int
    monthly_whatsapp_conversations: int
    description: str


#: Ordered smallest first. An Organization's tier is the first one whose seat
#: ceiling covers the Advisors it actually has, which is how "you have outgrown
#: your tier" becomes a reportable fact rather than an argument.
TIERS: tuple[Tier, ...] = (
    Tier(
        name="Fundadora",
        advisor_seats=3,
        monthly_whatsapp_conversations=1_000,
        description="Una operación que empieza: hasta tres asesores.",
    ),
    Tier(
        name="Equipo",
        advisor_seats=10,
        monthly_whatsapp_conversations=5_000,
        description="Un equipo establecido: hasta diez asesores.",
    ),
    Tier(
        name="Operación",
        advisor_seats=25,
        monthly_whatsapp_conversations=15_000,
        description="Una operación amplia: hasta veinticinco asesores.",
    ),
)

#: What the base package includes for every managed Organization. The two bounded
#: capabilities take their ceilings from the tier, so they are absent here.
BASE_PACKAGE: tuple[Capability, ...] = (
    Capability.COMMERCIAL_CRM,
    Capability.AUTHORIZED_CATALOG,
    Capability.LISTING_MEDIA,
    Capability.PUBLIC_SITE,
    Capability.WEBSITE_CONVERSATION,
    Capability.WHATSAPP_CHANNEL,
    Capability.CALENDAR_SCHEDULING,
    Capability.BUSINESS_INTELLIGENCE,
)

#: Sold separately. Each one is an integration or a commercial surface that costs
#: the platform real work to operate for a customer, which is the whole reason it
#: is not in the base package.
ADD_ONS: tuple[Capability, ...] = (
    Capability.EXTERNAL_INVENTORY,
    Capability.REACTIVATION_CAMPAIGNS,
    Capability.DEVELOPMENT_CAMPAIGNS,
    Capability.SPONSORED_PLACEMENT,
)

CAPABILITY_LABELS: dict[Capability, str] = {
    Capability.COMMERCIAL_CRM: "CRM comercial y seguimiento",
    Capability.ADVISOR_SEATS: "Lugares de asesor",
    Capability.AUTHORIZED_CATALOG: "Catálogo autorizado",
    Capability.LISTING_MEDIA: "Fotografía y medios de propiedades",
    Capability.PUBLIC_SITE: "Sitio público",
    Capability.WEBSITE_CONVERSATION: "Conversación en el sitio",
    Capability.WHATSAPP_CHANNEL: "Canal de WhatsApp",
    Capability.CALENDAR_SCHEDULING: "Agenda y citas",
    Capability.EXTERNAL_INVENTORY: "Inventario de colaboradores",
    Capability.REACTIVATION_CAMPAIGNS: "Reactivación por inventario nuevo",
    Capability.DEVELOPMENT_CAMPAIGNS: "Campañas de desarrollos",
    Capability.SPONSORED_PLACEMENT: "Posiciones patrocinadas",
    Capability.BUSINESS_INTELLIGENCE: "Tablero de resultados",
    Capability.MONTHLY_WHATSAPP_CONVERSATIONS: "Conversaciones de WhatsApp por mes",
}


class NotEntitled(CommercialError):
    """The Organization has not bought — or has lost — this capability.

    Carries the capability and the reason so the surface that refused can say
    which one and why, instead of the caller having to guess from a boolean.
    """

    message = "Esta organización no tiene habilitada esta capacidad."

    def __init__(self, capability: Capability, reason: str, detail: str) -> None:
        self.capability = capability
        self.reason = reason
        super().__init__(detail)


@dataclass(frozen=True)
class Entitlement:
    """One current entitlement, as evaluation returns it."""

    capability: Capability
    permitted: bool
    #: A stable machine-readable code for why. ``Entitled`` when permitted.
    reason: str
    #: Mexican Spanish, operator-facing.
    detail: str
    limit: int | None = None
    used: int | None = None
    source: EntitlementSource | None = None
    tier: str | None = None

    @property
    def remaining(self) -> int | None:
        """How much headroom is left, or ``None`` for an unbounded capability."""
        if self.limit is None or self.used is None:
            return None
        return max(self.limit - self.used, 0)


@dataclass(frozen=True)
class GrantEntitlement:
    """Enable, disable or re-limit one capability for one Organization."""

    organization_id: uuid.UUID
    capability: Capability
    state: EntitlementState
    reason: str
    limit_value: int | None = None
    source: EntitlementSource = EntitlementSource.ADD_ON
    package: str | None = None
    tier: str | None = None


def tier_for(advisors: int) -> Tier:
    """The smallest tier whose seats cover *advisors*.

    An Organization past the largest tier gets the largest one rather than an
    exception: the operation has already grown, and refusing to *name* its tier
    would not undo that. The seat check below is what refuses the next Advisor.
    """
    for tier in TIERS:
        if advisors <= tier.advisor_seats:
            return tier
    return TIERS[-1]


class Entitlements:
    """What one Organization may do. One question, one answer, one reason.

    Hides: the append-only history, the current-row partial index, which
    capabilities are bounded, how a ceiling is compared against real usage, and
    the tier table.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def evaluate(
        self,
        organization_id: uuid.UUID,
        capability: Capability,
        *,
        at: datetime | None = None,
    ) -> Entitlement:
        """Whether this Organization may use this capability, and why.

        Never raises for an ordinary "no". A caller that wants the refusal to
        stop the work calls :meth:`require` instead, which is the same evaluation
        with an exception on the end — so a surface cannot accidentally treat the
        absence of an entitlement as permission by forgetting to check a boolean.
        """
        moment = at or utc_now()
        row = await self._current(organization_id, capability)
        if row is None:
            return Entitlement(
                capability=capability,
                permitted=False,
                reason="NotRecorded",
                detail=(
                    f"«{CAPABILITY_LABELS.get(capability, capability.value)}» no "
                    "está incluida en el paquete de esta organización."
                ),
            )
        if row.state != EntitlementState.ENABLED.value:
            return Entitlement(
                capability=capability,
                permitted=False,
                reason="Disabled",
                detail=(
                    f"«{CAPABILITY_LABELS.get(capability, capability.value)}» "
                    "está deshabilitada para esta organización."
                ),
                limit=row.limit_value,
                source=EntitlementSource(row.source),
                tier=row.tier,
            )
        if capability not in BOUNDED or row.limit_value is None:
            return Entitlement(
                capability=capability,
                permitted=True,
                reason="Entitled",
                detail="Incluida en el paquete de esta organización.",
                limit=row.limit_value,
                source=EntitlementSource(row.source),
                tier=row.tier,
            )

        used = await self._usage(organization_id, capability, at=moment)
        within = used < row.limit_value
        return Entitlement(
            capability=capability,
            permitted=within,
            reason="Entitled" if within else "LimitReached",
            detail=(
                "Incluida en el paquete de esta organización."
                if within
                else (
                    f"Se alcanzó el límite de "
                    f"«{CAPABILITY_LABELS.get(capability, capability.value)}» "
                    f"({used} de {row.limit_value}). Amplía el plan para "
                    "continuar."
                )
            ),
            limit=row.limit_value,
            used=used,
            source=EntitlementSource(row.source),
            tier=row.tier,
        )

    async def require(
        self,
        actor: Actor,
        capability: Capability,
        *,
        at: datetime | None = None,
    ) -> Entitlement:
        """The entitlement, or a refusal that stops the caller.

        Takes an ``Actor`` so the Organization is the caller's own by
        construction. Every surface that *acts* uses this; the read-only
        entitlement panel uses :meth:`evaluate`.
        """
        decision = await self.evaluate(actor.organization_id, capability, at=at)
        if not decision.permitted:
            logger.info(
                "Refused %s for Organization %s: %s",
                capability.value,
                actor.organization_id,
                decision.reason,
            )
            raise NotEntitled(capability, decision.reason, decision.detail)
        return decision

    async def grant(
        self,
        operator: PlatformOperator,
        command: GrantEntitlement,
        *,
        at: datetime | None = None,
    ) -> OrganizationEntitlement:
        """Record a new current entitlement, superseding the old one.

        Append-only. The outgoing row is stamped ``superseded_at`` and kept,
        because an entitlement change lands while the operation is running: a
        campaign refused at 14:00 and permitted at 14:05 has to be explainable
        at both times, and an edited row cannot do that.

        Recording an identical entitlement is a no-op, so a restarted
        provisioning run does not fill the history with duplicates.
        """
        reason = require_reason(command.reason)
        moment = at or utc_now()
        if command.limit_value is not None and command.capability not in BOUNDED:
            raise NotEntitled(
                command.capability,
                "NotBounded",
                f"«{CAPABILITY_LABELS.get(command.capability, command.capability.value)}»"
                " no admite un límite numérico.",
            )

        current = await self._current(command.organization_id, command.capability)
        if current is not None and (
            current.state,
            current.limit_value,
            current.source,
            current.tier,
        ) == (
            command.state.value,
            command.limit_value,
            command.source.value,
            command.tier,
        ):
            return current

        if current is not None:
            current.superseded_at = moment
            await self._session.flush()

        row = OrganizationEntitlement(
            organization_id=command.organization_id,
            capability=command.capability.value,
            state=command.state.value,
            limit_value=command.limit_value,
            source=command.source.value,
            package=command.package,
            tier=command.tier,
            note=reason,
            recorded_by=operator.label,
            recorded_at=moment,
        )
        self._session.add(row)
        await self._session.flush()

        await record_audit(
            self._session,
            organization_id=command.organization_id,
            actor_type=operator.actor_type,
            actor_id=operator.label,
            action="GrantOrganizationEntitlement",
            subject_type="Organization",
            subject_id=str(command.organization_id),
            details={
                "capability": command.capability.value,
                "state": command.state.value,
                "limit": command.limit_value,
                "source": command.source.value,
                "tier": command.tier,
                "previous_state": current.state if current is not None else None,
                "previous_limit": (
                    current.limit_value if current is not None else None
                ),
                "reason": reason,
            },
            commit=False,
        )
        return row

    async def apply_package(
        self,
        operator: PlatformOperator,
        organization_id: uuid.UUID,
        *,
        tier: Tier,
        add_ons: tuple[Capability, ...] = (),
        reason: str,
        at: datetime | None = None,
    ) -> list[OrganizationEntitlement]:
        """Give an Organization the base package, one tier and named add-ons.

        The whole package is recorded explicitly rather than derived at read
        time. An entitlement that exists only as an ``if`` in this module cannot
        be reported to a customer, cannot be dated, and cannot be turned off for
        one Organization without a code change.

        Add-ons not named are recorded ``Disabled`` rather than omitted, so
        "we did not sell this" and "nobody has decided" stay different answers.
        """
        written: list[OrganizationEntitlement] = []
        for capability in BASE_PACKAGE:
            written.append(
                await self.grant(
                    operator,
                    GrantEntitlement(
                        organization_id=organization_id,
                        capability=capability,
                        state=EntitlementState.ENABLED,
                        reason=reason,
                        source=EntitlementSource.PACKAGE,
                        package=MANAGED_BASE,
                    ),
                    at=at,
                )
            )
        for capability, limit in (
            (Capability.ADVISOR_SEATS, tier.advisor_seats),
            (
                Capability.MONTHLY_WHATSAPP_CONVERSATIONS,
                tier.monthly_whatsapp_conversations,
            ),
        ):
            written.append(
                await self.grant(
                    operator,
                    GrantEntitlement(
                        organization_id=organization_id,
                        capability=capability,
                        state=EntitlementState.ENABLED,
                        reason=reason,
                        limit_value=limit,
                        source=EntitlementSource.TIER,
                        package=MANAGED_BASE,
                        tier=tier.name,
                    ),
                    at=at,
                )
            )
        for capability in ADD_ONS:
            written.append(
                await self.grant(
                    operator,
                    GrantEntitlement(
                        organization_id=organization_id,
                        capability=capability,
                        state=(
                            EntitlementState.ENABLED
                            if capability in add_ons
                            else EntitlementState.DISABLED
                        ),
                        reason=reason,
                        source=EntitlementSource.ADD_ON,
                        package=MANAGED_BASE,
                    ),
                    at=at,
                )
            )
        return written

    async def summary(
        self, organization_id: uuid.UUID, *, at: datetime | None = None
    ) -> list[Entitlement]:
        """Every capability's current standing, in declaration order.

        Every capability, not just the recorded ones: a customer asking what they
        have is entitled to see what they do not have, and a report that only
        lists grants cannot answer that.
        """
        moment = at or utc_now()
        return [
            await self.evaluate(organization_id, capability, at=moment)
            for capability in Capability
        ]

    async def history(
        self, organization_id: uuid.UUID, capability: Capability | None = None
    ) -> list[OrganizationEntitlement]:
        """Every entitlement row ever recorded, newest first."""
        query = select(OrganizationEntitlement).where(
            OrganizationEntitlement.organization_id == organization_id
        )
        if capability is not None:
            query = query.where(
                OrganizationEntitlement.capability == capability.value
            )
        rows = await self._session.scalars(
            query.order_by(OrganizationEntitlement.recorded_at.desc())
        )
        return list(rows)

    async def _current(
        self, organization_id: uuid.UUID, capability: Capability
    ) -> OrganizationEntitlement | None:
        found: OrganizationEntitlement | None = await self._session.scalar(
            select(OrganizationEntitlement)
            .where(OrganizationEntitlement.organization_id == organization_id)
            .where(OrganizationEntitlement.capability == capability.value)
            .where(OrganizationEntitlement.superseded_at.is_(None))
        )
        return found

    async def _usage(
        self, organization_id: uuid.UUID, capability: Capability, *, at: datetime
    ) -> int:
        """What the ceiling is compared against, measured now rather than stored.

        Advisor seats are counted from the member table, which is the only
        authority on how many Advisors exist. The conversation allowance reads
        the usage projection, because counting Conversations for a month on
        every check would put a scan in front of every outbound message.
        """
        if capability is Capability.ADVISOR_SEATS:
            counted = await self._session.scalar(
                select(func.count(OrganizationMember.id))
                .where(OrganizationMember.organization_id == organization_id)
                .where(OrganizationMember.active.is_(True))
                .where(OrganizationMember.advises.is_(True))
            )
            return int(counted or 0)
        if capability is Capability.MONTHLY_WHATSAPP_CONVERSATIONS:
            from realestate.domain.platform.usage import monthly_quantity
            from realestate.db.models import UsageMetric

            return await monthly_quantity(
                self._session,
                organization_id,
                UsageMetric.WHATSAPP_CONVERSATIONS,
                at=at,
            )
        return 0
