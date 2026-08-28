"""Administrator controls for read-only external inventory."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.api.operator import require_administrator, shell, tag
from realestate.api.ui import empty, escape, flash, local, table
from realestate.db.models import ExternalInventoryScope, ListingAvailability
from realestate.domain.clock import utc_now
from realestate.domain.commercial.actors import Actor, CommercialError
from realestate.domain.external_inventory.health import InventorySourceHealth
from realestate.domain.external_inventory.inventory import ExternalInventory
from realestate.domain.external_inventory.types import (
    AdministrationCandidateView,
    SourceHealthView,
)

router = APIRouter(prefix="/crm/inventario-externo", tags=["inventario-externo"])
ACTIVE = "/crm/inventario-externo"


def _inventory(
    request: Request, session: AsyncSession, actor: Actor
) -> ExternalInventory:
    return ExternalInventory(session, actor, request.app.state.easybroker)


def _page(
    actor: Actor,
    health: SourceHealthView,
    rows: tuple[AdministrationCandidateView, ...],
    *,
    message: str | None = None,
) -> HTMLResponse:
    health_content = (
        '<section class="card"><h2>Salud de EasyBroker</h2><div class="grid">'
        f"<p><strong>Estado</strong><br>{tag(health.status, 'ok' if health.status == 'Healthy' else 'warn')}</p>"
        f"<p><strong>Credencial</strong><br>{escape('Configurada' if health.credential_configured else 'No configurada')}</p>"
        f"<p><strong>Acceso API MLS</strong><br>{escape('Confirmado' if health.mls_access_confirmed else 'No confirmado')}</p>"
        f"<p><strong>Permiso de retención</strong><br>{escape('Confirmado' if health.retention_permission_confirmed else 'No confirmado')}</p>"
        f"<p><strong>Último éxito</strong><br>{escape(local(health.last_success_at))}</p>"
        f"<p><strong>Último error</strong><br>{escape(health.last_error_code or '—')}</p>"
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
        f"<td>{escape(row.municipality or 'Fuera o sin confirmar')}<br>{escape(row.source_scope)}</td>"
        f"<td>{tag(row.authority_state)}<br>{escape(row.availability)}</td>"
        f"<td>{escape(row.attribution or 'Sin atribución')}<br>{escape('Comisión conocida' if row.commission_known else 'Comisión pendiente')}</td>"
        f"<td>{escape(local(row.observed_at))}<br><span class='muted'>Vence {escape(local(row.freshness_deadline))}</span></td>"
        f"<td>{escape(', '.join(row.mapping_issues) or 'Sin incidencias de mapping')}<br>{escape(', '.join(row.changed_fields) or 'Sin cambios pendientes')}</td>"
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
    ) if rows else empty(
        "Todavía no hay candidatos externos indexados.",
        "Confirma primero la cuenta, el plan API MLS y los permisos operativos.",
    )
    return shell(
        actor,
        "Inventario externo",
        flash(message) + '<p class="lead">EasyBroker es una fuente secundaria de sólo lectura. Sus registros no crean ni sustituyen Listings autoritativos.</p>' + health_content + candidates,
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
    request: Request, actor: Actor = Depends(require_administrator)
) -> HTMLResponse:
    async with request.app.state.database.session_scope() as session:
        source = request.app.state.easybroker
        health = await InventorySourceHealth(
            session,
            actor,
            credential_configured=source.credential_configured,
            mls_access_confirmed=source.mls_access_confirmed,
            retention_permission_confirmed=source.retention_permission_confirmed,
        ).read(source.source_name)
        rows = await _inventory(request, session, actor).list_for_administration()
    return _page(actor, health, rows, message=request.query_params.get("mensaje"))


@router.post("/sincronizar")
async def synchronize_external_inventory(
    request: Request, actor: Actor = Depends(require_administrator)
) -> RedirectResponse:
    async with request.app.state.database.session_scope() as session:
        result = await _inventory(request, session, actor).synchronize(
            ExternalInventoryScope.COLLABORATOR, at=utc_now()
        )
    return RedirectResponse(
        f"{ACTIVE}?mensaje={result.status}%3A+{result.accepted}+en+zona%2C+{result.rejected}+rechazados",
        status_code=303,
    )


@router.post("/{listing_id}/revalidar")
async def refresh_external_candidate(
    listing_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_administrator),
) -> RedirectResponse:
    async with request.app.state.database.session_scope() as session:
        inventory = _inventory(request, session, actor)
        rows = await inventory.list_for_administration()
        row = next((candidate for candidate in rows if candidate.listing_id == listing_id), None)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        result = await inventory.refresh(row.source_listing_id, at=utc_now())
    return RedirectResponse(
        f"{ACTIVE}?mensaje=Actualizada%3A+{escape(', '.join(result.changed_fields) or 'sin cambios')}",
        status_code=303,
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
            await _inventory(request, session, actor).confirm_evidence(
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
    return RedirectResponse(f"{ACTIVE}?mensaje=Evidencia+registrada", status_code=303)


@router.post("/limpiar")
async def cleanup_external_cache(
    request: Request, actor: Actor = Depends(require_administrator)
) -> RedirectResponse:
    async with request.app.state.database.session_scope() as session:
        count = await _inventory(request, session, actor).purge_due(at=utc_now())
    return RedirectResponse(
        f"{ACTIVE}?mensaje={count}+candidatos+retirados+limpiados", status_code=303
    )
