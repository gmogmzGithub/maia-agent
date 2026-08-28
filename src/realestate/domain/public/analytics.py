"""Minimal allowlisted public measurement without behavioural profiles."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import PublicAnalyticsEvent, PublicAnalyticsEventName
from realestate.domain.commercial.actors import Actor
from realestate.domain.public.listing import PublicListing

ALLOWED_SURFACES = frozenset(
    {"Homepage", "Search", "TechnicalSheet", "Gallery", "Saved", "Maia"}
)
ALLOWED_PROPERTIES = frozenset({"count", "depth", "operation", "source"})


@dataclass(frozen=True)
class PublicEventCommand:
    event_key: str
    name: PublicAnalyticsEventName
    surface: str
    occurred_at: datetime
    listing_id: uuid.UUID | None = None
    properties: dict[str, Any] | None = None


class PublicAnalytics:
    """Validate and persist only the funnel facts Product has approved."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor

    async def record(self, command: PublicEventCommand) -> bool:
        if command.surface not in ALLOWED_SURFACES:
            raise ValueError("La superficie de medición no es válida.")
        properties = command.properties or {}
        if set(properties) - ALLOWED_PROPERTIES:
            raise ValueError("El evento contiene propiedades no permitidas.")
        if any(not isinstance(value, (str, int, bool)) for value in properties.values()):
            raise ValueError("El evento contiene valores no permitidos.")
        if any(isinstance(value, str) and len(value) > 30 for value in properties.values()):
            raise ValueError("El evento no acepta texto libre.")
        existing = await self._session.scalar(
            select(PublicAnalyticsEvent).where(
                PublicAnalyticsEvent.organization_id == self._actor.organization_id,
                PublicAnalyticsEvent.event_key == command.event_key,
            )
        )
        if existing is not None:
            return False
        tier = None
        if command.listing_id is not None:
            publication = await PublicListing(
                self._session, self._actor
            ).read_by_id(command.listing_id, at=command.occurred_at)
            if publication.listing is None:
                raise ValueError("No se mide una publicación retirada.")
            tier = publication.listing.presentation_tier
        self._session.add(
            PublicAnalyticsEvent(
                organization_id=self._actor.organization_id,
                event_key=command.event_key,
                name=command.name.value,
                listing_id=command.listing_id,
                presentation_tier=tier,
                surface=command.surface,
                properties=properties,
                occurred_at=command.occurred_at,
            )
        )
        await self._session.flush()
        return True
