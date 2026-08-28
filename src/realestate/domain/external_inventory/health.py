"""Read model for one external source's operational health."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import InventorySourceHealthRecord, InventorySourceStatus
from realestate.domain.commercial.actors import Actor
from realestate.domain.external_inventory.types import SourceHealthView


class InventorySourceHealth:
    def __init__(
        self,
        session: AsyncSession,
        actor: Actor,
        *,
        credential_configured: bool = False,
        mls_access_confirmed: bool = False,
        retention_permission_confirmed: bool = False,
    ) -> None:
        self._session = session
        self._actor = actor
        self._credential_configured = credential_configured
        self._mls_access_confirmed = mls_access_confirmed
        self._retention_permission_confirmed = retention_permission_confirmed

    async def read(self, source: str) -> SourceHealthView:
        self._actor.require_administrator()
        row = await self._session.scalar(
            select(InventorySourceHealthRecord).where(
                InventorySourceHealthRecord.organization_id
                == self._actor.organization_id,
                InventorySourceHealthRecord.source == source,
            )
        )
        if row is None:
            return SourceHealthView(
                source=source,
                status=(
                    InventorySourceStatus.NEVER_SYNCED.value
                    if self._credential_configured
                    else InventorySourceStatus.DISABLED.value
                ),
                credential_configured=self._credential_configured,
                mls_access_confirmed=self._mls_access_confirmed,
                retention_permission_confirmed=(
                    self._retention_permission_confirmed
                ),
                last_started_at=None,
                last_completed_at=None,
                last_success_at=None,
                last_cursor=None,
                last_error_code=None,
                last_error_detail=None,
                fetched_count=0,
                accepted_count=0,
                rejected_count=0,
                rate_limited_until=None,
            )
        return SourceHealthView(
            source=row.source,
            status=row.status,
            credential_configured=row.credential_configured,
            mls_access_confirmed=row.mls_access_confirmed,
            retention_permission_confirmed=row.retention_permission_confirmed,
            last_started_at=row.last_started_at,
            last_completed_at=row.last_completed_at,
            last_success_at=row.last_success_at,
            last_cursor=row.last_cursor,
            last_error_code=row.last_error_code,
            last_error_detail=row.last_error_detail,
            fetched_count=row.fetched_count,
            accepted_count=row.accepted_count,
            rejected_count=row.rejected_count,
            rate_limited_until=row.rate_limited_until,
        )
