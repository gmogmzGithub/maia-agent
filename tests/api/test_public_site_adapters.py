"""Small adapter and rendering contracts that do not require PostgreSQL."""

from __future__ import annotations

import io
import uuid
from typing import Any

import httpx
import pytest
from PIL import Image

from realestate.domain.public.catalog import SearchQuery
from realestate.domain.public.responders import _json_default
from realestate.site.app import _absolute_schema, _detail, _responsive_image
from realestate.site.gateway import GatewayResponse, HttpProductSiteGateway
from realestate.site.templates import (
    characteristics,
    facts_table,
    price,
    responsive_image,
    saved_item,
    saved_page,
    search_page,
    shared_page,
)


class StubHttpClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"method": method, "path": path, **kwargs})
        if path == "/binary":
            return httpx.Response(
                200,
                content=b"image",
                headers={"Content-Type": "image/jpeg", "ETag": '"one"'},
            )
        return httpx.Response(
            201,
            json={"ok": True},
            headers={"X-Result": "created"},
        )

    async def aclose(self) -> None:
        self.closed = True


async def test_http_gateway_keeps_product_auth_server_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = StubHttpClient()
    monkeypatch.setattr(
        "realestate.site.gateway.httpx.AsyncClient", lambda **_kwargs: client
    )
    gateway = HttpProductSiteGateway("http://product.test/", "internal-secret")

    json_result = await gateway.request(
        "POST",
        "/json",
        params={"page": 2},
        body={"action": "Add"},
        token_header=("X-Collection-Token", "opaque-browser-token"),
    )
    binary_result = await gateway.request("GET", "/binary")
    await gateway.aclose()

    assert json_result.status_code == 201 and json_result.data == {"ok": True}
    assert json_result.headers["x-result"] == "created"
    assert binary_result.data is None and binary_result.content == b"image"
    assert client.calls[0]["headers"] == {
        "Authorization": "Bearer internal-secret",
        "X-Collection-Token": "opaque-browser-token",
    }
    assert client.closed is True


def test_public_image_and_schema_helpers_fail_safely() -> None:
    small = Image.new("RGB", (320, 200), color=(20, 60, 40))
    small_bytes = io.BytesIO()
    small.save(small_bytes, format="JPEG")
    original = small_bytes.getvalue()
    assert _responsive_image(original, "image/jpeg", 480) == (
        original,
        "image/jpeg",
    )

    grayscale = Image.new("L", (1200, 800), color=120)
    large_bytes = io.BytesIO()
    grayscale.save(large_bytes, format="PNG")
    transformed, transformed_type = _responsive_image(
        large_bytes.getvalue(), "image/png", 480
    )
    assert transformed_type == "image/webp" and transformed.startswith(b"RIFF")
    assert _responsive_image(b"not-an-image", "text/plain", 480) == (
        b"not-an-image",
        "text/plain",
    )

    assert _absolute_schema([], "https://larevia.test") is None
    assert _absolute_schema(
        {
            "url": "/propiedades/casa",
            "image": ["/media/one", "https://cdn.test/two"],
        },
        "https://larevia.test",
    ) == {
        "url": "https://larevia.test/propiedades/casa",
        "image": ["https://larevia.test/media/one", "https://cdn.test/two"],
    }
    unavailable = GatewayResponse(503, {"detail": 503}, b"", "text/plain", {})
    assert _detail(unavailable) == "La operación no está disponible en este momento."
    reference = uuid.UUID("11111111-1111-4111-8111-111111111111")
    assert _json_default(reference) == str(reference)


def test_template_empty_and_fallback_states_remain_actionable() -> None:
    empty_search = search_page(
        {
            "listings": [],
            "total": 0,
            "has_more": True,
            "query": {"operation": "Rental", "page": 1, "page_size": 12},
        },
        query_string="operation=Rental",
    )
    assert "No encontramos propiedades" in empty_search
    assert "Mostrar más" in empty_search and "page=2" in empty_search
    assert "Todavía no has guardado" in saved_page({"items": []})
    assert "Esta selección está vacía" in shared_page({"items": []})

    unavailable = saved_item(
        {
            "listing_id": "listing-one",
            "title": "Casa retirada",
            "public_location": "Zapopan",
            "available": False,
            "listing": None,
        }
    )
    assert "Ya no disponible" in unavailable and "Quitar de guardadas" in unavailable
    assert responsive_image(None, "Sin imagen", loading="lazy").startswith(
        '<div class="image-placeholder"'
    )
    assert price({"price_amount": None}) == "Precio disponible previa consulta"
    assert price(
        {"price_amount": "por definir", "price_currency": "MXN", "operation": "Rental"}
    ) == "$por definir MXN / mes"
    assert characteristics(
        {"bedrooms": 3, "bathrooms": 2, "parking_spaces": 2}, limit=1
    ).count("<li>") == 1
    assert "Consulta los datos" in facts_table({})


@pytest.mark.parametrize(
    ("query", "message"),
    [
        (SearchQuery(operation="Unknown"), "operación"),
        (SearchQuery(zone="Monterrey"), "zona"),
        (SearchQuery(sort="personalized"), "orden"),
        (SearchQuery(minimum_price=-1), "mínimo"),
        (SearchQuery(maximum_price=-1), "máximo"),
        (SearchQuery(minimum_price=2, maximum_price=1), "superar"),
    ],
)
def test_search_query_rejects_every_unsupported_filter(
    query: SearchQuery, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        query.normalized()


def test_search_query_clamps_browser_pagination() -> None:
    normalized = SearchQuery(
        operation=" Sale ",
        zone=" Zapopan ",
        property_type=" House ",
        page=0,
        page_size=200,
    ).normalized()
    assert normalized.operation == "Sale"
    assert normalized.zone == "Zapopan"
    assert normalized.property_type == "House"
    assert normalized.page == 1 and normalized.page_size == 24
