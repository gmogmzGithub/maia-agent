"""One Organization's provider access, resolved from a reference.

Every credential in this product used to be a process-wide environment variable:
one Meta token, one Calendar service account, one EasyBroker key. That is exactly
right for one brokerage and catastrophic for two, because the failure is not a
refusal — it is a *success*. Organization B's messages go out over Organization
A's WhatsApp number, appear in A's Meta account, and are billed to A.

So this module has one rule and it has no exceptions:

    **A credential is never inherited.** If an Organization has no reference for
    a provider, the answer is a named refusal. It is not the platform default,
    not another Organization's value, and not an empty string that a client
    library will treat as anonymous access.

The one concession to history is explicit and bounded. The process environment
belongs to exactly one Organization — the founding one, named by
``PLATFORM_BOOTSTRAP_ORGANIZATION_SLUG`` — because that is whose numbers, tokens
and calendars those variables were written for. Every other Organization gets
nothing from the environment, and asking for it is refused with the reason. The
distinction is enforced by comparing an Organization *id*, not a name a caller
supplies, and there is a test whose entire purpose is to prove that the second
Organization cannot reach the first one's environment.

Product stores the *reference* — the name of an environment variable, or a path a
secret manager understands — and a fingerprint of the material that name last
resolved to. The material itself is never written to a table, a log, an audit
event, an export or a screen. That is what lets an operator see "the EasyBroker
key comes from ``LAREVIA_EASYBROKER_API_KEY`` and last changed on the 4th"
without anybody being able to read it.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    IntegrationProvider,
    Organization,
    OrganizationSecretReference,
    SecretReferenceState,
)
from realestate.domain.audit import record_audit
from realestate.domain.clock import utc_now
from realestate.domain.commercial.actors import Actor, CommercialError
from realestate.domain.platform.authority import PlatformOperator, require_reason

logger = logging.getLogger(__name__)

# A reference is a name. This pattern is what stops a caller from pasting the
# secret itself into the column: a token contains characters this rejects, and a
# value long enough to be a credential exceeds the length. It is a guard, not a
# guarantee, which is why the module also refuses anything that looks like a
# JSON document or a PEM block below.
REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./:-]{2,119}$")

# Substrings that mean somebody handed over material rather than a name.
_MATERIAL_MARKERS = ("-----BEGIN", "{", '"', "\n")


class MissingCredential(CommercialError):
    """This Organization has no usable access to this provider.

    A refusal rather than a silent absence, because the alternative — an empty
    token handed to a client library — produces an unauthenticated request whose
    provider error nobody traces back to configuration.
    """

    message = (
        "Esta organización no tiene una credencial registrada para ese "
        "proveedor. Regístrala antes de usar la integración."
    )


class UnresolvableCredential(CommercialError):
    """The reference exists but resolves to nothing.

    Distinct from :class:`MissingCredential` on purpose: "nobody configured it"
    and "somebody configured it and the secret is gone" need different fixes,
    and one message for both sends an operator to the wrong place.
    """

    message = (
        "La referencia de credencial de esta organización no resuelve a ningún "
        "valor. Revisa el secreto al que apunta."
    )


class InvalidReference(CommercialError):
    """What was submitted is not a reference."""

    message = (
        "Una referencia de credencial es un nombre, no el valor. Registra el "
        "nombre de la variable o la ruta del secreto."
    )


@dataclass(frozen=True, repr=False)
class ResolvedCredential:
    """One provider credential, with where it came from.

    ``origin`` is on the result rather than looked up separately because every
    caller that logs a provider failure wants it, and the one that does not want
    it cannot accidentally log ``material``: the field is excluded from the
    dataclass ``repr``.
    """

    organization_id: uuid.UUID
    provider: IntegrationProvider
    reference: str
    #: The secret. Excluded from ``repr`` so a stack trace, a log line
    #: interpolating the object, or a debugger summary cannot disclose it.
    material: str = ""
    origin: str = "SecretReference"
    fingerprint: str = ""

    def __repr__(self) -> str:  # pragma: no cover - defensive, not behaviour
        return (
            f"ResolvedCredential(organization_id={self.organization_id!r}, "
            f"provider={self.provider.value!r}, reference={self.reference!r}, "
            f"origin={self.origin!r}, material=<withheld>)"
        )


@dataclass(frozen=True)
class RecordSecretReference:
    """Register or rotate one Organization's reference for one provider."""

    organization_id: uuid.UUID
    provider: IntegrationProvider
    reference: str
    command_key: str
    reason: str


def fingerprint_of(material: str) -> str:
    """A digest that proves a value changed without disclosing it.

    Salted with a fixed, non-secret purpose string rather than unsalted, so the
    digest of a short credential is not a lookup into a rainbow table somebody
    already has. It is not a secret and it is still withheld from exports: a
    digest is a confirmation oracle for anybody who can guess the input.
    """
    return hashlib.sha256(f"maia-secret-fingerprint:{material}".encode()).hexdigest()


def validate_reference(reference: str) -> str:
    """The reference, normalised, or a refusal explaining what one is."""
    candidate = reference.strip()
    if not REFERENCE_PATTERN.match(candidate):
        raise InvalidReference()
    if any(marker in candidate for marker in _MATERIAL_MARKERS):
        raise InvalidReference()
    return candidate


class SecretResolver:
    """Turns a reference into material. The only place secrets are read.

    The local Compose implementation reads the process environment, which is what
    ``.env`` already is. A deployment that uses a secret manager replaces this
    object and nothing else: the domain never learns where secrets live, and the
    Organization-scoping above stays identical.

    ``overrides`` exists for the suites. It is a mapping rather than a patched
    ``os.environ`` because a test that mutates the process environment leaks into
    every other test in the session.
    """

    def __init__(self, overrides: Mapping[str, str] | None = None) -> None:
        self._overrides = dict(overrides or {})

    def resolve(self, reference: str) -> str | None:
        if reference in self._overrides:
            return self._overrides[reference] or None
        return os.environ.get(reference) or None

    def record(self, reference: str, material: str) -> None:
        """Supply a value for a reference without touching the environment.

        Used by the suites and by the local provisioning wizard. Deliberately
        not a general write path: this object cannot create a secret in a real
        secret manager, and pretending otherwise would make a provisioning run
        report success for a credential nobody stored.
        """
        self._overrides[reference] = material


class IntegrationCredentials:
    """One Organization's provider access. Nothing is shared or inherited.

    Hides: the reference table, the Active/Rotating precedence, the fingerprint,
    the bootstrap Organization's bounded environment fallback, and the refusal
    every other Organization gets instead of it.
    """

    def __init__(
        self,
        session: AsyncSession,
        resolver: SecretResolver | None = None,
        *,
        bootstrap_organization_id: uuid.UUID | None = None,
        legacy_values: Mapping[IntegrationProvider, str] | None = None,
    ) -> None:
        self._session = session
        self._resolver = resolver or SecretResolver()
        # The one Organization the process environment belongs to. ``None`` means
        # there is no bootstrap Organization on this installation, and then no
        # Organization gets a legacy value — which is the correct behaviour for
        # any deployment that was provisioned rather than grown.
        self._bootstrap_organization_id = bootstrap_organization_id
        self._legacy_values = dict(legacy_values or {})

    async def resolve(
        self, organization_id: uuid.UUID, provider: IntegrationProvider
    ) -> ResolvedCredential:
        """This Organization's credential for this provider, or a refusal.

        Precedence, and it is short on purpose:

        1. the Organization's own ``Active`` reference;
        2. its own ``Rotating`` reference, when the active one resolves to
           nothing — a rotation half-applied must not take the integration down;
        3. the process environment, **only** when this Organization is the
           bootstrap one;
        4. a refusal.

        There is no step that reads another Organization's row. That is the whole
        module.
        """
        rows = list(
            await self._session.scalars(
                select(OrganizationSecretReference)
                .where(OrganizationSecretReference.organization_id == organization_id)
                .where(OrganizationSecretReference.provider == provider.value)
                .where(
                    OrganizationSecretReference.state.in_(
                        (
                            SecretReferenceState.ACTIVE.value,
                            SecretReferenceState.ROTATING.value,
                        )
                    )
                )
                .order_by(OrganizationSecretReference.state)
            )
        )
        # ``Active`` sorts before ``Rotating`` alphabetically, which is a
        # coincidence and therefore not relied on: the preference is spelled out.
        ordered = [
            row for row in rows if row.state == SecretReferenceState.ACTIVE.value
        ] + [row for row in rows if row.state == SecretReferenceState.ROTATING.value]

        for row in ordered:
            material = self._resolver.resolve(row.reference)
            if material:
                return ResolvedCredential(
                    organization_id=organization_id,
                    provider=provider,
                    reference=row.reference,
                    material=material,
                    origin=f"SecretReference:{row.state}",
                    fingerprint=fingerprint_of(material),
                )

        if ordered:
            # A reference exists and resolves to nothing. Refusing here rather
            # than falling through to the bootstrap environment is deliberate:
            # an Organization that named its own secret must never silently be
            # served somebody else's.
            logger.error(
                "Organization %s has a %s reference that resolves to nothing",
                organization_id,
                provider.value,
            )
            raise UnresolvableCredential()

        legacy = self._legacy_values.get(provider)
        if (
            legacy
            and self._bootstrap_organization_id is not None
            and organization_id == self._bootstrap_organization_id
        ):
            logger.debug(
                "Resolved %s for the bootstrap Organization from the process "
                "environment; register a secret reference to remove this path",
                provider.value,
            )
            return ResolvedCredential(
                organization_id=organization_id,
                provider=provider,
                reference="",
                material=legacy,
                origin="LegacyProcessEnvironment",
                fingerprint=fingerprint_of(legacy),
            )

        logger.warning(
            "Refused %s access for Organization %s: no secret reference",
            provider.value,
            organization_id,
        )
        raise MissingCredential()

    async def try_resolve(
        self, organization_id: uuid.UUID, provider: IntegrationProvider
    ) -> ResolvedCredential | None:
        """The credential, or ``None`` where absence is an ordinary answer.

        Health reporting and the operator surfaces want to say "not configured"
        rather than fail. Every path that is about to *use* a provider calls
        :meth:`resolve` instead, because there the absence must stop the work.
        """
        try:
            return await self.resolve(organization_id, provider)
        except (MissingCredential, UnresolvableCredential):
            return None

    async def record(
        self,
        operator: PlatformOperator,
        command: RecordSecretReference,
        *,
        at: datetime | None = None,
    ) -> OrganizationSecretReference:
        """Register or rotate a reference. Does not commit.

        A platform operation, not an Organization Administrator's. Pointing a
        reference at a different secret means writing into the platform's secret
        store, which is not something a customer's login can reach — and an
        Administrator who could change the *name* without being able to change
        what it holds could only ever break their own integration. What an
        Administrator does get is :meth:`inventory`: the names and the
        fingerprints, so they can see what their operation is configured with
        (ADR-0052).

        Recording the reference the Organization already has is a no-op, so a
        restarted provisioning run is idempotent. Recording a *different* one is
        a rotation: the outgoing reference is marked ``Rotating`` and the new one
        becomes ``Active``, both rows surviving so the change is provable.

        Rotation does not verify that the new secret works. It cannot — the
        provider is the only authority on that — and pretending otherwise would
        make a successful rotation record a credential that fails on first use.
        What it does record is the fingerprint, so "the value actually changed"
        is answerable without the value.
        """
        reason = require_reason(command.reason)
        reference = validate_reference(command.reference)
        moment = at or utc_now()

        existing = list(
            await self._session.scalars(
                select(OrganizationSecretReference)
                .where(
                    OrganizationSecretReference.organization_id
                    == command.organization_id
                )
                .where(OrganizationSecretReference.provider == command.provider.value)
                .with_for_update()
            )
        )
        active = next(
            (
                row
                for row in existing
                if row.state == SecretReferenceState.ACTIVE.value
            ),
            None,
        )
        if active is not None and active.reference == reference:
            return active

        for row in existing:
            if row.state == SecretReferenceState.ACTIVE.value:
                row.state = SecretReferenceState.ROTATING.value
                row.rotated_at = moment
            elif row.state == SecretReferenceState.ROTATING.value:
                # Only one rotation may be in flight. A second would leave three
                # candidate credentials and no way to say which one is current.
                row.state = SecretReferenceState.REVOKED.value
                row.revoked_at = moment
        await self._session.flush()

        reused = next((row for row in existing if row.reference == reference), None)
        if reused is not None:
            reused.state = SecretReferenceState.ACTIVE.value
            reused.revoked_at = None
            reused.recorded_by = operator.label
            reused.recorded_at = moment
            record = reused
        else:
            record = OrganizationSecretReference(
                organization_id=command.organization_id,
                provider=command.provider.value,
                reference=reference,
                state=SecretReferenceState.ACTIVE.value,
                recorded_by=operator.label,
                recorded_at=moment,
            )
            self._session.add(record)
        material = self._resolver.resolve(reference)
        record.fingerprint = fingerprint_of(material) if material else None
        await self._session.flush()

        await record_audit(
            self._session,
            organization_id=command.organization_id,
            actor_type=operator.actor_type,
            actor_id=operator.label,
            action="RecordSecretReference",
            subject_type="IntegrationCredential",
            subject_id=f"{command.organization_id}:{command.provider.value}",
            details={
                "provider": command.provider.value,
                "reference": reference,
                "rotated_from": active.reference if active is not None else None,
                # The fingerprint, never the value. Present so an auditor can
                # see that a rotation changed something.
                "fingerprint": record.fingerprint,
                "resolves": material is not None,
                "reason": reason,
            },
            commit=False,
        )
        return record

    async def revoke(
        self,
        operator: PlatformOperator,
        *,
        organization_id: uuid.UUID,
        provider: IntegrationProvider,
        reason: str,
        at: datetime | None = None,
    ) -> int:
        """Withdraw every reference for one provider. Does not commit.

        Used by deprovisioning and by an operator ending an integration. The rows
        stay, because "we stopped having access on the 4th" is a fact somebody
        will need.
        """
        explanation = require_reason(reason)
        moment = at or utc_now()
        rows = list(
            await self._session.scalars(
                select(OrganizationSecretReference)
                .where(OrganizationSecretReference.organization_id == organization_id)
                .where(OrganizationSecretReference.provider == provider.value)
                .where(
                    OrganizationSecretReference.state
                    != SecretReferenceState.REVOKED.value
                )
                .with_for_update()
            )
        )
        for row in rows:
            row.state = SecretReferenceState.REVOKED.value
            row.revoked_at = moment
        if rows:
            await record_audit(
                self._session,
                organization_id=organization_id,
                actor_type=operator.actor_type,
                actor_id=operator.label,
                action="RevokeSecretReference",
                subject_type="IntegrationCredential",
                subject_id=f"{organization_id}:{provider.value}",
                details={
                    "provider": provider.value,
                    "revoked": len(rows),
                    "reason": explanation,
                },
                commit=False,
            )
        await self._session.flush()
        return len(rows)

    async def inventory(
        self, actor: Actor
    ) -> list[OrganizationSecretReference]:
        """Every reference this Organization holds, current first.

        Takes an ``Actor`` rather than an id, so the Organization is the caller's
        own by construction: there is no argument an Administrator could pass to
        read another Organization's integration configuration.

        Safe to render: a reference is a name and a fingerprint is a digest.
        """
        actor.require_administrator()
        rows = await self._session.scalars(
            select(OrganizationSecretReference)
            .where(OrganizationSecretReference.organization_id == actor.organization_id)
            .order_by(
                OrganizationSecretReference.provider,
                OrganizationSecretReference.state,
                OrganizationSecretReference.recorded_at.desc(),
            )
        )
        return list(rows)


async def bootstrap_organization_id(
    session: AsyncSession, slug: str
) -> uuid.UUID | None:
    """The Organization the process environment belongs to, if it exists.

    ``None`` rather than an exception: an installation provisioned from scratch
    has no bootstrap Organization, and on that installation the correct behaviour
    is that nobody gets a legacy environment value.
    """
    found: uuid.UUID | None = await session.scalar(
        select(Organization.id).where(Organization.slug == slug)
    )
    return found
