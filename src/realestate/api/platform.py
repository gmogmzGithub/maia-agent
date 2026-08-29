"""The internal platform surface: provisioning, entitlements, support, lifecycle.

Deliberately **not** part of the CRM. Every route here is authenticated by a
dedicated platform credential and refuses an Organization member's login, because
the two authorities are different things: an Organization Administrator runs a
brokerage, and a platform operator runs the service several brokerages are on. A
surface that accepted both would be one conditional away from a superadmin
(ADR-0054).

It is also deliberately **JSON rather than a form UI**. The Mexican Spanish
operator surfaces exist for the people running a brokerage; these routes are run
by Maia's own team from a terminal or a runbook, and the artefact that matters is
the recorded command with its written reason — not a page. What *is* rendered is
one read-only Spanish panel, ``/crm/plataforma``, so an Organization's own
Administrator can see their configuration version, entitlements, integration
references and — most importantly — every support access anybody was ever granted
into their data.

Nothing on this router can read an Organization's commercial records. Provisioning
writes configuration, entitlements, bindings and references; the lifecycle routes
count rows and write artifacts; nothing returns a Contact, an Opportunity or a
message. Reading those requires a support grant, which produces an ordinary
member row and goes through the ordinary CRM with the ordinary checks.
"""

from __future__ import annotations

import hmac
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from realestate.api.operator import require_administrator, shell
from realestate.api.ui import escape, local, table
from realestate.db.models import (
    Capability,
    ChannelBindingKind,
    DeletionScope,
    EntitlementState,
    IntegrationProvider,
    RetentionBasis,
)
from realestate.domain.commercial.actors import Actor, CommercialError
from realestate.domain.platform.authority import PlatformOperator
from realestate.domain.platform.configuration import (
    OrganizationConfiguration,
    RecordConfiguration,
)
from realestate.domain.platform.credentials import (
    IntegrationCredentials,
    RecordSecretReference,
)
from realestate.domain.platform.entitlements import (
    CAPABILITY_LABELS,
    Entitlements,
    GrantEntitlement,
    tier_for,
)
from realestate.domain.platform.imports import (
    ImportPlan,
    IncomingProperty,
    OrganizationImport,
)
from realestate.domain.platform.lifecycle import (
    DeleteOrganizationData,
    ExportOrganizationData,
    OrganizationDataLifecycle,
    RecordRetentionHold,
)
from realestate.domain.platform.provisioning import (
    ChannelAssignment,
    CredentialAssignment,
    DeprovisionOrganization,
    OrganizationProvisioning,
    ProvisionOrganization,
)
from realestate.domain.platform.registry import all_organizations
from realestate.domain.platform.routing import OrganizationRouting
from realestate.domain.platform.support import (
    GrantSupportAccess,
    SupportAccess,
)
from realestate.domain.platform.usage import PlatformUsage

PLATFORM_OPERATOR_HEADER = "X-Platform-Operator"


async def require_platform_operator(
    request: Request,
    authorization: str = Header(default=""),
    operator_label: str = Header(default="", alias=PLATFORM_OPERATOR_HEADER),
) -> PlatformOperator:
    """The only way a :class:`PlatformOperator` comes into existence.

    Two things are required and neither has a default: the shared platform
    credential, and a *name*. A platform action attributed to "the token" is an
    audit row nobody can follow up, so the header is mandatory even though the
    token alone would authenticate.

    An unset token refuses every request rather than allowing them, which is the
    correct default for a local installation nobody has configured for platform
    administration.
    """
    expected = request.app.state.settings.platform_operator_token
    supplied = authorization.strip()
    wanted = f"Bearer {expected}" if expected else ""
    if not wanted or not hmac.compare_digest(supplied, wanted):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere una credencial de operador de plataforma.",
        )
    label = operator_label.strip()
    if not label:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Falta el encabezado {PLATFORM_OPERATOR_HEADER}: toda operación "
                "de plataforma se registra con el nombre de quien la ejecuta."
            ),
        )
    return PlatformOperator(label=label)


router = APIRouter(
    prefix="/platform",
    tags=["platform"],
    dependencies=[Depends(require_platform_operator)],
)


def _json(value: object, *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(jsonable_encoder(value), status_code=status_code)


def _refusal(exc: CommercialError) -> JSONResponse:
    """A domain refusal as a 409 carrying the operator-facing sentence.

    409 rather than 400: these are not malformed requests, they are requests the
    product declines — a login another Organization holds, a live retention hold,
    an entitlement that does not admit a limit.
    """
    return _json({"result": "refused", "detail": exc.message}, status_code=409)


class ChannelBody(BaseModel):
    kind: ChannelBindingKind
    external_id: str = Field(min_length=1, max_length=200)


class CredentialBody(BaseModel):
    provider: IntegrationProvider
    #: The *name* of the secret, never its value. Rejected by the domain if it
    #: looks like material rather than a reference.
    reference: str = Field(min_length=3, max_length=200)


class CredentialRecordBody(CredentialBody):
    """A reference plus the reason it changed.

    The reason is in the body rather than a header because it is Mexican Spanish
    and HTTP headers are latin-1: "Rotación programada" cannot survive the trip.
    """

    model_config = {"extra": "forbid"}

    reason: str = Field(min_length=12, max_length=2_000)


class ProvisionBody(BaseModel):
    model_config = {"extra": "forbid"}

    slug: str = Field(min_length=2, max_length=60)
    display_name: str = Field(min_length=2, max_length=200)
    configuration: dict[str, Any]
    administrators: list[str] = Field(min_length=1)
    advisors: list[str] = Field(default_factory=list)
    default_advisor: str | None = None
    channels: list[ChannelBody] = Field(default_factory=list)
    credentials: list[CredentialBody] = Field(default_factory=list)
    add_ons: list[Capability] = Field(default_factory=list)
    reason: str = Field(min_length=12, max_length=2_000)
    command_key: str = Field(min_length=8, max_length=200)


class ReasonBody(BaseModel):
    model_config = {"extra": "forbid"}

    reason: str = Field(min_length=12, max_length=2_000)
    command_key: str = Field(min_length=8, max_length=200)


class ConfigurationBody(BaseModel):
    model_config = {"extra": "forbid"}

    document: dict[str, Any]
    reason: str = Field(min_length=12, max_length=2_000)
    command_key: str = Field(min_length=8, max_length=200)


class EntitlementBody(BaseModel):
    model_config = {"extra": "forbid"}

    capability: Capability
    state: EntitlementState
    limit_value: int | None = Field(default=None, ge=0)
    reason: str = Field(min_length=12, max_length=2_000)


class SupportBody(BaseModel):
    model_config = {"extra": "forbid"}

    engineer_login: str = Field(min_length=2, max_length=100)
    reason: str = Field(min_length=12, max_length=2_000)
    command_key: str = Field(min_length=8, max_length=200)
    hours: int = Field(default=2, ge=1, le=8)
    request_reference: str | None = Field(default=None, max_length=200)


class DeletionBody(BaseModel):
    model_config = {"extra": "forbid"}

    scope: DeletionScope
    reason: str = Field(min_length=12, max_length=2_000)
    command_key: str = Field(min_length=8, max_length=200)


class HoldBody(BaseModel):
    model_config = {"extra": "forbid"}

    basis: RetentionBasis
    authority: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=12, max_length=2_000)
    expires_at: datetime | None = None


class ImportPropertyBody(BaseModel):
    model_config = {"extra": "forbid"}

    source_reference: str = Field(min_length=1, max_length=200)
    property_key: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=200)
    property_type: str = Field(min_length=1, max_length=30)
    facts: dict[str, Any] = Field(default_factory=dict)
    visit_address: str | None = Field(default=None, max_length=500)


class ImportBody(BaseModel):
    model_config = {"extra": "forbid"}

    source: str = Field(min_length=2, max_length=300)
    records: list[ImportPropertyBody] = Field(min_length=1)
    reason: str = Field(min_length=12, max_length=2_000)
    command_key: str = Field(min_length=8, max_length=200)


# -- Organizations ------------------------------------------------------------


@router.get("/organizations")
async def organizations(request: Request) -> JSONResponse:
    """Every Organization and its lifecycle state. No commercial data."""
    async with request.app.state.database.session_scope() as session:
        rows = await all_organizations(session)
        return _json(
            {
                "organizations": [
                    {
                        "organization_id": str(item.organization_id),
                        "slug": item.slug,
                        "display_name": item.display_name,
                        "status": item.status.value,
                    }
                    for item in rows
                ]
            }
        )


@router.post("/organizations")
async def provision(
    request: Request,
    body: ProvisionBody,
    operator: PlatformOperator = Depends(require_platform_operator),
) -> JSONResponse:
    """Provision one Organization, or resume an interrupted run."""
    async with request.app.state.database.session_scope() as session:
        try:
            result = await OrganizationProvisioning(
                session, resolver=request.app.state.secret_resolver
            ).provision(
                operator,
                ProvisionOrganization(
                    slug=body.slug,
                    display_name=body.display_name,
                    configuration=body.configuration,
                    administrators=body.administrators,
                    advisors=body.advisors,
                    default_advisor=body.default_advisor,
                    channels=tuple(
                        ChannelAssignment(kind=item.kind, external_id=item.external_id)
                        for item in body.channels
                    ),
                    credentials=tuple(
                        CredentialAssignment(
                            provider=item.provider, reference=item.reference
                        )
                        for item in body.credentials
                    ),
                    add_ons=tuple(body.add_ons),
                    reason=body.reason,
                    command_key=body.command_key,
                ),
            )
        except CommercialError as exc:
            return _refusal(exc)
    return _json(
        {
            "result": "ok" if result.operable else "incomplete",
            "run_id": str(result.run_id),
            "organization_id": (
                str(result.organization_id)
                if result.organization_id is not None
                else None
            ),
            "state": result.state.value,
            "failure": result.failure,
            "steps": [
                {
                    "name": step.name,
                    "label": step.label,
                    "state": step.state.value,
                    "detail": dict(step.detail),
                }
                for step in result.steps
            ],
        },
        status_code=200 if result.operable else 409,
    )


@router.post("/organizations/{organization_id}/deprovision")
async def deprovision(
    request: Request,
    organization_id: uuid.UUID,
    body: ReasonBody,
    operator: PlatformOperator = Depends(require_platform_operator),
) -> JSONResponse:
    """Stop serving one Organization. Its data is retained."""
    async with request.app.state.database.session_scope() as session:
        try:
            result = await OrganizationProvisioning(session).deprovision(
                operator,
                DeprovisionOrganization(
                    organization_id=organization_id,
                    reason=body.reason,
                    command_key=body.command_key,
                ),
            )
        except CommercialError as exc:
            return _refusal(exc)
    return _json(
        {
            "result": "ok",
            "state": result.state.value,
            "undone": [step.name for step in result.steps],
            "data_retained": True,
        }
    )


@router.post("/organizations/{organization_id}/suspend")
async def suspend(
    request: Request,
    organization_id: uuid.UUID,
    body: ReasonBody,
    operator: PlatformOperator = Depends(require_platform_operator),
) -> JSONResponse:
    async with request.app.state.database.session_scope() as session:
        try:
            organization = await OrganizationProvisioning(session).suspend(
                operator, organization_id=organization_id, reason=body.reason
            )
            await session.commit()
        except CommercialError as exc:
            return _refusal(exc)
        return _json({"result": "ok", "status": organization.status})


@router.post("/organizations/{organization_id}/resume")
async def resume(
    request: Request,
    organization_id: uuid.UUID,
    body: ReasonBody,
    operator: PlatformOperator = Depends(require_platform_operator),
) -> JSONResponse:
    async with request.app.state.database.session_scope() as session:
        try:
            organization = await OrganizationProvisioning(session).resume(
                operator, organization_id=organization_id, reason=body.reason
            )
            await session.commit()
        except CommercialError as exc:
            return _refusal(exc)
        return _json({"result": "ok", "status": organization.status})


@router.post("/runs/{run_id}/rollback")
async def rollback(
    request: Request,
    run_id: uuid.UUID,
    body: ReasonBody,
    operator: PlatformOperator = Depends(require_platform_operator),
) -> JSONResponse:
    async with request.app.state.database.session_scope() as session:
        try:
            result = await OrganizationProvisioning(session).rollback(
                operator, run_id=run_id, reason=body.reason
            )
        except CommercialError as exc:
            return _refusal(exc)
    return _json(
        {
            "result": "ok",
            "state": result.state.value,
            "undone": [step.name for step in result.steps],
        }
    )


# -- Configuration, entitlements, credentials, channels -----------------------


@router.put("/organizations/{organization_id}/configuration")
async def record_configuration(
    request: Request,
    organization_id: uuid.UUID,
    body: ConfigurationBody,
    operator: PlatformOperator = Depends(require_platform_operator),
) -> JSONResponse:
    async with request.app.state.database.session_scope() as session:
        try:
            view = await OrganizationConfiguration(session).record(
                operator,
                RecordConfiguration(
                    organization_id=organization_id,
                    document=body.document,
                    reason=body.reason,
                    command_key=body.command_key,
                ),
            )
            await session.commit()
        except CommercialError as exc:
            return _refusal(exc)
        return _json(
            {
                "result": "ok",
                "version": view.version,
                "checksum": view.checksum,
                "sections": sorted(view.document),
            }
        )


@router.get("/organizations/{organization_id}/configuration")
async def read_configuration(
    request: Request, organization_id: uuid.UUID
) -> JSONResponse:
    async with request.app.state.database.session_scope() as session:
        history = await OrganizationConfiguration(session).history(organization_id)
        return _json(
            {
                "versions": [
                    {
                        "version": item.version,
                        "checksum": item.checksum,
                        "note": item.note,
                        "recorded_by": item.recorded_by,
                        "recorded_at": item.recorded_at,
                        "is_current": item.is_current,
                        "document": item.document,
                    }
                    for item in history.versions
                ]
            }
        )


@router.put("/organizations/{organization_id}/entitlements")
async def grant_entitlement(
    request: Request,
    organization_id: uuid.UUID,
    body: EntitlementBody,
    operator: PlatformOperator = Depends(require_platform_operator),
) -> JSONResponse:
    async with request.app.state.database.session_scope() as session:
        try:
            row = await Entitlements(session).grant(
                operator,
                GrantEntitlement(
                    organization_id=organization_id,
                    capability=body.capability,
                    state=body.state,
                    limit_value=body.limit_value,
                    reason=body.reason,
                ),
            )
            await session.commit()
        except CommercialError as exc:
            return _refusal(exc)
        return _json(
            {
                "result": "ok",
                "capability": row.capability,
                "state": row.state,
                "limit": row.limit_value,
            }
        )


@router.get("/organizations/{organization_id}/entitlements")
async def read_entitlements(
    request: Request, organization_id: uuid.UUID
) -> JSONResponse:
    async with request.app.state.database.session_scope() as session:
        summary = await Entitlements(session).summary(organization_id)
        return _json(
            {
                "entitlements": [
                    {
                        "capability": item.capability.value,
                        "label": CAPABILITY_LABELS.get(
                            item.capability, item.capability.value
                        ),
                        "permitted": item.permitted,
                        "reason": item.reason,
                        "detail": item.detail,
                        "limit": item.limit,
                        "used": item.used,
                        "remaining": item.remaining,
                        "source": item.source.value if item.source else None,
                        "tier": item.tier,
                    }
                    for item in summary
                ]
            }
        )


@router.put("/organizations/{organization_id}/credentials")
async def record_credential(
    request: Request,
    organization_id: uuid.UUID,
    body: CredentialRecordBody,
    operator: PlatformOperator = Depends(require_platform_operator),
) -> JSONResponse:
    """Register or rotate where one provider credential lives.

    The body is deliberately three named fields — provider, reference, reason —
    and ``extra: forbid``, so a caller who reaches for a field to put the
    credential in is refused rather than accommodated.
    """
    async with request.app.state.database.session_scope() as session:
        try:
            row = await IntegrationCredentials(
                session, request.app.state.secret_resolver
            ).record(
                operator,
                RecordSecretReference(
                    organization_id=organization_id,
                    provider=body.provider,
                    reference=body.reference,
                    command_key=f"credential:{organization_id}:{body.provider.value}",
                    reason=body.reason,
                ),
            )
            await session.commit()
        except CommercialError as exc:
            return _refusal(exc)
        return _json(
            {
                "result": "ok",
                "provider": row.provider,
                "reference": row.reference,
                "state": row.state,
                # Whether the name resolves to anything *here*. Not whether the
                # provider accepts it — only the provider knows that.
                "resolves": row.fingerprint is not None,
            }
        )


@router.put("/organizations/{organization_id}/channels")
async def bind_channel(
    request: Request,
    organization_id: uuid.UUID,
    body: ChannelBody,
    operator: PlatformOperator = Depends(require_platform_operator),
) -> JSONResponse:
    async with request.app.state.database.session_scope() as session:
        try:
            binding = await OrganizationRouting(session).bind(
                organization_id=organization_id,
                kind=body.kind,
                external_id=body.external_id,
                recorded_by=operator.label,
            )
            await session.commit()
        except CommercialError as exc:
            return _refusal(exc)
        return _json(
            {
                "result": "ok",
                "kind": binding.kind,
                "external_id": binding.external_id,
                "state": binding.state,
            }
        )


# -- Support access -----------------------------------------------------------


@router.post("/organizations/{organization_id}/support-access")
async def grant_support(
    request: Request,
    organization_id: uuid.UUID,
    body: SupportBody,
    operator: PlatformOperator = Depends(require_platform_operator),
) -> JSONResponse:
    """Issue temporary read-only access into one Organization's records."""
    async with request.app.state.database.session_scope() as session:
        try:
            grant = await SupportAccess(session).grant(
                operator,
                GrantSupportAccess(
                    organization_id=organization_id,
                    engineer_login=body.engineer_login,
                    reason=body.reason,
                    command_key=body.command_key,
                    hours=body.hours,
                    request_reference=body.request_reference,
                ),
            )
            await session.commit()
        except CommercialError as exc:
            return _refusal(exc)
        return _json(
            {
                "result": "ok",
                "grant_id": str(grant.grant_id),
                "login": grant.subject_login,
                "expires_at": grant.expires_at,
                "scope": "ReadOnly",
            }
        )


@router.post("/support-access/{grant_id}/revoke")
async def revoke_support(
    request: Request,
    grant_id: uuid.UUID,
    body: ReasonBody,
    operator: PlatformOperator = Depends(require_platform_operator),
) -> JSONResponse:
    async with request.app.state.database.session_scope() as session:
        try:
            grant = await SupportAccess(session).revoke(
                operator, grant_id=grant_id, reason=body.reason
            )
            await session.commit()
        except CommercialError as exc:
            return _refusal(exc)
        return _json({"result": "ok", "revoked_at": grant.revoked_at})


@router.get("/support-access")
async def list_support(request: Request) -> JSONResponse:
    async with request.app.state.database.session_scope() as session:
        grants = await SupportAccess(session).grants()
        return _json(
            {
                "grants": [
                    {
                        "grant_id": str(item.grant_id),
                        "organization": item.organization_slug,
                        "login": item.subject_login,
                        "reason": item.reason,
                        "request_reference": item.request_reference,
                        "granted_by": item.granted_by,
                        "granted_at": item.granted_at,
                        "expires_at": item.expires_at,
                        "revoked_at": item.revoked_at,
                        "use_count": item.use_count,
                        "state": item.state,
                    }
                    for item in grants
                ]
            }
        )


# -- Usage, import, and the data lifecycle ------------------------------------


@router.get("/organizations/{organization_id}/usage")
async def read_usage(request: Request, organization_id: uuid.UUID) -> JSONResponse:
    async with request.app.state.database.session_scope() as session:
        usage = await PlatformUsage(session).read(organization_id)
        return _json(
            {
                "period_start": usage.period_start,
                "readings": [
                    {
                        "metric": item.metric.value,
                        "label": item.label,
                        "quantity": item.quantity,
                        "unit": item.unit,
                    }
                    for item in usage.readings
                ],
            }
        )


@router.post("/organizations/{organization_id}/import/dry-run")
async def import_dry_run(
    request: Request,
    organization_id: uuid.UUID,
    body: ImportBody,
    operator: PlatformOperator = Depends(require_platform_operator),
) -> JSONResponse:
    return await _import(request, organization_id, body, operator, apply=False)


@router.post("/organizations/{organization_id}/import/apply")
async def import_apply(
    request: Request,
    organization_id: uuid.UUID,
    body: ImportBody,
    operator: PlatformOperator = Depends(require_platform_operator),
) -> JSONResponse:
    return await _import(request, organization_id, body, operator, apply=True)


@router.post("/import-runs/{run_id}/rollback")
async def import_rollback(
    request: Request,
    run_id: uuid.UUID,
    body: ReasonBody,
    operator: PlatformOperator = Depends(require_platform_operator),
) -> JSONResponse:
    async with request.app.state.database.session_scope() as session:
        try:
            report = await OrganizationImport(session).roll_back(
                operator, run_id=run_id, reason=body.reason
            )
        except CommercialError as exc:
            return _refusal(exc)
    return _json({"result": "ok", "state": report.state.value})


@router.post("/organizations/{organization_id}/export")
async def export_data(
    request: Request,
    organization_id: uuid.UUID,
    body: ReasonBody,
    operator: PlatformOperator = Depends(require_platform_operator),
) -> JSONResponse:
    async with request.app.state.database.session_scope() as session:
        try:
            result = await OrganizationDataLifecycle(
                session, root=_export_root(request)
            ).export(
                operator,
                ExportOrganizationData(
                    organization_id=organization_id,
                    reason=body.reason,
                    command_key=body.command_key,
                ),
            )
        except CommercialError as exc:
            return _refusal(exc)
    return _json(
        {
            "result": "ok",
            "artifact_path": result.artifact_path,
            "checksum": result.checksum,
            "byte_size": result.byte_size,
            "tables": result.tables,
            "rows": result.rows,
            "withheld": result.withheld,
        }
    )


@router.post("/organizations/{organization_id}/delete")
async def delete_data(
    request: Request,
    organization_id: uuid.UUID,
    body: DeletionBody,
    operator: PlatformOperator = Depends(require_platform_operator),
) -> JSONResponse:
    async with request.app.state.database.session_scope() as session:
        try:
            result = await OrganizationDataLifecycle(session).delete(
                operator,
                DeleteOrganizationData(
                    organization_id=organization_id,
                    scope=body.scope,
                    reason=body.reason,
                    command_key=body.command_key,
                ),
            )
        except CommercialError as exc:
            return _refusal(exc)
    return _json(
        {
            "result": "ok" if result.state.value == "Completed" else "blocked",
            "state": result.state.value,
            "deleted_rows": result.deleted,
            "deleted_tables": result.deleted_counts,
            "retained_rows": result.retained,
            "blocked_reason": result.blocked_reason,
        },
        status_code=200 if result.state.value == "Completed" else 409,
    )


@router.post("/organizations/{organization_id}/retention-holds")
async def record_hold(
    request: Request,
    organization_id: uuid.UUID,
    body: HoldBody,
    operator: PlatformOperator = Depends(require_platform_operator),
) -> JSONResponse:
    async with request.app.state.database.session_scope() as session:
        try:
            hold = await OrganizationDataLifecycle(session).record_hold(
                operator,
                RecordRetentionHold(
                    organization_id=organization_id,
                    basis=body.basis,
                    authority=body.authority,
                    description=body.description,
                    expires_at=body.expires_at,
                ),
            )
        except CommercialError as exc:
            return _refusal(exc)
    return _json({"result": "ok", "hold_id": str(hold.id)})


@router.post("/retention-holds/{hold_id}/release")
async def release_hold(
    request: Request,
    hold_id: uuid.UUID,
    body: ReasonBody,
    operator: PlatformOperator = Depends(require_platform_operator),
) -> JSONResponse:
    async with request.app.state.database.session_scope() as session:
        try:
            hold = await OrganizationDataLifecycle(session).release_hold(
                operator, hold_id=hold_id, reason=body.reason
            )
        except CommercialError as exc:
            return _refusal(exc)
    return _json({"result": "ok", "released_at": hold.released_at})


def _export_root(request: Request) -> Path:
    return Path(request.app.state.settings.organization_export_root)


async def _import(
    request: Request,
    organization_id: uuid.UUID,
    body: ImportBody,
    operator: PlatformOperator,
    *,
    apply: bool,
) -> JSONResponse:
    """One entry point for both modes, so their reports cannot diverge."""
    plan = ImportPlan(
        organization_id=organization_id,
        source=body.source,
        records=tuple(
            IncomingProperty(
                source_reference=item.source_reference,
                property_key=item.property_key,
                name=item.name,
                property_type=item.property_type,
                facts=item.facts,
                visit_address=item.visit_address,
            )
            for item in body.records
        ),
        reason=body.reason,
        command_key=body.command_key,
    )
    async with request.app.state.database.session_scope() as session:
        importer = OrganizationImport(session)
        try:
            report = (
                await importer.apply(operator, plan)
                if apply
                else await importer.plan(operator, plan)
            )
        except CommercialError as exc:
            return _refusal(exc)
    return _json(
        {
            "result": "ok",
            "run_id": str(report.run_id),
            "mode": report.mode.value,
            "state": report.state.value,
            "summary": report.summary,
            "provenance": dict(report.provenance),
            "findings": [
                {
                    "ordinal": item.ordinal,
                    "kind": item.kind.value,
                    "source_reference": item.source_reference,
                    "detail": item.detail,
                    "created_record_id": (
                        str(item.created_record_id)
                        if item.created_record_id is not None
                        else None
                    ),
                }
                for item in report.findings
            ],
        }
    )


# -- The Organization's own read-only view ------------------------------------

organization_router = APIRouter(prefix="/crm/plataforma", tags=["platform-panel"])


@organization_router.get("", response_class=HTMLResponse)
async def organization_panel(
    request: Request, actor: Actor = Depends(require_administrator)
) -> HTMLResponse:
    """What this Organization is configured with, entitled to, and who looked.

    Read-only, Administrator-only, and about the caller's own Organization by
    construction — there is no identifier on this route to point somewhere else.

    The support-access list is the part that matters. A customer on a managed
    platform has to be able to see, without asking, every time Maia's own team
    was given access to their records, for how long, and why (ADR-0054).
    """
    async with request.app.state.database.session_scope() as session:
        configuration = await OrganizationConfiguration(session).try_current(
            actor.organization_id
        )
        summary = await Entitlements(session).summary(actor.organization_id)
        references = await IntegrationCredentials(
            session, request.app.state.secret_resolver
        ).inventory(actor)
        bindings = await OrganizationRouting(session).bindings(actor.organization_id)
        grants = await SupportAccess(session).grants(actor.organization_id)
        usage = await PlatformUsage(session).read(actor.organization_id)
        holds = await OrganizationDataLifecycle(session).live_holds(
            actor.organization_id
        )

    advisors = next(
        (
            item
            for item in summary
            if item.capability is Capability.ADVISOR_SEATS
        ),
        None,
    )
    tier = tier_for(advisors.used or 0) if advisors is not None else None

    configuration_card = (
        '<div class="card"><h2>Configuración</h2>'
        f"<p>Versión <strong>{configuration.version}</strong> · registrada por "
        f"{escape(configuration.recorded_by)} el "
        f"{escape(local(configuration.recorded_at))}</p>"
        f'<p class="muted">{escape(configuration.note)}</p>'
        f'<p class="hint">Secciones: '
        f"{escape(', '.join(sorted(configuration.document)))}</p></div>"
        if configuration is not None
        else '<div class="card"><h2>Configuración</h2>'
        '<p class="hint">Aún no hay una configuración registrada para esta '
        "organización.</p></div>"
    )

    entitlement_rows = "".join(
        "<tr>"
        f"<td>{escape(CAPABILITY_LABELS.get(item.capability, item.capability.value))}</td>"
        f'<td><span class="tag {"ok" if item.permitted else "bad"}">'
        f'{"Incluida" if item.permitted else "No incluida"}</span></td>'
        f"<td>{escape(item.limit if item.limit is not None else 'Sin límite')}</td>"
        f"<td>{escape(item.used if item.used is not None else '—')}</td>"
        f"<td>{escape(item.detail)}</td>"
        "</tr>"
        for item in summary
    )

    reference_rows = "".join(
        "<tr>"
        f"<td>{escape(row.provider)}</td>"
        f"<td><code>{escape(row.reference)}</code></td>"
        f"<td>{escape(row.state)}</td>"
        f"<td>{escape(local(row.rotated_at) if row.rotated_at else '—')}</td>"
        "</tr>"
        for row in references
    )

    binding_rows = "".join(
        "<tr>"
        f"<td>{escape(row.kind)}</td>"
        f"<td><code>{escape(row.external_id)}</code></td>"
        f"<td>{escape(local(row.bound_at))}</td>"
        "</tr>"
        for row in bindings
    )

    grant_rows = "".join(
        "<tr>"
        f"<td>{escape(item.subject_login)}</td>"
        f"<td>{escape(item.state)}</td>"
        f"<td>{escape(local(item.granted_at))}</td>"
        f"<td>{escape(local(item.expires_at))}</td>"
        f"<td>{escape(item.reason)}</td>"
        f"<td>{escape(item.use_count)}</td>"
        "</tr>"
        for item in grants
    )

    usage_rows = "".join(
        "<tr>"
        f"<td>{escape(item.label)}</td>"
        f"<td>{escape(item.quantity)}</td>"
        f"<td>{escape(item.unit)}</td>"
        "</tr>"
        for item in usage.readings
    )

    hold_note = (
        '<div class="warn" role="status">'
        "Hay una retención vigente sobre la información de esta organización, "
        "por lo que una solicitud de eliminación se rechazará mientras siga "
        f"activa: {escape('; '.join(hold.authority for hold in holds))}.</div>"
        if holds
        else ""
    )

    content = (
        "<h1>Plataforma</h1>"
        '<p class="muted">Lo que Maia tiene registrado sobre esta organización: '
        "su configuración vigente, lo que incluye su plan, de dónde salen sus "
        "credenciales y cada acceso temporal del equipo de Maia a su "
        "información.</p>"
        f"{hold_note}"
        f"{configuration_card}"
        + (
            f'<div class="card"><h2>Plan</h2><p>Nivel actual: '
            f"<strong>{escape(tier.name)}</strong> — {escape(tier.description)}</p>"
            '<p class="hint">Los niveles describen el tamaño de la operación. '
            "Maia no cobra ni factura desde este producto.</p></div>"
            if tier is not None
            else ""
        )
        + table(
            "Capacidades incluidas en el plan de esta organización",
            ("Capacidad", "Estado", "Límite", "En uso", "Detalle"),
            entitlement_rows,
            empty_message="Aún no hay capacidades registradas.",
        )
        + table(
            "Uso medido del mes en curso",
            ("Medida", "Cantidad", "Unidad"),
            usage_rows,
            empty_message="Aún no hay uso medido.",
            empty_hint="El cálculo se actualiza cada hora.",
        )
        + table(
            "Referencias de credenciales de esta organización",
            ("Proveedor", "Referencia", "Estado", "Última rotación"),
            reference_rows,
            empty_message="No hay credenciales registradas.",
            empty_hint=(
                "Una referencia es el nombre del lugar donde vive la credencial. "
                "El valor nunca se guarda ni se muestra."
            ),
        )
        + table(
            "Canales asignados a esta organización",
            ("Tipo", "Identificador", "Desde"),
            binding_rows,
            empty_message="No hay canales asignados.",
        )
        + table(
            "Accesos temporales del equipo de Maia a esta información",
            ("Usuario", "Estado", "Otorgado", "Expira", "Motivo", "Usos"),
            grant_rows,
            empty_message="Nadie del equipo de Maia ha tenido acceso.",
            empty_hint=(
                "Todo acceso de soporte es de sólo lectura, temporal y queda "
                "registrado aquí."
            ),
        )
    )
    return shell(actor, "Plataforma", content, active="/crm/plataforma")
