"""SSR, progressive enhancement, accessibility and discovery for Stage 5."""

from __future__ import annotations

import copy
import io
import re
import uuid
from typing import Any

import httpx
from httpx import ASGITransport
from PIL import Image

from realestate.config import Settings
from realestate.site.app import CONVERSATION_COOKIE, SAVED_COOKIE, create_site_app
from realestate.site.gateway import GatewayResponse

LISTING_ID = str(uuid.UUID("11111111-1111-4111-8111-111111111111"))
MEDIA_ID = str(uuid.UUID("22222222-2222-4222-8222-222222222222"))
SECOND_MEDIA_ID = str(uuid.UUID("22222222-2222-4222-8222-333333333333"))
LISTING = {
    "listing_id": LISTING_ID,
    "slug": "casa-encino-larevia",
    "property_id": str(uuid.UUID("33333333-3333-4333-8333-333333333333")),
    "title": "Casa Encino",
    "physical_name": "Casa Encino",
    "public_location": "Zapopan, Jalisco",
    "property_type": "House",
    "physical_facts": {"bedrooms": 3, "construction_m2": 220},
    "listing_facts": {},
    "source_kind": "Organization",
    "source_name": "Larevia",
    "attribution": "Inventario propio",
    "presentation_tier": "SuperPremium",
    "gallery_url": "/propiedades/casa-encino-larevia/galeria",
    "technical_sheet_url": "/propiedades/casa-encino-larevia",
    "offers": [
        {
            "offer_id": str(uuid.uuid4()),
            "operation": "Sale",
            "price_amount": "9800000.00",
            "price_currency": "MXN",
            "price_visibility": "Visible",
            "consultation_copy": None,
            "terms": {},
        }
    ],
    "media": [
        {
            "media_id": MEDIA_ID,
            "url": f"/media/{MEDIA_ID}",
            "is_cover": True,
            "sort_order": 0,
            "space_group": "Fachada",
        },
        {
            "media_id": SECOND_MEDIA_ID,
            "url": f"/media/{SECOND_MEDIA_ID}",
            "is_cover": False,
            "sort_order": 1,
            "space_group": "Sala",
        },
    ],
    "updated_at": "2026-08-28T20:00:00Z",
}


def response(
    status_code: int,
    data: Any | None = None,
    *,
    content: bytes = b"",
    content_type: str = "application/json",
    headers: dict[str, str] | None = None,
) -> GatewayResponse:
    return GatewayResponse(
        status_code=status_code,
        data=data,
        content=content,
        content_type=content_type,
        headers=headers or {},
    )


class FakeProductGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.collection_token = "sc-server-confirmed"
        self.saved_items: list[dict[str, Any]] = []
        self.listing = copy.deepcopy(LISTING)
        image = Image.new("RGB", (1800, 1200), color=(191, 118, 74))
        destination = io.BytesIO()
        image.save(destination, format="JPEG")
        self.image = destination.getvalue()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        token_header: tuple[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> GatewayResponse:
        self.calls.append(
            {
                "method": method,
                "path": path,
                "params": params,
                "body": body,
                "token_header": token_header,
                "headers": headers,
            }
        )
        if path == "/internal/public-site/catalog":
            query = dict(params or {})
            return response(
                200,
                {
                    "query": query,
                    "listings": [self.listing],
                    "total": 1,
                    "has_more": False,
                },
            )
        if path.endswith("/listings/retirada"):
            return response(410, {"listing": None})
        if "/internal/public-site/listings/" in path:
            return response(200, {"listing": self.listing})
        if "/internal/public-site/discovery/" in path:
            return response(
                200,
                {
                    "title": "Casa Encino · Larevia",
                    "description": "Ficha autorizada de Casa Encino.",
                    "structured_data": {
                        "@context": "https://schema.org",
                        "@type": "RealEstateListing",
                        "name": "Casa Encino",
                        "url": "/propiedades/casa-encino-larevia",
                        "image": [f"/media/{MEDIA_ID}"],
                    },
                },
            )
        if "/internal/public-site/media/" in path:
            return response(
                200,
                content=self.image,
                content_type="image/jpeg",
                headers={"etag": '"synthetic"'},
            )
        if path == "/internal/public-site/saved" and method == "GET":
            return response(
                200,
                {
                    "collection_id": "44444444-4444-4444-8444-444444444444",
                    "protected": False,
                    "items": self.saved_items,
                },
            )
        if path == "/internal/public-site/saved":
            assert body is not None
            if body["action"] == "Add":
                self.saved_items = [
                    {
                        "listing_id": LISTING_ID,
                        "slug": self.listing["slug"],
                        "title": self.listing["title"],
                        "public_location": self.listing["public_location"],
                        "available": True,
                        "listing": self.listing,
                    }
                ]
            if body["action"] == "Delete":
                self.saved_items = []
            data = {
                "collection_id": "44444444-4444-4444-8444-444444444444",
                "collection_token": (
                    self.collection_token if body["action"] == "Add" else None
                ),
                "items": self.saved_items,
                "shared_token": "ss-fixed" if body["action"] == "Share" else None,
            }
            return response(200, data)
        if path == "/internal/public-site/shared/ss-fixed":
            return response(200, {"items": self.saved_items})
        if path == "/internal/public-site/conversation" and method == "GET":
            return response(200, {"conversation_id": None, "messages": []})
        if path == "/internal/public-site/conversation":
            return response(
                200,
                {
                    "conversation_id": "55555555-5555-4555-8555-555555555555",
                    "conversation_token": "wc-server-confirmed",
                    "reply": "Puedo ayudarte a comparar opciones.",
                    "messages": [
                        {"role": "Customer", "body": body["message"]},
                        {
                            "role": "Maia",
                            "body": "Puedo ayudarte a comparar opciones.",
                        },
                    ],
                },
            )
        if path == "/internal/public-site/handoffs":
            return response(
                200,
                {
                    "token": "LAR-1234567890ABCDEF1234567890ABCDEF1234567890ABCDEF",
                    "expires_at": "2026-08-28T20:30:00Z",
                },
            )
        if path == "/internal/public-site/events":
            return response(202, {})
        return response(404, {"detail": "No encontrado"})

    async def aclose(self) -> None:
        return None


class ForcedProductGateway(FakeProductGateway):
    def __init__(self) -> None:
        super().__init__()
        self.forced: dict[tuple[str, str], GatewayResponse] = {}

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        token_header: tuple[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> GatewayResponse:
        if forced := self.forced.get((method, path)):
            self.calls.append(
                {
                    "method": method,
                    "path": path,
                    "params": params,
                    "body": body,
                    "token_header": token_header,
                }
            )
            return forced
        return await super().request(
            method,
            path,
            params=params,
            body=body,
            token_header=token_header,
            headers=headers,
        )


class PaginatedProductGateway(FakeProductGateway):
    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        token_header: tuple[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> GatewayResponse:
        if path == "/internal/public-site/catalog" and params:
            if params.get("page") == 1:
                return response(
                    200,
                    {"listings": [self.listing], "total": 1, "has_more": True},
                )
            if params.get("page") == 2:
                return response(503, {"detail": "Catálogo no disponible"})
        return await super().request(
            method,
            path,
            params=params,
            body=body,
            token_header=token_header,
            headers=headers,
        )


def settings(*, whatsapp: str = "") -> Settings:
    return Settings(
        _env_file=None,
        PLUGIN_API_TOKEN="test-token",
        SITE_PUBLIC_ORIGIN="https://larevia.test",
        OFFICIAL_WHATSAPP_NUMBER=whatsapp,
    )


async def client_for(
    gateway: FakeProductGateway, *, whatsapp: str = ""
) -> httpx.AsyncClient:
    app = create_site_app(settings(whatsapp=whatsapp), gateway)
    return httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://larevia.test",
        follow_redirects=False,
    )


async def test_server_rendered_search_detail_gallery_and_local_discovery() -> None:
    gateway = FakeProductGateway()
    async with await client_for(gateway) as client:
        home = await client.get("/")
        search = await client.get(
            "/propiedades?operation=Sale&zone=Zapopan&minimum_price=6000000"
        )
        local = await client.get("/zonas/zapopan")
        sheet = await client.get("/propiedades/casa-encino-larevia")
        gallery = await client.get("/propiedades/casa-encino-larevia/galeria")
        withdrawn = await client.get("/propiedades/retirada")
        missing_zone = await client.get("/zonas/otra")

    assert home.status_code == 200
    assert "Acompañamiento inmobiliario" in home.text
    assert "hero-photo" in home.text
    assert f'src="/media/{MEDIA_ID}?w=960"' in home.text
    assert '<html lang="es-MX"' in home.text
    assert "<main id=\"contenido\">" in home.text
    assert "autoplay" not in home.text.casefold()
    assert search.status_code == 200
    assert 'content="noindex,follow"' in search.text
    assert '<link rel="canonical" href="https://larevia.test/propiedades">' in search.text
    assert 'value="6000000"' in search.text
    assert local.status_code == 200 and "Propiedades en Zapopan" in local.text
    assert sheet.status_code == 200
    assert "Datos autorizados" in sheet.text
    assert "RealEstateListing" in sheet.text
    assert "Super Premium" in sheet.text
    assert sheet.text.count('rel="preload"') == 1
    assert 'srcset="/media/' in sheet.text
    assert gallery.status_code == 200
    assert 'data-gallery-prev' in gallery.text and 'aria-live="polite"' in gallery.text
    assert withdrawn.status_code == 410
    assert "Esta propiedad ya no está disponible" in withdrawn.text
    assert "Casa Encino" not in withdrawn.text
    assert missing_zone.status_code == 404


async def test_saved_collection_uses_server_confirmation_secure_cookie_and_deletion() -> None:
    gateway = FakeProductGateway()
    async with await client_for(gateway) as client:
        added = await client.post(
            "/guardadas",
            data={
                "action": "Add",
                "command_key": "save-page-command",
                "listing_id": LISTING_ID,
                "return_to": "/propiedades/casa-encino-larevia",
            },
        )
        saved = await client.get("/guardadas")
        detail = await client.get("/propiedades/casa-encino-larevia")
        deleted = await client.post(
            "/guardadas",
            data={"action": "Delete", "command_key": "delete-page-command"},
        )

    assert added.status_code == 303
    cookie = added.headers["set-cookie"]
    assert f"{SAVED_COOKIE}=sc-server-confirmed" in cookie
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    assert saved.status_code == 200
    assert saved.headers["cache-control"] == "private, no-store"
    assert "Mis propiedades guardadas" in saved.text
    assert 'aria-pressed="true"' in detail.text
    assert "Guardada" in detail.text
    saved_get = next(
        call
        for call in gateway.calls
        if call["path"] == "/internal/public-site/saved"
        and call["method"] == "GET"
    )
    assert saved_get["token_header"] == (
        "X-Collection-Token",
        gateway.collection_token,
    )
    assert deleted.status_code == 303
    assert f"{SAVED_COOKIE}=\"\"" in deleted.headers["set-cookie"]
    assert "Max-Age=0" in deleted.headers["set-cookie"]


async def test_anonymous_maia_and_appointment_request_only_create_channel_handoff() -> None:
    gateway = FakeProductGateway()
    async with await client_for(gateway) as client:
        initial = await client.get(f"/maia?listing_id={LISTING_ID}")
        turn = await client.post(
            "/maia",
            data={
                "message": "Busco una casa en Zapopan",
                "command_key": "website-turn-command",
                "listing_ids": LISTING_ID,
            },
        )
        handoff = await client.post(
            "/handoffs",
            data={
                "purpose": "Appointment",
                "command_key": "appointment-handoff-command",
                "listing_id": LISTING_ID,
            },
        )

    assert initial.status_code == 200
    assert "La conversación empieza anónima" in initial.text
    assert turn.status_code == 200
    assert "Puedo ayudarte a comparar opciones" in turn.text
    assert f"{CONVERSATION_COOKIE}=wc-server-confirmed" in turn.headers["set-cookie"]
    assert handoff.status_code == 200
    assert "LAR-1234567890ABCDEF" in handoff.text
    handoff_call = next(
        call for call in gateway.calls if call["path"] == "/internal/public-site/handoffs"
    )
    assert handoff_call["body"]["purpose"] == "Appointment"
    assert all("appointment" not in call["path"] for call in gateway.calls)


async def test_official_whatsapp_redirect_preserves_only_opaque_reference() -> None:
    gateway = FakeProductGateway()
    async with await client_for(gateway, whatsapp="+52 33 1234 5678") as client:
        handoff = await client.post(
            "/handoffs",
            data={
                "purpose": "ContinueWhatsApp",
                "command_key": "whatsapp-handoff-command",
                "listing_id": LISTING_ID,
            },
        )

    assert handoff.status_code == 303
    assert handoff.headers["location"].startswith("https://wa.me/523312345678?")
    assert "LAR-1234567890ABCDEF" in handoff.headers["location"]
    assert LISTING_ID not in handoff.headers["location"]


async def test_media_robots_sitemap_security_and_frontend_budgets() -> None:
    gateway = FakeProductGateway()
    async with await client_for(gateway) as client:
        media = await client.get(f"/media/{MEDIA_ID}?w=480")
        robots = await client.get("/robots.txt")
        sitemap = await client.get("/sitemap.xml")
        css = await client.get("/assets/site.css")
        javascript = await client.get("/assets/site.js")
        home = await client.get("/")

    assert media.status_code == 200
    assert media.headers["content-type"].startswith("image/webp")
    assert len(media.content) < len(gateway.image)
    assert media.headers["cache-control"] == "public, no-cache"
    assert "User-agent: OAI-SearchBot\nAllow: /" in robots.text
    assert "User-agent: ChatGPT-User\nAllow: /" in robots.text
    assert "User-agent: GPTBot\nDisallow: /" in robots.text
    assert "User-agent: Google-Extended\nDisallow: /" in robots.text
    assert "Disallow: /guardadas" in robots.text
    assert "https://larevia.test/sitemap.xml" in robots.text
    assert sitemap.status_code == 200
    assert "casa-encino-larevia" in sitemap.text
    assert f"https://larevia.test/media/{MEDIA_ID}" in sitemap.text
    assert "default-src 'self'" in home.headers["content-security-policy"]
    assert "browsing-topics=()" in home.headers["permissions-policy"]
    assert len(css.content) < 40_000
    assert len(javascript.content) < 16_000
    assert len(home.content) < 90_000
    assert b"letter-spacing: -" not in css.content
    assert b"@media (prefers-reduced-motion: reduce)" in css.content
    assert b":focus-visible" in css.content
    assert b"localStorage" in javascript.content
    assert b"BroadcastChannel" in javascript.content
    assert b"MaiaStarted" not in javascript.content
    assert b"mousemove" not in javascript.content
    assert b"keydown" in javascript.content  # gallery keyboard, not key capture
    assert b"https://" not in javascript.content


async def test_public_pages_render_honest_failure_and_recovery_states() -> None:
    gateway = ForcedProductGateway()
    catalog_path = "/internal/public-site/catalog"
    gateway.forced[("GET", catalog_path)] = response(
        503, {"detail": "Catálogo temporalmente no disponible"}
    )
    async with await client_for(gateway) as client:
        home = await client.get("/")
        search = await client.get("/propiedades?zone=Zapopan")
        local = await client.get("/zonas/zapopan")
    assert home.status_code == 200 and "Propiedades para explorar" in home.text
    assert search.status_code == 200 and "No encontramos propiedades" in search.text
    assert local.status_code == 404

    gateway.forced.clear()
    gateway.forced[("GET", "/internal/public-site/listings/no-existe")] = response(
        404, {"detail": "No encontrada"}
    )
    gateway.forced[("GET", "/internal/public-site/listings/sin-datos")] = response(
        200, {"listing": "invalid"}
    )
    gateway.forced[("GET", f"/internal/public-site/media/{MEDIA_ID}")] = response(
        404, {"detail": "Medio retirado"}
    )
    gateway.forced[("GET", "/internal/public-site/shared/expirada")] = response(
        410, {"detail": "Selección expirada"}
    )
    async with await client_for(gateway) as client:
        missing = await client.get("/propiedades/no-existe")
        malformed = await client.get("/propiedades/sin-datos")
        missing_gallery = await client.get("/propiedades/no-existe/galeria")
        withdrawn_gallery = await client.get("/propiedades/retirada/galeria")
        missing_media = await client.get(f"/media/{MEDIA_ID}")
        expired_selection = await client.get("/selecciones/expirada")
    assert missing.status_code == malformed.status_code == missing_gallery.status_code == 404
    assert withdrawn_gallery.status_code == 410
    assert missing_media.status_code == 404
    assert expired_selection.status_code == 410

    gateway.forced.clear()
    gateway.forced[("POST", "/internal/public-site/saved")] = response(
        409, {"detail": "La propiedad ya no está disponible"}
    )
    async with await client_for(gateway) as client:
        json_error = await client.post(
            "/guardadas",
            headers={"Accept": "application/json"},
            data={"action": "Add", "command_key": "saved-error-json"},
        )
        html_error = await client.post(
            "/guardadas",
            data={"action": "Add", "command_key": "saved-error-html"},
        )
    assert json_error.status_code == 409
    assert json_error.json()["detail"] == "La propiedad ya no está disponible"
    assert html_error.status_code == 409 and "No pudimos actualizar" in html_error.text

    gateway.forced.clear()
    async with await client_for(gateway) as client:
        unsafe_redirect = await client.post(
            "/guardadas",
            data={
                "action": "Empty",
                "command_key": "saved-safe-redirect",
                "return_to": "//attacker.example",
            },
        )
        json_success = await client.post(
            "/guardadas",
            headers={"Accept": "application/json"},
            data={"action": "Empty", "command_key": "saved-json-success"},
        )
        shared = await client.post(
            "/guardadas",
            data={"action": "Share", "command_key": "saved-share-success"},
        )
    assert unsafe_redirect.headers["location"] == "/guardadas"
    assert json_success.status_code == 200 and json_success.json()["items"] == []
    assert shared.status_code == 303 and shared.headers["location"] == "/selecciones/ss-fixed"


async def test_maia_events_and_handoff_expose_bounded_error_states() -> None:
    gateway = ForcedProductGateway()
    gateway.saved_items = [
        {
            "listing_id": LISTING_ID,
            "slug": gateway.listing["slug"],
            "title": gateway.listing["title"],
            "public_location": gateway.listing["public_location"],
            "available": True,
            "listing": gateway.listing,
        },
        {
            "listing_id": "unavailable",
            "available": False,
            "listing": None,
        },
    ]
    gateway.forced[("POST", "/internal/public-site/conversation")] = response(
        200,
        {
            "conversation_id": "55555555-5555-4555-8555-555555555555",
            "conversation_token": "wc-reply-only",
            "reply": "Respuesta sin historial",
            "messages": [],
        },
    )
    async with await client_for(gateway) as client:
        saved_context = await client.get("/maia?guardadas=1")
        reply_only = await client.post(
            "/maia",
            data={"message": "Hola", "command_key": "maia-reply-only"},
        )
    assert saved_context.status_code == 200 and LISTING_ID in saved_context.text
    assert "unavailable" not in saved_context.text
    assert "Respuesta sin historial" in reply_only.text

    gateway.forced[("POST", "/internal/public-site/conversation")] = response(
        409, {"detail": "La conversación terminó"}
    )
    gateway.forced[("POST", "/internal/public-site/handoffs")] = response(
        409, {"detail": "La continuidad necesita contexto"}
    )
    gateway.forced[("POST", "/internal/public-site/events")] = response(
        422, {"detail": "Evento inválido"}
    )
    async with await client_for(gateway) as client:
        conversation_error = await client.post(
            "/maia",
            data={"message": "Hola", "command_key": "maia-error"},
        )
        handoff_error = await client.post(
            "/handoffs",
            data={"purpose": "ContinueWhatsApp", "command_key": "handoff-error"},
        )
        invalid_json = await client.post(
            "/eventos", content=b"not-json", headers={"Content-Type": "application/json"}
        )
        rejected_event = await client.post("/eventos", json={"name": "Unknown"})
    assert conversation_error.status_code == 409
    assert "La conversación terminó" in conversation_error.text
    assert handoff_error.status_code == 409
    assert "La continuidad necesita contexto" in handoff_error.text
    assert invalid_json.status_code == 400
    assert rejected_event.status_code == 422


async def test_favicon_and_sitemap_pagination_are_stable() -> None:
    gateway = PaginatedProductGateway()
    async with await client_for(gateway) as client:
        favicon = await client.get("/favicon.ico")
        sitemap = await client.get("/sitemap.xml")

    assert favicon.status_code == 204
    assert favicon.headers["cache-control"] == "public, max-age=86400"
    assert sitemap.status_code == 200
    assert "casa-encino-larevia" in sitemap.text


async def test_primary_public_surfaces_pass_semantic_accessibility_contracts() -> None:
    gateway = FakeProductGateway()
    async with await client_for(gateway) as client:
        pages = [
            await client.get("/"),
            await client.get("/propiedades"),
            await client.get("/propiedades/casa-encino-larevia"),
            await client.get("/propiedades/casa-encino-larevia/galeria"),
            await client.get("/guardadas"),
            await client.get("/maia"),
        ]

    for page in pages:
        assert page.status_code == 200
        assert '<html lang="es-MX"' in page.text
        assert page.text.count('<main id="contenido">') == 1
        assert page.text.count("<h1") == 1
        assert 'href="#contenido"' in page.text
        for image in re.findall(r"<img\b[^>]*>", page.text):
            assert re.search(r'\balt="[^"]*"', image)
        for textarea_id in re.findall(r'<textarea[^>]+id="([^"]+)"', page.text):
            assert f'for="{textarea_id}"' in page.text
