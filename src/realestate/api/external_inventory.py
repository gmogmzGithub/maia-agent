"""Administrator controls for read-only external inventory."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.api.operator import (
    redirect_back,
    require_administrator,
    shell,
    tag,
)
from realestate.api.ui import errors_box, escape, flash, local, table
from realestate.db.models import (
    ExternalCandidateState,
    ExternalInventoryScope,
    InventorySourceStatus,
    ListingAvailability,
)
from realestate.domain.clock import utc_now
from realestate.domain.commercial.actors import Actor, CommercialError, NotFound
from realestate.domain.external_inventory.health import InventorySourceHealth
from realestate.domain.external_inventory.inventory import ExternalInventory
from realestate.domain.external_inventory.types import (
    AdministrationCandidateView,
    SourceHealthView,
)

router = APIRouter(prefix="/crm/inventario-externo", tags=["inventario-externo"])
ACTIVE = "/crm/inventario-externo"


# Every operator-visible value is Mexican Spanish: the provider speaks English
# enum values and snake_case fault codes, and an Administrator reading this page
# must never be shown either. Unknown codes fall back to the raw string so a new
# provider fault stays visible instead of rendering blank.
STATUS_LABELS = {
    InventorySourceStatus.DISABLED.value: "Desactivada",
    InventorySourceStatus.NEVER_SYNCED.value: "Sin sincronizar",
    InventorySourceStatus.HEALTHY.value: "Sin incidencias",
    InventorySourceStatus.PARTIAL.value: "Parcial",
    InventorySourceStatus.RATE_LIMITED.value: "Límite de consultas alcanzado",
    InventorySourceStatus.FAILED.value: "Con fallas",
}
SCOPE_LABELS = {
    ExternalInventoryScope.ORGANIZATION.value: "Propia de la organización",
    ExternalInventoryScope.COLLABORATOR.value: "De colaborador",
}
AUTHORITY_LABELS = {
    ExternalCandidateState.AUTHORIZED.value: "Autorizada",
    ExternalCandidateState.PENDING.value: "Autoridad pendiente",
    ExternalCandidateState.DENIED.value: "Autoridad negada",
}
AVAILABILITY_LABELS = {
    ListingAvailability.AVAILABLE.value: "Disponible",
    ListingAvailability.RESERVED.value: "Reservada",
    ListingAvailability.SOLD.value: "Vendida",
    ListingAvailability.RENTED.value: "Rentada",
    ListingAvailability.TEMPORARILY_UNAVAILABLE.value: "No disponible temporalmente",
    ListingAvailability.UNKNOWN.value: "Por confirmar",
}
ERROR_LABELS = {
    "retention_not_confirmed": "Falta confirmar el permiso de retención",
    "credential_missing": "Falta la credencial",
    "mls_not_confirmed": "Falta confirmar el acceso API MLS",
    "invalid_credential": "Credencial rechazada",
    "plan_or_permission_denied": "El plan o los permisos no autorizan la consulta",
    "rate_limited": "Límite de consultas alcanzado",
    "provider_error": "Error del proveedor",
    "invalid_response": "Respuesta inválida del proveedor",
    "invalid_cursor": "Cursor de paginación inválido",
    "not_found": "La publicación ya no existe en la fuente",
    "access_denied": "La cuenta no puede leer esta fuente",
    "transport": "No se pudo contactar al proveedor",
    "partial_records": "Algunos registros no se pudieron leer",
}
ISSUE_LABELS = {
    "missing_title": "sin título",
    "missing_attribution": "sin atribución",
    "missing_operations": "sin operación",
    "missing_or_invalid_updated_at": "sin fecha de actualización válida",
    "missing_or_unknown_municipality": "municipio ausente o fuera de zona",
    "unknown_availability": "disponibilidad desconocida",
}


def _label(mapping: dict[str, str], value: str) -> str:
    return mapping.get(value, value)


def _issues(codes: tuple[str, ...]) -> str:
    return ", ".join(_label(ISSUE_LABELS, code) for code in codes)


async def _inventory(
    request: Request, session: AsyncSession, actor: Actor
) -> ExternalInventory:
    sources = getattr(
        request.app.state,
        "easybroker_sources",
        request.app.state.easybroker,
    )
    source = (
        await sources.for_organization(session, actor.organization_id)
        if hasattr(sources, "for_organization")
        else sources
    )
    return ExternalInventory(session, actor, source)


def _page(
    actor: Actor,
    health: SourceHealthView,
    rows: tuple[AdministrationCandidateView, ...],
    *,
    message: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    health_content = (
        '<section class="card"><h2>Salud de EasyBroker</h2><div class="grid">'
        f"<p><strong>Estado</strong><br>{tag(_label(STATUS_LABELS, health.status), 'ok' if health.status == InventorySourceStatus.HEALTHY.value else 'warn')}</p>"
        f"<p><strong>Credencial</strong><br>{escape('Configurada' if health.credential_configured else 'No configurada')}</p>"
        f"<p><strong>Acceso API MLS</strong><br>{escape('Confirmado' if health.mls_access_confirmed else 'No confirmado')}</p>"
        f"<p><strong>Permiso de retención</strong><br>{escape('Confirmado' if health.retention_permission_confirmed else 'No confirmado')}</p>"
        f"<p><strong>Último éxito</strong><br>{escape(local(health.last_success_at))}</p>"
        f"<p><strong>Último error</strong><br>{escape(_label(ERROR_LABELS, health.last_error_code) if health.last_error_code else '—')}</p>"
        f"<p><strong>Conteos</strong><br>{health.fetched_count} leídos · {health.accepted_count} en zona · {health.rejected_count} rechazados</p>"
        "</div>"
        '<form method="post" action="/crm/inventario-externo/sincronizar">'
        '<button>Sincronizar colaboradores de sólo lectura</button></form>'
        '<form method="post" action="/crm/inventario-externo/limpiar" class="inline">'
        '<button class="secondary">Limpiar caché retirada cuyo plazo venció</button></form>'
        '<p class="hint">La llave nunca se muestra. Sin acceso MLS y permiso de retención confirmados, Product rechaza la consulta antes de llamar al proveedor.</p></section>'
    )
    body_rows = "".join(
        "<tr>"
        f"<td><strong>{escape(row.title or 'Sin título')}</strong><br><span class='muted'>{escape(row.source_listing_id)}</span></td>"
        f"<td>{escape(row.municipality or 'Fuera o sin confirmar')}<br>{escape(_label(SCOPE_LABELS, row.source_scope))}</td>"
        f"<td>{tag(_label(AUTHORITY_LABELS, row.authority_state))}<br>{escape(_label(AVAILABILITY_LABELS, row.availability))}</td>"
        f"<td>{escape(row.attribution or 'Sin atribución')}<br>{escape('Comisión conocida' if row.commission_known else 'Comisión pendiente')}</td>"
        f"<td>{escape(local(row.observed_at))}<br><span class='muted'>Vence {escape(local(row.freshness_deadline))}</span></td>"
        f"<td>{escape(_issues(row.mapping_issues) or 'Sin incidencias de lectura')}<br>{escape(', '.join(row.changed_fields) or 'Sin cambios pendientes')}</td>"
        f"<td>{_controls(row)}</td>"
        "</tr>"
        for row in rows
    )
    candidates = table(
        "Candidatos externos, no catálogo autoritativo",
        ("Candidato", "Zona / alcance", "Autoridad", "Procedencia", "Frescura", "Revisión", "Controles"),
        body_rows,
        empty_message="Todavía no hay candidatos externos indexados.",
        empty_hint="Confirma primero la cuenta, el plan API MLS y los permisos operativos.",
    )
    return shell(
        actor,
        "Inventario externo",
        flash(message)
        + errors_box([error] if error else [])
        + '<p class="lead">EasyBroker es una fuente secundaria de sólo lectura. Sus registros no crean ni sustituyen Listings autoritativos.</p>'
        + health_content
        + candidates,
        active=ACTIVE,
    )


def _controls(row: AdministrationCandidateView) -> str:
    if row.withdrawn_at is not None:
        state = f"Retirada · borrar antes de {escape(local(row.deletion_due_at))}"
        if row.cache_deleted_at is not None:
            state = f"Caché eliminada {escape(local(row.cache_deleted_at))}"
        return f"<p>{state}</p>"
    commission_kind = "porcentaje"
    commission_value = ""
    if row.commission:
        commission_kind = escape(row.commission.get("kind", "fuente"))
        commission_value = escape(row.commission.get("value", row.commission.get("source_value", "")))
    return f"""
<form method="post" action="/crm/inventario-externo/{row.listing_id}/revalidar">
<button class="secondary">Actualizar desde la fuente</button></form>
<details><summary>Confirmar evidencia humana</summary>
<form method="post" action="/crm/inventario-externo/{row.listing_id}/evidencia">
<label>Evidencia de autoridad<input name="evidencia" value="{escape(row.authority_evidence or '')}" required></label>
<label>Atribución<input name="atribucion" value="{escape(row.attribution or '')}" required></label>
<label>Disponibilidad<select name="disponibilidad">
<option value="Available"{' selected' if row.availability == 'Available' else ''}>Disponible confirmada</option>
<option value="Unknown"{' selected' if row.availability != 'Available' else ''}>Por confirmar</option>
</select></label>
<label class="check"><input type="checkbox" name="colaboracion" value="1"{' checked' if row.collaboration_authorized else ''}> Colaboración vigente confirmada</label>
<label>Tipo de comisión<input name="tipo_comision" value="{commission_kind}"></label>
<label>Comisión conocida<input name="comision" value="{commission_value}" placeholder="Ej. 2.5% o acuerdo escrito"></label>
<button>Guardar evidencia; no publica</button></form></details>"""


@router.get("", response_class=HTMLResponse)
async def external_inventory_page(
    request: Request,
    actor: Actor = Depends(require_administrator),
    guardado: str = "",
    error: str = "",
) -> HTMLResponse:
    async with request.app.state.database.session_scope() as session:
        sources = getattr(
            request.app.state,
            "easybroker_sources",
            request.app.state.easybroker,
        )
        source = (
            await sources.for_organization(session, actor.organization_id)
            if hasattr(sources, "for_organization")
            else sources
        )
        health = await InventorySourceHealth(
            session,
            actor,
            credential_configured=source.credential_configured,
            mls_access_confirmed=source.mls_access_confirmed,
            retention_permission_confirmed=source.retention_permission_confirmed,
        ).read(source.source_name)
        rows = await (await _inventory(request, session, actor)).list_for_administration()
    return _page(actor, health, rows, message=guardado or None, error=error or None)


@router.post("/sincronizar")
async def synchronize_external_inventory(
    request: Request, actor: Actor = Depends(require_administrator)
) -> RedirectResponse:
    async with request.app.state.database.session_scope() as session:
        result = await (await _inventory(request, session, actor)).synchronize(
            ExternalInventoryScope.COLLABORATOR, at=utc_now()
        )
    return redirect_back(
        ACTIVE,
        saved=(
            f"{_label(STATUS_LABELS, result.status)}: {result.accepted} en zona, "
            f"{result.rejected} rechazados"
        ),
    )


@router.post("/{listing_id}/revalidar")
async def refresh_external_candidate(
    listing_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_administrator),
) -> RedirectResponse:
    try:
        async with request.app.state.database.session_scope() as session:
            result = await (await _inventory(request, session, actor)).refresh_candidate(
                listing_id, at=utc_now()
            )
    except NotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=exc.message
        ) from exc
    return redirect_back(
        ACTIVE,
        saved=f"Actualizada: {', '.join(result.changed_fields) or 'sin cambios'}",
    )


@router.post("/{listing_id}/evidencia")
async def confirm_external_evidence(
    listing_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_administrator),
) -> RedirectResponse:
    form = await request.form()
    evidence = str(form.get("evidencia", "")).strip()
    attribution = str(form.get("atribucion", "")).strip()
    availability = str(form.get("disponibilidad", "Unknown"))
    if availability not in {ListingAvailability.AVAILABLE.value, ListingAvailability.UNKNOWN.value}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
    commission_text = str(form.get("comision", "")).strip()
    commission = None
    if commission_text:
        commission = {
            "kind": str(form.get("tipo_comision", "")).strip() or "manual",
            "value": commission_text,
        }
    try:
        async with request.app.state.database.session_scope() as session:
            await (await _inventory(request, session, actor)).confirm_evidence(
                listing_id,
                authority_evidence=evidence,
                attribution=attribution,
                collaboration_authorized=form.get("colaboracion") == "1",
                commission=commission,
                availability=availability,
                at=utc_now(),
            )
    except CommercialError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    return redirect_back(ACTIVE, saved="Evidencia registrada")


@router.post("/limpiar")
async def cleanup_external_cache(
    request: Request, actor: Actor = Depends(require_administrator)
) -> RedirectResponse:
    async with request.app.state.database.session_scope() as session:
        count = await (await _inventory(request, session, actor)).purge_due(at=utc_now())
    return redirect_back(ACTIVE, saved=f"{count} candidatos retirados limpiados")
