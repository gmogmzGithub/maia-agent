"""Semantic, escaped Mexican-Spanish rendering for every public surface."""

from __future__ import annotations

import html
import json
import uuid
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

OPERATION_LABELS = {"Sale": "Venta", "Rental": "Renta", "Presale": "Preventa"}
TYPE_LABELS = {
    "House": "Casa",
    "Apartment": "Departamento",
    "Land": "Terreno",
    "Development": "Desarrollo",
}
FACT_LABELS = {
    "bedrooms": "Recámaras",
    "bathrooms": "Baños",
    "parking_spaces": "Estacionamientos",
    "construction_m2": "Construcción",
    "land_m2": "Terreno",
    "age_years": "Antigüedad",
    "floors": "Niveles",
}


def escape(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def absolute(origin: str, path: str) -> str:
    return f"{origin.rstrip('/')}/{path.lstrip('/')}"


def document(
    *,
    title: str,
    description: str,
    body: str,
    origin: str,
    canonical_path: str,
    indexable: bool = True,
    structured_data: dict[str, Any] | None = None,
    primary_image: str | None = None,
    tier: str = "Larevia",
    preload_image: str | None = None,
) -> str:
    canonical = absolute(origin, canonical_path)
    robots = "index,follow,max-image-preview:large" if indexable else "noindex,follow"
    social_image = ""
    if primary_image:
        image = absolute(origin, primary_image)
        social_image = (
            f'<meta property="og:image" content="{escape(image)}">'
            f'<meta name="twitter:image" content="{escape(image)}">'
        )
    structured = ""
    if structured_data is not None:
        payload = json.dumps(structured_data, ensure_ascii=False, default=str).replace(
            "<", "\\u003c"
        )
        structured = f'<script type="application/ld+json">{payload}</script>'
    preload = (
        f'<link rel="preload" as="image" href="{escape(preload_image)}" '
        'fetchpriority="high">'
        if preload_image
        else ""
    )
    return f"""<!doctype html>
<html lang="es-MX" data-tier="{escape(tier)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#173d35">
<meta name="description" content="{escape(description)}">
<meta name="robots" content="{robots}">
<link rel="canonical" href="{escape(canonical)}">
<meta property="og:type" content="website">
<meta property="og:locale" content="es_MX">
<meta property="og:site_name" content="Larevia">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(description)}">
<meta property="og:url" content="{escape(canonical)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{escape(title)}">
<meta name="twitter:description" content="{escape(description)}">
{social_image}{preload}
<link rel="stylesheet" href="/assets/site.css">
<script src="/assets/site.js" defer></script>
<title>{escape(title)}</title>
{structured}
</head>
<body>
<a class="skip-link" href="#contenido">Ir al contenido principal</a>
<header class="site-header">
  <a class="wordmark" href="/" aria-label="Larevia, inicio"><span>L</span> Larevia</a>
  <nav aria-label="Navegación principal">
    <a href="/propiedades">Propiedades</a>
    <a href="/guardadas">Guardadas</a>
    <a class="nav-maia" href="/maia">Hablar con Maia</a>
  </nav>
</header>
<main id="contenido">{body}</main>
<footer class="site-footer">
  <a class="wordmark wordmark-footer" href="/"><span>L</span> Larevia</a>
  <p>Acompañamiento inmobiliario que sí continúa.</p>
  <p class="fine-print">Larevia es un nombre de trabajo pendiente de validación de marca.</p>
</footer>
<div class="sr-only" id="live-region" role="status" aria-live="polite"></div>
</body>
</html>"""


def home(listings: list[dict[str, Any]]) -> str:
    featured = listings[0] if listings else None
    featured_cover = (
        next(
            (item for item in featured.get("media", []) if item.get("is_cover")),
            None,
        )
        if featured
        else None
    )
    featured_visual = (
        f"""<figure class="hero-photo">
    {responsive_image(featured_cover, featured.get("title"), loading="eager", priority=True)}
    <figcaption><span>{escape(featured.get("public_location") or "Área Metropolitana de Guadalajara")}</span>{escape(featured.get("title"))}</figcaption>
  </figure>"""
        if featured_cover and featured
        else '<div class="hero-photo hero-photo-empty" aria-hidden="true"><span>L</span></div>'
    )
    cards = cards_grid(listings, surface="Homepage")
    inventory = (
        f"<div class=\"listing-grid\">{cards}</div>"
        if cards
        else empty_state(
            "Estamos preparando el inventario público",
            "Sólo aparecerán propiedades con autorización y disponibilidad vigentes.",
        )
    )
    return f"""
<section class="hero">
  <div class="hero-copy-block">
    <p class="eyebrow">Larevia · Guadalajara</p>
    <h1>Acompañamiento inmobiliario<br>que sí continúa.</h1>
    <p class="hero-copy">Explora inventario autorizado o cuéntale a Maia qué estás buscando.</p>
    <div class="hero-actions">
      <a class="button button-primary" href="/maia">Cuéntale a Maia qué estás buscando</a>
      <a class="button button-secondary" href="/propiedades">Explorar propiedades</a>
    </div>
    <div class="service-route" aria-label="Zona inicial de servicio">
      <span>Guadalajara</span><span>Zapopan</span><span>Tlaquepaque</span>
    </div>
  </div>
  {featured_visual}
</section>
<section class="section-shell promise-grid" aria-labelledby="como-acompanamos">
  <div><p class="eyebrow">Una ruta clara</p><h2 id="como-acompanamos">Busca, conversa y solicita una visita</h2></div>
  <ol class="steps">
    <li><span>01</span><strong>Explora</strong><p>Consulta propiedades y datos autorizados.</p></li>
    <li><span>02</span><strong>Conversa</strong><p>Maia te ayuda a precisar lo que buscas.</p></li>
    <li><span>03</span><strong>Verifica</strong><p>La cita se confirma por el WhatsApp oficial.</p></li>
  </ol>
</section>
<section class="section-shell inventory-section" aria-labelledby="seleccion">
  <div class="section-heading"><div><p class="eyebrow">Selección actual</p><h2 id="seleccion">Propiedades para explorar</h2></div><a href="/propiedades">Ver todas</a></div>
  {inventory}
</section>"""


def search_page(
    result: dict[str, Any], *, query_string: str, heading: str = "Explorar propiedades"
) -> str:
    listings = list(result.get("listings") or [])
    total = int(result.get("total") or 0)
    query = result.get("query") or {}
    results = cards_grid(listings, surface="Search")
    if not results:
        results = empty_state(
            "No encontramos propiedades con esos criterios",
            "Conservamos tus filtros. Puedes quitar uno o contarle a Maia qué necesitas.",
            '<a class="button button-secondary" href="/maia">Dile a Maia qué buscas</a>',
        )
    more = ""
    if result.get("has_more"):
        next_query = dict(query)
        next_query["page"] = int(query.get("page") or 1) + 1
        more = f'<a class="button button-secondary load-more" href="/propiedades?{escape(urlencode(_query_params(next_query)))}">Mostrar más</a>'
    return f"""
<section class="catalog-hero section-shell">
  <p class="eyebrow">Inventario autorizado</p><h1>{escape(heading)}</h1>
  <p>Filtros explícitos, resultados actuales y ninguna personalización oculta.</p>
</section>
<section class="search-shell section-shell" aria-label="Buscar propiedades">
  {search_form(query)}
</section>
<section class="section-shell" aria-labelledby="resultados">
  <div class="section-heading"><h2 id="resultados">{total} resultado{'s' if total != 1 else ''}</h2><p class="muted">{escape(_criteria_summary(query))}</p></div>
  <div class="listing-grid">{results}</div>{more}
</section>"""


def search_form(query: dict[str, Any]) -> str:
    operation = str(query.get("operation") or "")
    zone = str(query.get("zone") or "")
    property_type = str(query.get("property_type") or "")
    sort = str(query.get("sort") or "relevance")
    return f"""<form class="search-form" action="/propiedades" method="get">
<label>Operación<select name="operation"><option value="">Todas</option>{_options(OPERATION_LABELS, operation)}</select></label>
<label>Zona<select name="zone"><option value="">Toda el área</option>{_options({zone: zone for zone in ('Guadalajara','Zapopan','Tlaquepaque')}, zone)}</select></label>
<label>Tipo<select name="property_type"><option value="">Todos</option>{_options(TYPE_LABELS, property_type)}</select></label>
<details class="more-filters"><summary>Precio y orden</summary><div class="detail-fields">
<label>Precio mínimo<input inputmode="numeric" name="minimum_price" value="{escape(query.get('minimum_price'))}" autocomplete="off"></label>
<label>Precio máximo<input inputmode="numeric" name="maximum_price" value="{escape(query.get('maximum_price'))}" autocomplete="off"></label>
<label>Orden<select name="sort">{_options({'relevance':'Más relevantes','recent':'Más recientes','price_asc':'Menor precio','price_desc':'Mayor precio'}, sort)}</select></label>
</div></details>
<button class="button button-primary" type="submit">Buscar</button>
</form>"""


def cards_grid(listings: list[dict[str, Any]], *, surface: str) -> str:
    return "".join(listing_card(item, surface=surface) for item in listings)


def listing_card(
    listing: dict[str, Any], *, surface: str, already_saved: bool = False
) -> str:
    already_saved = already_saved or bool(listing.get("_saved"))
    cover = next((item for item in listing.get("media", []) if item.get("is_cover")), None)
    media = responsive_image(cover, listing.get("title"), loading="lazy") if cover else ""
    offers = "".join(offer_badge(offer) for offer in listing.get("offers", []))
    facts = characteristics(listing.get("physical_facts") or {}, limit=4)
    listing_id = escape(listing.get("listing_id"))
    slug = escape(listing.get("slug"))
    return f"""<article class="listing-card" data-analytics="ListingImpression" data-listing-id="{listing_id}" data-surface="{escape(surface)}">
<a class="card-media" href="/propiedades/{slug}">{media}<span class="tier-mark">{escape(_tier_label(listing.get('presentation_tier')))}</span></a>
<div class="card-body"><p class="location">{escape(listing.get('public_location') or 'Área Metropolitana de Guadalajara')}</p>
<h3><a href="/propiedades/{slug}">{escape(listing.get('title'))}</a></h3>
<div class="offers">{offers}</div>{facts}
{save_form(listing_id, return_to=f'/propiedades/{slug}', already_saved=already_saved)}
</div></article>"""


def technical_sheet(listing: dict[str, Any], discovery: dict[str, Any]) -> str:
    media = list(listing.get("media") or [])
    cover = next((item for item in media if item.get("is_cover")), media[0] if media else None)
    cover_html = responsive_image(cover, listing.get("title"), loading="eager", priority=True)
    offers = "".join(offer_section(item) for item in listing.get("offers", []))
    facts = facts_table(listing.get("physical_facts") or {})
    listing_id = escape(listing.get("listing_id"))
    slug = escape(listing.get("slug"))
    return f"""<article class="listing-detail tier-{escape(str(listing.get('presentation_tier') or 'Larevia').lower())}">
<header class="detail-hero"><div class="detail-cover">{cover_html}</div>
<div class="detail-intro"><p class="eyebrow">{escape(_tier_label(listing.get('presentation_tier')))}</p>
<h1>{escape(listing.get('title'))}</h1><p class="detail-location">{escape(listing.get('public_location'))}</p>
<div class="offers offers-large">{offers}</div>
<div class="detail-actions">{save_form(listing_id, return_to=f'/propiedades/{slug}', already_saved=bool(listing.get('_saved')))}<a class="button button-secondary" href="/propiedades/{slug}/galeria">Abrir galería</a></div>
</div></header>
<div class="detail-layout section-shell"><section aria-labelledby="datos"><p class="eyebrow">Ficha técnica</p><h2 id="datos">Datos autorizados</h2>{facts}</section>
<aside class="maia-panel"><p class="eyebrow">Maia</p><h2>¿Te interesa esta propiedad?</h2><p>Conserva el contexto al continuar en el sitio o por el WhatsApp oficial.</p>{interest_actions(listing)}</aside></div>
<section class="section-shell attribution"><h2>Publicación</h2><p>{escape(listing.get('attribution'))}</p><p class="muted">Fuente: {escape(listing.get('source_name'))}</p></section>
</article>"""


def gallery(listing: dict[str, Any]) -> str:
    media = list(listing.get("media") or [])
    slides = "".join(
        f'<figure class="gallery-slide" id="foto-{index + 1}" tabindex="-1">'
        f'{responsive_image(item, f"{listing.get("title")} — fotografía {index + 1}", loading="eager" if index < 2 else "lazy", priority=index == 0)}'
        f'<figcaption>{escape(item.get("space_group") or "Propiedad")} · {index + 1} de {len(media)}</figcaption></figure>'
        for index, item in enumerate(media)
    )
    slug = escape(listing.get("slug"))
    return f"""<article class="gallery" data-gallery>
<header class="gallery-header"><div><p class="eyebrow">Galería · {escape(_tier_label(listing.get('presentation_tier')))}</p><h1>{escape(listing.get('title'))}</h1><p>{escape(listing.get('public_location'))}</p></div>
<div class="gallery-links"><a href="/propiedades/{slug}">Ver ficha técnica</a></div></header>
<div class="gallery-stage">{slides}</div>
<div class="gallery-controls" aria-label="Controles de galería"><button type="button" data-gallery-prev aria-label="Fotografía anterior">←</button><output aria-live="polite" data-gallery-count>1 de {len(media)}</output><button type="button" data-gallery-next aria-label="Fotografía siguiente">→</button></div>
<aside class="gallery-interest"><h2>Me interesa esta propiedad</h2>{interest_actions(listing)}</aside>
</article>"""


def interest_actions(listing: dict[str, Any]) -> str:
    listing_id = escape(listing.get("listing_id"))
    return f"""<div class="interest-actions">
<form action="/handoffs" method="post"><input type="hidden" name="purpose" value="ContinueWhatsApp"><input type="hidden" name="listing_id" value="{listing_id}"><input type="hidden" name="command_key" value="handoff-{uuid.uuid4()}"><button class="button button-whatsapp" type="submit">Seguir por WhatsApp</button></form>
<a class="button button-secondary" href="/maia?listing_id={listing_id}">Continuar en el sitio</a>
<form action="/handoffs" method="post"><input type="hidden" name="purpose" value="Appointment"><input type="hidden" name="listing_id" value="{listing_id}"><input type="hidden" name="command_key" value="appointment-{uuid.uuid4()}"><button class="text-button" type="submit">Solicitar una cita</button></form>
<p class="fine-print">La cita sólo queda confirmada después de verificarla por el WhatsApp oficial.</p>
</div>"""


def saved_page(result: dict[str, Any]) -> str:
    items = list(result.get("items") or [])
    content = "".join(saved_item(item) for item in items)
    if not content:
        content = empty_state(
            "Todavía no has guardado propiedades",
            "Usa el control Guardar en cualquier resultado o ficha.",
            '<a class="button button-secondary" href="/propiedades">Explorar propiedades</a>',
        )
    protection = ""
    collection_id = result.get("collection_id")
    if collection_id and not result.get("protected"):
        protection = f"""<aside class="protection"><h2>Protege tu selección con WhatsApp</h2><p>Sin protección, borrar los datos del navegador elimina el acceso a esta colección. No usamos huellas digitales.</p>
<form action="/handoffs" method="post"><input type="hidden" name="purpose" value="SavedCollectionProtection"><input type="hidden" name="saved_collection_id" value="{escape(collection_id)}"><input type="hidden" name="command_key" value="protect-{uuid.uuid4()}"><button class="button button-whatsapp" type="submit">Proteger con WhatsApp</button></form></aside>"""
    controls = ""
    if items:
        controls = f"""<div class="collection-controls"><form action="/guardadas" method="post"><input type="hidden" name="action" value="Share"><input type="hidden" name="command_key" value="share-{uuid.uuid4()}"><button class="button button-secondary" type="submit">Compartir mi selección</button></form>
<a class="button button-secondary" href="/maia?guardadas=1">Hablar con Maia sobre mis propiedades guardadas</a>
<form action="/guardadas" method="post"><input type="hidden" name="action" value="Empty"><input type="hidden" name="command_key" value="empty-{uuid.uuid4()}"><button class="text-button danger-text" type="submit">Vaciar mis propiedades guardadas</button></form></div>"""
    return f"""<section class="section-shell saved-header"><p class="eyebrow">Tu selección</p><h1>Mis propiedades guardadas</h1><p>La confirmación del servidor es la verdad de esta lista.</p></section>
<section class="section-shell"><div class="saved-grid">{content}</div>{controls}{protection}</section>"""


def saved_item(item: dict[str, Any]) -> str:
    listing = item.get("listing")
    if item.get("available") and listing:
        card = listing_card(listing, surface="Saved", already_saved=True)
        return f'<div class="saved-item">{card}</div>'
    return f"""<article class="listing-card unavailable-card"><div class="card-body"><p class="eyebrow">Ya no disponible</p><h2>{escape(item.get('title'))}</h2><p>{escape(item.get('public_location'))}</p>
<form action="/guardadas" method="post"><input type="hidden" name="action" value="Remove"><input type="hidden" name="listing_id" value="{escape(item.get('listing_id'))}"><input type="hidden" name="command_key" value="remove-{uuid.uuid4()}"><button class="text-button" type="submit">Quitar de guardadas</button></form><a href="/propiedades">Ver propiedades similares</a></div></article>"""


def shared_page(result: dict[str, Any]) -> str:
    items = list(result.get("items") or [])
    content = "".join(saved_item(item) for item in items) or empty_state(
        "Esta selección está vacía", "No contiene propiedades para mostrar."
    )
    return f"""<section class="section-shell saved-header"><p class="eyebrow">Selección compartida</p><h1>Propiedades elegidas</h1><p>Es una fotografía fija de la selección al momento de compartirla.</p></section><section class="section-shell"><div class="saved-grid">{content}</div></section>"""


def conversation_page(
    messages: list[dict[str, Any]],
    *,
    conversation_id: str | None = None,
    listing_ids: list[str] | None = None,
    error: str = "",
) -> str:
    thread = "".join(
        f'<li class="message {"message-maia" if message.get("role") == "Maia" else "message-person"}"><span>{"Maia" if message.get("role") == "Maia" else "Tú"}</span><p>{escape(message.get("body"))}</p></li>'
        for message in messages
    )
    if not thread:
        thread = '<li class="message message-maia"><span>Maia</span><p>Hola. Cuéntame qué tipo de propiedad buscas y en qué zona.</p></li>'
    contexts = "".join(
        f'<input type="hidden" name="listing_ids" value="{escape(item)}">'
        for item in (listing_ids or [])
    )
    error_html = f'<p class="form-error" role="alert">{escape(error)}</p>' if error else ""
    whatsapp = ""
    if conversation_id:
        whatsapp = f"""<form action="/handoffs" method="post"><input type="hidden" name="purpose" value="ContinueWhatsApp"><input type="hidden" name="website_conversation_id" value="{escape(conversation_id)}"><input type="hidden" name="command_key" value="conversation-handoff-{uuid.uuid4()}"><button class="button button-whatsapp" type="submit">Seguir por WhatsApp</button></form>"""
    return f"""<section class="conversation-shell"><header><p class="eyebrow">Asistente de Larevia</p><h1>Conversa con Maia</h1><p>La conversación empieza anónima. Para identificarte o confirmar una cita, continúa por el WhatsApp oficial.</p>{whatsapp}</header>
<ol class="conversation-thread" aria-label="Conversación">{thread}</ol>
{error_html}<form class="composer" action="/maia" method="post"><label for="mensaje" class="sr-only">Mensaje para Maia</label><textarea id="mensaje" name="message" maxlength="2000" required placeholder="Ejemplo: Busco una casa en Zapopan con tres recámaras"></textarea>{contexts}<input type="hidden" name="command_key" value="message-{uuid.uuid4()}"><button class="button button-primary" type="submit">Enviar a Maia</button></form>
<p class="fine-print">No escribas aquí tu teléfono ni correo. No registramos teclas, recorridos del mouse ni repetición de sesión.</p></section>"""


def unavailable_page() -> str:
    return """<section class="section-shell unavailable"><p class="eyebrow">Publicación retirada</p><h1>Esta propiedad ya no está disponible</h1><p>La retiramos de las superficies públicas. Puedes explorar el inventario autorizado actual.</p><a class="button button-primary" href="/propiedades">Ver propiedades disponibles</a></section>"""


def handoff_page(reference: str, *, expires_at: str) -> str:
    return f"""<section class="section-shell handoff"><p class="eyebrow">Continuidad protegida</p><h1>Sigue en el WhatsApp oficial</h1><p>Envía esta referencia desde WhatsApp. No contiene tu nombre, teléfono ni conversación.</p><code>{escape(reference)}</code><p class="fine-print">La referencia vence {escape(expires_at)} y sólo puede usarse una vez.</p></section>"""


def empty_state(title: str, message: str, action: str = "") -> str:
    return f'<div class="empty-state"><span aria-hidden="true">L</span><h2>{escape(title)}</h2><p>{escape(message)}</p>{action}</div>'


def responsive_image(
    media: dict[str, Any] | None,
    alt: object,
    *,
    loading: str,
    priority: bool = False,
) -> str:
    if not media:
        return '<div class="image-placeholder" aria-hidden="true"><span>L</span></div>'
    path = str(media.get("url"))
    return (
        f'<img src="{escape(path)}?w=960" '
        f'srcset="{escape(path)}?w=480 480w, {escape(path)}?w=960 960w, '
        f'{escape(path)}?w=1440 1440w" sizes="(max-width:700px) 100vw, 50vw" '
        f'width="960" height="720" alt="{escape(alt)}" loading="{loading}" '
        f'decoding="async"{(" fetchpriority=\"high\"" if priority else "")}>'
    )


def save_form(
    listing_id: str, *, return_to: str, already_saved: bool = False
) -> str:
    action = "Remove" if already_saved else "Add"
    pressed = "true" if already_saved else "false"
    icon = "♥" if already_saved else "♡"
    label = "Guardada" if already_saved else "Guardar"
    return f"""<form class="save-form" action="/guardadas" method="post" data-save-form>
<input type="hidden" name="action" value="{action}"><input type="hidden" name="listing_id" value="{listing_id}"><input type="hidden" name="command_key" value="save-{uuid.uuid4()}"><input type="hidden" name="return_to" value="{escape(return_to)}">
<button class="save-button" type="submit" aria-pressed="{pressed}"><span aria-hidden="true">{icon}</span><span data-save-label>{label}</span></button></form>"""


def offer_badge(offer: dict[str, Any]) -> str:
    operation = OPERATION_LABELS.get(str(offer.get("operation")), str(offer.get("operation")))
    return f'<span><strong>{escape(operation)}</strong> {escape(price(offer))}</span>'


def offer_section(offer: dict[str, Any]) -> str:
    operation = OPERATION_LABELS.get(str(offer.get("operation")), str(offer.get("operation")))
    return f'<section class="offer-block"><h2>{escape(operation)}</h2><p>{escape(price(offer))}</p></section>'


def price(offer: dict[str, Any]) -> str:
    amount = offer.get("price_amount")
    if amount is None:
        return str(offer.get("consultation_copy") or "Precio disponible previa consulta")
    try:
        number = Decimal(str(amount))
        rendered = f"{number:,.0f}"
    except Exception:
        rendered = str(amount)
    suffix = " / mes" if offer.get("operation") == "Rental" else ""
    return f"${rendered} {offer.get('price_currency', 'MXN')}{suffix}"


def characteristics(facts: dict[str, Any], *, limit: int) -> str:
    values = []
    for key, label in FACT_LABELS.items():
        if facts.get(key) not in (None, ""):
            suffix = " m²" if key in {"construction_m2", "land_m2"} else ""
            values.append(f"<li><strong>{escape(facts[key])}{suffix}</strong> {escape(label)}</li>")
        if len(values) == limit:
            break
    return f'<ul class="characteristics">{"".join(values)}</ul>' if values else ""


def facts_table(facts: dict[str, Any]) -> str:
    rows = []
    for key, label in FACT_LABELS.items():
        if facts.get(key) not in (None, ""):
            suffix = " m²" if key in {"construction_m2", "land_m2"} else ""
            rows.append(f"<div><dt>{escape(label)}</dt><dd>{escape(facts[key])}{suffix}</dd></div>")
    return f'<dl class="facts">{"".join(rows)}</dl>' if rows else "<p>Consulta los datos disponibles con Maia.</p>"


def _options(options: dict[str, str], selected: str) -> str:
    return "".join(
        f'<option value="{escape(value)}"{(" selected" if value == selected else "")}>{escape(label)}</option>'
        for value, label in options.items()
    )


def _query_params(query: dict[str, Any]) -> dict[str, str]:
    return {
        key: str(value)
        for key, value in query.items()
        if value not in (None, "", False) and key != "page_size"
    }


def _criteria_summary(query: dict[str, Any]) -> str:
    selected = [
        OPERATION_LABELS.get(str(query.get("operation")), ""),
        str(query.get("zone") or ""),
        TYPE_LABELS.get(str(query.get("property_type")), ""),
    ]
    return " · ".join(item for item in selected if item) or "Sin filtros"


def _tier_label(value: object) -> str:
    return "Super Premium" if value == "SuperPremium" else str(value or "Larevia")
