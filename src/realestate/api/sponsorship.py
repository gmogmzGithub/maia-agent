"""The Administrator's sponsorship surface: price, quote, deliver, report, share.

Everything commercial about paid visibility is on one page, in the order the sale
actually happens: publish a price catalog, open a campaign over an eligible
Listing, write the commercial clearance, quote, accept, schedule, watch delivery,
share a report.

Two things are visible here and nowhere else, deliberately. The first is
capacity, so an Administrator selling a fourth concurrent campaign sees the
refusal coming instead of discovering it at reservation. The second is the
pricing gate: while no catalog is published, this page says the first price
requires pilot data rather than offering an empty field somebody would fill in
with a guess (SAN-062).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.api.operator import (
    redirect_back,
    require_administrator,
    shell,
    tag,
)
from realestate.api.ui import (
    errors_box,
    escape,
    flash,
    local,
    parse_datetime_input,
    table,
)
from realestate.db.models import (
    CatalogListing,
    CollectionState,
    ListingPublicationState,
    PriceCatalogStatus,
    ReportAudience,
    SponsoredSurface,
    SponsorshipCampaignStatus,
)
from realestate.domain.analytics.definitions import CURRENT_DEFINITION_VERSION
from realestate.domain.clock import utc_now
from realestate.domain.commercial.actors import Actor, CommercialError
from realestate.domain.sponsorship.campaigns import (
    BUYER_KINDS,
    CampaignView,
    OpenCampaign,
    RecordCollection,
    ScheduleCampaign,
    SponsorshipCampaigns,
)
from realestate.domain.sponsorship.capacity import (
    SponsorshipCapacity,
    SurfaceForecast,
)
from realestate.domain.sponsorship.labels import (
    EDITORIAL_LABEL,
    NON_CAUSAL_DISCLAIMER,
    SPONSORED_DISCLOSURE,
    SPONSORED_LABEL,
)
from realestate.domain.sponsorship.pricing import (
    PACKAGES,
    CatalogView,
    DraftCatalog,
    PriceLine,
    PublishCatalog,
    SponsorshipPricing,
)
from realestate.domain.sponsorship.quoting import (
    AcceptQuote,
    QuoteCommand,
    QuoteView,
    SponsorshipQuoting,
)
from realestate.domain.sponsorship.reporting import SponsorshipReport, SponsorshipReporting
from realestate.domain.sponsorship.sharing import (
    ShareStatus,
    SponsorshipSharing,
    report_lines,
)

router = APIRouter(prefix="/crm/patrocinios", tags=["patrocinios"])
ACTIVE = "/crm/patrocinios"

#: The window the capacity panel forecasts over: one package's duration, which
#: is the period a buyer is actually asking about.
SALES_HORIZON = timedelta(days=30)

STATUS_LABELS = {
    SponsorshipCampaignStatus.DRAFT.value: "Borrador",
    SponsorshipCampaignStatus.QUOTED.value: "Cotizada",
    SponsorshipCampaignStatus.RESERVED.value: "Reservada",
    SponsorshipCampaignStatus.SCHEDULED.value: "Programada",
    SponsorshipCampaignStatus.ACTIVE.value: "Activa",
    SponsorshipCampaignStatus.PAUSED.value: "Pausada",
    SponsorshipCampaignStatus.COMPLETED.value: "Completada",
    SponsorshipCampaignStatus.CANCELLED.value: "Cancelada",
}
BUYER_LABELS = {
    "Owner": "Propietario",
    "Developer": "Desarrollador",
    "Collaborator": "Colaborador",
}
PACKAGE_LABELS = {
    "Search": "Búsqueda",
    "Homepage": "Portada",
    "Both": "Búsqueda y portada",
}
COLLECTION_LABELS = {
    CollectionState.NOT_INVOICED.value: "Sin facturar",
    CollectionState.AWAITING_PAYMENT.value: "Esperando pago",
    CollectionState.COLLECTED.value: "Cobrado",
    CollectionState.WAIVED.value: "Condonado",
    CollectionState.UNCOLLECTIBLE.value: "Incobrable",
}
CATALOG_LABELS = {
    PriceCatalogStatus.DRAFT.value: "Borrador",
    PriceCatalogStatus.PUBLISHED.value: "Publicado",
    PriceCatalogStatus.RETIRED.value: "Retirado",
}


@dataclass(frozen=True)
class PageData:
    campaigns: tuple[CampaignView, ...]
    titles: dict[uuid.UUID, str]
    catalogs: tuple[CatalogView, ...]
    published: CatalogView | None
    quotes: dict[uuid.UUID, tuple[QuoteView, ...]]
    capacity: tuple[SurfaceForecast, ...]
    publishable: tuple[tuple[uuid.UUID, str], ...]
    shares: dict[uuid.UUID, tuple[ShareStatus, ...]]


def _decimal(raw: object, field: str) -> Decimal:
    try:
        return Decimal(str(raw).strip() or "0")
    except InvalidOperation as exc:
        raise ValueError(f"{field} no es una cantidad válida.") from exc


def _label(mapping: dict[str, str], value: str | None) -> str:
    return mapping.get(value or "", value or "")


async def _page_data(session: AsyncSession, actor: Actor) -> PageData:
    moment = utc_now()
    campaigns = await SponsorshipCampaigns(session, actor).campaigns()
    pricing = SponsorshipPricing(session, actor)
    catalogs = await pricing.catalogs()
    published = next(
        (
            item
            for item in catalogs
            if item.status == PriceCatalogStatus.PUBLISHED.value
        ),
        None,
    )
    quoting = SponsorshipQuoting(session, actor)
    quotes = {
        campaign.campaign_id: await quoting.quotes(campaign.campaign_id)
        for campaign in campaigns
    }
    capacity_module = SponsorshipCapacity(session, actor)
    capacity = tuple(
        [
            await capacity_module.forecast(
                surface.value, moment, moment + SALES_HORIZON
            )
            for surface in SponsoredSurface
        ]
    )
    titles = {
        listing_id: title
        for listing_id, title in await session.execute(
            select(CatalogListing.id, CatalogListing.title).where(
                CatalogListing.organization_id == actor.organization_id
            )
        )
    }
    publishable = tuple(
        (listing_id, title)
        for listing_id, title in await session.execute(
            select(CatalogListing.id, CatalogListing.title)
            .where(
                CatalogListing.organization_id == actor.organization_id,
                CatalogListing.publication_state
                == ListingPublicationState.PUBLISHED.value,
            )
            .order_by(CatalogListing.title)
        )
    )
    sharing = SponsorshipSharing(session, actor)
    shares = {
        campaign.campaign_id: tuple(await sharing.shares(campaign.campaign_id))
        for campaign in campaigns
    }
    return PageData(
        campaigns=campaigns,
        titles=titles,
        catalogs=catalogs,
        published=published,
        quotes=quotes,
        capacity=capacity,
        publishable=publishable,
        shares=shares,
    )


def _campaign_controls(view: CampaignView, published: CatalogView | None) -> str:
    controls: list[str] = []
    base = f"{ACTIVE}/campanas/{view.campaign_id}"
    controls.append(
        f'<details><summary>Validación comercial (SAN-065)</summary>'
        f'<form method="post" action="{base}/validacion">'
        f'<label>Nota del administrador<textarea name="evidence" required '
        f'minlength="8"></textarea></label><button>Registrar validación</button>'
        f"</form></details>"
    )
    if view.status in {
        SponsorshipCampaignStatus.DRAFT.value,
        SponsorshipCampaignStatus.QUOTED.value,
    }:
        if published is None:
            controls.append(
                '<p class="warn">No hay catálogo publicado: el primer precio '
                "requiere datos del piloto.</p>"
            )
        else:
            controls.append(
                f'<details><summary>Cotizar</summary>'
                f'<form method="post" action="{base}/cotizar">'
                f'<label>Días<input name="duration_days" value="30" inputmode="numeric">'
                f"</label>"
                f'<label>Descuento<input name="discount_amount" value="0" '
                f'inputmode="numeric"></label>'
                f'<label>Razón del descuento<input name="discount_reason"></label>'
                f"<button>Emitir cotización de 7 días</button></form></details>"
            )
    if view.status == SponsorshipCampaignStatus.RESERVED.value:
        controls.append(
            f'<details><summary>Programar</summary>'
            f'<form method="post" action="{base}/programar">'
            f'<label>Inicio<input type="datetime-local" name="starts_on" required>'
            f"</label><button>Programar</button></form></details>"
        )
    if view.status in {
        SponsorshipCampaignStatus.SCHEDULED.value,
        SponsorshipCampaignStatus.PAUSED.value,
    }:
        controls.append(
            f'<form method="post" action="{base}/activar"><button>Activar</button>'
            f"</form>"
        )
    if view.status == SponsorshipCampaignStatus.ACTIVE.value:
        controls.append(
            f'<form method="post" action="{base}/pausar">'
            f'<input type="hidden" name="reason" value="Pausa administrativa">'
            f'<button class="secondary">Pausar</button></form>'
        )
    if view.status != SponsorshipCampaignStatus.CANCELLED.value:
        controls.append(
            f'<form method="post" action="{base}/cancelar">'
            f'<input type="hidden" name="reason" value="Cancelación administrativa">'
            f'<button class="secondary">Cancelar</button></form>'
        )
    collection_options = "".join(
        f'<option value="{escape(key)}"'
        f'{" selected" if key == view.collection_state else ""}>'
        f"{escape(value)}</option>"
        for key, value in COLLECTION_LABELS.items()
    )
    controls.append(
        f'<details><summary>Cobro externo</summary>'
        f'<form method="post" action="{base}/cobro">'
        f'<label>Estado<select name="state">{collection_options}</select></label>'
        f'<label>Referencia<input name="reference"></label>'
        f"<button>Registrar estado observado</button></form>"
        f'<p class="hint">Product no cobra, no factura y no mueve dinero: sólo '
        f"registra lo que alguien observó fuera del sistema.</p></details>"
    )
    controls.append(
        f'<details><summary>Reporte y enlace</summary>'
        f'<p><a href="{base}/reporte">Ver reporte interno</a></p>'
        f'<form method="post" action="{base}/compartir">'
        f'<label>Vigencia en días<input name="days" value="14" inputmode="numeric">'
        f"</label><button>Generar enlace de comprador</button></form></details>"
    )
    return "".join(controls)


def _page(actor: Actor, data: PageData, message: str | None, error: str | None) -> HTMLResponse:
    capacity_rows = "".join(
        "<tr>"
        f"<td>{escape(_label(PACKAGE_LABELS, item.surface))}</td>"
        f"<td>{item.concurrent_campaigns}</td>"
        f"<td>{item.reserved}</td>"
        f"<td>{item.available}</td>"
        f"<td>{escape(item.exposure_note)}</td>"
        "</tr>"
        for item in data.capacity
    )
    catalog_rows = "".join(
        "<tr>"
        f"<td><strong>{escape(item.version)}</strong></td>"
        f"<td>{tag(_label(CATALOG_LABELS, item.status), 'ok' if item.status == PriceCatalogStatus.PUBLISHED.value else '')}</td>"
        f"<td>{'<br>'.join(f'{escape(_label(PACKAGE_LABELS, line.package))} {line.duration_days} d: {line.amount} {escape(item.currency)}' for line in item.lines) or 'Sin precios'}</td>"
        f"<td>{escape(item.pilot_evidence or 'Sin evidencia del piloto')}</td>"
        f"<td>{_catalog_controls(item)}</td>"
        "</tr>"
        for item in data.catalogs
    )
    campaign_rows = "".join(
        "<tr>"
        f"<td><strong>{escape(data.titles.get(view.listing_id, 'Publicación'))}</strong>"
        f"<br><span class='muted'>{escape(view.buyer_label)} · "
        f"{escape(_label(BUYER_LABELS, view.buyer_kind))}</span></td>"
        f"<td>{tag(_label(STATUS_LABELS, view.status), _status_kind(view.status))}"
        f"<br>{escape(_label(PACKAGE_LABELS, view.package))}</td>"
        f"<td>{view.delivered_days} de {view.paid_days} días<br>"
        f"<span class='muted'>{view.remaining_days} restantes</span></td>"
        f"<td>{escape(_label(COLLECTION_LABELS, view.collection_state))}<br>"
        f"<span class='muted'>{escape(view.paused_reason or '')}</span></td>"
        f"<td>{_quote_summary(data.quotes.get(view.campaign_id, ()))}</td>"
        f"<td>{_campaign_controls(view, data.published)}</td>"
        "</tr>"
        for view in data.campaigns
    )
    share_rows = "".join(
        "<tr>"
        f"<td>{escape(data.titles.get(view.listing_id, 'Publicación'))}</td>"
        f"<td>{escape(local(share.created_at))}</td>"
        f"<td>{escape(local(share.expires_at))}</td>"
        f"<td>{share.views} vistas</td>"
        f"<td>{escape('Revocado' if share.revoked_at else 'Vigente')}</td>"
        f"<td>{'' if share.revoked_at else _revoke_form(share.link_id)}</td>"
        "</tr>"
        for view in data.campaigns
        for share in data.shares.get(view.campaign_id, ())
    )
    listing_options = "".join(
        f'<option value="{escape(listing_id)}">{escape(title)}</option>'
        for listing_id, title in data.publishable
    )
    buyer_options = "".join(
        f'<option value="{escape(kind)}">{escape(_label(BUYER_LABELS, kind))}</option>'
        for kind in BUYER_KINDS
    )
    package_options = "".join(
        f'<option value="{escape(package)}">'
        f"{escape(_label(PACKAGE_LABELS, package))}</option>"
        for package in PACKAGES
    )
    content = f"""
{flash(message)}
{errors_box([error] if error else [])}
<h1>Patrocinios</h1>
<p class="muted">{escape(SPONSORED_DISCLOSURE)}</p>
<p class="hint">«{escape(EDITORIAL_LABEL)}» es selección editorial sin pago y nunca
se usa para una campaña. Toda exposición pagada se etiqueta
«{escape(SPONSORED_LABEL)}».</p>

<h2>Capacidad por superficie</h2>
{table(
    "Campañas concurrentes vendibles y exposición medida",
    ("Superficie", "Límite", "Reservadas", "Disponibles", "Exposición medida"),
    capacity_rows,
)}
<div class="card"><h3>Ajustar capacidad</h3>
<form method="post" action="{ACTIVE}/capacidad">
<div class="grid">
<label>Superficie<select name="surface">
{"".join(f'<option value="{escape(item.value)}">{escape(_label(PACKAGE_LABELS, item.value))}</option>' for item in SponsoredSurface)}
</select></label>
<label>Campañas concurrentes<input name="concurrent" inputmode="numeric" value="2">
</label>
</div>
<div class="actions"><button>Guardar</button></div>
</form></div>

<h2>Catálogo de precios</h2>
{table(
    "Versiones del catálogo",
    ("Versión", "Estado", "Paquetes", "Evidencia del piloto", "Acciones"),
    catalog_rows,
    empty_message="No hay ninguna versión del catálogo.",
    empty_hint=(
        "El primer precio se fija con tráfico medido del piloto, no con un "
        "pronóstico (SAN-062)."
    ),
)}
<div class="card"><h3>Nueva versión en borrador</h3>
<form method="post" action="{ACTIVE}/catalogos">
<div class="grid">
<label>Versión<input name="version" required placeholder="precios-piloto-1"></label>
<label>Moneda<input name="currency" value="MXN" required></label>
<label>Búsqueda 30 días<input name="search" inputmode="numeric" value="0"></label>
<label>Portada 30 días<input name="homepage" inputmode="numeric" value="0"></label>
<label>Ambas 30 días<input name="both" inputmode="numeric" value="0"></label>
</div>
<div class="actions"><button>Guardar borrador</button></div>
</form></div>

<h2>Campañas</h2>
{table(
    "Campañas de patrocinio",
    (
        "Publicación y comprador",
        "Estado",
        "Entrega",
        "Cobro externo",
        "Cotizaciones",
        "Acciones",
    ),
    campaign_rows,
    empty_message="No hay campañas de patrocinio.",
)}
<div class="card"><h3>Abrir una campaña</h3>
<form method="post" action="{ACTIVE}/campanas">
<div class="grid">
<label>Publicación<select name="listing_id" required>{listing_options}</select></label>
<label>Tipo de comprador<select name="buyer_kind">{buyer_options}</select></label>
<label>Comprador<input name="buyer_label" required></label>
<label>Paquete<select name="package">{package_options}</select></label>
<label>Días pagados<input name="paid_days" value="30" inputmode="numeric"></label>
</div>
<div class="actions"><button>Abrir en borrador</button></div>
</form></div>

<h2>Enlaces de comprador</h2>
{table(
    "Enlaces expirables de sólo lectura",
    ("Publicación", "Creado", "Vence", "Uso", "Estado", "Acciones"),
    share_rows,
    empty_message="No hay enlaces generados.",
    empty_hint=(
        "Un comprador no recibe cuenta del CRM: sólo un enlace expirable y "
        "revocable con cifras agregadas."
    ),
)}
<p class="hint">{escape(NON_CAUSAL_DISCLAIMER)}</p>
"""
    return shell(actor, "Patrocinios", content, active=ACTIVE)


def _status_kind(status: str) -> str:
    if status in {
        SponsorshipCampaignStatus.CANCELLED.value,
        SponsorshipCampaignStatus.PAUSED.value,
    }:
        return "bad"
    if status == SponsorshipCampaignStatus.ACTIVE.value:
        return "ok"
    return ""


def _catalog_controls(item: CatalogView) -> str:
    if item.status == PriceCatalogStatus.PUBLISHED.value:
        return "Vigente"
    if item.status == PriceCatalogStatus.RETIRED.value:
        return "Retirado"
    return (
        f'<details><summary>Publicar</summary>'
        f'<form method="post" action="{ACTIVE}/catalogos/{item.catalog_id}/publicar">'
        f'<label>Evidencia del piloto<textarea name="pilot_evidence" required '
        f'minlength="8"></textarea></label><button>Publicar versión</button>'
        f"</form></details>"
    )


def _quote_summary(quotes: tuple[QuoteView, ...]) -> str:
    if not quotes:
        return "Sin cotizaciones"
    rows: list[str] = []
    for quote in quotes:
        accept = (
            f'<form method="post" action="{ACTIVE}/cotizaciones/{quote.quote_id}/aceptar">'
            f'<label>Inicio<input type="datetime-local" name="starts_on" required>'
            f"</label><button>Aceptar y reservar</button></form>"
            if quote.status == "Issued"
            else ""
        )
        rows.append(
            f"<li><strong>{quote.total_amount} {escape(quote.currency)}</strong> · "
            f"{escape(quote.catalog_version)} · vence "
            f"{escape(local(quote.expires_at))} · {escape(quote.status)}"
            + (
                f"<br><span class='muted'>Descuento {quote.discount_amount}: "
                f"{escape(quote.discount_reason)}</span>"
                if quote.discount_amount
                else ""
            )
            + accept
            + "</li>"
        )
    return f'<ul class="plain">{"".join(rows)}</ul>'


def _revoke_form(link_id: uuid.UUID) -> str:
    return (
        f'<form method="post" action="{ACTIVE}/enlaces/{link_id}/revocar">'
        f'<button class="secondary">Revocar</button></form>'
    )


@router.get("", response_class=HTMLResponse)
async def sponsorship_page(
    request: Request,
    actor: Actor = Depends(require_administrator),
    guardado: str = "",
    error: str = "",
) -> HTMLResponse:
    async with request.app.state.database.session_scope() as session:
        data = await _page_data(session, actor)
    return _page(actor, data, guardado or None, error or None)


@router.post("/capacidad")
async def set_capacity(
    request: Request, actor: Actor = Depends(require_administrator)
) -> RedirectResponse:
    form = await request.form()
    try:
        async with request.app.state.database.session_scope() as session:
            await SponsorshipCapacity(session, actor).set_limit(
                str(form.get("surface", "")),
                int(str(form.get("concurrent", "0"))),
                at=utc_now(),
            )
            await session.commit()
    except (ValueError, CommercialError) as exc:
        return redirect_back(ACTIVE, error=_message(exc))
    return redirect_back(ACTIVE, saved="Capacidad actualizada")


@router.post("/catalogos")
async def draft_catalog(
    request: Request, actor: Actor = Depends(require_administrator)
) -> RedirectResponse:
    form = await request.form()
    try:
        lines = tuple(
            PriceLine(package, 30, _decimal(form.get(field, "0"), package))
            for package, field in (
                ("Search", "search"),
                ("Homepage", "homepage"),
                ("Both", "both"),
            )
        )
        async with request.app.state.database.session_scope() as session:
            await SponsorshipPricing(session, actor).draft(
                DraftCatalog(
                    version=str(form.get("version", "")),
                    currency=str(form.get("currency", "MXN")),
                    lines=lines,
                    command_key=f"catalog:{form.get('version', '')}",
                ),
                at=utc_now(),
            )
            await session.commit()
    except (ValueError, CommercialError) as exc:
        return redirect_back(ACTIVE, error=_message(exc))
    return redirect_back(ACTIVE, saved="Borrador de catálogo guardado")


@router.post("/catalogos/{catalog_id}/publicar")
async def publish_catalog(
    catalog_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_administrator),
) -> RedirectResponse:
    form = await request.form()
    try:
        async with request.app.state.database.session_scope() as session:
            await SponsorshipPricing(session, actor).publish(
                PublishCatalog(catalog_id, str(form.get("pilot_evidence", ""))),
                at=utc_now(),
            )
            await session.commit()
    except (ValueError, CommercialError) as exc:
        return redirect_back(ACTIVE, error=_message(exc))
    return redirect_back(ACTIVE, saved="Catálogo publicado")


@router.post("/campanas")
async def open_campaign(
    request: Request, actor: Actor = Depends(require_administrator)
) -> RedirectResponse:
    form = await request.form()
    try:
        async with request.app.state.database.session_scope() as session:
            await SponsorshipCampaigns(session, actor).open(
                OpenCampaign(
                    listing_id=uuid.UUID(str(form.get("listing_id", ""))),
                    buyer_kind=str(form.get("buyer_kind", "")),
                    buyer_label=str(form.get("buyer_label", "")),
                    package=str(form.get("package", "")),
                    paid_days=int(str(form.get("paid_days", "30"))),
                ),
                at=utc_now(),
            )
            await session.commit()
    except (ValueError, CommercialError) as exc:
        return redirect_back(ACTIVE, error=_message(exc))
    return redirect_back(ACTIVE, saved="Campaña abierta en borrador")


@router.post("/campanas/{campaign_id}/validacion")
async def record_clearance(
    campaign_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_administrator),
) -> RedirectResponse:
    form = await request.form()
    try:
        async with request.app.state.database.session_scope() as session:
            await SponsorshipCampaigns(session, actor).record_clearance(
                campaign_id, str(form.get("evidence", "")), at=utc_now()
            )
            await session.commit()
    except (ValueError, CommercialError) as exc:
        return redirect_back(ACTIVE, error=_message(exc))
    return redirect_back(ACTIVE, saved="Validación comercial registrada")


@router.post("/campanas/{campaign_id}/cotizar")
async def quote_campaign(
    campaign_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_administrator),
) -> RedirectResponse:
    form = await request.form()
    try:
        async with request.app.state.database.session_scope() as session:
            view = await SponsorshipQuoting(session, actor).quote(
                QuoteCommand(
                    campaign_id=campaign_id,
                    command_key=f"quote:{campaign_id}:{utc_now().isoformat()}",
                    duration_days=int(str(form.get("duration_days", "30"))),
                    discount_amount=_decimal(
                        form.get("discount_amount", "0"), "El descuento"
                    ),
                    discount_reason=str(form.get("discount_reason", "")),
                ),
                at=utc_now(),
            )
            await session.commit()
    except (ValueError, CommercialError) as exc:
        return redirect_back(ACTIVE, error=_message(exc))
    return redirect_back(
        ACTIVE, saved=f"Cotización {view.total_amount} {view.currency}"
    )


@router.post("/cotizaciones/{quote_id}/aceptar")
async def accept_quote(
    quote_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_administrator),
) -> RedirectResponse:
    form = await request.form()
    try:
        starts_on = _moment(str(form.get("starts_on", "")))
        async with request.app.state.database.session_scope() as session:
            await SponsorshipQuoting(session, actor).accept(
                AcceptQuote(quote_id, starts_on), at=utc_now()
            )
            await session.commit()
    except (ValueError, CommercialError) as exc:
        return redirect_back(ACTIVE, error=_message(exc))
    return redirect_back(ACTIVE, saved="Cotización aceptada y capacidad reservada")


@router.post("/campanas/{campaign_id}/programar")
async def schedule_campaign(
    campaign_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_administrator),
) -> RedirectResponse:
    form = await request.form()
    try:
        async with request.app.state.database.session_scope() as session:
            await SponsorshipCampaigns(session, actor).schedule(
                ScheduleCampaign(campaign_id, _moment(str(form.get("starts_on", "")))),
                at=utc_now(),
            )
            await session.commit()
    except (ValueError, CommercialError) as exc:
        return redirect_back(ACTIVE, error=_message(exc))
    return redirect_back(ACTIVE, saved="Campaña programada")


@router.post("/campanas/{campaign_id}/activar")
async def activate_campaign(
    campaign_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_administrator),
) -> RedirectResponse:
    try:
        async with request.app.state.database.session_scope() as session:
            await SponsorshipCampaigns(session, actor).activate(
                campaign_id, at=utc_now()
            )
            await session.commit()
    except (ValueError, CommercialError) as exc:
        return redirect_back(ACTIVE, error=_message(exc))
    return redirect_back(ACTIVE, saved="Campaña activa")


@router.post("/campanas/{campaign_id}/pausar")
async def pause_campaign(
    campaign_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_administrator),
) -> RedirectResponse:
    form = await request.form()
    try:
        async with request.app.state.database.session_scope() as session:
            await SponsorshipCampaigns(session, actor).pause(
                campaign_id, str(form.get("reason", "")), at=utc_now()
            )
            await session.commit()
    except (ValueError, CommercialError) as exc:
        return redirect_back(ACTIVE, error=_message(exc))
    return redirect_back(
        ACTIVE, saved="Campaña pausada; los días pagados restantes se conservan"
    )


@router.post("/campanas/{campaign_id}/cancelar")
async def cancel_campaign(
    campaign_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_administrator),
) -> RedirectResponse:
    form = await request.form()
    try:
        async with request.app.state.database.session_scope() as session:
            await SponsorshipCampaigns(session, actor).cancel(
                campaign_id, str(form.get("reason", "")), at=utc_now()
            )
            await session.commit()
    except (ValueError, CommercialError) as exc:
        return redirect_back(ACTIVE, error=_message(exc))
    return redirect_back(ACTIVE, saved="Campaña cancelada y capacidad liberada")


@router.post("/campanas/{campaign_id}/cobro")
async def record_collection(
    campaign_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_administrator),
) -> RedirectResponse:
    form = await request.form()
    try:
        state = CollectionState(str(form.get("state", "")))
        async with request.app.state.database.session_scope() as session:
            await SponsorshipCampaigns(session, actor).record_collection(
                RecordCollection(campaign_id, state, str(form.get("reference", ""))),
                at=utc_now(),
            )
            await session.commit()
    except (ValueError, CommercialError) as exc:
        return redirect_back(ACTIVE, error=_message(exc))
    return redirect_back(ACTIVE, saved="Estado de cobro externo registrado")


@router.post("/campanas/{campaign_id}/compartir")
async def share_report(
    campaign_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_administrator),
) -> RedirectResponse:
    form = await request.form()
    try:
        async with request.app.state.database.session_scope() as session:
            minted = await SponsorshipSharing(session, actor).share(
                campaign_id,
                at=utc_now(),
                days=int(str(form.get("days", "14"))),
                definition_version=CURRENT_DEFINITION_VERSION,
            )
            await session.commit()
    except (ValueError, CommercialError) as exc:
        return redirect_back(ACTIVE, error=_message(exc))
    # The raw token exists exactly once, here. It is shown to the Administrator
    # so they can send it, and it is never recoverable afterwards.
    return redirect_back(ACTIVE, saved=f"Enlace generado: {minted.path}")


@router.post("/enlaces/{link_id}/revocar")
async def revoke_link(
    link_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_administrator),
) -> RedirectResponse:
    try:
        async with request.app.state.database.session_scope() as session:
            await SponsorshipSharing(session, actor).revoke(link_id, at=utc_now())
            await session.commit()
    except (ValueError, CommercialError) as exc:
        return redirect_back(ACTIVE, error=_message(exc))
    return redirect_back(ACTIVE, saved="Enlace revocado")


@router.get("/campanas/{campaign_id}/reporte", response_class=HTMLResponse)
async def internal_report(
    campaign_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_administrator),
) -> HTMLResponse:
    """The Administrator's view: the buyer's figures plus the commercial half."""
    try:
        async with request.app.state.database.session_scope() as session:
            report = await SponsorshipReporting(session, actor).generate(
                campaign_id, ReportAudience.ADMINISTRATOR, at=utc_now()
            )
    except CommercialError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    shared = _internal_campaign_report(report)
    internal = report.internal
    assert internal is not None
    internal_block = f"""
<h2>Sólo interno</h2>
<dl class="pairs">
<dt>Cobro externo</dt><dd>{escape(_label(COLLECTION_LABELS, internal.collection_state))}
 · {escape(internal.collection_reference or 'Sin referencia')}</dd>
<dt>Versión del catálogo</dt><dd>{escape(internal.catalog_version or 'Sin cotización')}</dd>
<dt>Descuento</dt><dd>{internal.discount_amount} ·
 {escape(internal.discount_reason or 'Sin descuento')}</dd>
<dt>Capacidad disponible</dt><dd>{escape(', '.join(f'{key}: {value}' for key, value in sorted(internal.capacity_available.items())) or 'Sin superficies')}</dd>
<dt>Tráfico inválido</dt><dd>{escape(', '.join(f'{key}: {value}' for key, value in sorted(internal.invalid_events.items())) or 'Sin eventos excluidos')}</dd>
<dt>Duplicados suprimidos</dt><dd>{internal.duplicate_suppressed}</dd>
<dt>Completitud de datos de seguimiento</dt>
<dd>{escape(internal.follow_up_data_completeness.text)}</dd>
<dt>Completitud de resultados</dt><dd>{escape(internal.outcome_completeness.text)}</dd>
</dl>
<p class="hint">Un comprador nunca recibe este bloque, ni identidad de contacto,
teléfonos, contenido de conversaciones, búsquedas individuales ni colecciones
guardadas.</p>
<p><a href="{ACTIVE}">Volver a patrocinios</a></p>
"""
    return shell(
        actor,
        f"Reporte de campaña {SPONSORED_LABEL}",
        shared + internal_block,
        active=ACTIVE,
    )


def _internal_campaign_report(report: SponsorshipReport) -> str:
    """The campaign dashboard in the same order and vocabulary as the buyer view."""
    steps = {row.step: row for row in report.funnel}

    def count(step: str) -> int:
        return steps[step].count or 0

    interest = sum(
        count(step) for step in ("SavedOrShared", "MaiaStarted", "WhatsAppHandoff")
    )
    headline = (
        ("Impresiones visibles", count("SponsoredVisibleImpression")),
        ("Aperturas de publicación", count("ListingOpened")),
        ("Acciones de interés", interest),
        ("Solicitudes de cita", count("AppointmentRequested")),
    )
    stats = "".join(
        '<div class="stat"><div class="muted">'
        f'{escape(label)}</div><div class="value">{value}</div></div>'
        for label, value in headline
    )
    status = "".join(
        '<div class="stat"><div class="muted">'
        f'{escape(label)}</div><div class="value">{escape(value)}</div></div>'
        for label, value in (
            ("Estado", report.campaign.status_label),
            ("Días pagados", report.campaign.paid_days),
            ("Entregados", report.campaign.delivered_days),
            ("Restantes", report.campaign.remaining_days),
        )
    )
    trend_rows = "".join(
        "<tr>"
        f'<th scope="row">{point.period_start:%d/%m/%Y}</th>'
        f"<td>{point.visible_impressions}</td>"
        f"<td>{point.listing_opens}</td>"
        f"<td>{point.interest_actions}</td>"
        "</tr>"
        for point in report.trend
    )
    funnel_rows = "".join(
        "<tr>"
        f'<th scope="row">{escape(row.label)}</th>'
        f"<td>{escape(row.count if row.count is not None else 'Sin registrar')}</td>"
        f"<td>{escape(row.from_previous.text)}</td>"
        "</tr>"
        for row in report.funnel
    )
    details: list[str] = []
    in_details = False
    for line in report_lines(report):
        if line.text == "Definiciones":
            break
        if line.text == "Resultados conocidos":
            in_details = True
        if not in_details or not line.text:
            continue
        details.append(
            f'<h2 class="report-heading">{escape(line.text)}</h2>'
            if str(line.style) == "heading"
            else f"<p>{escape(line.text)}</p>"
        )
    definitions = "".join(
        f"<li>{escape(definition)}</li>" for definition in report.definitions
    )
    return f"""
<h1>Reporte de campaña {escape(report.label)}</h1>
<p class="muted">{escape(report.listing_title)} · periodo
{report.period_start:%d/%m/%Y} a {report.period_end:%d/%m/%Y} · definiciones
{escape(report.definition_version)}</p>
<h2>Cuatro cifras para empezar</h2>
<div class="stats">{stats}</div>
<h2>Estado de la campaña</h2>
<div class="stats">{status}</div>
<h2>Tendencia diaria</h2>
{table(
    "Visibilidad, aperturas e interés por día",
    ("Fecha", "Visibles", "Aperturas", "Interés"),
    trend_rows,
    empty_message="Todavía no hay historial medido para este periodo.",
)}
<h2>Embudo completo</h2>
{table(
    "Del lugar entregado al resultado conocido",
    ("Paso", "Volumen", "Conversión anterior"),
    funnel_rows,
)}
{"".join(details)}
<h2>Definiciones de medición</h2>
<ul>{definitions}</ul>
<p>{escape(report.disclosure)}</p>
<p class="hint">{escape(report.disclaimer)}</p>
"""


def _message(exc: Exception) -> str:
    return exc.message if isinstance(exc, CommercialError) else str(exc)


def _moment(raw: str) -> datetime:
    parsed = parse_datetime_input(raw)
    if parsed is None:
        raise ValueError("La fecha y hora no son válidas.")
    return parsed
