"""The public site's paid sections, session cookie, and buyer report page.

The site process has no database and no provider credentials; it renders what
Product hands it. So these tests drive the real site app against a fake Product
gateway and assert on the HTML and the headers — the part a visitor, a screen
reader and a search engine actually see.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import pytest
from httpx import ASGITransport

from realestate.config import Settings
from realestate.site.app import SESSION_COOKIE, create_site_app
from realestate.site.gateway import GatewayResponse
from realestate.site.templates import SPONSORED_ARIA_LABEL, SPONSORED_LABEL

LISTING_ID = "11111111-1111-1111-1111-111111111111"
SPONSORED_LISTING_ID = "22222222-2222-2222-2222-222222222222"
CAMPAIGN_ID = "33333333-3333-3333-3333-333333333333"
EXPOSURE_ID = "44444444-4444-4444-4444-444444444444"


def listing(listing_id: str, slug: str, title: str) -> dict[str, Any]:
    return {
        "listing_id": listing_id,
        "slug": slug,
        "title": title,
        "public_location": "Zapopan, Jalisco",
        "property_type": "House",
        "presentation_tier": "Premium",
        "physical_facts": {"bedrooms": 3},
        "listing_facts": {},
        "source_kind": "Organization",
        "source_name": "Larevia",
        "attribution": "Fuente: Larevia",
        "gallery_url": f"/propiedades/{slug}/galeria",
        "technical_sheet_url": f"/propiedades/{slug}",
        "offers": [
            {
                "offer_id": "44444444-4444-4444-4444-444444444444",
                "operation": "Sale",
                "price_amount": "5200000",
                "price_currency": "MXN",
                "price_visibility": "Visible",
                "consultation_copy": None,
                "terms": {},
            }
        ],
        "media": [],
        "updated_at": "2026-08-28T20:00:00Z",
    }


class SponsoredGateway:
    """A Product stand-in that answers the catalog and the paid section."""

    def __init__(self, *, with_sponsored: bool = True) -> None:
        self.calls: list[dict[str, Any]] = []
        self.with_sponsored = with_sponsored

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
                "headers": headers,
            }
        )
        if path == "/internal/public-site/catalog":
            return _json(
                {
                    "query": dict(params or {}),
                    "listings": [listing(LISTING_ID, "casa-organica", "Casa Orgánica")],
                    "total": 1,
                    "has_more": False,
                }
            )
        if path == "/internal/public-site/sponsored":
            if not self.with_sponsored:
                return _json({"surface": "Search", "cards": [], "available_slots": 0})
            return _json(
                {
                    "surface": params.get("surface") if params else "Search",
                    "available_slots": 2,
                    "disclosure": "Una publicación patrocinada compra visibilidad.",
                    "cards": [
                        {
                            "position": 1,
                            "campaign_id": CAMPAIGN_ID,
                            "exposure_id": EXPOSURE_ID,
                            "label": SPONSORED_LABEL,
                            "accessible_label": SPONSORED_ARIA_LABEL,
                            "listing": listing(
                                SPONSORED_LISTING_ID,
                                "casa-patrocinada",
                                "Casa Patrocinada",
                            ),
                        }
                    ],
                }
            )
        if path.startswith("/internal/public-site/sponsorship-report/"):
            if "revocado" in path:
                return _json({"detail": "Ya no está disponible."}, status_code=410)
            if path.endswith("/pdf"):
                return GatewayResponse(
                    status_code=200,
                    data=None,
                    content=b"%PDF-1.7 sintetico",
                    content_type="application/pdf",
                    headers={},
                )
            return _json(
                {
                    "label": SPONSORED_LABEL,
                    "listing_title": "Casa Patrocinada",
                    "definition_version": "measurement-v1",
                    "period_start": "2026-08-28T00:00:00Z",
                    "period_end": "2026-09-01T00:00:00Z",
                    "summary": [
                        {"label": "Impresiones visibles", "value": 12},
                        {"label": "Aperturas de publicación", "value": 7},
                        {"label": "Acciones de interés", "value": 5},
                        {"label": "Solicitudes de cita", "value": 3},
                    ],
                    "status": {
                        "state": "Activa",
                        "paid_days": 30,
                        "delivered_days": 3,
                        "remaining_days": 27,
                    },
                    "trend": [
                        {
                            "date": "2026-08-28T00:00:00Z",
                            "visible": 12,
                            "opens": 7,
                            "interest": 5,
                        }
                    ],
                    "funnel": [
                        {
                            "label": "Impresiones visibles",
                            "value": 12,
                            "conversion": "66.7 %",
                        },
                        {
                            "label": "Exploración significativa de galería",
                            "value": None,
                            "conversion": "Muestra protegida",
                        },
                    ],
                    "definitions": [
                        "Visible: al menos 50 % de la tarjeta durante 1 segundo."
                    ],
                    "disclosure": "La visibilidad pagada no cambia las recomendaciones de Maia.",
                    "disclaimer": "Estas cifras no miden causalidad.",
                    "lines": [
                        {"text": "Reporte de campaña Patrocinada", "style": "title"},
                        {"text": "Embudo", "style": "heading"},
                        {"text": "Impresiones visibles: 12", "style": "body"},
                    ],
                }
            )
        if path == "/internal/public-site/sponsored/visible":
            return _json({"counted": True}, status_code=202)
        if path.startswith("/internal/public-site/measurement/"):
            return _json({"recorded": True}, status_code=202)
        if path.startswith("/internal/public-site/listings/"):
            return _json({"listing": listing(LISTING_ID, "casa-organica", "Casa Orgánica")})
        if path.startswith("/internal/public-site/discovery/"):
            return _json({"title": "Casa Orgánica", "description": "Ficha", "structured_data": None})
        if path == "/internal/public-site/saved":
            return _json({"items": [], "collection_token": None})
        return _json({"detail": "No encontrado"}, status_code=404)

    async def aclose(self) -> None:
        return None


def _json(data: Any, *, status_code: int = 200) -> GatewayResponse:
    return GatewayResponse(
        status_code=status_code,
        data=data,
        content=json.dumps(data).encode(),
        content_type="application/json",
        headers={},
    )


def settings() -> Settings:
    return Settings(
        _env_file=None,
        PLUGIN_API_TOKEN="test-token",
        SITE_PUBLIC_ORIGIN="https://larevia.test",
    )


async def client_for(gateway: SponsoredGateway) -> httpx.AsyncClient:
    app = create_site_app(settings(), gateway)
    return httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://larevia.test",
        follow_redirects=False,
    )


@pytest.mark.parametrize("path", ["/", "/propiedades"])
async def test_a_paid_card_is_labelled_visibly_and_accessibly(path) -> None:
    gateway = SponsoredGateway()
    async with await client_for(gateway) as client:
        response = await client.get(path)
    body = response.text
    assert response.status_code == 200
    assert f">{SPONSORED_LABEL}<" in body
    assert f'aria-label="{SPONSORED_ARIA_LABEL}"' in body
    assert f'data-sponsored-campaign="{CAMPAIGN_ID}"' in body
    assert f'data-sponsored-exposure="{EXPOSURE_ID}"' in body
    # The organic card is present, and its own article carries no label at all.
    assert "Casa Orgánica" in body
    organic_article = next(
        block
        for block in re.findall(r"<article .*?</article>", body, flags=re.S)
        if LISTING_ID in block
    )
    assert SPONSORED_LABEL not in organic_article
    assert "aria-label" not in organic_article
    assert "sponsored" not in organic_article


async def test_the_homepage_paid_section_has_its_own_heading() -> None:
    gateway = SponsoredGateway()
    async with await client_for(gateway) as client:
        body = (await client.get("/")).text
    assert 'id="patrocinadas"' in body
    assert "Propiedades con visibilidad patrocinada" in body
    assert "Una publicación patrocinada compra visibilidad." in body


async def test_a_surface_with_no_paid_section_renders_none() -> None:
    gateway = SponsoredGateway(with_sponsored=False)
    async with await client_for(gateway) as client:
        body = (await client.get("/")).text
    assert SPONSORED_LABEL not in body
    assert 'id="patrocinadas"' not in body


async def test_the_site_mints_one_opaque_session_reference_and_reuses_it() -> None:
    """A capping reference, not an advertising identifier.

    Random, HttpOnly, secure, one day long, and used for exactly one thing: the
    per-session daily cap on paid Visible Impressions. It is never joined to a
    Contact, and Product pseudonymises it before storing anything derived from it.
    """
    gateway = SponsoredGateway()
    async with await client_for(gateway) as client:
        first = await client.get("/")
        cookie = first.cookies.get(SESSION_COOKIE)
        assert cookie is not None
        assert len(cookie) == 32
        header = first.headers["set-cookie"]
        assert "HttpOnly" in header
        assert "Secure" in header
        assert "SameSite=lax" in header
        assert "Max-Age=86400" in header

        # The client already holds the cookie from the first response, so the
        # second request carries it and must not be given a new one.
        second = await client.get("/propiedades")
        assert SESSION_COOKIE not in second.headers.get("set-cookie", "")

    forwarded = [
        call["headers"]
        for call in gateway.calls
        if call["path"] == "/internal/public-site/sponsored"
    ]
    assert forwarded[0]["X-Session-Reference"] == cookie
    assert forwarded[-1]["X-Session-Reference"] == cookie
    assert forwarded[-1]["X-Crawler"] == "false"


async def test_a_crawler_is_reported_as_one_without_its_agent_being_forwarded() -> None:
    gateway = SponsoredGateway()
    async with await client_for(gateway) as client:
        await client.get(
            "/propiedades",
            headers={"user-agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"},
        )
    call = next(
        item
        for item in gateway.calls
        if item["path"] == "/internal/public-site/sponsored"
    )
    assert call["headers"]["X-Crawler"] == "true"
    assert "Googlebot" not in json.dumps(call["headers"])


async def test_the_search_page_asks_only_about_the_results_it_is_showing() -> None:
    """The organic ids travel so Product can skip a duplicate card, and only that."""
    gateway = SponsoredGateway()
    async with await client_for(gateway) as client:
        await client.get("/propiedades")
    call = next(
        item
        for item in gateway.calls
        if item["path"] == "/internal/public-site/sponsored"
    )
    assert call["params"]["surface"] == "Search"
    assert call["params"]["visible_results"] == 1
    assert call["params"]["organic"] == LISTING_ID


async def test_the_technical_sheet_records_its_own_listing_open() -> None:
    """Server-side, so the count does not depend on a script running."""
    gateway = SponsoredGateway()
    async with await client_for(gateway) as client:
        await client.get("/propiedades/casa-organica")
    call = next(
        item
        for item in gateway.calls
        if item["path"] == "/internal/public-site/measurement/listing-open"
    )
    assert call["method"] == "POST"


async def test_two_first_time_browsers_get_distinct_listing_open_keys() -> None:
    gateway = SponsoredGateway()
    async with await client_for(gateway) as first:
        await first.get("/propiedades/casa-organica")
    async with await client_for(gateway) as second:
        await second.get("/propiedades/casa-organica")

    calls = [
        item
        for item in gateway.calls
        if item["path"] == "/internal/public-site/measurement/listing-open"
    ]
    assert len(calls) == 2
    assert calls[0]["body"]["event_key"] != calls[1]["body"]["event_key"]
    for call in calls:
        reference = call["headers"]["X-Session-Reference"]
        assert reference not in call["body"]["event_key"]


async def test_the_buyer_report_page_is_private_noindex_and_offers_the_pdf() -> None:
    gateway = SponsoredGateway()
    async with await client_for(gateway) as client:
        page = await client.get("/reportes/token-sintetico")
        pdf = await client.get("/reportes/token-sintetico/patrocinio.pdf")

    assert page.status_code == 200
    assert page.headers["cache-control"] == "private, no-store"
    assert page.headers["x-robots-tag"] == "noindex, follow"
    assert "Reporte de campaña" in page.text
    assert "Cuatro cifras para empezar" in page.text
    assert page.text.count("Impresiones visibles") >= 2
    assert "Tendencia" in page.text
    assert "Embudo completo" in page.text
    assert "Muestra protegida" in page.text
    assert "Estas cifras no miden causalidad" in page.text
    assert "/reportes/token-sintetico/patrocinio.pdf" in page.text
    # No cookie is set: the link is the whole surface, not the start of a session.
    assert "set-cookie" not in page.headers

    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF-1.7")
    assert pdf.headers["cache-control"] == "private, no-store"


async def test_a_revoked_report_link_renders_a_410_page_and_a_410_pdf() -> None:
    gateway = SponsoredGateway()
    async with await client_for(gateway) as client:
        page = await client.get("/reportes/revocado")
        pdf = await client.get("/reportes/revocado/patrocinio.pdf")
    assert page.status_code == 410
    assert "Reporte no disponible" in page.text
    assert page.headers["x-robots-tag"] == "noindex, follow"
    assert pdf.status_code == 410


async def test_the_visibility_and_gallery_beacons_forward_and_validate() -> None:
    gateway = SponsoredGateway()
    async with await client_for(gateway) as client:
        accepted = await client.post(
            "/patrocinadas/visible",
            json={
                "exposure_id": EXPOSURE_ID,
                "visible_fraction": 0.6,
                "continuous_milliseconds": 1200,
                "occurred_at": "2026-08-28T18:00:00+00:00",
            },
        )
        depth = await client.post(
            "/medicion/galeria",
            json={
                "event_key": "galeria-sintetica",
                "listing_id": SPONSORED_LISTING_ID,
                "photographs": 6,
                "gallery_fraction": 0.5,
                "occurred_at": "2026-08-28T18:00:00+00:00",
            },
        )
        malformed = await client.post(
            "/patrocinadas/visible", content=b"no-es-json"
        )
        malformed_depth = await client.post("/medicion/galeria", content=b"{")

    assert accepted.status_code == 202
    assert depth.status_code == 202
    assert malformed.status_code == 400
    assert malformed_depth.status_code == 400
    forwarded = next(
        call for call in gateway.calls if call["path"] == "/internal/public-site/sponsored/visible"
    )
    assert forwarded["body"] == {
        "exposure_id": EXPOSURE_ID,
        "visible_fraction": 0.6,
        "continuous_milliseconds": 1200,
        "occurred_at": "2026-08-28T18:00:00+00:00",
    }


async def test_the_paid_section_survives_a_product_failure_without_a_page_error(
) -> None:
    """Measurement and monetisation must never be able to break the page.

    A Product answer the site cannot use means no sponsored section, not a 500 —
    the visitor still gets the catalogue they came for.
    """

    class BrokenSponsored(SponsoredGateway):
        async def request(self, method, path, **kwargs):  # noqa: ANN001, ANN003
            if path == "/internal/public-site/sponsored":
                return _json({"detail": "No disponible"}, status_code=503)
            return await super().request(method, path, **kwargs)

    gateway = BrokenSponsored()
    async with await client_for(gateway) as client:
        response = await client.get("/propiedades")
    assert response.status_code == 200
    assert "Casa Orgánica" in response.text
    assert SPONSORED_LABEL not in response.text
