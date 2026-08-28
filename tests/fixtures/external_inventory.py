"""Certified, public-safe EasyBroker-shaped fixtures and a fake source port."""

from __future__ import annotations

import copy
from typing import Any

from realestate.db.models import ExternalInventoryScope
from realestate.domain.external_inventory.ports import InventorySourceError
from realestate.domain.external_inventory.types import SourcePage


def easybroker_property(
    source_id: str = "EB-FAKE-001",
    *,
    municipality: str = "Zapopan",
    status: str = "active",
    price: int = 5_750_000,
) -> dict[str, Any]:
    """Sanitized response shape derived from the official property contract."""
    return {
        "public_id": source_id,
        "title": "Casa demo en jardín",
        "description": "Datos completamente sintéticos para pruebas públicas.",
        "property_type": "House",
        "status": status,
        "updated_at": "2026-08-28T16:30:00Z",
        "location": {
            "name": f"Colonia Demo, {municipality}, Jalisco",
            "municipality": municipality,
        },
        "bedrooms": 3,
        "bathrooms": 2,
        "parking_spaces": 2,
        "construction_size": 180,
        "operations": [
            {
                "type": "sale",
                "amount": price,
                "currency": "MXN",
                "unit": "total",
            }
        ],
        "agent": {"name": "Agente Demo"},
        "agency": {"name": "Inmobiliaria Demo"},
        "url": f"https://example.invalid/properties/{source_id}",
        "shared_commission_percentage": 50,
    }


class FakeInventorySource:
    source_name = "EasyBroker"
    credential_configured = True
    mls_access_confirmed = True
    retention_permission_confirmed = True

    def __init__(self, records: list[dict[str, Any]] | None = None) -> None:
        values = records or [easybroker_property()]
        self.details = {
            str(value["public_id"]): copy.deepcopy(value) for value in values
        }
        self.pages: dict[str | None, SourcePage] = {
            None: SourcePage(
                records=tuple(
                    {
                        "public_id": value["public_id"],
                        "title": value.get("title"),
                        "updated_at": value.get("updated_at"),
                    }
                    for value in values
                ),
                next_cursor=None,
            )
        }
        self.list_errors: dict[str | None, InventorySourceError] = {}
        self.retrieve_errors: dict[str, InventorySourceError] = {}
        self.list_calls: list[tuple[ExternalInventoryScope, str | None, int]] = []
        self.retrieve_calls: list[tuple[ExternalInventoryScope, str]] = []

    async def list_page(
        self,
        scope: ExternalInventoryScope,
        *,
        cursor: str | None,
        limit: int,
    ) -> SourcePage:
        self.list_calls.append((scope, cursor, limit))
        if error := self.list_errors.get(cursor):
            raise error
        return self.pages.get(cursor, SourcePage(records=(), next_cursor=None))

    async def retrieve(
        self, scope: ExternalInventoryScope, source_listing_id: str
    ) -> dict[str, Any]:
        self.retrieve_calls.append((scope, source_listing_id))
        if error := self.retrieve_errors.get(source_listing_id):
            raise error
        return copy.deepcopy(self.details[source_listing_id])

    async def aclose(self) -> None:
        return None
