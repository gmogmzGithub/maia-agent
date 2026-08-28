"""Read-only EasyBroker HTTP adapter.

Only GET requests exist in this module. Product policy, persistence, service-area
filtering and authority decisions deliberately live above it.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

import httpx

from realestate.db.models import ExternalInventoryScope
from realestate.domain.external_inventory.ports import (
    InventorySourceError,
    SourceAccessDenied,
    SourceNotFound,
)
from realestate.domain.external_inventory.types import SourcePage

Sleep = Callable[[float], Awaitable[None]]


class EasyBrokerAdapter:
    source_name = "EasyBroker"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.easybroker.com/v1",
        mls_access_confirmed: bool = False,
        retention_permission_confirmed: bool = False,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
        max_attempts: int = 3,
        sleep: Sleep = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.credential_configured = bool(api_key.strip())
        self.mls_access_confirmed = mls_access_confirmed
        self.retention_permission_confirmed = retention_permission_confirmed
        self._api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout_seconds
        )
        self._max_attempts = max(1, max_attempts)
        self._sleep = sleep
        self._monotonic = monotonic
        self._request_lock = asyncio.Lock()
        self._last_request_at: float | None = None

    async def list_page(
        self,
        scope: ExternalInventoryScope,
        *,
        cursor: str | None,
        limit: int,
    ) -> SourcePage:
        self._require_scope(scope)
        page = self._page(cursor)
        payload = await self._request_json(
            self._collection_path(scope), params={"page": page, "limit": min(limit, 50)}
        )
        content = payload.get("content")
        if not isinstance(content, list):
            raise InventorySourceError(
                "invalid_response", "EasyBroker returned no content list."
            )
        records = tuple(item for item in content if isinstance(item, dict))
        pagination = payload.get("pagination")
        next_cursor: str | None = None
        if isinstance(pagination, dict):
            next_page = pagination.get("next_page")
            if isinstance(next_page, int) and next_page > page:
                next_cursor = str(next_page)
            elif isinstance(next_page, str) and next_page.isdigit():
                next_cursor = next_page
            elif pagination.get("has_next_page") is True:
                next_cursor = str(page + 1)
            else:
                total_pages = pagination.get("total_pages")
                if isinstance(total_pages, int) and page < total_pages:
                    next_cursor = str(page + 1)
        return SourcePage(records=records, next_cursor=next_cursor)

    async def retrieve(
        self, scope: ExternalInventoryScope, source_listing_id: str
    ) -> dict[str, Any]:
        self._require_scope(scope)
        safe_id = quote(source_listing_id, safe="")
        return await self._request_json(f"{self._collection_path(scope)}/{safe_id}")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _require_scope(self, scope: ExternalInventoryScope) -> None:
        if not self.credential_configured:
            raise SourceAccessDenied("credential_missing")
        if scope is ExternalInventoryScope.COLLABORATOR and not self.mls_access_confirmed:
            raise SourceAccessDenied("mls_not_confirmed")

    @staticmethod
    def _collection_path(scope: ExternalInventoryScope) -> str:
        return "/properties" if scope is ExternalInventoryScope.ORGANIZATION else "/mls_properties"

    @staticmethod
    def _page(cursor: str | None) -> int:
        if cursor is None:
            return 1
        if not cursor.isdigit() or int(cursor) < 1:
            raise InventorySourceError("invalid_cursor", "The source cursor is invalid.")
        return int(cursor)

    async def _pace(self) -> None:
        async with self._request_lock:
            now = self._monotonic()
            if self._last_request_at is not None:
                wait = 0.05 - (now - self._last_request_at)
                if wait > 0:
                    await self._sleep(wait)
            self._last_request_at = self._monotonic()

    async def _request_json(
        self,
        path: str,
        *,
        params: dict[str, str | int | float | bool | None] | None = None,
    ) -> dict[str, Any]:
        last_error: InventorySourceError | None = None
        for attempt in range(self._max_attempts):
            await self._pace()
            try:
                response = await self._client.get(
                    path,
                    params=params,
                    headers={
                        "Accept": "application/json",
                        "X-Authorization": self._api_key,
                    },
                )
            except httpx.TimeoutException:
                last_error = InventorySourceError(
                    "timeout", "EasyBroker did not answer before the timeout."
                )
            except httpx.HTTPError:
                last_error = InventorySourceError(
                    "transport", "EasyBroker could not be reached."
                )
            else:
                if response.status_code == 404:
                    raise SourceNotFound()
                if response.status_code in {401, 403}:
                    raise SourceAccessDenied(
                        "invalid_credential"
                        if response.status_code == 401
                        else "plan_or_permission_denied"
                    )
                if response.status_code == 429:
                    retry_after = self._retry_after(response)
                    last_error = InventorySourceError(
                        "rate_limited",
                        "EasyBroker rate limit reached.",
                        retry_after_seconds=retry_after,
                    )
                elif response.status_code >= 500:
                    last_error = InventorySourceError(
                        "provider_error", "EasyBroker returned a server error."
                    )
                elif response.is_error:
                    raise InventorySourceError(
                        f"http_{response.status_code}",
                        "EasyBroker rejected the read request.",
                    )
                else:
                    try:
                        payload = response.json()
                    except json.JSONDecodeError as exc:
                        raise InventorySourceError(
                            "invalid_response", "EasyBroker returned invalid JSON."
                        ) from exc
                    if not isinstance(payload, dict):
                        raise InventorySourceError(
                            "invalid_response", "EasyBroker returned a non-object response."
                        )
                    return payload
            assert last_error is not None
            if attempt + 1 < self._max_attempts:
                delay = (
                    last_error.retry_after_seconds
                    if last_error.retry_after_seconds is not None
                    else 0.25 * (2**attempt)
                )
                await self._sleep(min(max(delay, 0.0), 30.0))
        assert last_error is not None
        raise last_error

    @staticmethod
    def _retry_after(response: httpx.Response) -> float:
        raw = response.headers.get("Retry-After", "1")
        try:
            return max(float(raw), 0.0)
        except ValueError:
            return 1.0
