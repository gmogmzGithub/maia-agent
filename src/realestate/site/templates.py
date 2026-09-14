"""Semantic, escaped Mexican-Spanish rendering for every public surface."""

from __future__ import annotations

import html
import json
import uuid
from datetime import UTC, datetime
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
SPONSORED_LABEL = "Patrocinada"
SPONSORED_ARIA_LABEL = "Publicación patrocinada, visibilidad pagada"
FACT_LABELS = {
    "bedrooms": "Recámaras",
    "bathrooms": "Baños",
    "parking_spaces": "Estacionamientos",
    "construction_m2": "Construcción",
    "land_m2": "Terreno",
    "age_years": "Antigüedad",
    "floors": "Niveles",
}

_ICON_PATHS = {
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "filter": '<path d="M4 6h16M7 12h10M10 18h4"/>',
    "heart": '<path d="M20.8 5.8c-2.1-2.1-5.5-2.1-7.6 0L12 7l-1.2-1.2a5.4 5.4 0 0 0-7.6 7.6L12 22l8.8-8.6a5.4 5.4 0 0 0 0-7.6Z"/>',
    "map": '<path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3zM9 3v15M15 6v15"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "message": '<path d="M4 5.5h16v11H9l-5 4z"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/>',
    "user": '<circle cx="12" cy="8" r="3.5"/><path d="M5.5 20c.4-4 2.5-6 6.5-6s6.1 2 6.5 6"/>',
    "grid": '<rect x="4" y="4" width="6" height="6"/><rect x="14" y="4" width="6" height="6"/><rect x="4" y="14" width="6" height="6"/><rect x="14" y="14" width="6" height="6"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="5" cy="6" r="1"/><circle cx="5" cy="12" r="1"/><circle cx="5" cy="18" r="1"/>',
    "expand": '<path d="M9 4H4v5M15 4h5v5M9 20H4v-5M15 20h5v-5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5"/>',
    "close": '<path d="m6 6 12 12M18 6 6 18"/>',
    "bed": '<path d="M3 18v-7M21 18v-5a2 2 0 0 0-2-2H9v7M3 14h18M6 11V8h3a2 2 0 0 1 2 2v1"/>',
    "bath": '<path d="M4 13h16v2a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5zM7 13V6a3 3 0 0 1 5-2l1 1"/>',
    "parking": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M9 17V7h4a3 3 0 0 1 0 6H9"/>',
    "area": '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/>',
}


def escape(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def absolute(origin: str, path: str) -> str:
    return f"{origin.rstrip('/')}/{path.lstrip('/')}"


def icon(name: str, *, class_name: str = "icon") -> str:
    return (
        f'<svg class="{escape(class_name)}" aria-hidden="true" viewBox="0 0 24 24" '
        f'fill="none" stroke="currentColor" stroke-width="1.75" '
        f'stroke-linecap="round" stroke-linejoin="round">{_ICON_PATHS[name]}</svg>'
    )


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
        f'<link rel="preload" as="image" href="{escape(preload_image)}" fetchpriority="high">'
        if preload_image
        else ""
    )
    return f"""<!doctype html>
<html lang="es-MX" data-tier="{escape(tier)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#f7f5ef">
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
<header class="site-header" data-site-header>
  <div class="header-start">
    <a class="wordmark" href="/" aria-label="Larevia, inicio">Larevia</a>
    <nav id="navegacion-principal" class="header-primary" aria-label="Navegación principal" data-site-nav>
      <a href="/propiedades?operation=Sale">Comprar</a>
      <a href="/propiedades?operation=Rental">Rentar</a>
      <a href="/#zonas">Zonas</a>
    </nav>
  </div>
  {ai_launcher("header")}
  <div class="header-actions">
    <a class="saved-link" href="/guardadas">{icon("heart")}<span>Guardadas</span></a>
    <button class="account-toggle" type="button" aria-expanded="false" aria-controls="cuenta-demo" data-account-toggle>{icon("user")}<span>Cuenta demo</span></button>
    <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="navegacion-principal" data-nav-toggle>{icon("menu")}<span class="sr-only">Menú</span></button>
  </div>
</header>
{account_demo_panel()}
<div class="page-layer" data-page-layer><main id="contenido">{body}</main>
<footer class="site-footer">
  <div class="footer-brand"><a class="wordmark wordmark-footer" href="/">Larevia</a><p>Acompañamiento inmobiliario que sí continúa.</p></div>
  <nav aria-label="Navegación secundaria"><a href="/propiedades">Propiedades</a><a href="/#zonas">Zonas</a><a href="/maia">Maia</a><a href="/#vende">Vende o renta</a></nav>
  <div class="footer-meta"><p>Guadalajara · Zapopan · Tlaquepaque</p></div>
</footer></div>
{ai_dialog()}
<div class="sr-only" id="live-region" role="status" aria-live="polite"></div>
</body>
</html>"""


def ai_launcher(location: str) -> str:
    compact = " ai-launcher-main" if location == "main" else ""
    return f"""<button class="ai-launcher{compact}" type="button" data-ai-launcher aria-haspopup="dialog"><span class="ai-launcher-query">{icon("search")}<span data-ai-prompt aria-hidden="true">Buscar casas en Zapopan</span><span class="sr-only">Abrir Buscador con IA</span></span><strong>Buscador con IA</strong></button>"""


def account_demo_panel() -> str:
    return """<aside id="cuenta-demo" class="account-demo" data-account-demo hidden><div><span class="demo-badge">Demo</span><button type="button" data-account-close aria-label="Cerrar Cuenta demo">×</button></div><h2>Cuenta demo</h2><p>Esta vista representa el espacio de cuenta que llegará después. No crea un perfil ni guarda datos personales.</p><a href="/guardadas">Ver propiedades guardadas</a><a class="admin-link" href="/admin/properties">Administrar propiedades</a></aside>"""


def ai_dialog() -> str:
    return f"""<dialog class="ai-dialog" data-ai-dialog aria-labelledby="ai-dialog-title"><section class="ai-window"><header class="ai-window-header"><div><span class="ai-status-dot" aria-hidden="true"></span><strong id="ai-dialog-title">Maia</strong><small>Buscador con IA</small></div><div class="ai-window-actions"><button type="button" data-ai-expand aria-pressed="false" aria-label="Expandir conversación" title="Expandir">{icon("expand")}</button><button type="button" data-ai-new data-ai-conversation-action aria-label="Nueva conversación" title="Nueva conversación">{icon("plus")}</button><button type="button" data-ai-delete data-ai-conversation-action aria-label="Borrar conversación" title="Borrar conversación">{icon("trash")}</button><button type="button" data-ai-close aria-label="Cerrar conversación" title="Cerrar">{icon("close")}</button></div></header><div class="ai-window-body"><div class="ai-empty" data-ai-empty><p class="eyebrow">Búsqueda conversacional</p><h2>¿Qué propiedad estás buscando?</h2><p>Cuéntame una zona, presupuesto o característica. Consultaré únicamente el inventario público actual.</p><div class="ai-suggestions"><button type="button" data-ai-suggestion="Busca casas en Zapopan">Casas en Zapopan</button><button type="button" data-ai-suggestion="Busca departamentos en renta">Departamentos en renta</button><button type="button" data-ai-suggestion="Muéstrame propiedades con tres recámaras">Tres recámaras</button></div></div><ol class="ai-thread" data-ai-thread aria-label="Conversación con Maia"></ol><p class="ai-status" data-ai-status role="status" aria-live="polite" hidden></p></div><form class="ai-composer" data-ai-form action="/maia" method="post"><label class="sr-only" for="ai-message">Mensaje para Maia</label><textarea id="ai-message" name="message" maxlength="2000" rows="1" placeholder="Pregunta o describe tu búsqueda…" required data-ai-input></textarea><button type="submit" aria-label="Enviar a Maia">{icon("arrow")}</button></form><p class="ai-fallback"><a href="/maia">Abrir la versión accesible en una página</a></p></section></dialog>"""


def sponsored_section(result: dict[str, Any]) -> str:
    cards = list(result.get("cards") or [])
    if not cards:
        return ""
    rendered = "".join(
        sponsored_card(card, surface="Homepage", position=index + 1)
        for index, card in enumerate(cards)
    )
    return f"""<section class="section-shell sponsored-section" aria-labelledby="patrocinadas"><div class="section-heading"><div><p class="eyebrow">{escape(SPONSORED_LABEL)}</p><h2 id="patrocinadas">Propiedades con visibilidad patrocinada</h2></div></div><p class="muted sponsored-disclosure">{escape(result.get("disclosure"))}</p><div class="listing-grid">{rendered}</div></section>"""


def sponsored_card(
    card: dict[str, Any], *, surface: str, position: int, operation: str = ""
) -> str:
    return listing_card(
        dict(card.get("listing") or {}),
        surface=surface,
        sponsored_exposure_id=str(card.get("exposure_id") or ""),
        sponsored_campaign_id=str(card.get("campaign_id") or ""),
        sponsored_position=position,
        operation=operation,
    )


def home(
    listings: list[dict[str, Any]], sponsored: dict[str, Any] | None = None
) -> str:
    cards = cards_grid(listings[:8], surface="Homepage")
    inventory = (
        f'<div class="listing-grid">{cards}</div>'
        if cards
        else empty_state(
            "Estamos preparando el inventario público",
            "Sólo aparecerán propiedades con autorización y disponibilidad vigentes.",
            '<a class="button button-secondary" href="/maia">Cuéntale a Maia qué buscas</a>',
        )
    )
    return f"""
<section class="home-intro section-shell"><div><p class="eyebrow">Acompañamiento inmobiliario</p><h1>Encuentra un lugar que sí encaje contigo.</h1><p>Explora inventario autorizado o describe lo que buscas; Maia te ayuda a convertir una idea en criterios claros.</p></div><div class="home-search-card">{ai_launcher("main")}<div class="home-quick-links"><a href="/propiedades?operation=Sale">Comprar</a><a href="/propiedades?operation=Rental">Rentar</a><a href="/propiedades?sort=recent">Ver propiedades nuevas</a></div></div></section>
<section class="section-shell inventory-section" aria-labelledby="seleccion"><div class="section-heading"><div><p class="eyebrow">Selección actual</p><h2 id="seleccion">Propiedades para explorar</h2></div><a class="direction-link" href="/propiedades">Ver todas {icon("arrow")}</a></div><div class="listing-grid view-grid">{cards if cards else inventory}</div></section>
<section class="section-shell zones-section" id="zonas" aria-labelledby="zonas-title"><div class="section-heading"><div><p class="eyebrow">Tres municipios, una búsqueda clara</p><h2 id="zonas-title">Explora por zona</h2></div></div>{zone_cards(listings)}</section>
<section class="process-section" id="como-funciona" aria-labelledby="proceso-title"><div class="section-shell process-layout"><div><p class="eyebrow">Acompañamiento inmobiliario que sí continúa</p><h2 id="proceso-title">De la búsqueda a una visita verificada.</h2><p>Maia ayuda a precisar lo que necesitas; Larevia conserva la verdad del inventario, disponibilidad y citas.</p></div><ol class="steps"><li><span>01</span><strong>Explora</strong><p>Consulta propiedades y datos autorizados.</p></li><li><span>02</span><strong>Conversa</strong><p>Maia conserva el contexto sin pedir una cuenta.</p></li><li><span>03</span><strong>Verifica</strong><p>La visita se confirma por el WhatsApp oficial.</p></li></ol></div></section>
<section class="section-shell seller-section" id="vende"><div><p class="eyebrow">Para propietarios</p><h2>Vende o renta tu propiedad con una ruta humana.</h2><p>Maia reúne lo esencial y entrega la conversación al equipo de Larevia para continuar.</p></div><a class="button button-secondary" href="/maia?motivo=publicar">Quiero hablar de mi propiedad</a></section>
<section class="section-shell experts-section" aria-labelledby="expertos-title"><div><p class="eyebrow">Especialistas inmobiliarios</p><h2 id="expertos-title">La tecnología acompaña. Las personas responden.</h2></div><article class="expert-card"><span aria-hidden="true">EL</span><div><strong>Equipo Larevia</strong><p>Asesoría inmobiliaria personalizada</p><small>Atención en español para comprar, vender o rentar.</small></div></article></section>
{sponsored_section(sponsored or {})}
<section class="closing-cta"><div><p class="eyebrow">Empieza por lo que ya sabes</p><h2>Una zona, un presupuesto o simplemente una idea.</h2></div><a class="button button-primary" href="/propiedades">Explorar propiedades</a></section>"""


def hero_search_form() -> str:
    return f"""<form class="hero-search" action="/propiedades" method="get" aria-label="Buscar propiedades"><label><span>Operación</span><select name="operation"><option value="Sale">Comprar</option><option value="Rental">Rentar</option><option value="Presale">Preventa</option></select></label><label><span>Zona</span><select name="zone"><option value="">Toda el área</option><option>Guadalajara</option><option>Zapopan</option><option>Tlaquepaque</option></select></label><label><span>Tipo</span><select name="property_type"><option value="">Cualquier propiedad</option>{_options(TYPE_LABELS, "")}</select></label><button class="button button-primary" type="submit">{icon("search")} Buscar</button><a class="hero-maia-link" href="/maia">Cuéntaselo a Maia {icon("arrow")}</a></form>"""


def zone_cards(listings: list[dict[str, Any]]) -> str:
    cards: list[str] = []
    for slug, zone in (
        ("guadalajara", "Guadalajara"),
        ("zapopan", "Zapopan"),
        ("tlaquepaque", "Tlaquepaque"),
    ):
        matching = [
            listing
            for listing in listings
            if zone.casefold() in str(listing.get("public_location") or "").casefold()
        ]
        cover = next(
            (
                media
                for listing in matching
                for media in listing.get("media", [])
                if media.get("is_cover")
            ),
            None,
        )
        image = responsive_image(
            cover,
            f"Propiedad publicada en {zone}",
            loading="lazy",
            sizes="(max-width: 760px) 100vw, 33vw",
        )
        count = (
            f"{len(matching)} en esta selección"
            if matching
            else "Explorar inventario actual"
        )
        cards.append(
            f'<a class="zone-card" href="/zonas/{slug}"><span class="zone-media">{image}</span><span class="zone-copy"><small>Área de servicio</small><strong>{zone}</strong><span>{count} {icon("arrow")}</span></span></a>'
        )
    return f'<div class="zone-grid">{"".join(cards)}</div>'


def search_page(
    result: dict[str, Any],
    *,
    query_string: str,
    heading: str = "Explorar propiedades",
    sponsored: dict[str, Any] | None = None,
) -> str:
    listings = list(result.get("listings") or [])
    total = int(result.get("total") or 0)
    query = result.get("query") or {}
    view = "lista" if query.get("view") == "lista" else "cuadricula"
    view_class = "list" if view == "lista" else "grid"
    results = search_results_grid(
        listings, sponsored or {}, operation=str(query.get("operation") or "")
    )
    if not results:
        results = empty_state(
            "No encontramos propiedades con esos criterios",
            "Conservamos tus filtros. Puedes quitar uno o contarle a Maia qué necesitas.",
            '<a class="button button-secondary" href="/maia">Dile a Maia qué buscas</a>',
        )
    more = ""
    if result.get("has_more"):
        next_query = dict(query)
        next_query["vista"] = view
        next_query["page"] = int(query.get("page") or 1) + 1
        params = escape(urlencode(_query_params(next_query)))
        more = f'<a class="button button-secondary load-more" href="/propiedades?{params}">Mostrar más</a>'
    view_query = _query_params(query)
    view_query.pop("page", None)
    grid_query = escape(urlencode({**view_query, "vista": "cuadricula"}))
    list_query = escape(urlencode({**view_query, "vista": "lista"}))
    return f"""<header class="catalog-hero section-shell"><nav class="breadcrumbs" aria-label="Ruta"><a href="/">Inicio</a><span>/</span><span>Propiedades</span></nav><p class="eyebrow">Inventario autorizado</p><h1>{escape(heading)}</h1><p>Información clara para comparar y decidir.</p></header><section class="search-shell" aria-label="Buscar propiedades"><div class="section-shell">{search_form(query, total=total)}</div></section><section class="results-shell" aria-labelledby="resultados"><div class="results-toolbar"><div><h2 id="resultados">{total} resultado{"s" if total != 1 else ""}</h2><p>{escape(_criteria_summary(query))}</p></div><nav class="view-switcher" aria-label="Vista de resultados"><a href="/propiedades?{grid_query}" aria-current="{'page' if view == 'cuadricula' else 'false'}" title="Cuadrícula">{icon("grid")}<span class="sr-only">Vista de cuadrícula</span></a><a href="/propiedades?{list_query}" aria-current="{'page' if view == 'lista' else 'false'}" title="Lista">{icon("list")}<span class="sr-only">Vista de lista</span></a></nav></div><div class="listing-grid view-{view_class}">{results}</div>{more}</section>"""


def search_form(query: dict[str, Any], *, total: int = 0) -> str:
    operation = str(query.get("operation") or "")
    zone = str(query.get("zone") or "")
    property_type = str(query.get("property_type") or "")
    sort = str(query.get("sort") or "relevance")
    zones = {item: item for item in ("Guadalajara", "Zapopan", "Tlaquepaque")}
    sorts = {
        "relevance": "Más relevantes",
        "recent": "Más nuevas",
        "price_asc": "Menor precio",
        "price_desc": "Mayor precio",
    }
    residential_attributes = " hidden" if property_type == "Land" else ""
    residential_input_attributes = " disabled" if property_type == "Land" else ""
    detailed_facts = f"""<label data-residential-filter{residential_attributes}>Recámaras mínimas<input inputmode="numeric" name="minimum_bedrooms" value="{escape(query.get("minimum_bedrooms"))}" min="0" autocomplete="off"{residential_input_attributes}></label><label data-residential-filter{residential_attributes}>Baños mínimos<input inputmode="decimal" name="minimum_bathrooms" value="{escape(query.get("minimum_bathrooms"))}" min="0" step="0.5" autocomplete="off"{residential_input_attributes}></label><label data-residential-filter{residential_attributes}>Estacionamientos mínimos<input inputmode="numeric" name="minimum_parking_spaces" value="{escape(query.get("minimum_parking_spaces"))}" min="0" autocomplete="off"{residential_input_attributes}></label>"""
    result_label = f"Ver {total} propiedad" if total == 1 else f"Ver {total} propiedades"
    return f"""<form class="search-form" action="/propiedades" method="get"><input type="hidden" name="vista" value="{escape(query.get('view') or 'cuadricula')}"><label><span>Operación</span><select name="operation"><option value="">Todas</option>{_options(OPERATION_LABELS, operation)}</select></label><label><span>Zona</span><select name="zone"><option value="">Toda el área</option>{_options(zones, zone)}</select></label><label><span>Tipo</span><select name="property_type" data-property-type-filter><option value="">Todos</option>{_options(TYPE_LABELS, property_type)}</select></label><details class="filter-drawer" data-filter-drawer><summary>{icon("filter")} Filtros</summary><div class="filter-panel"><div class="filter-panel-heading"><div><p class="eyebrow">Refina tu búsqueda</p><h2>Filtros</h2></div><button class="filter-close" type="button" data-filter-close aria-label="Cerrar filtros">×</button></div><div class="filter-fields"><label>Precio mínimo<input inputmode="numeric" name="minimum_price" value="{escape(query.get("minimum_price"))}" autocomplete="off"></label><label>Precio máximo<input inputmode="numeric" name="maximum_price" value="{escape(query.get("maximum_price"))}" autocomplete="off"></label>{detailed_facts}<label>Construcción mínima (m²)<input inputmode="decimal" name="minimum_construction_m2" value="{escape(query.get("minimum_construction_m2"))}" min="0" autocomplete="off"></label><label>Orden<select name="sort">{_options(sorts, sort)}</select></label></div><p class="fine-print">Sólo aplicamos los criterios que ves aquí.</p><button class="button button-primary filter-apply" type="submit">{result_label}</button></div></details><button class="button button-primary" type="submit">{icon("search")} Buscar</button><button class="search-maia" type="button" data-ai-launcher>Cuéntaselo a Maia</button></form>"""


def cards_grid(listings: list[dict[str, Any]], *, surface: str) -> str:
    return "".join(listing_card(item, surface=surface) for item in listings)


def search_results_grid(
    listings: list[dict[str, Any]],
    sponsored: dict[str, Any],
    *,
    operation: str = "",
) -> str:
    cards = list(sponsored.get("cards") or [])
    if not cards:
        return "".join(
            listing_card(item, surface="Search", operation=operation)
            for item in listings
        )
    out: list[str] = []
    for index, listing in enumerate(listings):
        if index % 6 == 0 and cards:
            out.append(
                sponsored_card(
                    cards.pop(0),
                    surface="Search",
                    position=index // 6 + 1,
                    operation=operation,
                )
            )
        out.append(listing_card(listing, surface="Search", operation=operation))
    for offset, card in enumerate(cards):
        out.append(
            sponsored_card(
                card,
                surface="Search",
                position=len(listings) // 6 + offset + 1,
                operation=operation,
            )
        )
    return "".join(out)


def listing_card(
    listing: dict[str, Any],
    *,
    surface: str,
    already_saved: bool = False,
    sponsored_exposure_id: str = "",
    sponsored_campaign_id: str = "",
    sponsored_position: int = 0,
    operation: str = "",
) -> str:
    already_saved = already_saved or bool(listing.get("_saved"))
    media = card_media(listing, surface=surface)
    visible_offers = list(listing.get("offers", []))
    if surface == "Search" and operation:
        visible_offers = [
            offer for offer in visible_offers if offer.get("operation") == operation
        ]
    offers = "".join(offer_badge(offer) for offer in visible_offers)
    facts = characteristics(listing.get("physical_facts") or {}, limit=4)
    listing_id = escape(listing.get("listing_id"))
    slug = escape(listing.get("slug"))
    sponsored = bool(sponsored_campaign_id and sponsored_exposure_id)
    detail_url = f"/propiedades/{slug}"
    if sponsored:
        detail_url += f"?patrocinio={escape(sponsored_exposure_id)}"
    attributes = (
        f' data-sponsored-campaign="{escape(sponsored_campaign_id)}" data-sponsored-exposure="{escape(sponsored_exposure_id)}" data-sponsored-position="{sponsored_position}" aria-label="{escape(SPONSORED_ARIA_LABEL)}"'
        if sponsored
        else ""
    )
    label = (
        f'<span class="tag-sponsored">{escape(SPONSORED_LABEL)}</span>'
        if sponsored
        else ""
    )
    classes = "listing-card sponsored" if sponsored else "listing-card"
    property_type = TYPE_LABELS.get(
        str(listing.get("property_type")),
        str(listing.get("property_type") or "Propiedad"),
    )
    first_offer = visible_offers[0] if visible_offers else {}
    operation_label = OPERATION_LABELS.get(str(first_offer.get("operation")), "")
    save = save_form(
        listing_id,
        return_to=f"/propiedades/{slug}",
        already_saved=already_saved,
        compact=True,
        phone_required=bool(listing.get("_save_phone_required")),
    )
    recency = recency_label(listing.get("first_published_at"))
    recency_badge = f'<span class="recency-badge">{escape(recency)}</span>' if recency else ""
    attribution = escape(listing.get("source_name") or listing.get("attribution") or "")
    source = f'<span class="card-source">{attribution}</span>' if attribution else ""
    return f"""<article class="{classes}" data-analytics="ListingImpression" data-listing-id="{listing_id}" data-surface="{escape(surface)}"{attributes}><div class="card-media-wrap"><a class="card-media" href="{detail_url}">{media}</a>{save}{label}</div><div class="card-body"><p class="card-kicker">{escape(operation_label)} · {escape(property_type)}</p><div class="offers">{offers}</div><h3><a href="{detail_url}">{escape(listing.get("title"))}</a></h3><p class="location">{escape(listing.get("public_location") or "Área Metropolitana de Guadalajara")}</p>{facts}<footer class="card-meta">{source}{recency_badge}</footer></div></article>"""


def technical_sheet(
    listing: dict[str, Any],
    discovery: dict[str, Any],
    *,
    sponsored_exposure: str | None = None,
) -> str:
    media = list(listing.get("media") or [])
    offers = "".join(offer_section(item) for item in listing.get("offers", []))
    facts = facts_table(listing.get("physical_facts") or {})
    highlights = characteristics(listing.get("physical_facts") or {}, limit=4)
    listing_id = escape(listing.get("listing_id"))
    slug = escape(listing.get("slug"))
    sponsorship_query = (
        f"?patrocinio={escape(sponsored_exposure)}" if sponsored_exposure else ""
    )
    tier = str(listing.get("presentation_tier") or "Larevia")
    tier_label = "Super Premium" if tier == "SuperPremium" else tier
    description = str(
        (listing.get("listing_facts") or {}).get("description")
        or discovery.get("description")
        or "Consulta los datos autorizados y conversa con Maia para resolver dudas sobre esta propiedad."
    )
    save = save_form(
        listing_id,
        return_to=f"/propiedades/{slug}{sponsorship_query}",
        already_saved=bool(listing.get("_saved")),
        phone_required=bool(listing.get("_save_phone_required")),
    )
    return f"""<article class="listing-detail tier-{escape(tier.lower())}"><header class="detail-heading section-shell"><nav class="breadcrumbs" aria-label="Ruta"><a href="/">Inicio</a><span>/</span><a href="/propiedades">Propiedades</a><span>/</span><span aria-current="page">{escape(listing.get("title"))}</span></nav><div><p class="sr-only">Presentación {escape(tier_label)}</p><p class="detail-location">{escape(listing.get("public_location"))}</p><h1>{escape(listing.get("title"))}</h1></div><div class="detail-heading-actions">{save}<button class="text-button" type="button" data-share-page data-share-title="{escape(listing.get("title"))}">Compartir</button></div></header>{media_mosaic(media, listing.get("title"), slug, sponsorship_query)}<nav class="detail-subnav" aria-label="Secciones de la propiedad"><a href="#resumen">Resumen</a><a href="#datos">Características</a><a href="#especialista">Especialista</a><a href="#publicacion">Publicación</a></nav><div class="detail-layout section-shell"><main><section id="resumen" class="detail-summary"><p class="eyebrow">La propiedad</p><h2>Lo esencial, sin ruido.</h2>{highlights}<p class="detail-description">{escape(description)}</p></section><section id="datos" class="facts-section"><p class="eyebrow">Ficha técnica</p><h2>Datos autorizados</h2>{facts}</section><section id="especialista" class="property-expert"><span class="expert-initials" aria-hidden="true">EL</span><div><p class="eyebrow">Tu especialista en esta propiedad</p><h2>Equipo Larevia</h2><p>Asesoría inmobiliaria personalizada · Atención en español</p><small>Te acompañamos para verificar disponibilidad y coordinar la visita.</small></div></section></main><aside class="interest-rail"><div class="rail-card"><div class="offers offers-large">{offers}</div><h2>¿Te interesa esta propiedad?</h2><p>Maia conserva el contexto y te acompaña hacia el WhatsApp oficial cuando necesites verificar una visita.</p>{interest_actions(listing, sponsored_exposure=sponsored_exposure)}</div></aside></div><section id="publicacion" class="section-shell attribution"><p class="eyebrow">Publicación</p><h2>Origen y autoridad</h2><p>{escape(listing.get("attribution"))}</p><p class="muted">Fuente: {escape(listing.get("source_name"))}</p></section></article>"""


def media_mosaic(
    media: list[dict[str, Any]], title: object, slug: str, query: str
) -> str:
    items = media[:5]
    if not items:
        return '<div class="detail-mosaic mosaic-empty"><div class="image-placeholder"><span>Larevia</span></div></div>'
    rendered = "".join(
        f'<a class="mosaic-item mosaic-item-{index + 1}" href="/propiedades/{escape(slug)}/galeria{query}">{responsive_image(item, f"{title} — fotografía {index + 1}", loading="eager" if index == 0 else "lazy", priority=index == 0, sizes="(max-width: 760px) 100vw, 60vw")}</a>'
        for index, item in enumerate(items)
    )
    return f'<div class="detail-mosaic mosaic-count-{len(items)}">{rendered}<a class="mosaic-open button button-light" href="/propiedades/{escape(slug)}/galeria{query}">Ver {len(media)} fotos</a></div>'


def gallery(listing: dict[str, Any]) -> str:
    media = list(listing.get("media") or [])
    title = str(listing.get("title") or "Propiedad")
    slides = "".join(
        f'<figure class="gallery-slide" id="foto-{index + 1}" tabindex="-1">{responsive_image(item, f"{title} — fotografía {index + 1}", loading="eager" if index < 2 else "lazy", priority=index == 0, sizes="100vw")}<figcaption><span>{escape(item.get("space_group") or "Propiedad")}</span><span>{index + 1} de {len(media)}</span></figcaption></figure>'
        for index, item in enumerate(media)
    )
    thumbnails = "".join(
        f'<a href="#foto-{index + 1}" data-gallery-thumbnail data-gallery-index="{index}" aria-label="Ver fotografía {index + 1}">{responsive_image(item, "", loading="lazy", sizes="120px")}</a>'
        for index, item in enumerate(media)
    )
    slug = escape(listing.get("slug"))
    tier = escape(str(listing.get("presentation_tier") or "Larevia").lower())
    return f"""<article class="gallery tier-{tier}" data-gallery><header class="gallery-header"><div><nav class="breadcrumbs" aria-label="Ruta"><a href="/propiedades/{slug}">Ficha técnica</a><span>/</span><span>Galería</span></nav><p class="eyebrow">Galería autorizada</p><h1>{escape(title)}</h1><p>{escape(listing.get("public_location"))}</p></div><a class="direction-link" href="/propiedades/{slug}">Volver a la ficha {icon("arrow")}</a></header><div class="gallery-layout"><div><div class="gallery-stage">{slides}</div><div class="gallery-controls" aria-label="Controles de galería"><button type="button" data-gallery-prev aria-label="Fotografía anterior">←</button><output aria-live="polite" data-gallery-count>1 de {len(media)}</output><button type="button" data-gallery-next aria-label="Fotografía siguiente">→</button></div><nav class="gallery-thumbnails" aria-label="Miniaturas de la galería">{thumbnails}</nav></div><aside class="gallery-interest"><p class="eyebrow">Siguiente paso</p><h2>Me interesa esta propiedad</h2>{interest_actions(listing)}</aside></div></article>"""


def interest_actions(
    listing: dict[str, Any], *, sponsored_exposure: str | None = None
) -> str:
    listing_id = escape(listing.get("listing_id"))
    exposure_input = (
        f'<input type="hidden" name="sponsored_exposure" value="{escape(sponsored_exposure)}">'
        if sponsored_exposure
        else ""
    )
    exposure_query = (
        f"&patrocinio={escape(sponsored_exposure)}" if sponsored_exposure else ""
    )
    return f"""<div class="interest-actions"><a class="button button-primary" href="/maia?listing_id={listing_id}{exposure_query}">{icon("message")} Me interesa esta propiedad</a><form action="/handoffs" method="post"><input type="hidden" name="purpose" value="ContinueWhatsApp"><input type="hidden" name="listing_id" value="{listing_id}">{exposure_input}<input type="hidden" name="command_key" value="handoff-{uuid.uuid4()}"><button class="button button-secondary" type="submit">Seguir por WhatsApp</button></form><form action="/handoffs" method="post"><input type="hidden" name="purpose" value="Appointment"><input type="hidden" name="listing_id" value="{listing_id}">{exposure_input}<input type="hidden" name="command_key" value="appointment-{uuid.uuid4()}"><button class="text-button" type="submit">Solicitar una visita</button></form><p class="fine-print">La visita sólo queda confirmada después de verificarla por el WhatsApp oficial.</p></div>"""


def saved_page(result: dict[str, Any]) -> str:
    items = list(result.get("items") or [])
    phone_required = not bool(result.get("phone_claimed") or result.get("protected"))
    content = "".join(saved_item(item, phone_required=phone_required) for item in items)
    if not content:
        content = empty_state(
            "Todavía no has guardado propiedades",
            "Usa el corazón en cualquier resultado o ficha. Te pediremos tu teléfono antes del primer guardado; no necesitas contraseña.",
            '<a class="button button-secondary" href="/propiedades">Explorar propiedades</a>',
        )
    protection = ""
    collection_id = result.get("collection_id")
    if collection_id and not result.get("protected"):
        protection = f"""<aside class="protection"><div><p class="eyebrow">Continuidad opcional</p><h2>Protege tu selección con WhatsApp</h2><p>Sin protección, borrar los datos del navegador elimina el acceso. No usamos huellas digitales.</p></div><form action="/handoffs" method="post"><input type="hidden" name="purpose" value="SavedCollectionProtection"><input type="hidden" name="saved_collection_id" value="{escape(collection_id)}"><input type="hidden" name="command_key" value="protect-{uuid.uuid4()}"><button class="button button-secondary" type="submit">Proteger con WhatsApp</button></form></aside>"""
    controls = ""
    if items:
        controls = f"""<div class="collection-controls"><form action="/guardadas" method="post"><input type="hidden" name="action" value="Share"><input type="hidden" name="command_key" value="share-{uuid.uuid4()}"><button class="button button-secondary" type="submit">Compartir selección</button></form><a class="button button-primary" href="/maia?guardadas=1">Hablar con Maia</a><form action="/guardadas" method="post"><input type="hidden" name="action" value="Empty"><input type="hidden" name="command_key" value="empty-{uuid.uuid4()}"><button class="text-button danger-text" type="submit">Vaciar guardadas</button></form></div>"""
    return f"""<header class="collection-hero section-shell"><p class="eyebrow">Tu selección privada</p><h1>Propiedades guardadas</h1><p>Una lista tranquila para volver, revisar y compartir. La confirmación del servidor siempre es la verdad.</p></header><section class="section-shell"><div class="saved-grid">{content}</div>{controls}{protection}</section>"""


def saved_item(item: dict[str, Any], *, phone_required: bool = False) -> str:
    listing = item.get("listing")
    if item.get("available") and listing:
        listing["_save_phone_required"] = phone_required
        return f'<div class="saved-item">{listing_card(listing, surface="Saved", already_saved=True)}</div>'
    return f"""<article class="listing-card unavailable-card"><div class="card-body"><p class="eyebrow">Ya no disponible</p><h2>{escape(item.get("title"))}</h2><p>{escape(item.get("public_location"))}</p><form action="/guardadas" method="post"><input type="hidden" name="action" value="Remove"><input type="hidden" name="listing_id" value="{escape(item.get("listing_id"))}"><input type="hidden" name="command_key" value="remove-{uuid.uuid4()}"><button class="text-button" type="submit">Quitar de guardadas</button></form><a href="/propiedades">Ver propiedades actuales</a></div></article>"""


def shared_page(result: dict[str, Any]) -> str:
    items = list(result.get("items") or [])
    content = "".join(saved_item(item) for item in items) or empty_state(
        "Esta selección está vacía", "No contiene propiedades para mostrar."
    )
    return f"""<header class="collection-hero section-shell"><p class="eyebrow">Selección compartida · Sólo lectura</p><h1>Propiedades elegidas</h1><p>Una fotografía fija de la selección al momento de compartirla, sin identidad ni edición.</p></header><section class="section-shell"><div class="saved-grid">{content}</div></section>"""


def phone_required_page(
    *, listing_id: str, return_to: str, command_key: str, error: str = ""
) -> str:
    error_html = f'<p class="form-error">{escape(error)}</p>' if error else ""
    return f"""<section class="state-page phone-required-page section-shell"><span class="state-mark" aria-hidden="true"></span><p class="eyebrow">Tu selección</p><h1>Guarda esta propiedad con tu teléfono</h1><p>Tu número vincula esta selección en este navegador y nos permite conservar tu historial de guardadas. No crea una cuenta ni se considera verificado.</p>{error_html}<form class="phone-required-form" action="/guardadas" method="post"><input type="hidden" name="action" value="Add"><input type="hidden" name="listing_id" value="{escape(listing_id)}"><input type="hidden" name="command_key" value="{escape(command_key)}"><input type="hidden" name="return_to" value="{escape(return_to)}"><label for="saved-phone-page">Número de teléfono</label><input id="saved-phone-page" name="phone_number" type="tel" inputmode="tel" autocomplete="tel" placeholder="33 1234 5678" required><button class="button button-primary" type="submit">Guardar propiedad</button></form><p class="fine-print">Para recuperar la selección en otro dispositivo deberás verificarla por el WhatsApp oficial.</p></section>"""


def conversation_page(
    messages: list[dict[str, Any]],
    *,
    conversation_id: str | None = None,
    listing_ids: list[str] | None = None,
    error: str = "",
    sponsored_exposure: str | None = None,
) -> str:
    thread = "".join(
        f'<li class="message {"message-maia" if message.get("role") == "Maia" else "message-person"}"><span>{"Maia" if message.get("role") == "Maia" else "Tú"}</span><p>{escape(message.get("body"))}</p></li>'
        for message in messages
    )
    if not thread:
        thread = '<li class="message message-maia"><span>Maia</span><p>Hola. Puedo ayudarte a precisar zona, presupuesto y tipo de propiedad.</p></li>'
    ids = listing_ids or []
    contexts = "".join(
        f'<input type="hidden" name="listing_ids" value="{escape(item)}">'
        for item in ids
    )
    context_card = (
        f'<div class="conversation-context"><span>{len(ids)}</span><p><strong>Propiedad en contexto</strong><br>Maia responderá usando sólo información autorizada.</p></div>'
        if ids
        else ""
    )
    error_html = (
        f'<p class="form-error" role="alert">{escape(error)}</p>' if error else ""
    )
    exposure_input = (
        f'<input type="hidden" name="sponsored_exposure" value="{escape(sponsored_exposure)}">'
        if sponsored_exposure
        else ""
    )
    whatsapp = ""
    if conversation_id:
        whatsapp = f"""<form action="/handoffs" method="post"><input type="hidden" name="purpose" value="ContinueWhatsApp"><input type="hidden" name="website_conversation_id" value="{escape(conversation_id)}">{exposure_input}<input type="hidden" name="command_key" value="conversation-handoff-{uuid.uuid4()}"><button class="button button-secondary" type="submit">Seguir por WhatsApp</button></form>"""
    return f"""<section class="conversation-page"><aside class="conversation-intro"><p class="eyebrow">Asistente de Larevia</p><h1>Conversa con Maia</h1><p>La conversación empieza anónima y sin cuenta. Maia puede ayudarte a buscar, comparar y entender información autorizada.</p>{context_card}<div class="prompt-list"><button type="button" data-prompt="Busco una casa en Zapopan con tres recámaras">Casa en Zapopan</button><button type="button" data-prompt="Quiero rentar un departamento en Guadalajara">Rentar departamento</button><button type="button" data-prompt="Ayúdame a comparar mis propiedades guardadas">Comparar guardadas</button></div><div class="privacy-note"><strong>Tu privacidad primero</strong><p>No escribas teléfono ni correo aquí. Para identificarte o verificar una visita, continúa por el WhatsApp oficial.</p>{whatsapp}</div></aside><div class="conversation-panel"><ol class="conversation-thread" aria-label="Conversación">{thread}</ol>{error_html}<form class="composer" action="/maia" method="post"><label for="mensaje" class="sr-only">Mensaje para Maia</label><textarea id="mensaje" name="message" maxlength="2000" required placeholder="Ejemplo: Busco una casa en Zapopan con tres recámaras"></textarea>{contexts}{exposure_input}<input type="hidden" name="command_key" value="message-{uuid.uuid4()}"><button class="button button-primary" type="submit">Enviar a Maia {icon("arrow")}</button></form><p class="fine-print">No registramos teclas, recorridos del mouse ni repetición de sesión.</p></div></section>"""


def unavailable_page() -> str:
    return """<section class="state-page section-shell"><span class="state-mark" aria-hidden="true"></span><p class="eyebrow">Publicación retirada</p><h1>Esta propiedad ya no está disponible</h1><p>La fotografía y los datos dejaron las superficies públicas. Puedes explorar el inventario autorizado actual.</p><a class="button button-primary" href="/propiedades">Ver propiedades disponibles</a></section>"""


def handoff_page(reference: str, *, expires_at: str) -> str:
    return f"""<section class="state-page handoff section-shell"><span class="state-mark" aria-hidden="true"></span><p class="eyebrow">Continuidad protegida</p><h1>Sigue en el WhatsApp oficial</h1><p>Envía esta referencia desde WhatsApp. No contiene tu nombre, teléfono ni conversación.</p><code>{escape(reference)}</code><p class="fine-print">La referencia vence {escape(expires_at)} y sólo puede usarse una vez.</p></section>"""


def report_page(data: dict[str, Any], *, token: str) -> str:
    rendered: list[str] = []
    structured = bool(data.get("summary"))
    include_line = not structured
    for line in data.get("lines") or []:
        text = str(line.get("text") or "")
        style = str(line.get("style") or "body")
        if structured and style == "heading" and text == "Resultados conocidos":
            include_line = True
        if structured and style == "heading" and text == "Definiciones":
            include_line = False
        if not include_line or not text:
            continue
        if style == "title":
            rendered.append(f"<h1>{escape(text)}</h1>")
        elif style == "heading":
            rendered.append(f'<h2 class="report-heading">{escape(text)}</h2>')
        else:
            rendered.append(f'<p class="report-line">{escape(text)}</p>')
    download = f'<a class="button button-secondary" href="/reportes/{escape(token)}/patrocinio.pdf">Descargar PDF</a>'
    if not structured:
        return f'<section class="report-shell"><p class="eyebrow">{escape(data.get("label"))}</p>{"".join(rendered)}<div class="report-actions">{download}</div></section>'

    def shown(value: object) -> str:
        return "Muestra protegida" if value is None else str(value)

    summary = "".join(
        f'<div class="report-metric"><span>{escape(item.get("label"))}</span><strong>{escape(shown(item.get("value")))}</strong></div>'
        for item in data.get("summary") or []
    )
    status = data.get("status") or {}
    status_block = f"""<div class="report-status"><div><span>Estado</span><strong>{escape(status.get("state"))}</strong></div><div><span>Días pagados</span><strong>{escape(status.get("paid_days"))}</strong></div><div><span>Entregados</span><strong>{escape(status.get("delivered_days"))}</strong></div><div><span>Restantes</span><strong>{escape(status.get("remaining_days"))}</strong></div></div>"""
    funnel_rows = "".join(
        f'<tr><th scope="row">{escape(item.get("label"))}</th><td>{escape(shown(item.get("value")))}</td><td>{escape(item.get("conversion"))}</td></tr>'
        for item in data.get("funnel") or []
    )
    trend_rows = (
        "".join(
            f'<tr><th scope="row">{escape(str(item.get("date"))[:10])}</th><td>{escape(shown(item.get("visible")))}</td><td>{escape(shown(item.get("opens")))}</td><td>{escape(shown(item.get("interest")))}</td></tr>'
            for item in data.get("trend") or []
        )
        or '<tr><td colspan="4">Sin actividad registrada en el periodo.</td></tr>'
    )
    definitions = "".join(
        f"<li>{escape(item)}</li>" for item in data.get("definitions") or []
    )
    return f"""<section class="report-shell"><header class="report-hero"><p class="eyebrow">{escape(data.get("label"))}</p><h1>Reporte de campaña</h1><p>{escape(data.get("listing_title"))}</p><p class="report-period">{escape(str(data.get("period_start"))[:10])} a {escape(str(data.get("period_end"))[:10])} · {escape(data.get("definition_version"))}</p></header><section aria-labelledby="resumen"><h2 id="resumen">Cuatro cifras para empezar</h2><div class="report-metrics">{summary}</div></section><section aria-labelledby="estado"><h2 id="estado">Estado</h2>{status_block}</section><section aria-labelledby="tendencia"><h2 id="tendencia">Tendencia</h2><div class="report-table-wrap"><table><thead><tr><th>Fecha</th><th>Visibles</th><th>Aperturas</th><th>Interés</th></tr></thead><tbody>{trend_rows}</tbody></table></div></section><section aria-labelledby="embudo"><h2 id="embudo">Embudo completo</h2><div class="report-table-wrap"><table><thead><tr><th>Paso</th><th>Volumen</th><th>Conversión anterior</th></tr></thead><tbody>{funnel_rows}</tbody></table></div></section><section class="report-detail">{"".join(rendered)}</section><section aria-labelledby="definiciones"><h2 id="definiciones">Cómo leerlo</h2><ul class="report-definitions">{definitions}</ul></section><aside class="report-disclosure"><p>{escape(data.get("disclosure"))}</p><p>{escape(data.get("disclaimer"))}</p></aside><div class="report-actions">{download}</div></section>"""


def empty_state(title: str, message: str, action: str = "") -> str:
    return f'<div class="empty-state"><span class="empty-mark" aria-hidden="true"></span><h2>{escape(title)}</h2><p>{escape(message)}</p>{action}</div>'


def responsive_image(
    media: dict[str, Any] | None,
    alt: object,
    *,
    loading: str,
    priority: bool = False,
    sizes: str = "(max-width:700px) 100vw, 50vw",
) -> str:
    if not media:
        return '<div class="image-placeholder" aria-hidden="true"><span>Larevia</span></div>'
    path = str(media.get("url"))
    priority_attribute = ' fetchpriority="high"' if priority else ""
    return (
        f'<img src="{escape(path)}?w=960" '
        f'srcset="{escape(path)}?w=480 480w, {escape(path)}?w=960 960w, '
        f'{escape(path)}?w=1440 1440w" sizes="{escape(sizes)}" width="960" '
        f'height="640" alt="{escape(alt)}" loading="{loading}" '
        f'decoding="async"{priority_attribute}>'
    )


def card_media(listing: dict[str, Any], *, surface: str) -> str:
    title = listing.get("title")
    items = sorted(
        list(listing.get("media") or []),
        key=lambda item: (not bool(item.get("is_cover")), int(item.get("sort_order") or 0)),
    )
    if not items:
        return responsive_image(None, listing.get("title"), loading="lazy")
    count = min(len(items), 4) if surface in {"Search", "Homepage"} else 1
    if count < 3:
        return responsive_image(
            items[0],
            listing.get("title"),
            loading="lazy",
            sizes="(max-width: 760px) 100vw, (max-width: 1180px) 50vw, 33vw",
        )
    photos = "".join(
        f'<span class="card-photo card-photo-{index + 1}">{responsive_image(item, f"{title} — fotografía {index + 1}", loading="lazy", sizes="(max-width: 760px) 100vw, 33vw")}</span>'
        for index, item in enumerate(items[:count])
    )
    return f'<span class="card-mosaic card-mosaic-{count}">{photos}</span>'


def recency_label(
    first_published_at: datetime | str | None, *, now: datetime | None = None
) -> str:
    """Return the short public-age label based only on first publication."""

    if first_published_at is None:
        return ""
    if isinstance(first_published_at, str):
        try:
            published = datetime.fromisoformat(first_published_at.replace("Z", "+00:00"))
        except ValueError:
            return ""
    else:
        published = first_published_at
    if published.tzinfo is None:
        published = published.replace(tzinfo=UTC)
    moment = now or datetime.now(UTC)
    elapsed = moment - published.astimezone(UTC)
    hours = elapsed.total_seconds() / 3600
    if hours < 0 or hours >= 192:
        return ""
    if hours < 48:
        return "Nueva"
    return f"{int(hours // 24)} días"


def save_form(
    listing_id: str,
    *,
    return_to: str,
    already_saved: bool = False,
    compact: bool = False,
    phone_required: bool = False,
) -> str:
    action = "Remove" if already_saved else "Add"
    pressed = "true" if already_saved else "false"
    label = "Guardada" if already_saved else "Guardar"
    compact_class = " save-form-compact" if compact else ""
    phone_dialog = ""
    if not already_saved:
        phone_dialog = """<dialog class="phone-dialog" data-phone-dialog><div class="phone-dialog-heading"><div><p class="eyebrow">Tu selección</p><h2>Guarda con tu teléfono</h2></div><button type="button" data-phone-close aria-label="Cerrar">×</button></div><p>Tu número nos permite conservar tu historial de guardadas en este navegador. No crea una cuenta ni se considera verificado.</p><label>Número de teléfono<input name="phone_number" type="tel" inputmode="tel" autocomplete="tel" placeholder="33 1234 5678"></label><p class="form-error" data-phone-error hidden></p><button class="button button-primary" type="submit">Guardar propiedad</button><p class="fine-print">Para recuperar la selección en otro dispositivo deberás verificarla por el WhatsApp oficial.</p></dialog>"""
    required = "true" if phone_required and not already_saved else "false"
    return f"""<form class="save-form{compact_class}" action="/guardadas" method="post" data-save-form data-phone-required="{required}"><input type="hidden" name="action" value="{action}"><input type="hidden" name="listing_id" value="{listing_id}"><input type="hidden" name="command_key" value="save-{uuid.uuid4()}"><input type="hidden" name="return_to" value="{escape(return_to)}"><button class="save-button" type="submit" aria-pressed="{pressed}">{icon("heart")}<span data-save-label>{label}</span></button>{phone_dialog}</form>"""


def offer_badge(offer: dict[str, Any]) -> str:
    operation = OPERATION_LABELS.get(
        str(offer.get("operation")), str(offer.get("operation"))
    )
    return f"<span><strong>{escape(price(offer))}</strong><small>{escape(operation)}</small></span>"


def offer_section(offer: dict[str, Any]) -> str:
    operation = OPERATION_LABELS.get(
        str(offer.get("operation")), str(offer.get("operation"))
    )
    return f'<section class="offer-block"><span>{escape(operation)}</span><p>{escape(price(offer))}</p></section>'


def price(offer: dict[str, Any]) -> str:
    amount = offer.get("price_amount")
    if amount is None:
        return str(
            offer.get("consultation_copy") or "Precio disponible previa consulta"
        )
    try:
        rendered = f"{Decimal(str(amount)):,.0f}"
    except Exception:
        rendered = str(amount)
    suffix = " / mes" if offer.get("operation") == "Rental" else ""
    return f"${rendered} {offer.get('price_currency', 'MXN')}{suffix}"


def characteristics(facts: dict[str, Any], *, limit: int) -> str:
    displayed = dict(facts)
    if displayed.get("bathrooms") in (None, "") and displayed.get(
        "full_bathrooms"
    ) not in (None, ""):
        total = Decimal(str(displayed["full_bathrooms"])) + Decimal(
            str(displayed.get("half_bathrooms") or 0)
        ) / Decimal("2")
        displayed["bathrooms"] = int(total) if total == int(total) else total
    fact_icons = {
        "bedrooms": "bed",
        "bathrooms": "bath",
        "parking_spaces": "parking",
        "construction_m2": "area",
        "land_m2": "area",
        "age_years": "area",
        "floors": "area",
    }
    values: list[str] = []
    for key, label in FACT_LABELS.items():
        if displayed.get(key) not in (None, ""):
            suffix = " m²" if key in {"construction_m2", "land_m2"} else ""
            values.append(
                f'<li>{icon(fact_icons[key])}<span><strong>{escape(displayed[key])}{suffix}</strong><small>{escape(label)}</small></span></li>'
            )
        if len(values) == limit:
            break
    return f'<ul class="characteristics">{"".join(values)}</ul>' if values else ""


def facts_table(facts: dict[str, Any]) -> str:
    displayed = dict(facts)
    if displayed.get("bathrooms") in (None, "") and displayed.get(
        "full_bathrooms"
    ) not in (None, ""):
        total = Decimal(str(displayed["full_bathrooms"])) + Decimal(
            str(displayed.get("half_bathrooms") or 0)
        ) / Decimal("2")
        displayed["bathrooms"] = int(total) if total == int(total) else total
    rows: list[str] = []
    for key, label in FACT_LABELS.items():
        if displayed.get(key) not in (None, ""):
            suffix = " m²" if key in {"construction_m2", "land_m2"} else ""
            rows.append(
                f"<div><dt>{escape(label)}</dt><dd>{escape(displayed[key])}{suffix}</dd></div>"
            )
    return (
        f'<dl class="facts">{"".join(rows)}</dl>'
        if rows
        else "<p>Consulta los datos disponibles con Maia.</p>"
    )


def _options(options: dict[str, str], selected: str) -> str:
    return "".join(
        f'<option value="{escape(value)}"{(" selected" if value == selected else "")}>{escape(label)}</option>'
        for value, label in options.items()
    )


def _query_params(query: dict[str, Any]) -> dict[str, str]:
    return {
        key: str(value)
        for key, value in query.items()
        if value not in (None, "", False) and key not in {"page_size", "view"}
    }


def _criteria_summary(query: dict[str, Any]) -> str:
    selected = [
        OPERATION_LABELS.get(str(query.get("operation")), ""),
        str(query.get("zone") or ""),
        TYPE_LABELS.get(str(query.get("property_type")), ""),
    ]
    if query.get("minimum_price") not in (None, ""):
        selected.append(f"Desde ${_summary_number(query['minimum_price'])}")
    if query.get("maximum_price") not in (None, ""):
        selected.append(f"Hasta ${_summary_number(query['maximum_price'])}")
    for key, label in (
        ("minimum_bedrooms", "recámaras"),
        ("minimum_bathrooms", "baños"),
        ("minimum_parking_spaces", "estacionamientos"),
    ):
        if query.get(key) not in (None, ""):
            selected.append(f"{_summary_number(query[key])}+ {label}")
    if query.get("minimum_construction_m2") not in (None, ""):
        selected.append(
            f"{_summary_number(query['minimum_construction_m2'])}+ m² de construcción"
        )
    selected.append(
        {
            "recent": "Más nuevas",
            "price_asc": "Menor precio",
            "price_desc": "Mayor precio",
        }.get(str(query.get("sort") or ""), "")
    )
    return " · ".join(item for item in selected if item) or "Sin filtros"


def _summary_number(value: object) -> str:
    try:
        number = Decimal(str(value))
    except (ArithmeticError, ValueError):  # pragma: no cover - defensive Product data
        return str(value)
    if number == number.to_integral_value():
        return f"{int(number):,}"
    return format(number.normalize(), "f")
