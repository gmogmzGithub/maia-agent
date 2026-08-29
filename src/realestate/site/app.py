"""Separate SSR process for the public Larevia experience (ADR-0034)."""

from __future__ import annotations

import asyncio
import io
import json
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError

from realestate.config import Settings, get_settings
from realestate.site.gateway import (
    GatewayResponse,
    HttpProductSiteGateway,
    ProductSiteGateway,
    host_of,
)
from realestate.site.templates import (
    absolute,
    conversation_page,
    document,
    escape,
    gallery,
    handoff_page,
    home,
    report_page,
    saved_page,
    search_page,
    shared_page,
    technical_sheet,
    unavailable_page,
)

SAVED_COOKIE = "larevia_saved"
CONVERSATION_COOKIE = "larevia_conversation"

#: An opaque per-browser reference used for one thing only: the per-session
#: daily cap on paid Visible Impressions (ADR-0043). It is random, carries no
#: identity, is never joined to a Contact, and Product pseudonymises it before
#: storing anything derived from it. It is not an advertising identifier and
#: there is no profile behind it.
SESSION_COOKIE = "larevia_sesion"

#: Shorter than the saved-collection cookie on purpose. A frequency cap needs a
#: session, not a year-long identity.
SESSION_COOKIE_MAX_AGE = 24 * 60 * 60

COOKIE_MAX_AGE = 365 * 24 * 60 * 60
LOCAL_PAGES = {
    "guadalajara": "Guadalajara",
    "zapopan": "Zapopan",
    "tlaquepaque": "Tlaquepaque",
}
_SAFE_RETURN = re.compile(r"^/(?!/)[A-Za-z0-9/_?&=.%+-]*$")


def _response_headers(*, private: bool = False) -> dict[str, str]:
    return {
        "Cache-Control": "private, no-store" if private else "public, max-age=0, must-revalidate",
        "Content-Language": "es-MX",
        "Content-Security-Policy": (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; form-action 'self' https://wa.me; "
            "base-uri 'none'; frame-ancestors 'none'; object-src 'none'"
        ),
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), browsing-topics=()",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }


def _html(
    content: str,
    *,
    status_code: int = 200,
    private: bool = False,
    noindex: bool = False,
) -> HTMLResponse:
    headers = _response_headers(private=private)
    if noindex:
        headers["X-Robots-Tag"] = "noindex, follow"
    return HTMLResponse(content, status_code=status_code, headers=headers)


def _detail(response: GatewayResponse) -> str:
    if isinstance(response.data, dict):
        detail = response.data.get("detail")
        if isinstance(detail, str):
            return detail
    return "La operación no está disponible en este momento."


def _data(response: GatewayResponse) -> dict[str, Any]:
    return response.data if isinstance(response.data, dict) else {}


def _token_header(name: str, token: str | None) -> tuple[str, str] | None:
    return (name, token) if token else None


def _crawler(user_agent: str) -> bool:
    """Whether the caller names itself a crawler.

    Decided here and sent to Product as a boolean. The user-agent string itself
    never crosses the boundary, so no analytics row can hold one: excluding bot
    traffic must not become a reason to store a device fingerprint.
    """
    folded = user_agent.casefold()
    return any(
        token in folded
        for token in (
            "bot",
            "crawler",
            "spider",
            "slurp",
            "headlesschrome",
            "python-requests",
            "curl/",
            "wget/",
        )
    )


def _session_reference(request: Request) -> str:
    """Return the browser reference used throughout this request.

    Sponsored selection happens before the HTML response exists.  Minting the
    value here ensures the Served event and the cookie written later name the
    same browser session, including on the very first page view.
    """
    existing = request.cookies.get(SESSION_COOKIE)
    if existing:
        return existing
    minted = getattr(request.state, "session_reference", None)
    if not isinstance(minted, str):
        minted = uuid.uuid4().hex
        request.state.session_reference = minted
    return minted


def _measurement_headers(
    request: Request, *, sponsored_exposure: object | None = None
) -> dict[str, str]:
    """The session reference and crawler flag Product needs for capping."""
    headers = {"X-Crawler": "true" if _crawler(request.headers.get("user-agent", "")) else "false"}
    headers["X-Session-Reference"] = _session_reference(request)
    exposure = sponsored_exposure or request.query_params.get("patrocinio")
    if exposure:
        headers["X-Sponsored-Exposure"] = str(exposure)
    return headers


def _set_session_cookie(response: Response, request: Request) -> str:
    """Ensure the browser has a capping reference, minting one if needed."""
    existing = request.cookies.get(SESSION_COOKIE)
    if existing:
        return existing
    minted = _session_reference(request)
    response.set_cookie(
        SESSION_COOKIE,
        minted,
        max_age=SESSION_COOKIE_MAX_AGE,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return minted


def _set_cookie(response: Response, name: str, token: str | None) -> None:
    if token:
        response.set_cookie(
            name,
            token,
            max_age=COOKIE_MAX_AGE,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/",
        )


def create_site_app(
    settings: Settings | None = None, gateway: ProductSiteGateway | None = None
) -> FastAPI:
    configuration = settings or get_settings()
    owns_gateway = gateway is None
    product = gateway or HttpProductSiteGateway(
        configuration.product_internal_base_url,
        configuration.site_internal_token,
        site_host=host_of(configuration.site_public_origin),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.gateway = product
        try:
            yield
        finally:
            if owns_gateway:
                await product.aclose()

    site = FastAPI(
        title="Larevia — sitio público",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    site.state.settings = configuration
    site.state.gateway = product
    assets = Path(__file__).parent / "assets"
    site.mount("/assets", StaticFiles(directory=assets), name="public-assets")

    @site.get("/", response_class=HTMLResponse)
    async def homepage(request: Request) -> HTMLResponse:
        result = await product.request(
            "GET", "/internal/public-site/catalog", params={"page_size": 8}
        )
        listings = list(_data(result).get("listings") or []) if result.status_code == 200 else []
        await _annotate_saved(listings, request, product)
        sponsored = await _sponsored(
            request, product, surface="Homepage", listings=listings
        )
        body = home(listings, sponsored)
        structured = {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": "Larevia",
            "url": configuration.site_public_origin,
            "inLanguage": "es-MX",
        }
        response = _html(
            document(
                title="Larevia · Acompañamiento inmobiliario que sí continúa",
                description=(
                    "Explora propiedades autorizadas en Guadalajara, Zapopan y "
                    "Tlaquepaque, y conversa con Maia."
                ),
                body=body,
                origin=configuration.site_public_origin,
                canonical_path="/",
                structured_data=structured,
            )
        )
        _set_session_cookie(response, request)
        return response

    @site.get("/propiedades", response_class=HTMLResponse)
    async def properties(request: Request) -> HTMLResponse:
        params = {
            key: value
            for key, value in request.query_params.multi_items()
            if key
            in {
                "operation",
                "zone",
                "property_type",
                "minimum_price",
                "maximum_price",
                "sort",
                "page",
            }
            and value
        }
        result = await product.request(
            "GET", "/internal/public-site/catalog", params={**params, "page_size": 12}
        )
        data = _data(result) if result.status_code == 200 else {
            "listings": [],
            "total": 0,
            "query": params,
        }
        listings = list(data.get("listings") or [])
        await _annotate_saved(listings, request, product)
        sponsored = await _sponsored(
            request, product, surface="Search", listings=listings
        )
        if result.status_code != 200:
            body = search_page(data, query_string="", sponsored=sponsored)
        else:
            body = search_page(
                data, query_string=str(request.url.query), sponsored=sponsored
            )
        dynamic = bool(params)
        response = _html(
            document(
                title="Propiedades autorizadas · Larevia",
                description="Inventario autorizado y disponible de Larevia.",
                body=body,
                origin=configuration.site_public_origin,
                canonical_path="/propiedades",
                indexable=not dynamic,
            ),
            noindex=dynamic,
        )
        _set_session_cookie(response, request)
        return response

    @site.get("/zonas/{zone_slug}", response_class=HTMLResponse)
    async def local_page(request: Request, zone_slug: str) -> HTMLResponse:
        zone = LOCAL_PAGES.get(zone_slug)
        if zone is None:
            return _not_found(configuration)
        result = await product.request(
            "GET",
            "/internal/public-site/catalog",
            params={"zone": zone, "page_size": 12},
        )
        data = _data(result)
        if result.status_code != 200 or not data.get("listings"):
            return _not_found(configuration)
        await _annotate_saved(list(data.get("listings") or []), request, product)
        return _html(
            document(
                title=f"Propiedades en {zone} · Larevia",
                description=f"Inventario autorizado actual de Larevia en {zone}.",
                body=search_page(
                    data,
                    query_string=f"zone={quote(zone)}",
                    heading=f"Propiedades en {zone}",
                ),
                origin=configuration.site_public_origin,
                canonical_path=f"/zonas/{zone_slug}",
            )
        )

    @site.get("/propiedades/{slug}", response_class=HTMLResponse)
    async def property_sheet(request: Request, slug: str) -> HTMLResponse:
        result = await product.request(
            "GET", f"/internal/public-site/listings/{quote(slug, safe='')}"
        )
        if result.status_code == 404:
            return _not_found(configuration)
        if result.status_code == 410:
            return _html(
                document(
                    title="Propiedad no disponible · Larevia",
                    description="Esta publicación ya no está disponible en Larevia.",
                    body=unavailable_page(),
                    origin=configuration.site_public_origin,
                    canonical_path=f"/propiedades/{slug}",
                    indexable=False,
                ),
                status_code=410,
                noindex=True,
            )
        data = _data(result)
        listing = data.get("listing")
        if not isinstance(listing, dict):
            return _not_found(configuration)
        await _annotate_saved([listing], request, product)
        discovery = await product.request(
            "GET", f"/internal/public-site/discovery/{listing['listing_id']}"
        )
        projection = _data(discovery)
        structured = _absolute_schema(
            projection.get("structured_data"), configuration.site_public_origin
        )
        cover = next(
            (item for item in listing.get("media", []) if item.get("is_cover")), None
        )
        primary = cover.get("url") if isinstance(cover, dict) else None
        # Recorded here, on the server, rather than from a beacon: serving the
        # Technical Sheet is Product's own fact, and a script-dependent count
        # would systematically under-report the slowest devices.
        await _record_listing_open(request, product, str(listing["listing_id"]))
        response = _html(
            document(
                title=str(projection.get("title") or f"{listing['title']} · Larevia"),
                description=str(
                    projection.get("description")
                    or f"Consulta la ficha autorizada de {listing['title']}."
                ),
                body=technical_sheet(
                    listing,
                    projection,
                    sponsored_exposure=request.query_params.get("patrocinio"),
                ),
                origin=configuration.site_public_origin,
                canonical_path=f"/propiedades/{slug}",
                structured_data=structured,
                primary_image=primary,
                tier=str(listing.get("presentation_tier") or "Larevia"),
                preload_image=f"{primary}?w=960" if primary else None,
            )
        )
        _set_session_cookie(response, request)
        return response

    @site.get("/propiedades/{slug}/galeria", response_class=HTMLResponse)
    async def property_gallery(request: Request, slug: str) -> HTMLResponse:
        result = await product.request(
            "GET", f"/internal/public-site/listings/{quote(slug, safe='')}"
        )
        if result.status_code == 410:
            return _html(
                document(
                    title="Galería no disponible · Larevia",
                    description="Esta galería ya no está disponible.",
                    body=unavailable_page(),
                    origin=configuration.site_public_origin,
                    canonical_path=f"/propiedades/{slug}/galeria",
                    indexable=False,
                ),
                status_code=410,
                noindex=True,
            )
        listing = _data(result).get("listing")
        if result.status_code != 200 or not isinstance(listing, dict):
            return _not_found(configuration)
        cover = next(
            (item for item in listing.get("media", []) if item.get("is_cover")), None
        )
        primary = cover.get("url") if isinstance(cover, dict) else None
        return _html(
            document(
                title=f"Galería de {listing['title']} · Larevia",
                description=f"Fotografías autorizadas de {listing['title']}.",
                body=gallery(listing),
                origin=configuration.site_public_origin,
                canonical_path=f"/propiedades/{slug}/galeria",
                primary_image=primary,
                tier=str(listing.get("presentation_tier") or "Larevia"),
                preload_image=f"{primary}?w=960" if primary else None,
            )
        )

    @site.get("/media/{media_id}")
    async def media(
        request: Request,
        media_id: uuid.UUID,
        w: int = Query(default=960, ge=320, le=1600),
    ) -> Response:
        result = await product.request(
            "GET", f"/internal/public-site/media/{media_id}"
        )
        if result.status_code != 200:
            return Response(status_code=404, headers={"X-Robots-Tag": "noindex"})
        width = min((480, 960, 1440), key=lambda candidate: abs(candidate - w))
        etag = f'"{result.headers.get("etag", str(media_id)).strip(chr(34))}-{width}"'
        headers = {
            "Cache-Control": "public, no-cache",
            "ETag": etag,
            "X-Content-Type-Options": "nosniff",
        }
        # The rendition is decided by the upstream ETag and the width alone, so a
        # revalidation can be answered before Pillow runs. Without this every
        # conditional request paid a full LANCZOS resize and WEBP encode to
        # produce bytes the browser already had.
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        content, content_type = await asyncio.to_thread(
            _responsive_image, result.content, result.content_type, width
        )
        return Response(content, media_type=content_type, headers=headers)

    @site.get("/guardadas", response_class=HTMLResponse)
    async def saved(request: Request) -> HTMLResponse:
        token = request.cookies.get(SAVED_COOKIE)
        result = await product.request(
            "GET",
            "/internal/public-site/saved",
            token_header=_token_header("X-Collection-Token", token),
        )
        body = saved_page(_data(result))
        return _html(
            document(
                title="Mis propiedades guardadas · Larevia",
                description="Tu colección de propiedades guardadas en Larevia.",
                body=body,
                origin=configuration.site_public_origin,
                canonical_path="/guardadas",
                indexable=False,
            ),
            private=True,
            noindex=True,
        )

    @site.post("/guardadas")
    async def mutate_saved(request: Request) -> Response:
        form = await request.form()
        body: dict[str, Any] = {
            "action": str(form.get("action") or ""),
            "command_key": str(form.get("command_key") or ""),
        }
        if form.get("listing_id"):
            body["listing_id"] = str(form["listing_id"])
        result = await product.request(
            "POST",
            "/internal/public-site/saved",
            body=body,
            token_header=_token_header(
                "X-Collection-Token", request.cookies.get(SAVED_COOKIE)
            ),
        )
        data = _data(result)
        if result.status_code >= 400:
            if "application/json" in request.headers.get("accept", ""):
                return Response(
                    json.dumps({"detail": _detail(result)}),
                    status_code=result.status_code,
                    media_type="application/json",
                )
            return _html(
                document(
                    title="No pudimos actualizar tus guardadas · Larevia",
                    description="No se pudo actualizar la colección.",
                    body=saved_page({"items": []}),
                    origin=configuration.site_public_origin,
                    canonical_path="/guardadas",
                    indexable=False,
                ),
                status_code=result.status_code,
                private=True,
                noindex=True,
            )
        if body["action"] == "Share" and data.get("shared_token"):
            response: Response = RedirectResponse(
                f"/selecciones/{data['shared_token']}", status_code=303
            )
        elif "application/json" in request.headers.get("accept", ""):
            response = Response(
                json.dumps(data, default=str), media_type="application/json"
            )
        else:
            target = str(form.get("return_to") or "/guardadas")
            if not _SAFE_RETURN.fullmatch(target):
                target = "/guardadas"
            response = RedirectResponse(target, status_code=303)
        if body["action"] == "Delete":
            response.delete_cookie(SAVED_COOKIE, path="/")
        else:
            _set_cookie(response, SAVED_COOKIE, data.get("collection_token"))
        return response

    @site.get("/selecciones/{token}", response_class=HTMLResponse)
    async def selection(request: Request, token: str) -> HTMLResponse:
        result = await product.request(
            "GET", f"/internal/public-site/shared/{quote(token, safe='-')}"
        )
        if result.status_code != 200:
            return _html(
                document(
                    title="Selección no disponible · Larevia",
                    description="Esta selección compartida ya no está disponible.",
                    body=unavailable_page(),
                    origin=configuration.site_public_origin,
                    canonical_path=f"/selecciones/{token}",
                    indexable=False,
                ),
                status_code=410,
                noindex=True,
            )
        return _html(
            document(
                title="Selección compartida · Larevia",
                description="Una selección compartida de propiedades de Larevia.",
                body=shared_page(_data(result)),
                origin=configuration.site_public_origin,
                canonical_path=f"/selecciones/{token}",
                indexable=False,
            ),
            noindex=True,
        )

    @site.get("/maia", response_class=HTMLResponse)
    async def maia(request: Request) -> HTMLResponse:
        conversation = await product.request(
            "GET",
            "/internal/public-site/conversation",
            token_header=_token_header(
                "X-Conversation-Token", request.cookies.get(CONVERSATION_COOKIE)
            ),
        )
        context: list[str] = []
        if listing_id := request.query_params.get("listing_id"):
            context.append(listing_id)
        if request.query_params.get("guardadas") == "1":
            saved_result = await product.request(
                "GET",
                "/internal/public-site/saved",
                token_header=_token_header(
                    "X-Collection-Token", request.cookies.get(SAVED_COOKIE)
                ),
            )
            context.extend(
                str(item["listing_id"])
                for item in _data(saved_result).get("items", [])
                if item.get("available")
            )
        data = _data(conversation)
        return _html(
            document(
                title="Conversa con Maia · Larevia",
                description="Conversa de forma anónima con Maia sobre propiedades autorizadas.",
                body=conversation_page(
                    list(data.get("messages") or []),
                    conversation_id=(
                        str(data["conversation_id"])
                        if data.get("conversation_id")
                        else None
                    ),
                    listing_ids=context,
                    sponsored_exposure=request.query_params.get("patrocinio"),
                ),
                origin=configuration.site_public_origin,
                canonical_path="/maia",
                indexable=False,
            ),
            private=True,
            noindex=True,
        )

    @site.post("/maia", response_class=HTMLResponse)
    async def talk_to_maia(request: Request) -> HTMLResponse:
        form = await request.form()
        body = {
            "message": str(form.get("message") or ""),
            "command_key": str(form.get("command_key") or ""),
            "listing_ids": [str(value) for value in form.getlist("listing_ids")],
        }
        sponsored_exposure = str(form.get("sponsored_exposure") or "") or None
        result = await product.request(
            "POST",
            "/internal/public-site/conversation",
            body=body,
            token_header=_token_header(
                "X-Conversation-Token", request.cookies.get(CONVERSATION_COOKIE)
            ),
            headers=_measurement_headers(
                request, sponsored_exposure=sponsored_exposure
            ),
        )
        data = _data(result)
        messages = list(data.get("messages") or [])
        if data.get("reply") and not messages:
            messages.append({"role": "Maia", "body": data["reply"]})
        content = document(
            title="Conversa con Maia · Larevia",
            description="Conversa de forma anónima con Maia.",
            body=conversation_page(
                messages,
                conversation_id=(
                    str(data["conversation_id"])
                    if data.get("conversation_id")
                    else None
                ),
                listing_ids=list(body["listing_ids"]),
                sponsored_exposure=sponsored_exposure,
                error=_detail(result) if result.status_code >= 400 else "",
            ),
            origin=configuration.site_public_origin,
            canonical_path="/maia",
            indexable=False,
        )
        response = _html(
            content,
            status_code=result.status_code if result.status_code >= 400 else 200,
            private=True,
            noindex=True,
        )
        _set_cookie(response, CONVERSATION_COOKIE, data.get("conversation_token"))
        return response

    @site.post("/handoffs")
    async def create_handoff(request: Request) -> Response:
        form = await request.form()
        body = {
            key: str(form[key])
            for key in (
                "purpose",
                "command_key",
                "website_conversation_id",
                "saved_collection_id",
                "listing_id",
            )
            if form.get(key)
        }
        sponsored_exposure = str(form.get("sponsored_exposure") or "") or None
        result = await product.request(
            "POST",
            "/internal/public-site/handoffs",
            body=body,
            headers=_measurement_headers(
                request, sponsored_exposure=sponsored_exposure
            ),
        )
        if result.status_code >= 400:
            return _html(
                document(
                    title="No pudimos continuar · Larevia",
                    description="La referencia de continuidad no pudo crearse.",
                    body=f'<section class="section-shell unavailable"><h1>No pudimos continuar</h1><p>{escape(_detail(result))}</p></section>',
                    origin=configuration.site_public_origin,
                    canonical_path="/maia",
                    indexable=False,
                ),
                status_code=result.status_code,
                private=True,
                noindex=True,
            )
        data = _data(result)
        await _record_handoff_event(product, body)
        reference = str(data["token"])
        if configuration.official_whatsapp_number:
            number = "".join(
                character
                for character in configuration.official_whatsapp_number
                if character.isdigit()
            )
            text = f"Quiero continuar con Maia. Referencia {reference}"
            return RedirectResponse(
                f"https://wa.me/{number}?{urlencode({'text': text})}", status_code=303
            )
        return _html(
            document(
                title="Sigue por WhatsApp · Larevia",
                description="Referencia opaca para continuar por el WhatsApp oficial.",
                body=handoff_page(reference, expires_at=str(data.get("expires_at"))),
                origin=configuration.site_public_origin,
                canonical_path="/maia",
                indexable=False,
            ),
            private=True,
            noindex=True,
        )

    @site.post("/eventos", status_code=202)
    async def events(request: Request) -> Response:
        try:
            body = await request.json()
        except ValueError:
            return Response(status_code=400)
        exposure = body.pop("exposure_id", None) if isinstance(body, dict) else None
        result = await product.request(
            "POST",
            "/internal/public-site/events",
            body=body,
            headers=_measurement_headers(request, sponsored_exposure=exposure),
        )
        return Response(status_code=202 if result.status_code < 400 else 422)

    @site.post("/medicion/galeria", status_code=202)
    async def gallery_depth(request: Request) -> Response:
        """Forward one gallery-depth observation. Product applies the threshold.

        Two numbers only: how many photographs were reached and what share of
        the gallery that is. No per-photograph timing, no scroll path, nothing
        that would amount to a behavioural profile.
        """
        try:
            body = await request.json()
        except ValueError:
            return Response(status_code=400)
        exposure = body.pop("exposure_id", None) if isinstance(body, dict) else None
        result = await product.request(
            "POST",
            "/internal/public-site/measurement/gallery-depth",
            body=body,
            headers=_measurement_headers(request, sponsored_exposure=exposure),
        )
        return Response(status_code=202 if result.status_code < 400 else 422)

    @site.post("/patrocinadas/visible", status_code=202)
    async def sponsored_visible(request: Request) -> Response:
        """Forward one browser visibility observation. Product decides.

        The page reports the measured fraction and duration; it never reports a
        verdict. Product applies the versioned threshold, so a modified client
        cannot manufacture Visible Impressions for a campaign.
        """
        try:
            body = await request.json()
        except ValueError:
            return Response(status_code=400)
        result = await product.request(
            "POST",
            "/internal/public-site/sponsored/visible",
            body=body,
            headers=_measurement_headers(request),
        )
        return Response(status_code=202 if result.status_code < 400 else 422)

    @site.get("/reportes/{token}", response_class=HTMLResponse)
    async def buyer_report(request: Request, token: str) -> HTMLResponse:
        """One buyer's campaign report, reached by an expiring link only.

        No account, no navigation into the rest of the site, and no cookie: the
        link is the whole authorization and the page is the whole surface. A
        withdrawn or expired link renders the same page as an unknown one.
        """
        result = await product.request(
            "GET", f"/internal/public-site/sponsorship-report/{quote(token, safe='')}"
        )
        if result.status_code != 200:
            return _html(
                document(
                    title="Reporte no disponible · Larevia",
                    description="Este enlace de reporte ya no está disponible.",
                    body=(
                        '<section class="report-shell"><h1>Reporte no disponible</h1>'
                        "<p>Este enlace expiró o fue revocado. Pide uno nuevo a "
                        "Larevia.</p></section>"
                    ),
                    origin=configuration.site_public_origin,
                    canonical_path="/",
                    indexable=False,
                ),
                status_code=410,
                private=True,
                noindex=True,
            )
        data = _data(result)
        return _html(
            document(
                title=f"Reporte de campaña {data.get('label')} · Larevia",
                description="Reporte agregado de una campaña patrocinada.",
                body=report_page(data, token=token),
                origin=configuration.site_public_origin,
                canonical_path="/",
                indexable=False,
            ),
            private=True,
            noindex=True,
        )

    @site.get("/reportes/{token}/patrocinio.pdf")
    async def buyer_report_pdf(request: Request, token: str) -> Response:
        result = await product.request(
            "GET",
            f"/internal/public-site/sponsorship-report/{quote(token, safe='')}/pdf",
        )
        if result.status_code != 200:
            return PlainTextResponse(
                "Este enlace de reporte ya no está disponible.",
                status_code=410,
                headers={"Cache-Control": "private, no-store"},
            )
        return Response(
            result.content,
            media_type="application/pdf",
            headers={
                "Cache-Control": "private, no-store",
                "Content-Disposition": (
                    'attachment; filename="reporte-patrocinada.pdf"'
                ),
                "X-Content-Type-Options": "nosniff",
            },
        )

    @site.get("/robots.txt", response_class=PlainTextResponse)
    async def robots(request: Request) -> PlainTextResponse:
        sitemap_url = absolute(configuration.site_public_origin, "/sitemap.xml")
        content = f"""# Search and user-requested retrieval are allowed; training is not.
User-agent: OAI-SearchBot
Allow: /

User-agent: ChatGPT-User
Allow: /

User-agent: GPTBot
Disallow: /

User-agent: Google-Extended
Disallow: /

User-agent: *
Allow: /
Disallow: /guardadas
Disallow: /maia
Disallow: /selecciones/

Sitemap: {sitemap_url}
"""
        return PlainTextResponse(content, headers=_response_headers())

    @site.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(
            status_code=204,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @site.get("/sitemap.xml")
    async def sitemap(request: Request) -> Response:
        listings: list[dict[str, Any]] = []
        page = 1
        while True:
            result = await product.request(
                "GET",
                "/internal/public-site/catalog",
                params={"page_size": 24, "page": page},
            )
            if result.status_code != 200:
                break
            data = _data(result)
            listings.extend(data.get("listings") or [])
            if not data.get("has_more"):
                break
            page += 1
        paths = ["/", "/propiedades"]
        zones = {
            zone_slug
            for zone_slug, zone in LOCAL_PAGES.items()
            if any(zone.casefold() in str(item.get("public_location") or "").casefold() for item in listings)
        }
        paths.extend(f"/zonas/{zone}" for zone in sorted(zones))
        urls = [f"<url><loc>{escape(absolute(configuration.site_public_origin, path))}</loc></url>" for path in paths]
        for listing in listings:
            images = "".join(
                f"<image:image><image:loc>{escape(absolute(configuration.site_public_origin, item['url']))}</image:loc></image:image>"
                for item in listing.get("media", [])
            )
            lastmod = listing.get("updated_at")
            stamp = f"<lastmod>{escape(str(lastmod)[:10])}</lastmod>" if lastmod else ""
            for path in (
                f"/propiedades/{listing['slug']}",
                f"/propiedades/{listing['slug']}/galeria",
            ):
                urls.append(
                    f"<url><loc>{escape(absolute(configuration.site_public_origin, path))}</loc>{stamp}{images}</url>"
                )
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">'
            f"{''.join(urls)}</urlset>"
        )
        return Response(
            xml,
            media_type="application/xml",
            headers={"Cache-Control": "public, max-age=300", "X-Content-Type-Options": "nosniff"},
        )

    return site


def _not_found(settings: Settings) -> HTMLResponse:
    return _html(
        document(
            title="Página no encontrada · Larevia",
            description="No encontramos esta página.",
            body='<section class="section-shell unavailable"><p class="eyebrow">404</p><h1>No encontramos esta página</h1><a class="button button-primary" href="/propiedades">Explorar propiedades</a></section>',
            origin=settings.site_public_origin,
            canonical_path="/",
            indexable=False,
        ),
        status_code=404,
        noindex=True,
    )


def _responsive_image(content: bytes, content_type: str, width: int) -> tuple[bytes, str]:
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.load()
            if image.width <= width:
                return content, content_type
            target_height = max(1, round(image.height * width / image.width))
            image.thumbnail((width, target_height), Image.Resampling.LANCZOS)
            output_image: Image.Image = image
            if output_image.mode not in {"RGB", "RGBA"}:
                output_image = output_image.convert("RGB")
            destination = io.BytesIO()
            output_image.save(destination, format="WEBP", quality=82, method=4)
            return destination.getvalue(), "image/webp"
    except (UnidentifiedImageError, OSError):
        return content, content_type


def _absolute_schema(value: Any, origin: str) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    def visit(item: Any, key: str = "") -> Any:
        if isinstance(item, dict):
            return {name: visit(child, name) for name, child in item.items()}
        if isinstance(item, list):
            return [visit(child, key) for child in item]
        if key in {"url", "image"} and isinstance(item, str) and item.startswith("/"):
            return absolute(origin, item)
        return item

    result = visit(value)
    return result if isinstance(result, dict) else None


async def _record_handoff_event(
    product: ProductSiteGateway, handoff: dict[str, str]
) -> None:
    appointment = handoff.get("purpose") == "Appointment"
    await product.request(
        "POST",
        "/internal/public-site/events",
        body={
            "event_key": f"event-{uuid.uuid4()}",
            "name": "AppointmentRequested" if appointment else "HandoffCreated",
            "surface": "TechnicalSheet" if handoff.get("listing_id") else "Maia",
            "listing_id": handoff.get("listing_id"),
            "properties": {"source": "website"},
            "occurred_at": datetime.now(tz=UTC).isoformat(),
        },
    )


async def _record_listing_open(
    request: Request, product: ProductSiteGateway, listing_id: str
) -> None:
    """Record one served Technical Sheet, keyed per session, listing and day.

    A page reload inside the same session and day is the same open, which is
    what keeps a refreshed tab from inflating a buyer's funnel. Failures are
    ignored on purpose: measurement must never be able to break the page it is
    measuring.
    """
    await product.request(
        "POST",
        "/internal/public-site/measurement/listing-open",
        body={
            "event_key": f"open:{listing_id}:{uuid.uuid4().hex}",
            "listing_id": listing_id,
            "surface": "TechnicalSheet",
            "occurred_at": datetime.now(tz=UTC).isoformat(),
        },
        headers=_measurement_headers(request),
    )


async def _sponsored(
    request: Request,
    product: ProductSiteGateway,
    *,
    surface: str,
    listings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Ask Product for this surface's paid section.

    A separate call from the catalog on purpose. The organic list the site
    already holds is passed in only so Product can skip a card that is already
    visible on the page; nothing about the paid answer can reorder it, and a
    failed or empty answer simply means no sponsored section renders.
    """
    result = await product.request(
        "GET",
        "/internal/public-site/sponsored",
        params={
            "surface": surface,
            "visible_results": len(listings),
            "organic": ",".join(
                str(item.get("listing_id")) for item in listings if item.get("listing_id")
            ),
        },
        headers=_measurement_headers(request),
    )
    if result.status_code != 200:
        return {}
    return _data(result)


async def _annotate_saved(
    listings: list[dict[str, Any]],
    request: Request,
    product: ProductSiteGateway,
) -> None:
    """Render server-confirmed save state without exposing the HttpOnly token."""
    token = request.cookies.get(SAVED_COOKIE)
    if not token or not listings:
        return
    result = await product.request(
        "GET",
        "/internal/public-site/saved",
        token_header=("X-Collection-Token", token),
    )
    saved_ids = {
        str(item.get("listing_id"))
        for item in _data(result).get("items", [])
    }
    for listing in listings:
        listing["_saved"] = str(listing.get("listing_id")) in saved_ids


app = create_site_app()
