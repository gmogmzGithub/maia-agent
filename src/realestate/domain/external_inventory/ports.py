"""The narrow true-external seam used by the inventory module."""

from __future__ import annotations

from typing import Any, Protocol

from realestate.db.models import ExternalInventoryScope
from realestate.domain.external_inventory.types import SourcePage


class InventorySourceError(Exception):
    def __init__(self, code: str, detail: str, *, retry_after_seconds: float | None = None) -> None:
        self.code = code
        self.detail = detail
        self.retry_after_seconds = retry_after_seconds
        super().__init__(detail)


class SourceNotFound(InventorySourceError):
    def __init__(self) -> None:
        super().__init__("not_found", "The source listing no longer exists.")


class SourceAccessDenied(InventorySourceError):
    def __init__(self, code: str = "access_denied") -> None:
        super().__init__(code, "The configured account cannot read this source.")


class InventorySource(Protocol):
    source_name: str
    credential_configured: bool
    mls_access_confirmed: bool
    retention_permission_confirmed: bool

    async def list_page(
        self,
        scope: ExternalInventoryScope,
        *,
        cursor: str | None,
        limit: int,
    ) -> SourcePage: ...

    async def retrieve(
        self, scope: ExternalInventoryScope, source_listing_id: str
    ) -> dict[str, Any]: ...

    async def aclose(self) -> None: ...
