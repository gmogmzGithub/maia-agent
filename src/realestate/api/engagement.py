"""Mexican-Spanish Admin controls for reviewed Stage 7 outreach."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.api.operator import require_administrator, shell, tag
from realestate.api.ui import empty, escape, flash, local, table
from realestate.db.models import (
    ApprovedMessageTemplate,
    CampaignAudienceMember,
    CatalogListing,
    Development,
    DevelopmentCampaign,
    PropertyNeed,
    ReactivationCandidate,
)
from realestate.domain.clock import utc_now
from realestate.domain.commercial.actors import Actor, CommercialError
from realestate.domain.engagement.campaigns import (
    ActivateCampaign,
    Campaigns,
    CancelCampaign,
    PauseCampaign,
    PlanCampaign,
)
from realestate.domain.engagement.reactivation import (
    AuthorizeReactivation,
    Reactivation,
    RejectReactivation,
    RevokeReactivation,
)
from realestate.domain.engagement.templates import TemplateRegistry

router = APIRouter(prefix="/crm/reactivacion", tags=["reactivacion"])
ACTIVE = "/crm/reactivacion"


@dataclass(frozen=True)
class PageData:
    templates: tuple[ApprovedMessageTemplate, ...]
    candidates: tuple[tuple[ReactivationCandidate, str], ...]
    campaigns: tuple[DevelopmentCampaign, ...]
    developments: tuple[Development, ...]
    needs: tuple[PropertyNeed, ...]
    results: dict[uuid.UUID, dict[str, int]]
    audience: tuple[CampaignAudienceMember, ...]


def _uuid_list(raw: str) -> tuple[uuid.UUID, ...]:
    values: list[uuid.UUID] = []
    for part in raw.replace("\n", ",").split(","):
        if not part.strip():
            continue
        try:
            value = uuid.UUID(part.strip())
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La audiencia contiene un identificador inválido.",
            ) from exc
        if value not in values:
            values.append(value)
    return tuple(values)


def _reactivation(
    request: Request, session: AsyncSession, actor: Actor
) -> Reactivation:
    return Reactivation(
        session,
        actor,
        activation_approved=request.app.state.settings.marketing_outbound_activated,
    )


def _campaigns(request: Request, session: AsyncSession, actor: Actor) -> Campaigns:
    return Campaigns(
        session,
        actor,
        activation_approved=request.app.state.settings.marketing_outbound_activated,
    )


async def _page_data(session: AsyncSession, actor: Actor) -> PageData:
    templates = tuple(
        await session.scalars(
            select(ApprovedMessageTemplate)
            .where(ApprovedMessageTemplate.organization_id == actor.organization_id)
            .order_by(
                ApprovedMessageTemplate.provider_status,
                ApprovedMessageTemplate.template_name,
            )
        )
    )
    candidates = tuple(
        (row, title)
        for row, title in await session.execute(
            select(ReactivationCandidate, CatalogListing.title)
            .join(CatalogListing, CatalogListing.id == ReactivationCandidate.listing_id)
            .where(ReactivationCandidate.organization_id == actor.organization_id)
            .order_by(ReactivationCandidate.created_at.desc())
        )
    )
    campaigns = tuple(
        await session.scalars(
            select(DevelopmentCampaign)
            .where(DevelopmentCampaign.organization_id == actor.organization_id)
            .order_by(DevelopmentCampaign.created_at.desc())
        )
    )
    developments = tuple(
        await session.scalars(
            select(Development)
            .where(Development.organization_id == actor.organization_id)
            .order_by(Development.name)
        )
    )
    needs = tuple(
        await session.scalars(
            select(PropertyNeed)
            .where(PropertyNeed.organization_id == actor.organization_id)
            .order_by(PropertyNeed.created_at.desc())
            .limit(100)
        )
    )
    results = {
        campaign_id: {
            state: count
            for state, count in await session.execute(
                select(CampaignAudienceMember.status, func.count())
                .where(CampaignAudienceMember.campaign_id == campaign_id)
                .group_by(CampaignAudienceMember.status)
            )
        }
        for campaign_id in (row.id for row in campaigns)
    }
    audience = (
        tuple(
            await session.scalars(
                select(CampaignAudienceMember)
                .where(
                    CampaignAudienceMember.campaign_id.in_(
                        [campaign.id for campaign in campaigns]
                    )
                )
                .order_by(
                    CampaignAudienceMember.campaign_id,
                    CampaignAudienceMember.audience_reference,
                )
            )
        )
        if campaigns
        else ()
    )
    return PageData(
        templates, candidates, campaigns, developments, needs, results, audience
    )


def _page(
    actor: Actor,
    data: PageData,
    message: str | None,
    *,
    activation_approved: bool,
) -> HTMLResponse:
    templates = data.templates
    candidates = data.candidates
    campaigns = data.campaigns
    developments = data.developments
    needs = data.needs
    results = data.results
    audience = data.audience
    template_rows = "".join(
        "<tr>"
        f"<td><strong>{escape(row.template_name)}</strong><br>{escape(row.language_code)}</td>"
        f"<td>{tag(row.provider_status, 'ok' if row.provider_status == 'Approved' else 'warn')}<br>{escape(row.category)}</td>"
        f"<td>{escape(row.quality or 'Sin señal')}<br>{escape(local(row.observed_at))}</td>"
        f"<td>{escape(row.body_text or 'Sin cuerpo estático')}</td>"
        "</tr>"
        for row in templates
    )
    template_section = (
        table(
            "Plantillas verificadas con Meta",
            ("Plantilla", "Estado", "Calidad / observación", "Contenido exacto"),
            template_rows,
            empty_message="No hay plantillas verificadas.",
            empty_hint="Sin una plantilla Marketing aprobada y vigente no puede salir ningún contacto proactivo.",
        )
        if templates
        else empty(
            "No hay plantillas verificadas.",
            "Sin una plantilla Marketing aprobada y vigente no puede salir ningún contacto proactivo.",
        )
    )
    candidate_rows = "".join(
        "<tr>"
        f"<td><strong>{escape(title)}</strong><br><span class='muted'>{escape(row.id)}</span></td>"
        f"<td>{tag(row.match_kind)}<br>{escape(row.rule_version)}</td>"
        f"<td>{tag(row.status, 'bad' if row.status == 'Denied' else '')}<br>{escape(row.review_reason or 'Pendiente de revisión')}</td>"
        f"<td>{_candidate_controls(row)}</td>"
        "</tr>"
        for row, title in candidates
    )
    candidate_section = (
        table(
            "Candidatos de reactivación",
            ("Publicación", "Coincidencia", "Decisión", "Controles"),
            candidate_rows,
            empty_message="No hay candidatos.",
            empty_hint="Buscar una publicación sólo propone coincidencias; nunca envía.",
        )
        if candidates
        else empty(
            "No hay candidatos.",
            "Buscar una publicación sólo propone coincidencias; nunca envía.",
        )
    )
    campaign_rows = "".join(
        "<tr>"
        f"<td><strong>{escape(row.name)}</strong><br><span class='muted'>{escape(row.id)}</span></td>"
        f"<td>{tag(row.status)}<br>{escape(row.criteria_version)}</td>"
        f"<td>{escape(' · '.join(f'{key}: {value}' for key, value in results.get(row.id, {}).items()) or 'Sin audiencia')}</td>"
        f"<td>{escape(row.frequency_cap)} cada {escape(row.frequency_window_days)} días · máximo {escape(row.max_recipients)}<br>Silencio {escape(row.quiet_hours_start)}:00–{escape(row.quiet_hours_end)}:00</td>"
        f"<td>{_campaign_controls(row)}</td>"
        "</tr>"
        for row in campaigns
    )
    campaign_section = (
        table(
            "Campañas de desarrollos",
            ("Campaña", "Estado", "Resultados", "Límites", "Controles"),
            campaign_rows,
            empty_message="No hay campañas planeadas.",
            empty_hint="Toda audiencia debe nombrar necesidades concretas y muestra exclusiones antes de activarse.",
        )
        if campaigns
        else empty(
            "No hay campañas planeadas.",
            "Toda audiencia debe nombrar necesidades concretas y muestra exclusiones antes de activarse.",
        )
    )
    audience_rows = "".join(
        "<tr>"
        f"<td>{escape(row.audience_reference)}</td>"
        f"<td>{escape(row.campaign_id)}</td>"
        f"<td>{tag(row.status, 'bad' if row.status in {'Denied', 'Excluded'} else '')}</td>"
        f"<td>{escape(', '.join(row.reasons) or 'Cumple los criterios')}</td>"
        f"<td>{escape(local(row.resolved_at))}</td>"
        "</tr>"
        for row in audience
    )
    audience_section = (
        table(
            "Vista previa y resultados por referencia",
            ("Referencia", "Campaña", "Estado", "Explicación", "Resuelto"),
            audience_rows,
            empty_message="Todavía no hay una audiencia resuelta.",
            empty_hint="La vista usa referencias de Product; no muestra nombres, teléfonos ni conversaciones.",
        )
        if audience
        else empty(
            "Todavía no hay una audiencia resuelta.",
            "La vista usa referencias de Product; no muestra nombres, teléfonos ni conversaciones.",
        )
    )
    development_options = "".join(
        f'<option value="{row.id}">{escape(row.name)} · {escape(row.facts_review_state)}</option>'
        for row in developments
    )
    need_hint = ", ".join(str(row.id) for row in needs[:8]) or "Sin necesidades"
    activation = "Activado" if activation_approved else "Denied"
    controls = f"""
<section class="card"><h2>Estado de activación</h2>
<p><strong>Despacho real:</strong> {activation}. Requiere aceptación explícita de los gates legales, operativos y del proveedor.</p>
<p><strong>Consentimiento:</strong> Denied. SAN-010, aviso y ruta de captura siguen pendientes; un administrador no puede otorgarlo por el contacto.</p>
<p><strong>Proveedores reales:</strong> sólo cuentan las observaciones mostradas arriba. La presencia de credenciales no prueba aprobación, calidad ni capacidad.</p>
<form method="post" action="{ACTIVE}/plantillas/sincronizar"><button>Verificar plantillas con Meta</button></form></section>
<section class="card"><h2>Proponer reactivaciones</h2>
<form method="post" action="{ACTIVE}/descubrir"><label>ID de publicación autorizada<input name="listing_id" required></label><button>Buscar coincidencias; no enviar</button></form></section>
<section class="card"><h2>Planear campaña</h2>
<form method="post" action="{ACTIVE}/campanas">
<label>Desarrollo<select name="development_id" required>{development_options}</select></label>
<label>Nombre<input name="name" required></label>
<label>Necesidades explícitas, separadas por coma<textarea name="property_need_ids" required placeholder="{escape(need_hint)}"></textarea></label>
<label>Exclusiones explícitas, separadas por coma<textarea name="exclude_property_need_ids"></textarea></label>
<label>Zona requerida<input name="service_area_contains" placeholder="Ej. Zapopan"></label>
<div class="grid"><label>Plantilla<input name="template_name" required></label><label>Idioma exacto<input name="template_language" value="es_MX" required></label></div>
<label>Contenido exacto observado<textarea name="content_preview" required></textarea></label>
<div class="grid"><label>Tope por contacto<input type="number" name="frequency_cap" value="1" min="1"></label><label>Ventana en días<input type="number" name="frequency_window_days" value="30" min="1"></label><label>Máximo de destinatarios<input type="number" name="max_recipients" value="50" min="1" max="500"></label></div>
<button>Guardar borrador y resolver audiencia</button></form></section>"""
    return shell(
        actor,
        "Reactivación y campañas",
        flash(message)
        + '<p class="lead">Cada destinatario, contenido y momento queda explicado. Ninguna revisión administrativa evita consentimiento, supresión o plantilla vigente.</p>'
        + controls
        + template_section
        + candidate_section
        + campaign_section
        + audience_section,
        active=ACTIVE,
    )


def _candidate_controls(row: ReactivationCandidate) -> str:
    if row.status == "Pending":
        return f"""<details><summary>Revisar</summary><form method="post" action="{ACTIVE}/candidatos/{row.id}/autorizar">
<label>Plantilla<input name="template_name" required></label><label>Idioma<input name="template_language" value="es_MX" required></label><label>Contenido exacto<textarea name="message_preview" required></textarea></label><label>Motivo de autorización<input name="reason" required></label><button>Autorizar para ejecución</button></form>
<form method="post" action="{ACTIVE}/candidatos/{row.id}/rechazar"><label>Motivo<input name="reason" required></label><button class="secondary">Rechazar</button></form></details>"""
    if row.status == "Authorized":
        return f'<form method="post" action="{ACTIVE}/candidatos/{row.id}/revocar"><input name="reason" value="Decisión administrativa" required><button class="secondary">Revocar antes del envío</button></form>'
    return "Sin acciones nuevas"


def _campaign_controls(row: DevelopmentCampaign) -> str:
    controls: list[str] = []
    if row.status in {"Draft", "Paused"}:
        controls.append(
            f'<form method="post" action="{ACTIVE}/campanas/{row.id}/activar"><button>Activar</button></form>'
        )
    if row.status == "Active":
        controls.append(
            f'<form method="post" action="{ACTIVE}/campanas/{row.id}/pausar"><input type="hidden" name="reason" value="Pausa administrativa"><button class="secondary">Pausar</button></form>'
        )
    if row.status != "Cancelled":
        controls.append(
            f'<form method="post" action="{ACTIVE}/campanas/{row.id}/cancelar"><input type="hidden" name="reason" value="Cancelación administrativa"><button class="secondary">Cancelar</button></form>'
        )
    return "".join(controls) or "Sin acciones nuevas"


@router.get("", response_class=HTMLResponse)
async def engagement_page(
    request: Request, actor: Actor = Depends(require_administrator)
) -> HTMLResponse:
    async with request.app.state.database.session_scope() as session:
        data = await _page_data(session, actor)
    return _page(
        actor,
        data,
        request.query_params.get("mensaje"),
        activation_approved=request.app.state.settings.marketing_outbound_activated,
    )


@router.post("/plantillas/sincronizar")
async def synchronize_templates(
    request: Request, actor: Actor = Depends(require_administrator)
) -> RedirectResponse:
    try:
        async with request.app.state.database.session_scope() as session:
            result = await TemplateRegistry(session).synchronize(
                actor, request.app.state.meta_templates, at=utc_now()
            )
            await session.commit()
    except CommercialError as exc:
        return RedirectResponse(
            f"{ACTIVE}?mensaje={escape(exc.message)}", status_code=303
        )
    return RedirectResponse(
        f"{ACTIVE}?mensaje={result.observed}+plantillas+observadas", status_code=303
    )


@router.post("/descubrir")
async def discover_reactivations(
    request: Request, actor: Actor = Depends(require_administrator)
) -> RedirectResponse:
    form = await request.form()
    try:
        listing_id = uuid.UUID(str(form.get("listing_id", "")))
        async with request.app.state.database.session_scope() as session:
            rows = await _reactivation(request, session, actor).discover(
                listing_id, at=utc_now()
            )
            await session.commit()
    except (ValueError, CommercialError) as exc:
        detail = exc.message if isinstance(exc, CommercialError) else "ID inválido."
        raise HTTPException(status_code=400, detail=detail) from exc
    return RedirectResponse(f"{ACTIVE}?mensaje={len(rows)}+candidatos", status_code=303)


@router.post("/candidatos/{candidate_id}/autorizar")
async def authorize_candidate(
    candidate_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_administrator),
) -> RedirectResponse:
    form = await request.form()
    try:
        async with request.app.state.database.session_scope() as session:
            row = await _reactivation(request, session, actor).authorize(
                AuthorizeReactivation(
                    candidate_id,
                    str(form.get("template_name", "")),
                    str(form.get("template_language", "")),
                    str(form.get("message_preview", "")),
                    str(form.get("reason", "")),
                ),
                at=utc_now(),
            )
            await session.commit()
    except CommercialError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return RedirectResponse(f"{ACTIVE}?mensaje={escape(row.status)}", status_code=303)


@router.post("/candidatos/{candidate_id}/rechazar")
async def reject_candidate(
    candidate_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_administrator),
) -> RedirectResponse:
    form = await request.form()
    try:
        async with request.app.state.database.session_scope() as session:
            await _reactivation(request, session, actor).reject(
                RejectReactivation(candidate_id, str(form.get("reason", ""))),
                at=utc_now(),
            )
            await session.commit()
    except CommercialError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return RedirectResponse(f"{ACTIVE}?mensaje=Candidato+rechazado", status_code=303)


@router.post("/candidatos/{candidate_id}/revocar")
async def revoke_candidate(
    candidate_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_administrator),
) -> RedirectResponse:
    form = await request.form()
    try:
        async with request.app.state.database.session_scope() as session:
            await _reactivation(request, session, actor).revoke(
                RevokeReactivation(candidate_id, str(form.get("reason", ""))),
                at=utc_now(),
            )
            await session.commit()
    except CommercialError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return RedirectResponse(f"{ACTIVE}?mensaje=Autorización+revocada", status_code=303)


@router.post("/campanas")
async def plan_campaign(
    request: Request, actor: Actor = Depends(require_administrator)
) -> RedirectResponse:
    form = await request.form()
    try:
        command = PlanCampaign(
            development_id=uuid.UUID(str(form.get("development_id", ""))),
            name=str(form.get("name", "")),
            property_need_ids=_uuid_list(str(form.get("property_need_ids", ""))),
            exclude_property_need_ids=_uuid_list(
                str(form.get("exclude_property_need_ids", ""))
            ),
            template_name=str(form.get("template_name", "")),
            template_language=str(form.get("template_language", "")),
            content_preview=str(form.get("content_preview", "")),
            service_area_contains=str(form.get("service_area_contains", "")),
            frequency_cap=int(str(form.get("frequency_cap", "1"))),
            frequency_window_days=int(str(form.get("frequency_window_days", "30"))),
            max_recipients=int(str(form.get("max_recipients", "50"))),
        )
        async with request.app.state.database.session_scope() as session:
            result = await _campaigns(request, session, actor).plan(
                command, at=utc_now()
            )
            await session.commit()
    except (ValueError, CommercialError) as exc:
        detail = exc.message if isinstance(exc, CommercialError) else "Datos inválidos."
        raise HTTPException(status_code=400, detail=detail) from exc
    return RedirectResponse(
        f"{ACTIVE}?mensaje=Campaña+en+borrador+{result.campaign_id}", status_code=303
    )


@router.post("/campanas/{campaign_id}/activar")
async def activate_campaign(
    campaign_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_administrator),
) -> RedirectResponse:
    try:
        async with request.app.state.database.session_scope() as session:
            await _campaigns(request, session, actor).activate(
                ActivateCampaign(campaign_id), at=utc_now()
            )
            await session.commit()
    except CommercialError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return RedirectResponse(f"{ACTIVE}?mensaje=Campaña+activa", status_code=303)


@router.post("/campanas/{campaign_id}/pausar")
async def pause_campaign(
    campaign_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_administrator),
) -> RedirectResponse:
    form = await request.form()
    try:
        async with request.app.state.database.session_scope() as session:
            await _campaigns(request, session, actor).pause(
                PauseCampaign(campaign_id, str(form.get("reason", ""))), at=utc_now()
            )
            await session.commit()
    except CommercialError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return RedirectResponse(f"{ACTIVE}?mensaje=Campaña+pausada", status_code=303)


@router.post("/campanas/{campaign_id}/cancelar")
async def cancel_campaign(
    campaign_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_administrator),
) -> RedirectResponse:
    form = await request.form()
    try:
        async with request.app.state.database.session_scope() as session:
            await _campaigns(request, session, actor).cancel(
                CancelCampaign(campaign_id, str(form.get("reason", ""))), at=utc_now()
            )
            await session.commit()
    except CommercialError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return RedirectResponse(f"{ACTIVE}?mensaje=Campaña+cancelada", status_code=303)
