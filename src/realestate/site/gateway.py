"""HTTP adapter for the Product-owned public-site contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

# Re-exported: the site's app module imports them from here, and Product reads
# the same two names, so the two processes cannot disagree about what a host is
# or about which header carries it.
from realestate.hosts import SITE_HOST_HEADER as SITE_HOST_HEADER
from realestate.hosts import host_of as host_of


@dataclass(frozen=True)
class GatewayResponse:
    status_code: int
    data: Any | None
    content: bytes
    content_type: str
    headers: dict[str, str]


class ProductSiteGateway(Protocol):
    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        token_header: tuple[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> GatewayResponse: ...

    async def aclose(self) -> None: ...


class HttpProductSiteGateway:
    """Production adapter; browser traffic never receives Product credentials."""

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float = 30.0,
        *,
        site_host: str = "",
    ) -> None:
        self._token = token
        self._site_host = site_host
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout, follow_redirects=False
        )

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
        # ``headers`` carries non-secret measurement context — the opaque
        # session reference and the crawler flag. It is a separate argument from
        # ``token_header`` so a caller adding measurement context cannot
        # accidentally displace the Authorization header.
        sent = {"Authorization": f"Bearer {self._token}", **(headers or {})}
        if self._site_host:
            # Set after the caller's headers so a measurement header cannot
            # displace the value Product resolves the Organization from.
            sent[SITE_HOST_HEADER] = self._site_host
        if token_header is not None:
            sent[token_header[0]] = token_header[1]
        response = await self._client.request(
            method, path, params=params, json=body, headers=sent
        )
        content_type = response.headers.get("content-type", "application/octet-stream")
        data: Any | None = None
        if "json" in content_type:
            data = response.json()
        return GatewayResponse(
            status_code=response.status_code,
            data=data,
            content=response.content,
            content_type=content_type,
            headers={key.lower(): value for key, value in response.headers.items()},
        )

    async def aclose(self) -> None:
        await self._client.aclose()
