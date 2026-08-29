"""Paced cleanup of withdrawn external-inventory cache entries."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from realestate.domain.clock import utc_now
from realestate.db.engine import Database
from realestate.db.models import Organization
from realestate.domain.commercial.actors import Actor
from realestate.domain.external_inventory.inventory import ExternalInventory
from realestate.domain.external_inventory.ports import InventorySource
from realestate.domain.platform.providers import OrganizationEasyBrokerAdapters


class ExternalInventoryCleanupWorker:
    """Delete cached withdrawn payloads before their provider deadline."""

    def __init__(
        self,
        database: Database,
        source: InventorySource | OrganizationEasyBrokerAdapters,
        *,
        interval_seconds: float = 300,
    ) -> None:
        self._database = database
        self._source = source
        self._interval = timedelta(seconds=interval_seconds)
        self._last_run: datetime | None = None

    async def tick(self, *, now: datetime | None = None) -> int | None:
        at = now or utc_now()
        if self._last_run is not None and at < self._last_run + self._interval:
            return None
        self._last_run = at
        deleted = 0
        async with self._database.session_scope() as session:
            organization_ids = tuple(await session.scalars(select(Organization.id)))
            for organization_id in organization_ids:
                actor = Actor.product(organization_id, "ExternalInventoryCleanup")
                source = self._source
                if isinstance(source, OrganizationEasyBrokerAdapters):
                    source = await source.for_organization(session, organization_id)
                deleted += await ExternalInventory(
                    session, actor, source
                ).purge_due(at=at)
        return deleted
