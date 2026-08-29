"""Bringing an Organization into existence, and taking it out again.

Provisioning is the operation most likely to fail halfway. It creates an
Organization row, a configuration document, a team, entitlements, channel
bindings and secret references, and any one of those can fail on a duplicate
login, an identifier another Organization already holds, or a database that went
away. A provisioning routine that is one long function leaves a *partially
created* Organization: a row that exists, looks operable, has no default Advisor
and cannot receive a message.

So the run is a list of named steps with their own rows, and three properties
follow from that:

**Resumable.** Re-running the same command key skips the steps that completed and
continues from the first that did not. Each step is individually idempotent, so
"skip" and "do it again" produce the same state — which is what makes the resume
safe even if a step completed but its row did not.

**Reversible.** Every step declares how to undo itself, and rollback walks them
backwards. Deprovisioning is the same list read in reverse, which is why it shares
this table instead of having its own.

**Not operable until finished.** The Organization is created ``Provisioning`` and
becomes ``Active`` only in the final step. Until then the routing module refuses
its channels and the directory refuses its logins, so a half-built Organization
cannot answer a customer (ADR-0055).

One thing provisioning deliberately does *not* do: verify that a credential works.
It records where the credential should be found and whether the name currently
resolves to anything. Whether the provider accepts it is the provider's answer,
and a provisioning run that claimed otherwise would report success for an
integration that fails on first use.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    Capability,
    ChannelBindingKind,
    ChannelBindingState,
    IntegrationProvider,
    Organization,
    OrganizationChannelBinding,
    OrganizationMember,
    OrganizationProvisioningRun,
    OrganizationProvisioningStep,
    OrganizationSecretReference,
    OrganizationStatus,
    ProvisioningState,
    SecretReferenceState,
)
from realestate.domain.audit import record_audit
from realestate.domain.clock import utc_now
from realestate.domain.commercial.actors import CommercialError, NotFound
from realestate.domain.commercial.organization import (
    DirectoryPlan,
    OrganizationDirectory,
)
from realestate.domain.platform.authority import PlatformOperator, require_reason
from realestate.domain.platform.configuration import (
    OrganizationConfiguration,
    RecordConfiguration,
    validate_document,
)
from realestate.domain.platform.credentials import (
    IntegrationCredentials,
    RecordSecretReference,
    SecretResolver,
    validate_reference,
)
from realestate.domain.platform.entitlements import (
    Entitlements,
    tier_for,
)
from realestate.domain.platform.routing import OrganizationRouting

logger = logging.getLogger(__name__)

#: The steps, in order. Named rather than numbered so a run's history stays
#: readable after the list changes: a step that no longer exists is still a row
#: somebody can look up, and a new step slotted in the middle does not renumber
#: everything before it.
STEP_ORGANIZATION = "Organization"
STEP_CONFIGURATION = "Configuration"
STEP_ENTITLEMENTS = "Entitlements"
STEP_TEAM = "Team"
STEP_CHANNELS = "Channels"
STEP_CREDENTIALS = "Credentials"
STEP_ACTIVATION = "Activation"

STEP_ORDER: tuple[str, ...] = (
    STEP_ORGANIZATION,
    STEP_CONFIGURATION,
    STEP_ENTITLEMENTS,
    STEP_TEAM,
    STEP_CHANNELS,
    STEP_CREDENTIALS,
    STEP_ACTIVATION,
)

STEP_LABELS: dict[str, str] = {
    STEP_ORGANIZATION: "Crear la organización",
    STEP_CONFIGURATION: "Registrar la configuración",
    STEP_ENTITLEMENTS: "Registrar el paquete y los complementos",
    STEP_TEAM: "Dar de alta al equipo inicial",
    STEP_CHANNELS: "Asignar los canales",
    STEP_CREDENTIALS: "Registrar las referencias de credenciales",
    STEP_ACTIVATION: "Poner la organización a operar",
}

SLUG_PATTERN = "abcdefghijklmnopqrstuvwxyz0123456789-"


class ProvisioningRefused(CommercialError):
    """The run cannot proceed as asked."""

    message = "No se puede aprovisionar la organización con esos datos."


class ProvisioningIncomplete(CommercialError):
    """A step failed. The run is resumable; the Organization is not operable."""

    message = (
        "El aprovisionamiento quedó incompleto. La organización no está "
        "operando y el proceso puede reintentarse o revertirse."
    )


@dataclass(frozen=True)
class ChannelAssignment:
    """One external identifier this Organization will own."""

    kind: ChannelBindingKind
    external_id: str


@dataclass(frozen=True)
class CredentialAssignment:
    """Where one of this Organization's provider credentials lives."""

    provider: IntegrationProvider
    reference: str


@dataclass(frozen=True)
class ProvisionOrganization:
    """Everything needed to stand one Brokerage Organization up.

    Deliberately one command rather than seven calls. The alternative — an
    operator running the steps by hand — is how an Organization ends up with a
    catalog and no channel, or a team and no entitlements.
    """

    slug: str
    display_name: str
    #: The versioned configuration document. Validated by
    #: :mod:`~realestate.domain.platform.configuration`, so no credential can
    #: reach it.
    configuration: Mapping[str, Any]
    #: Administrator logins. At least one, because an Organization with no
    #: administrator has nobody who can add one.
    administrators: Sequence[str]
    advisors: Sequence[str] = ()
    default_advisor: str | None = None
    channels: Sequence[ChannelAssignment] = ()
    credentials: Sequence[CredentialAssignment] = ()
    #: Add-ons this Organization bought. Everything else is recorded disabled.
    add_ons: Sequence[Capability] = ()
    reason: str = ""
    command_key: str = ""


@dataclass(frozen=True)
class DeprovisionOrganization:
    """Take one Organization out of service without destroying its history.

    Deliberately not deletion. Removing the data is
    :meth:`~realestate.domain.platform.lifecycle.OrganizationDataLifecycle.delete`,
    which is a separate, separately authorised request bounded by retention:
    conflating "stop serving them" with "erase them" is how a suspension becomes
    an accident nobody can undo.
    """

    organization_id: uuid.UUID
    reason: str
    command_key: str


@dataclass(frozen=True)
class StepOutcome:
    name: str
    label: str
    state: ProvisioningState
    detail: Mapping[str, Any] = field(default_factory=dict)

    @property
    def completed(self) -> bool:
        return self.state is ProvisioningState.COMPLETED


@dataclass(frozen=True)
class ProvisioningResult:
    """What one run did, step by step."""

    run_id: uuid.UUID
    slug: str
    organization_id: uuid.UUID | None
    state: ProvisioningState
    steps: tuple[StepOutcome, ...] = field(default_factory=tuple)
    failure: str | None = None

    @property
    def operable(self) -> bool:
        return self.state is ProvisioningState.COMPLETED

    def step(self, name: str) -> StepOutcome | None:
        return next((item for item in self.steps if item.name == name), None)


def normalise_slug(raw: str) -> str:
    """A slug is lowercase, hyphenated and short, or it is refused.

    Refused rather than coerced. The slug appears in operator surfaces, log
    lines and the bootstrap comparison; silently rewriting what somebody typed
    makes the value they see and the value they entered different things.
    """
    slug = raw.strip().lower()
    if not 2 <= len(slug) <= 60:
        raise ProvisioningRefused(
            "El identificador de la organización debe tener entre 2 y 60 "
            "caracteres."
        )
    if any(character not in SLUG_PATTERN for character in slug):
        raise ProvisioningRefused(
            "El identificador de la organización sólo admite minúsculas, "
            "números y guiones."
        )
    if slug.startswith("-") or slug.endswith("-"):
        raise ProvisioningRefused(
            "El identificador de la organización no puede empezar ni terminar "
            "con guión."
        )
    return slug


class OrganizationProvisioning:
    """Stand an Organization up, or take it down, one resumable step at a time.

    Hides: the run and step rows, resume, rollback, the order the steps have to
    run in, and the fact that the Organization is not operable until the last one
    finishes.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        resolver: SecretResolver | None = None,
    ) -> None:
        self._session = session
        self._resolver = resolver or SecretResolver()

    # -- Provision ---------------------------------------------------------

    async def provision(
        self,
        operator: PlatformOperator,
        command: ProvisionOrganization,
        *,
        at: datetime | None = None,
    ) -> ProvisioningResult:
        """Create or resume one Organization. Commits per completed step.

        Committing per step is the point: a run interrupted after step four
        resumes at step five rather than starting over, and a step that failed
        did not leave half of its own work behind.
        """
        reason = require_reason(command.reason or "Aprovisionamiento inicial.")
        slug = normalise_slug(command.slug)
        moment = at or utc_now()
        if not command.command_key.strip():
            raise ProvisioningRefused(
                "Falta la clave de operación del aprovisionamiento."
            )
        if not command.administrators:
            raise ProvisioningRefused(
                "Una organización necesita al menos un administrador."
            )
        # Validated before anything is written: a document that will be refused
        # in step two must not leave an Organization row behind from step one.
        document = validate_document(command.configuration)
        for assignment in command.credentials:
            validate_reference(assignment.reference)

        run = await self._run(
            slug=slug,
            command_key=command.command_key,
            intent="Provision",
            operator=operator,
            plan={
                "display_name": command.display_name,
                "administrators": list(command.administrators),
                "advisors": list(command.advisors),
                "default_advisor": command.default_advisor,
                "channels": [
                    {"kind": item.kind.value, "external_id": item.external_id}
                    for item in command.channels
                ],
                # Names only, never values.
                "credentials": [
                    {"provider": item.provider.value, "reference": item.reference}
                    for item in command.credentials
                ],
                "add_ons": [item.value for item in command.add_ons],
                "reason": reason,
            },
            at=moment,
        )
        await self._session.commit()

        # Read as plain values before any step runs. A failed step rolls the
        # session back, which expires every ORM object it loaded — and touching
        # an expired attribute afterwards is synchronous IO inside an async
        # session, which SQLAlchemy refuses with ``MissingGreenlet`` rather than
        # the failure the operator needs to read.
        run_id = run.id
        steps: list[StepOutcome] = []
        organization_id = run.organization_id

        async def run_step(
            name: str,
            action: Callable[[], Coroutine[Any, Any, Mapping[str, Any]]],
        ) -> bool:
            nonlocal organization_id
            existing = await self._step(run_id, name)
            if existing is not None and existing.state == ProvisioningState.COMPLETED.value:
                steps.append(
                    StepOutcome(
                        name=name,
                        label=STEP_LABELS[name],
                        state=ProvisioningState.COMPLETED,
                        detail=dict(existing.detail),
                    )
                )
                return True
            try:
                detail = await action()
            except Exception as exc:  # noqa: BLE001 - recorded, then re-raised as a refusal
                await self._session.rollback()
                await self._fail(run_id, name, exc, at=moment)
                await self._session.commit()
                steps.append(
                    StepOutcome(
                        name=name,
                        label=STEP_LABELS[name],
                        state=ProvisioningState.FAILED,
                        detail={"error": _describe(exc)},
                    )
                )
                return False
            await self._complete(run_id, name, detail, at=moment)
            await self._session.commit()
            steps.append(
                StepOutcome(
                    name=name,
                    label=STEP_LABELS[name],
                    state=ProvisioningState.COMPLETED,
                    detail=detail,
                )
            )
            return True

        async def create_organization() -> Mapping[str, Any]:
            nonlocal organization_id
            organization = await self._session.scalar(
                select(Organization).where(Organization.slug == slug).with_for_update()
            )
            if organization is None:
                organization = Organization(
                    slug=slug,
                    display_name=command.display_name.strip() or slug,
                    status=OrganizationStatus.PROVISIONING.value,
                    created_at=moment,
                )
                self._session.add(organization)
                await self._session.flush()
            elif organization.status == OrganizationStatus.ACTIVE.value:
                # Already operating. Re-running provisioning against a live
                # Organization would rewrite its configuration and team from a
                # plan that may be months old.
                raise ProvisioningRefused(
                    f"La organización «{slug}» ya está operando. Usa la "
                    "configuración versionada para cambiarla."
                )
            organization_id = organization.id
            refreshed = await self._session.get(
                OrganizationProvisioningRun, run_id, with_for_update=True
            )
            if refreshed is not None:
                refreshed.organization_id = organization.id
            return {"organization_id": str(organization.id), "slug": slug}

        async def record_configuration() -> Mapping[str, Any]:
            assert organization_id is not None
            view = await OrganizationConfiguration(self._session).record(
                operator,
                RecordConfiguration(
                    organization_id=organization_id,
                    document=document,
                    reason=reason,
                    command_key=f"{command.command_key}:configuration",
                ),
                at=moment,
            )
            return {"version": view.version, "checksum": view.checksum}

        async def record_entitlements() -> Mapping[str, Any]:
            assert organization_id is not None
            tier = tier_for(len(set(command.advisors) | set(command.administrators)))
            await Entitlements(self._session).apply_package(
                operator,
                organization_id,
                tier=tier,
                add_ons=tuple(command.add_ons),
                reason=reason,
                at=moment,
            )
            return {
                "tier": tier.name,
                "advisor_seats": tier.advisor_seats,
                "add_ons": [item.value for item in command.add_ons],
            }

        async def reconcile_team() -> Mapping[str, Any]:
            assert organization_id is not None
            await self._reject_taken_logins(
                organization_id,
                tuple(command.administrators) + tuple(command.advisors),
            )
            plan = DirectoryPlan(
                administrators=tuple(command.administrators),
                advisors=tuple(command.advisors),
                default_advisor=command.default_advisor
                or (command.advisors[0] if command.advisors else None),
            )
            result = await OrganizationDirectory(self._session).reconcile(
                plan, organization_id=organization_id
            )
            return {
                "created": list(result.created),
                "updated": list(result.updated),
                "default_advisor": plan.default_advisor,
            }

        async def bind_channels() -> Mapping[str, Any]:
            assert organization_id is not None
            routing = OrganizationRouting(self._session)
            bound: list[str] = []
            for assignment in command.channels:
                await routing.bind(
                    organization_id=organization_id,
                    kind=assignment.kind,
                    external_id=assignment.external_id,
                    recorded_by=operator.label,
                )
                bound.append(f"{assignment.kind.value}:{assignment.external_id}")
            return {"bound": bound}

        async def record_credentials() -> Mapping[str, Any]:
            assert organization_id is not None
            credentials = IntegrationCredentials(self._session, self._resolver)
            recorded: list[dict[str, Any]] = []
            for assignment in command.credentials:
                row = await credentials.record(
                    operator,
                    RecordSecretReference(
                        organization_id=organization_id,
                        provider=assignment.provider,
                        reference=assignment.reference,
                        command_key=(
                            f"{command.command_key}:credential:"
                            f"{assignment.provider.value}"
                        ),
                        reason=reason,
                    ),
                    at=moment,
                )
                recorded.append(
                    {
                        "provider": assignment.provider.value,
                        "reference": row.reference,
                        # Whether the name resolves *today*. Not whether the
                        # provider accepts it — only the provider knows that.
                        "resolves": row.fingerprint is not None,
                    }
                )
            return {"credentials": recorded}

        async def activate() -> Mapping[str, Any]:
            assert organization_id is not None
            organization = await self._session.get(
                Organization, organization_id, with_for_update=True
            )
            if organization is None:  # pragma: no cover - step one created it
                raise NotFound("La organización desapareció durante el proceso.")
            organization.status = OrganizationStatus.ACTIVE.value
            organization.activated_at = organization.activated_at or moment
            organization.suspended_at = None
            return {"activated_at": organization.activated_at.isoformat()}

        for name, action in (
            (STEP_ORGANIZATION, create_organization),
            (STEP_CONFIGURATION, record_configuration),
            (STEP_ENTITLEMENTS, record_entitlements),
            (STEP_TEAM, reconcile_team),
            (STEP_CHANNELS, bind_channels),
            (STEP_CREDENTIALS, record_credentials),
            (STEP_ACTIVATION, activate),
        ):
            if not await run_step(name, action):
                failure = steps[-1].detail.get("error")
                await self._finish(
                    run_id, ProvisioningState.FAILED, failure=str(failure), at=moment
                )
                await self._session.commit()
                logger.error(
                    "Provisioning %r stopped at step %s: %s", slug, name, failure
                )
                return ProvisioningResult(
                    run_id=run_id,
                    slug=slug,
                    organization_id=organization_id,
                    state=ProvisioningState.FAILED,
                    steps=tuple(steps),
                    failure=str(failure),
                )

        await self._finish(run_id, ProvisioningState.COMPLETED, at=moment)
        await record_audit(
            self._session,
            organization_id=organization_id,
            actor_type=operator.actor_type,
            actor_id=operator.label,
            action="ProvisionOrganization",
            subject_type="Organization",
            subject_id=str(organization_id),
            details={
                "slug": slug,
                "steps": [item.name for item in steps],
                "reason": reason,
            },
            commit=False,
        )
        await self._session.commit()
        logger.info("Provisioned Organization %r (%s)", slug, organization_id)
        return ProvisioningResult(
            run_id=run_id,
            slug=slug,
            organization_id=organization_id,
            state=ProvisioningState.COMPLETED,
            steps=tuple(steps),
        )

    # -- Rollback and deprovision ------------------------------------------

    async def rollback(
        self,
        operator: PlatformOperator,
        *,
        run_id: uuid.UUID,
        reason: str,
        at: datetime | None = None,
    ) -> ProvisioningResult:
        """Undo a failed or unwanted run, newest step first. Commits.

        What rollback does *not* do is delete the Organization row. It retires the
        channel bindings, revokes the secret references, deactivates the members
        it created and leaves the Organization ``Deprovisioned`` — because the
        provisioning history, the audit rows and any record already created have
        to remain, and because deleting a row that other tables reference under
        RESTRICT would fail anyway.
        """
        explanation = require_reason(reason)
        moment = at or utc_now()
        run = await self._session.get(
            OrganizationProvisioningRun, run_id, with_for_update=True
        )
        if run is None:
            raise NotFound("No encontramos ese aprovisionamiento.")
        steps = list(
            await self._session.scalars(
                select(OrganizationProvisioningStep)
                .where(OrganizationProvisioningStep.run_id == run_id)
                .order_by(OrganizationProvisioningStep.ordinal.desc())
            )
        )
        undone: list[StepOutcome] = []
        for step in steps:
            if step.state != ProvisioningState.COMPLETED.value:
                continue
            await self._undo(step.name, run.organization_id, operator, at=moment)
            step.state = ProvisioningState.ROLLED_BACK.value
            step.rolled_back_at = moment
            undone.append(
                StepOutcome(
                    name=step.name,
                    label=STEP_LABELS.get(step.name, step.name),
                    state=ProvisioningState.ROLLED_BACK,
                    detail=dict(step.detail),
                )
            )
        run.state = ProvisioningState.ROLLED_BACK.value
        run.completed_at = moment
        run.failure = explanation
        await record_audit(
            self._session,
            organization_id=run.organization_id,
            actor_type=operator.actor_type,
            actor_id=operator.label,
            action="RollBackProvisioning",
            subject_type="OrganizationProvisioningRun",
            subject_id=str(run.id),
            details={
                "slug": run.slug,
                "undone": [item.name for item in undone],
                "reason": explanation,
            },
            commit=False,
        )
        await self._session.commit()
        return ProvisioningResult(
            run_id=run.id,
            slug=run.slug,
            organization_id=run.organization_id,
            state=ProvisioningState.ROLLED_BACK,
            steps=tuple(undone),
            failure=explanation,
        )

    async def deprovision(
        self,
        operator: PlatformOperator,
        command: DeprovisionOrganization,
        *,
        at: datetime | None = None,
    ) -> ProvisioningResult:
        """Stop serving one Organization, reversibly. Commits.

        Idempotent: deprovisioning an Organization that is already deprovisioned
        replays its run rather than doing the work twice.
        """
        explanation = require_reason(command.reason)
        moment = at or utc_now()
        organization = await self._session.get(
            Organization, command.organization_id, with_for_update=True
        )
        if organization is None:
            raise NotFound("No encontramos esa organización.")

        run = await self._run(
            slug=organization.slug,
            command_key=command.command_key,
            intent="Deprovision",
            operator=operator,
            plan={"reason": explanation},
            at=moment,
            organization_id=organization.id,
        )
        if run.state == ProvisioningState.COMPLETED.value:
            return ProvisioningResult(
                run_id=run.id,
                slug=organization.slug,
                organization_id=organization.id,
                state=ProvisioningState.COMPLETED,
            )

        organization.status = OrganizationStatus.DEPROVISIONING.value
        await self._session.flush()

        undone: list[StepOutcome] = []
        for name in reversed(STEP_ORDER):
            if name == STEP_ORGANIZATION:
                continue
            await self._undo(name, organization.id, operator, at=moment)
            undone.append(
                StepOutcome(
                    name=name,
                    label=STEP_LABELS[name],
                    state=ProvisioningState.ROLLED_BACK,
                )
            )
        organization.status = OrganizationStatus.DEPROVISIONED.value
        organization.deprovisioned_at = moment
        run.state = ProvisioningState.COMPLETED.value
        run.completed_at = moment

        await record_audit(
            self._session,
            organization_id=organization.id,
            actor_type=operator.actor_type,
            actor_id=operator.label,
            action="DeprovisionOrganization",
            subject_type="Organization",
            subject_id=str(organization.id),
            details={
                "slug": organization.slug,
                "reason": explanation,
                # Said explicitly because it is the question somebody will ask:
                # the data is still here, and removing it is a separate request.
                "data_retained": True,
            },
            commit=False,
        )
        await self._session.commit()
        logger.info(
            "Deprovisioned Organization %r; its data is retained until a "
            "deletion request is authorised",
            organization.slug,
        )
        return ProvisioningResult(
            run_id=run.id,
            slug=organization.slug,
            organization_id=organization.id,
            state=ProvisioningState.COMPLETED,
            steps=tuple(undone),
        )

    async def suspend(
        self,
        operator: PlatformOperator,
        *,
        organization_id: uuid.UUID,
        reason: str,
        at: datetime | None = None,
    ) -> Organization:
        """Pause service without undoing anything. Does not commit.

        Distinct from deprovisioning: channels stay bound, credentials stay
        registered, members stay listed. Nothing is processed and nobody can log
        in, so resuming is one status change rather than a second provisioning.
        """
        explanation = require_reason(reason)
        moment = at or utc_now()
        organization = await self._session.get(
            Organization, organization_id, with_for_update=True
        )
        if organization is None:
            raise NotFound("No encontramos esa organización.")
        organization.status = OrganizationStatus.SUSPENDED.value
        organization.suspended_at = moment
        await record_audit(
            self._session,
            organization_id=organization_id,
            actor_type=operator.actor_type,
            actor_id=operator.label,
            action="SuspendOrganization",
            subject_type="Organization",
            subject_id=str(organization_id),
            details={"slug": organization.slug, "reason": explanation},
            commit=False,
        )
        await self._session.flush()
        return organization

    async def resume(
        self,
        operator: PlatformOperator,
        *,
        organization_id: uuid.UUID,
        reason: str,
        at: datetime | None = None,
    ) -> Organization:
        """Undo a suspension. Does not commit."""
        explanation = require_reason(reason)
        moment = at or utc_now()
        organization = await self._session.get(
            Organization, organization_id, with_for_update=True
        )
        if organization is None:
            raise NotFound("No encontramos esa organización.")
        if organization.status == OrganizationStatus.DEPROVISIONED.value:
            raise ProvisioningRefused(
                "Una organización dada de baja se vuelve a aprovisionar; no se "
                "reanuda."
            )
        organization.status = OrganizationStatus.ACTIVE.value
        organization.activated_at = organization.activated_at or moment
        organization.suspended_at = None
        await record_audit(
            self._session,
            organization_id=organization_id,
            actor_type=operator.actor_type,
            actor_id=operator.label,
            action="ResumeOrganization",
            subject_type="Organization",
            subject_id=str(organization_id),
            details={"slug": organization.slug, "reason": explanation},
            commit=False,
        )
        await self._session.flush()
        return organization

    # -- Reporting ---------------------------------------------------------

    async def runs(
        self, *, slug: str | None = None
    ) -> list[OrganizationProvisioningRun]:
        """Provisioning history, newest first."""
        query = select(OrganizationProvisioningRun)
        if slug is not None:
            query = query.where(OrganizationProvisioningRun.slug == slug)
        rows = await self._session.scalars(
            query.order_by(OrganizationProvisioningRun.started_at.desc())
        )
        return list(rows)

    async def steps_of(
        self, run_id: uuid.UUID
    ) -> list[OrganizationProvisioningStep]:
        rows = await self._session.scalars(
            select(OrganizationProvisioningStep)
            .where(OrganizationProvisioningStep.run_id == run_id)
            .order_by(OrganizationProvisioningStep.ordinal)
        )
        return list(rows)

    # -- internals ---------------------------------------------------------

    async def _run(
        self,
        *,
        slug: str,
        command_key: str,
        intent: str,
        operator: PlatformOperator,
        plan: Mapping[str, Any],
        at: datetime,
        organization_id: uuid.UUID | None = None,
    ) -> OrganizationProvisioningRun:
        """The run row for this command key, created or resumed."""
        existing: OrganizationProvisioningRun | None = await self._session.scalar(
            select(OrganizationProvisioningRun)
            .where(OrganizationProvisioningRun.command_key == command_key)
            .with_for_update()
        )
        if existing is not None:
            if existing.slug != slug or existing.intent != intent:
                raise ProvisioningRefused(
                    "Esa clave de operación ya se usó para otro "
                    "aprovisionamiento."
                )
            if dict(existing.plan) != dict(plan):
                raise ProvisioningRefused(
                    "Esa clave de operación ya pertenece a un plan distinto. "
                    "Reintenta con el plan original o usa una clave nueva."
                )
            return existing
        run = OrganizationProvisioningRun(
            command_key=command_key,
            slug=slug,
            organization_id=organization_id,
            intent=intent,
            state=ProvisioningState.PENDING.value,
            requested_by=operator.label,
            plan=dict(plan),
            started_at=at,
        )
        self._session.add(run)
        await self._session.flush()
        return run

    async def _step(
        self, run_id: uuid.UUID, name: str
    ) -> OrganizationProvisioningStep | None:
        found: OrganizationProvisioningStep | None = await self._session.scalar(
            select(OrganizationProvisioningStep)
            .where(OrganizationProvisioningStep.run_id == run_id)
            .where(OrganizationProvisioningStep.name == name)
        )
        return found

    async def _upsert_step(
        self, run_id: uuid.UUID, name: str
    ) -> OrganizationProvisioningStep:
        step = await self._step(run_id, name)
        if step is None:
            step = OrganizationProvisioningStep(
                run_id=run_id,
                ordinal=STEP_ORDER.index(name),
                name=name,
                state=ProvisioningState.PENDING.value,
            )
            self._session.add(step)
            await self._session.flush()
        return step

    async def _complete(
        self,
        run_id: uuid.UUID,
        name: str,
        detail: Mapping[str, Any],
        *,
        at: datetime,
    ) -> None:
        step = await self._upsert_step(run_id, name)
        step.state = ProvisioningState.COMPLETED.value
        step.detail = dict(detail)
        step.completed_at = at
        await self._session.flush()

    async def _fail(
        self, run_id: uuid.UUID, name: str, error: Exception, *, at: datetime
    ) -> None:
        step = await self._upsert_step(run_id, name)
        step.state = ProvisioningState.FAILED.value
        step.detail = {"error": _describe(error)}
        step.completed_at = at
        await self._session.flush()

    async def _finish(
        self,
        run_id: uuid.UUID,
        state: ProvisioningState,
        *,
        failure: str | None = None,
        at: datetime,
    ) -> None:
        run = await self._session.get(
            OrganizationProvisioningRun, run_id, with_for_update=True
        )
        if run is None:  # pragma: no cover - created above
            return
        run.state = state.value
        run.completed_at = at
        run.failure = failure
        await self._session.flush()

    async def _undo(
        self,
        name: str,
        organization_id: uuid.UUID | None,
        operator: PlatformOperator,
        *,
        at: datetime,
    ) -> None:
        """Reverse one step, as far as reversing it is meaningful.

        Configuration and entitlements are *not* reversed: both are append-only
        histories, and deleting the record of what an Organization was configured
        with or entitled to would remove the evidence for every decision taken
        while it operated. What rollback removes is the *capability* — channels,
        credentials, active members, operating status.
        """
        if organization_id is None:
            return
        if name == STEP_CHANNELS:
            bindings = await self._session.scalars(
                select(OrganizationChannelBinding)
                .where(OrganizationChannelBinding.organization_id == organization_id)
                .where(
                    OrganizationChannelBinding.state == ChannelBindingState.ACTIVE.value
                )
                .with_for_update()
            )
            for binding in bindings:
                binding.state = ChannelBindingState.RETIRED.value
                binding.retired_at = at
        elif name == STEP_CREDENTIALS:
            references = await self._session.scalars(
                select(OrganizationSecretReference)
                .where(
                    OrganizationSecretReference.organization_id == organization_id
                )
                .where(
                    OrganizationSecretReference.state
                    != SecretReferenceState.REVOKED.value
                )
                .with_for_update()
            )
            for reference in references:
                reference.state = SecretReferenceState.REVOKED.value
                reference.revoked_at = at
        elif name == STEP_TEAM:
            members = await self._session.scalars(
                select(OrganizationMember)
                .where(OrganizationMember.organization_id == organization_id)
                .where(OrganizationMember.active.is_(True))
                .with_for_update()
            )
            for member in members:
                member.active = False
                member.is_default_advisor = False
        elif name == STEP_ACTIVATION:
            organization = await self._session.get(
                Organization, organization_id, with_for_update=True
            )
            if organization is not None and (
                organization.status == OrganizationStatus.ACTIVE.value
            ):
                organization.status = OrganizationStatus.DEPROVISIONING.value
        await self._session.flush()

    async def _reject_taken_logins(
        self, organization_id: uuid.UUID, logins: Sequence[str]
    ) -> None:
        """Refuse a login another Organization already holds, by name.

        The login namespace is platform-wide because HTTP Basic carries no
        Organization. Left to the unique index this would surface as a constraint
        violation with no remedy in it; named here, the operator is told which
        login to change before anything has been written.
        """
        wanted = [login.strip() for login in logins if login.strip()]
        if not wanted:
            return
        rows = await self._session.execute(
            select(OrganizationMember.login)
            .where(OrganizationMember.login.in_(wanted))
            .where(OrganizationMember.organization_id != organization_id)
        )
        taken = sorted({row[0] for row in rows})
        if taken:
            raise ProvisioningRefused(
                "Estos usuarios ya pertenecen a otra organización: "
                + ", ".join(taken)
                + ". Elige otros identificadores de acceso."
            )

    async def count(self) -> int:
        """How many Organizations exist, for the platform overview."""
        total = await self._session.scalar(select(func.count(Organization.id)))
        return int(total or 0)


def _describe(error: Exception) -> str:
    """One readable line for a failed step.

    A :class:`~realestate.domain.commercial.actors.CommercialError` already
    carries Mexican Spanish an operator can act on; anything else gets its type
    and message, because a bare ``repr`` in a step row is not a report.
    """
    if isinstance(error, CommercialError):
        return error.message
    return f"{type(error).__name__}: {error}"
