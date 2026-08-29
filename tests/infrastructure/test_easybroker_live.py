"""Opt-in provider smoke test; public CI never requires external access."""

from __future__ import annotations

import os

import pytest

from realestate.db.models import ExternalInventoryScope
from realestate.domain.external_inventory.easybroker import EasyBrokerAdapter

pytestmark = [pytest.mark.live_external_inventory]


@pytest.mark.skipif(
    os.environ.get("RUN_EASYBROKER_LIVE_TESTS") != "1"
    or not os.environ.get("EASYBROKER_STAGING_API_KEY"),
    reason="requires explicit opt-in and a separate EasyBroker staging key",
)
async def test_staging_can_list_organization_properties_read_only() -> None:
    adapter = EasyBrokerAdapter(
        api_key=os.environ["EASYBROKER_STAGING_API_KEY"],
        base_url="https://api.stagingeb.com/v1",
    )
    try:
        page = await adapter.list_page(
            ExternalInventoryScope.ORGANIZATION, cursor=None, limit=1
        )
    finally:
        await adapter.aclose()
    assert len(page.records) <= 1
