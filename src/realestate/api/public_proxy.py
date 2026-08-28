"""Host-port proxy to the separate loopback-only public-site process."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse
import httpx

router = APIRouter(include_in_schema=False)

_PUBLIC_ROOTS = frozenset(
    {
        "assets",
        "eventos",
        "favicon.ico",
        "guardadas",
        "handoffs",
        "maia",
        "media",
        "propiedades",
        "robots.txt",
        "selecciones",
        "sitemap.xml",
        "zonas",
    }
)
_FORWARDED_REQUEST_HEADERS = frozenset(
    {"accept", "content-type", "cookie", "if-none-match", "user-agent"}
)
_FORWARDED_RESPONSE_HEADERS = frozenset(
    {
        "cache-control",
        "content-language",
        "content-type",
        "content-security-policy",
        "etag",
        "location",
        "permissions-policy",
        "referrer-policy",
        "set-cookie",
        "x-content-type-options",
        "x-frame-options",
        "x-robots-tag",
    }
)


@router.api_route("/", methods=["GET", "HEAD"])
async def public_root(request: Request) -> Response:
    return await _proxy(request, "")


@router.api_route(
    "/{path:path}", methods=["GET", "HEAD", "POST"]
)
async def public_path(request: Request, path: str) -> Response:
    if path.split("/", 1)[0] not in _PUBLIC_ROOTS:
        return PlainTextResponse("not found", status_code=404)
    return await _proxy(request, path)


async def _proxy(request: Request, path: str) -> Response:
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() in _FORWARDED_REQUEST_HEADERS
    }
    try:
        upstream = await request.app.state.public_site_proxy.request(
            request.method,
            f"/{path}" if path else "/",
            params=list(request.query_params.multi_items()),
            content=await request.body(),
            headers=headers,
        )
    except httpx.HTTPError:
        return PlainTextResponse(
            "El sitio público no está disponible en este momento.", status_code=503
        )
    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() in _FORWARDED_RESPONSE_HEADERS
    }
    return Response(
        upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )
