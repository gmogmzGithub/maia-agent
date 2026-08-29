"""Which Organization an inbound identifier belongs to.

ADR-0019 said the product would eventually need this mapping and named the seam:
:meth:`OrganizationDirectory.organization_id` resolved the Brokerage Organization
by slug because "Meta's webhook knows a phone number, not a brokerage". This
module is the mapping landing on that seam.

The rule it enforces is short and absolute: **an unbound identifier is a refusal,
never a default.** The shortcut a second Organization makes dangerous is not the
slug lookup itself — it is what happens when the lookup fails. Falling back to
"the only Organization" would file one brokerage's customer under another's
Contacts, write to them from the wrong channel, and attribute the Opportunity to
somebody who never spoke to them. That failure is silent, permanent, and
discovered by the customer.

So a webhook for an unbound phone number id is rejected and logged with the
identifier, which is exactly the signal an operator needs: either a provisioning
step was missed or somebody pointed a number at the wrong installation.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    ChannelBindingKind,
    ChannelBindingState,
    Organization,
    OrganizationChannelBinding,
    OrganizationStatus,
)
from realestate.domain.clock import utc_now
from realestate.domain.commercial.actors import CommercialError

logger = logging.getLogger(__name__)


class UnroutableChannel(CommercialError):
    """No Organization claims this identifier, so nothing may be done with it.

    Deliberately not a :class:`~realestate.domain.commercial.actors.NotFound`.
    NotFound is what an operator sees when a record is not theirs; this is an
    installation problem, and conflating them would hide a misdirected channel
    behind a sentence about permissions.
    """

    message = (
        "Ese canal no está asignado a ninguna organización. Revisa la "
        "configuración antes de procesar mensajes de ese número."
    )


class OrganizationNotOperating(CommercialError):
    """The Organization exists but is not accepting work right now.

    A suspended or half-provisioned Organization must not answer a customer.
    Accepting the message and answering it later is not an option either: the
    reply would arrive from a brokerage the customer was told had stopped.
    """

    message = (
        "La organización de ese canal no está operando en este momento; el "
        "mensaje no se procesó."
    )


@dataclass(frozen=True)
class RoutedOrganization:
    """One resolved Organization, with the binding that resolved it."""

    organization_id: uuid.UUID
    slug: str
    display_name: str
    kind: ChannelBindingKind
    external_id: str


class OrganizationRouting:
    """Resolve an external identifier to the Organization that owns it.

    Hides: the binding table, the active-binding partial index, the lifecycle
    check, and the decision that an unbound identifier is refused rather than
    defaulted.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._resolved: dict[tuple[ChannelBindingKind, str], RoutedOrganization] = {}

    async def resolve(
        self, kind: ChannelBindingKind, external_id: str
    ) -> RoutedOrganization:
        """The Organization that owns *external_id*, or a refusal.

        Two refusals, kept apart because they need different remedies: nobody
        claims the identifier, or the claimant is not operating.

        A successful answer is remembered for the life of this instance, which is
        the life of one session: Meta batches many messages and delivery
        callbacks that all arrived on the same phone number id into one webhook
        body, and re-asking the database who owns that number once per item is a
        query per message where one would do. Memoised here rather than in the
        webhook route so every caller gets it, and only for successes — a refusal
        stays loud, logging the identifier each time an operator's misconfigured
        number is used.
        """
        identifier = external_id.strip()
        if not identifier:
            raise UnroutableChannel()
        cached = self._resolved.get((kind, identifier))
        if cached is not None:
            return cached
        row = (
            await self._session.execute(
                select(OrganizationChannelBinding, Organization)
                .join(
                    Organization,
                    Organization.id == OrganizationChannelBinding.organization_id,
                )
                .where(OrganizationChannelBinding.kind == kind.value)
                .where(OrganizationChannelBinding.external_id == identifier)
                .where(
                    OrganizationChannelBinding.state == ChannelBindingState.ACTIVE.value
                )
            )
        ).first()
        if row is None:
            logger.warning(
                "Refused inbound work for an unbound %s %r: no Organization claims it",
                kind.value,
                identifier,
            )
            raise UnroutableChannel()
        binding, organization = row
        if organization.status != OrganizationStatus.ACTIVE.value:
            logger.warning(
                "Refused inbound work for %s %r: Organization %s is %s",
                kind.value,
                identifier,
                organization.slug,
                organization.status,
            )
            raise OrganizationNotOperating()
        routed = RoutedOrganization(
            organization_id=organization.id,
            slug=organization.slug,
            display_name=organization.display_name,
            kind=kind,
            external_id=binding.external_id,
        )
        self._resolved[(kind, identifier)] = routed
        return routed

    async def bindings(
        self, organization_id: uuid.UUID, kind: ChannelBindingKind | None = None
    ) -> list[OrganizationChannelBinding]:
        """One Organization's active bindings, for the operator surface."""
        query = (
            select(OrganizationChannelBinding)
            .where(OrganizationChannelBinding.organization_id == organization_id)
            .where(OrganizationChannelBinding.state == ChannelBindingState.ACTIVE.value)
        )
        if kind is not None:
            query = query.where(OrganizationChannelBinding.kind == kind.value)
        rows = await self._session.scalars(
            query.order_by(
                OrganizationChannelBinding.kind, OrganizationChannelBinding.external_id
            )
        )
        return list(rows)

    async def bind(
        self,
        *,
        organization_id: uuid.UUID,
        kind: ChannelBindingKind,
        external_id: str,
        recorded_by: str,
    ) -> OrganizationChannelBinding:
        """Claim an identifier for one Organization. Idempotent, does not commit.

        A second claim by the *same* Organization returns the existing binding. A
        claim on an identifier another Organization holds is refused here rather
        than left to the unique index, so the message names the conflict instead
        of being a constraint violation.
        """
        identifier = external_id.strip()
        if not identifier:
            raise UnroutableChannel("El identificador del canal no puede estar vacío.")
        held: OrganizationChannelBinding | None = await self._session.scalar(
            select(OrganizationChannelBinding)
            .where(OrganizationChannelBinding.kind == kind.value)
            .where(OrganizationChannelBinding.external_id == identifier)
            .where(OrganizationChannelBinding.state == ChannelBindingState.ACTIVE.value)
        )
        if held is not None:
            if held.organization_id == organization_id:
                return held
            raise UnroutableChannel(
                "Ese identificador de canal ya pertenece a otra organización. "
                "Retíralo de la organización actual antes de asignarlo."
            )
        binding = OrganizationChannelBinding(
            organization_id=organization_id,
            kind=kind.value,
            external_id=identifier,
            state=ChannelBindingState.ACTIVE.value,
            recorded_by=recorded_by,
        )
        self._session.add(binding)
        self._resolved.clear()
        await self._session.flush()
        return binding

    async def retire(
        self,
        *,
        organization_id: uuid.UUID,
        kind: ChannelBindingKind,
        external_id: str,
        at: datetime | None = None,
    ) -> bool:
        """Release an identifier. The row is kept, never deleted.

        Who owned a phone number and when is exactly the sort of question an
        incident asks months later.
        """
        binding: OrganizationChannelBinding | None = await self._session.scalar(
            select(OrganizationChannelBinding)
            .where(OrganizationChannelBinding.organization_id == organization_id)
            .where(OrganizationChannelBinding.kind == kind.value)
            .where(OrganizationChannelBinding.external_id == external_id.strip())
            .where(OrganizationChannelBinding.state == ChannelBindingState.ACTIVE.value)
        )
        if binding is None:
            return False
        binding.state = ChannelBindingState.RETIRED.value
        binding.retired_at = at or utc_now()
        self._resolved.clear()
        await self._session.flush()
        return True
