"""Administración del catálogo autoritativo, en español mexicano."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.datastructures import UploadFile

from realestate.api.operator import (
    command_field,
    command_key,
    require_actor,
    require_administrator,
    shell,
    tag,
)
from realestate.api.ui import empty, errors_box, escape, flash, options, table
from realestate.db.models import (
    CatalogPresentationTier,
    FactsReviewState,
    ListingAuthority,
    ListingAvailability,
    ListingOfferOperation,
    ListingPublicationState,
    ListingSourceKind,
    OfferAvailability,
)
from realestate.domain.catalog.administration import (
    CatalogAdministration,
    CreateListing,
    CreateProperty,
    ReviewListingFacts,
    ReviewPropertyFacts,
    SetListingAuthority,
    SetListingAvailability,
    SetPublicationState,
    SetReadinessOverride,
    SetTierOverride,
)
from realestate.domain.catalog.media import (
    AddMedia,
    ArrangeMedia,
    MediaAdministration,
    MediaPlacement,
    RevokeMedia,
)
from realestate.domain.catalog.offers import (
    CompleteOperation,
    OfferManagement,
    RecordOffer,
)
from realestate.domain.catalog.projection import (
    AdministrationListing,
    CatalogProjection,
)
from realestate.domain.commercial.actors import Actor, CommercialError

router = APIRouter(prefix="/crm/catalogo", tags=["catalogo"])
ACTIVE = "/crm/catalogo"

SOURCE_LABELS = {
    ListingSourceKind.ORGANIZATION.value: "Publicación de la organización",
    ListingSourceKind.COLLABORATOR.value: "Publicación de colaborador",
}
AVAILABILITY_LABELS = {
    ListingAvailability.AVAILABLE.value: "Disponible",
    ListingAvailability.RESERVED.value: "Reservada",
    ListingAvailability.SOLD.value: "Vendida",
    ListingAvailability.RENTED.value: "Rentada",
    ListingAvailability.TEMPORARILY_UNAVAILABLE.value: "No disponible temporalmente",
    ListingAvailability.UNKNOWN.value: "Por confirmar",
}
PUBLICATION_LABELS = {
    ListingPublicationState.DRAFT.value: "Borrador",
    ListingPublicationState.PUBLISHED.value: "Publicada",
    ListingPublicationState.UNPUBLISHED.value: "Retirada de publicación",
}
AUTHORITY_LABELS = {
    ListingAuthority.AUTHORIZED.value: "Autorizada",
    ListingAuthority.PENDING.value: "Autoridad pendiente",
    ListingAuthority.EXPIRED.value: "Autoridad vencida",
    ListingAuthority.REVOKED.value: "Autoridad revocada",
}
REVIEW_LABELS = {
    FactsReviewState.PENDING.value: "Pendiente",
    FactsReviewState.APPROVED.value: "Aprobada",
    FactsReviewState.NEEDS_REVIEW.value: "Requiere revisión",
}
OPERATION_LABELS = {
    ListingOfferOperation.SALE.value: "Venta",
    ListingOfferOperation.RENTAL.value: "Renta",
    ListingOfferOperation.PRESALE.value: "Preventa",
}
OFFER_AVAILABILITY_LABELS = {
    OfferAvailability.AVAILABLE.value: "Disponible",
    OfferAvailability.RESERVED.value: "Reservada",
    OfferAvailability.COMPLETED.value: "Concluida",
    OfferAvailability.TEMPORARILY_UNAVAILABLE.value: "No disponible temporalmente",
    OfferAvailability.WITHDRAWN.value: "Retirada",
    OfferAvailability.UNKNOWN.value: "Por confirmar",
}


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _enum_options(enum_type: Any, current: str, labels: dict[str, str]) -> str:
    return options([member.value for member in enum_type], current, labels)


def _uuid(value: object, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"{label} no es válido.") from exc


def _decimal(value: object) -> Decimal:
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("El precio no es válido.") from exc
    if not amount.is_finite():
        raise ValueError("El precio no es válido.")
    return amount


def _optional_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("La fecha de revalidación no es válida.") from exc
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _money(amount: Decimal, currency: str) -> str:
    return f"{amount:,.2f} {currency}"


def _offers_summary(row: AdministrationListing) -> str:
    if not row.offers:
        return tag("Sin oferta", "bad")
    return "<br>".join(
        f"{tag(OPERATION_LABELS.get(offer.operation, offer.operation))} "
        f"{escape(_money(offer.price_amount, offer.price_currency))} · "
        f"{escape(OFFER_AVAILABILITY_LABELS.get(offer.availability, offer.availability))}"
        for offer in row.offers
    )


def _action_summary(row: AdministrationListing) -> str:
    if not row.action_reasons:
        return tag("Lista para publicar", "ok")
    reasons = "".join(f"<li>{escape(reason.capitalize())}</li>" for reason in row.action_reasons)
    return f"{tag('Requiere acción', 'warn')}<ul>{reasons}</ul>"


def _list_page(
    actor: Actor,
    rows: tuple[AdministrationListing, ...],
    *,
    message: str | None = None,
) -> HTMLResponse:
    body_rows = "".join(
        "<tr>"
        f'<td><a href="/crm/catalogo/{row.listing_id}"><strong>{escape(row.physical_name)}</strong></a>'
        f'<br><span class="muted">Inmueble: {escape(row.physical_key)}</span></td>'
        f"<td>{escape(row.title)}<br><span class='muted'>{escape(row.listing_key)}</span></td>"
        f"<td>{escape(SOURCE_LABELS.get(row.source_kind, row.source_kind))}<br>"
        f'<span class="muted">{escape(row.source_name)}</span></td>'
        f"<td>{_offers_summary(row)}</td>"
        f"<td>{tag(AVAILABILITY_LABELS.get(row.availability, row.availability))}<br>"
        f"{tag(PUBLICATION_LABELS.get(row.publication_state, row.publication_state))}<br>"
        f"{tag(AUTHORITY_LABELS.get(row.authority, row.authority))}</td>"
        f"<td>{escape(row.presentation_tier or 'Sin nivel')}"
        f"{' · override' if row.tier_override else ''}</td>"
        f"<td>{_action_summary(row)}</td>"
        "</tr>"
        for row in rows
    )
    actions = (
        '<div class="actions"><a class="button" href="/crm/catalogo/nueva">'
        "Registrar inmueble y publicación</a>"
        '<a class="button secondary" href="/admin/properties">'
        "Importación legacy</a></div>"
        if actor.is_administrator
        else '<p class="hint">Consulta limitada a los inmuebles donde eres experto vigente.</p>'
    )
    content = (
        flash(message)
        + '<p class="lead">Distingue la realidad física, la publicación de cada fuente y sus ofertas comerciales. '
        "Nada se publica por capturarlo aquí.</p>"
        + actions
        + table(
            "Inventario inmobiliario autoritativo",
            (
                "Inmueble físico o modelo",
                "Publicación",
                "Fuente",
                "Ofertas",
                "Estados independientes",
                "Presentación",
                "Acción",
            ),
            body_rows,
            empty_message="Todavía no hay publicaciones en el catálogo.",
            empty_hint=(
                "Registra primero un inmueble físico y una publicación; quedarán pendientes hasta revisión."
                if actor.is_administrator
                else "Un administrador debe designarte como experto de un inmueble."
            ),
        )
    )
    return shell(actor, "Catálogo inmobiliario", content, active=ACTIVE)


def _offer_rows(row: AdministrationListing) -> str:
    return "".join(
        "<tr>"
        f"<td>{escape(OPERATION_LABELS.get(offer.operation, offer.operation))}</td>"
        f"<td>{escape(_money(offer.price_amount, offer.price_currency))}</td>"
        f"<td>{escape('Precio oculto' if offer.price_visibility == 'Hidden' else 'Precio visible')}</td>"
        f"<td>{escape(REVIEW_LABELS.get(offer.terms_review_state, offer.terms_review_state))}</td>"
        f"<td>{escape(OFFER_AVAILABILITY_LABELS.get(offer.availability, offer.availability))}</td>"
        "</tr>"
        for offer in row.offers
    )


def _media_section(row: AdministrationListing, editable: bool) -> str:
    active = [media for media in row.media if media.revoked_at is None]
    revoked = [media for media in row.media if media.revoked_at is not None]
    if active:
        media_rows = "".join(
            "<tr>"
            f"<td><input type='radio' name='portada' value='{media.media_id}'"
            f"{' checked' if media.is_cover else ''}{'' if editable else ' disabled'}> "
            f"{escape(media.original_filename)}</td>"
            f"<td><input name='orden_{media.media_id}' type='number' min='0' value='{media.sort_order}'"
            f"{' required' if editable else ' disabled'}></td>"
            f"<td><input name='grupo_{media.media_id}' value='{escape(media.space_group or '')}'"
            f"{' ' if editable else ' disabled'}></td>"
            f"<td>{escape(AUTHORITY_LABELS.get(media.authority, media.authority))}</td>"
            f"<td>{tag('Alta resolución', 'ok') if media.high_resolution else tag('Resolución sin confirmar', 'warn')}</td>"
            f"<td>{('<button name=\"accion\" value=\"revocar:' + str(media.media_id) + '\" class=\"danger\">Revocar y limpiar</button>') if editable else 'Sólo consulta'}</td>"
            "</tr>"
            for media in active
        )
        arrangement = (
            f'<form method="post" action="/crm/catalogo/{row.listing_id}/medios">'
            f"{command_field()}"
            + table(
                "Fotografías activas",
                ("Portada", "Orden", "Grupo", "Autoridad", "Calidad", "Acción"),
                media_rows,
            )
            + ('<button name="accion" value="ordenar">Guardar portada, orden y grupos</button></form>' if editable else "")
        )
    else:
        arrangement = empty("No hay fotografías activas.")
    cleanup = ""
    if revoked:
        cleanup = '<h3>Medios revocados</h3><ul>' + "".join(
            f"<li>{escape(media.original_filename)} · "
            f"{escape('Limpieza completa' if media.cleanup_complete else 'Limpieza pendiente: reintenta la revocación')}</li>"
            for media in revoked
        ) + "</ul>"
    upload = ""
    if editable:
        upload = f"""
<h3>Agregar fotografía autorizada</h3>
<form method="post" action="/crm/catalogo/{row.listing_id}/medios" enctype="multipart/form-data">
{command_field()}<input type="hidden" name="accion" value="agregar">
<div class="grid">
<label>Archivo JPG, PNG o WebP *<input type="file" name="archivo" accept="image/jpeg,image/png,image/webp" required></label>
<label>Procedencia *<input name="procedencia" required></label>
<label>Evidencia de autoridad *<input name="evidencia" required></label>
<label>Orden *<input type="number" name="orden" min="0" required></label>
<label>Grupo de espacio<input name="grupo"></label>
<label class="check"><input type="checkbox" name="portada" value="1"> Usar como portada</label>
<label class="check"><input type="checkbox" name="alta_resolucion" value="1"> Alta resolución confirmada por Admin</label>
</div><button>Guardar después de confirmar almacenamiento</button>
</form>"""
    return f'<section class="card"><h2>Medios</h2>{arrangement}{cleanup}{upload}</section>'


def _forms(row: AdministrationListing) -> str:
    return f"""
<section class="card"><h2>Revisiones de datos</h2><div class="grid">
<form method="post" action="/crm/catalogo/{row.listing_id}/cambiar">{command_field()}
<input type="hidden" name="accion" value="revisar_inmueble">
<label>Datos del inmueble físico<select name="estado">{_enum_options(FactsReviewState, row.physical_facts_review_state, REVIEW_LABELS)}</select></label>
<button>Guardar revisión física</button></form>
<form method="post" action="/crm/catalogo/{row.listing_id}/cambiar">{command_field()}
<input type="hidden" name="accion" value="revisar_publicacion">
<label>Datos de la publicación<select name="estado">{_enum_options(FactsReviewState, row.listing_facts_review_state, REVIEW_LABELS)}</select></label>
<button>Guardar revisión de publicación</button></form>
</div></section>
<section class="card"><h2>Estados independientes</h2><div class="grid">
<form method="post" action="/crm/catalogo/{row.listing_id}/cambiar">{command_field()}
<input type="hidden" name="accion" value="disponibilidad"><label>Disponibilidad<select name="estado">{_enum_options(ListingAvailability, row.availability, AVAILABILITY_LABELS)}</select></label><button>Confirmar disponibilidad</button></form>
<form method="post" action="/crm/catalogo/{row.listing_id}/cambiar">{command_field()}
<input type="hidden" name="accion" value="publicacion"><label>Estado de publicación<select name="estado">{_enum_options(ListingPublicationState, row.publication_state, PUBLICATION_LABELS)}</select></label><button>Confirmar estado público</button></form>
<form method="post" action="/crm/catalogo/{row.listing_id}/cambiar">{command_field()}
<input type="hidden" name="accion" value="autoridad">
<label>Autoridad<select name="estado">{_enum_options(ListingAuthority, row.authority, AUTHORITY_LABELS)}</select></label>
<label>Evidencia<input name="evidencia" value="{escape(row.authority_evidence or '')}"></label>
<label>Revalidar antes de<input type="datetime-local" name="revalidar"></label>
<button>Confirmar autoridad</button></form>
</div></section>
<section class="card"><h2>Oferta comercial</h2>
<form method="post" action="/crm/catalogo/{row.listing_id}/cambiar">{command_field()}<input type="hidden" name="accion" value="oferta"><div class="grid">
<label>Operación<select name="operacion">{_enum_options(ListingOfferOperation, 'Sale', OPERATION_LABELS)}</select></label>
<label>Precio<input type="number" min="0.01" step="0.01" name="precio" required></label>
<label>Moneda<select name="moneda"><option>MXN</option><option>USD</option></select></label>
<label>Visibilidad<select name="visibilidad"><option value="Visible">Precio visible</option><option value="Hidden">Ocultar precio y usar texto aprobado</option></select></label>
<label>Revisión de términos<select name="revision">{_enum_options(FactsReviewState, 'Pending', REVIEW_LABELS)}</select></label>
<label>Disponibilidad de la oferta<select name="disponibilidad">{_enum_options(OfferAvailability, 'Unknown', OFFER_AVAILABILITY_LABELS)}</select></label>
</div><button>Guardar oferta</button></form>
<form method="post" action="/crm/catalogo/{row.listing_id}/cambiar" class="inline">{command_field()}<input type="hidden" name="accion" value="concluir"><label>Concluir operación<select name="operacion">{_enum_options(ListingOfferOperation, 'Sale', OPERATION_LABELS)}</select></label><button class="danger">Confirmar operación concluida</button></form>
</section>
<section class="card"><h2>Presentación</h2><div class="grid">
<form method="post" action="/crm/catalogo/{row.listing_id}/cambiar">{command_field()}<input type="hidden" name="accion" value="nivel"><label>Override de nivel<select name="nivel"><option value="">Usar cálculo automático</option>{_enum_options(CatalogPresentationTier, row.tier_override or '', {})}</select></label><button>Guardar override auditable</button></form>
<form method="post" action="/crm/catalogo/{row.listing_id}/cambiar">{command_field()}<input type="hidden" name="accion" value="readiness"><label class="check"><input type="checkbox" name="habilitado" value="1"{' checked' if row.readiness_overridden else ''}> Override Admin de preparación</label><button>Guardar override auditable</button></form>
</div></section>"""


def _detail_page(
    actor: Actor,
    row: AdministrationListing,
    *,
    saved: bool = False,
    errors: list[str] | None = None,
) -> HTMLResponse:
    readiness = (
        tag("Lista para publicar", "ok")
        if not row.action_reasons
        else _action_summary(row)
    )
    content = (
        flash("El servidor confirmó el cambio." if saved else None)
        + errors_box(errors or [])
        + '<div class="actions"><a class="button secondary" href="/crm/catalogo">Volver al catálogo</a></div>'
        + f"""
<section class="card"><h2>Qué representa cada registro</h2>
<dl class="pairs">
<dt>Inmueble físico o modelo</dt><dd>{escape(row.physical_name)} · {escape(row.physical_key)}</dd>
<dt>Publicación de fuente</dt><dd>{escape(row.title)} · {escape(row.listing_key)}</dd>
<dt>Fuente y atribución</dt><dd>{escape(SOURCE_LABELS.get(row.source_kind, row.source_kind))}: {escape(row.source_name)} · {escape(row.attribution)}</dd>
<dt>Galería aprobada</dt><dd>{escape(row.gallery_path)}</dd>
<dt>Ficha técnica aprobada</dt><dd>{escape(row.technical_sheet_path)}</dd>
</dl></section>
<section class="card"><h2>Estado autoritativo</h2><div class="grid">
<div><strong>Disponibilidad</strong><br>{tag(AVAILABILITY_LABELS.get(row.availability, row.availability))}</div>
<div><strong>Publicación</strong><br>{tag(PUBLICATION_LABELS.get(row.publication_state, row.publication_state))}</div>
<div><strong>Autoridad</strong><br>{tag(AUTHORITY_LABELS.get(row.authority, row.authority))}</div>
<div><strong>Nivel</strong><br>{escape(row.presentation_tier or 'Sin nivel')} {'· override Admin' if row.tier_override else '· automático'}</div>
</div><h3>Preparación</h3>{readiness}</section>
<section class="card"><h2>Ofertas: relación separada de la publicación</h2>{table('Ofertas comerciales', ('Operación', 'Precio', 'Visibilidad', 'Términos', 'Disponibilidad'), _offer_rows(row), empty_message='No hay ofertas.')}</section>"""
        + (_forms(row) if actor.is_administrator else '<div class="note">Tienes acceso de consulta como experto; sólo un administrador puede cambiar el catálogo.</div>')
        + _media_section(row, actor.is_administrator)
    )
    return shell(actor, row.title, content, active=ACTIVE)


@router.get("", response_class=HTMLResponse)
async def catalog_index(
    request: Request,
    saved: int = 0,
    actor: Actor = Depends(require_actor),
) -> HTMLResponse:
    async with request.app.state.database.session_scope() as session:
        rows = await CatalogProjection(session, actor).list_for_administration(_now())
    return _list_page(actor, rows, message="El servidor confirmó el registro." if saved else None)


@router.get("/nueva", response_class=HTMLResponse)
async def new_catalog_listing(
    actor: Actor = Depends(require_administrator),
) -> HTMLResponse:
    content = f"""
<p class="lead">Este registro crea tres relaciones distintas. Empieza bloqueado: un Admin debe revisar datos, autoridad, disponibilidad y términos antes de publicar.</p>
<form method="post" action="/crm/catalogo">{command_field()}
<section class="card"><h2>Inmueble físico</h2><div class="grid">
<label>Clave estable *<input name="clave_inmueble" pattern="[a-z0-9]+(?:-[a-z0-9]+)*" required></label>
<label>Nombre *<input name="nombre_inmueble" required></label>
<label>Tipo *<select name="tipo"><option value="House">Casa</option><option value="Apartment">Departamento</option><option value="Land">Terreno</option><option value="Other">Otro</option></select></label>
<label>Procedencia de los datos *<input name="procedencia_inmueble" required></label>
</div></section>
<section class="card"><h2>Publicación comercial de una fuente</h2><div class="grid">
<label>Clave de publicación *<input name="clave_publicacion" pattern="[a-z0-9]+(?:-[a-z0-9]+)*" required></label>
<label>Título *<input name="titulo" required></label>
<label>Tipo de fuente<select name="fuente_tipo">{_enum_options(ListingSourceKind, ListingSourceKind.ORGANIZATION.value, SOURCE_LABELS)}</select></label>
<label>Nombre de la fuente *<input name="fuente_nombre" required></label>
<label>Atribución *<input name="atribucion" required></label>
<label>Ubicación pública<input name="ubicacion"></label>
<label class="full">Procedencia de la publicación *<input name="procedencia_publicacion" required></label>
</div></section>
<section class="card"><h2>Oferta inicial</h2><div class="grid">
<label>Operación<select name="operacion">{_enum_options(ListingOfferOperation, ListingOfferOperation.SALE.value, OPERATION_LABELS)}</select></label>
<label>Precio *<input type="number" min="0.01" step="0.01" name="precio" required></label>
<label>Moneda<select name="moneda"><option>MXN</option><option>USD</option></select></label>
<label>Visibilidad<select name="visibilidad"><option value="Visible">Precio visible</option><option value="Hidden">Precio oculto con texto aprobado</option></select></label>
</div></section><button>Registrar como pendiente</button> <a href="/crm/catalogo">Cancelar</a></form>"""
    return shell(actor, "Registrar inmueble y publicación", content, active=ACTIVE)


@router.post("", response_class=HTMLResponse, response_model=None)
async def create_catalog_listing(
    request: Request,
    actor: Actor = Depends(require_administrator),
) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    try:
        key = command_key(form, "catalogo-crear")
        price = _decimal(form.get("precio"))
        async with request.app.state.database.session_scope() as session:
            catalog = CatalogAdministration(session)
            physical = await catalog.record(
                actor,
                CreateProperty(
                    property_key=str(form.get("clave_inmueble", "")),
                    name=str(form.get("nombre_inmueble", "")),
                    property_type=str(form.get("tipo", "")),
                    facts={},
                    provenance={"nota": str(form.get("procedencia_inmueble", ""))},
                    command_key=f"{key}:inmueble",
                ),
            )
            listing = await catalog.record(
                actor,
                CreateListing(
                    property_uuid=physical.subject_id,
                    listing_key=str(form.get("clave_publicacion", "")),
                    source_kind=str(form.get("fuente_tipo", "")),
                    source_name=str(form.get("fuente_nombre", "")),
                    attribution=str(form.get("atribucion", "")),
                    title=str(form.get("titulo", "")),
                    public_location=str(form.get("ubicacion", "")) or None,
                    provenance={"nota": str(form.get("procedencia_publicacion", ""))},
                    facts={},
                    command_key=f"{key}:publicacion",
                ),
            )
            await OfferManagement(session).record(
                actor,
                RecordOffer(
                    listing_id=listing.subject_id,
                    operation=str(form.get("operacion", "")),
                    price_amount=price,
                    price_currency=str(form.get("moneda", "")),
                    price_visibility=str(form.get("visibilidad", "")),
                    terms={},
                    terms_review_state=FactsReviewState.PENDING.value,
                    availability=OfferAvailability.UNKNOWN.value,
                    command_key=f"{key}:oferta",
                ),
            )
            await session.commit()
    except (CommercialError, ValueError) as exc:
        response = shell(
            actor,
            "No se registró el catálogo",
            errors_box([str(exc)]) + '<p><a href="/crm/catalogo/nueva">Volver al formulario</a></p>',
            active=ACTIVE,
        )
        response.status_code = 422
        return response
    return RedirectResponse(f"/crm/catalogo/{listing.subject_id}?saved=1", status_code=303)


async def _load_detail(request: Request, actor: Actor, listing_id: uuid.UUID) -> AdministrationListing:
    async with request.app.state.database.session_scope() as session:
        return await CatalogProjection(session, actor).get_for_administration(listing_id, _now())


@router.get("/{listing_id}", response_class=HTMLResponse)
async def catalog_detail(
    request: Request,
    listing_id: uuid.UUID,
    saved: int = 0,
    actor: Actor = Depends(require_actor),
) -> HTMLResponse:
    try:
        row = await _load_detail(request, actor, listing_id)
    except CommercialError as exc:
        response = shell(actor, "No disponible", errors_box([exc.message]), active=ACTIVE)
        response.status_code = 404
        return response
    return _detail_page(actor, row, saved=bool(saved))


@router.post("/{listing_id}/cambiar", response_class=HTMLResponse, response_model=None)
async def change_catalog_listing(
    request: Request,
    listing_id: uuid.UUID,
    actor: Actor = Depends(require_administrator),
) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    try:
        key = command_key(form, f"catalogo:{listing_id}")
        action = str(form.get("accion", ""))
        async with request.app.state.database.session_scope() as session:
            row = await CatalogProjection(session, actor).get_for_administration(listing_id, _now())
            catalog = CatalogAdministration(session)
            if action == "revisar_inmueble":
                if row.property_uuid is None:
                    raise ValueError("Este registro representa un modelo, no una unidad física.")
                command: Any = ReviewPropertyFacts(
                    property_uuid=row.property_uuid,
                    review_state=FactsReviewState(str(form.get("estado", ""))),
                    facts=row.physical_facts,
                    command_key=key,
                )
                await catalog.record(actor, command)
            elif action == "revisar_publicacion":
                await catalog.record(actor, ReviewListingFacts(
                    listing_id=listing_id,
                    review_state=FactsReviewState(str(form.get("estado", ""))),
                    facts=row.listing_facts,
                    command_key=key,
                ))
            elif action == "disponibilidad":
                await catalog.record(actor, SetListingAvailability(
                    listing_id, ListingAvailability(str(form.get("estado", ""))), key
                ))
            elif action == "publicacion":
                await catalog.record(actor, SetPublicationState(
                    listing_id, ListingPublicationState(str(form.get("estado", ""))), key
                ))
            elif action == "autoridad":
                await catalog.record(actor, SetListingAuthority(
                    listing_id=listing_id,
                    authority=ListingAuthority(str(form.get("estado", ""))),
                    evidence=str(form.get("evidencia", "")) or None,
                    checked_at=_now(),
                    revalidate_by=_optional_datetime(form.get("revalidar")),
                    command_key=key,
                ))
            elif action == "nivel":
                await catalog.record(actor, SetTierOverride(
                    listing_id, str(form.get("nivel", "")) or None, key
                ))
            elif action == "readiness":
                await catalog.record(actor, SetReadinessOverride(
                    listing_id, form.get("habilitado") == "1", key
                ))
            elif action == "oferta":
                await OfferManagement(session).record(actor, RecordOffer(
                    listing_id=listing_id,
                    operation=str(form.get("operacion", "")),
                    price_amount=_decimal(form.get("precio")),
                    price_currency=str(form.get("moneda", "")),
                    price_visibility=str(form.get("visibilidad", "")),
                    terms={},
                    terms_review_state=str(form.get("revision", "")),
                    availability=str(form.get("disponibilidad", "")),
                    command_key=key,
                ))
            elif action == "concluir":
                await OfferManagement(session).record(actor, CompleteOperation(
                    listing_id, str(form.get("operacion", "")), key
                ))
            else:
                raise ValueError("La acción solicitada no es válida.")
            await session.commit()
    except (CommercialError, ValueError) as exc:
        row = await _load_detail(request, actor, listing_id)
        response = _detail_page(actor, row, errors=[str(exc)])
        response.status_code = 422
        return response
    return RedirectResponse(f"/crm/catalogo/{listing_id}?saved=1", status_code=303)


@router.post("/{listing_id}/medios", response_class=HTMLResponse, response_model=None)
async def change_catalog_media(
    request: Request,
    listing_id: uuid.UUID,
    actor: Actor = Depends(require_administrator),
) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    try:
        key = command_key(form, f"catalogo-medios:{listing_id}")
        action = str(form.get("accion", ""))
        async with request.app.state.database.session_scope() as session:
            media = MediaAdministration(session, request.app.state.media_storage)
            if action == "agregar":
                upload = form.get("archivo")
                if not isinstance(upload, UploadFile):
                    raise ValueError("Selecciona una fotografía válida.")
                await media.record(actor, AddMedia(
                    listing_id=listing_id,
                    original_filename=upload.filename or "",
                    content_type=upload.content_type or "",
                    content=await upload.read(),
                    provenance=str(form.get("procedencia", "")),
                    authority=ListingAuthority.AUTHORIZED,
                    authority_evidence=str(form.get("evidencia", "")) or None,
                    is_cover=form.get("portada") == "1",
                    sort_order=int(str(form.get("orden", ""))),
                    space_group=str(form.get("grupo", "")) or None,
                    high_resolution=form.get("alta_resolucion") == "1",
                    cache_keys=(),
                    command_key=key,
                ))
            elif action == "ordenar":
                row = await CatalogProjection(session, actor).get_for_administration(listing_id, _now())
                active = [item for item in row.media if item.revoked_at is None]
                cover = _uuid(form.get("portada"), "La portada")
                placements = tuple(
                    MediaPlacement(
                        media_id=item.media_id,
                        sort_order=int(str(form.get(f"orden_{item.media_id}", ""))),
                        space_group=str(form.get(f"grupo_{item.media_id}", "")) or None,
                    )
                    for item in active
                )
                await media.record(actor, ArrangeMedia(listing_id, cover, placements, key))
            elif action.startswith("revocar:"):
                await media.record(actor, RevokeMedia(_uuid(action.split(":", 1)[1], "El medio"), key))
            else:
                raise ValueError("La acción de medios no es válida.")
    except (CommercialError, ValueError) as exc:
        row = await _load_detail(request, actor, listing_id)
        response = _detail_page(actor, row, errors=[str(exc)])
        response.status_code = 422
        return response
    return RedirectResponse(f"/crm/catalogo/{listing_id}?saved=1", status_code=303)
