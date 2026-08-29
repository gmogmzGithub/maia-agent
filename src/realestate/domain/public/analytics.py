"""Minimal allowlisted public measurement without behavioural profiles.

Stage 5 established this surface: a closed set of funnel names, no free text, no
keystrokes, no session replay, no advertising identifier. Stage 8 keeps every one
of those limits and adds one thing — the accepted events are also enqueued into
the durable analytics Outbox, so business intelligence reads the same facts the
public funnel already recorded instead of a second, subtly different stream.

The bridge is a mapping, not an identity. ``ListingImpression`` has no Stage 8
counterpart on purpose: a card scrolling past is not a Listing open, and the
Stage 8 funnel counts served and visible impressions only where somebody paid
for the position and the browser reported the visibility.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    AnalyticsEventName,
    PublicAnalyticsEvent,
    PublicAnalyticsEventName,
)
from realestate.domain.analytics.events import AnalyticsEvent, AnalyticsEvents
from realestate.domain.analytics.taxonomy import SCHEMAS
from realestate.domain.commercial.actors import Actor
from realestate.domain.public.listing import PublicListing

ALLOWED_SURFACES = frozenset(
    {"Homepage", "Search", "TechnicalSheet", "Gallery", "Saved", "Maia"}
)
ALLOWED_PROPERTIES = frozenset({"count", "depth", "operation", "source"})

#: Which Stage 8 domain event each Stage 5 funnel name also produces. A name
#: absent from this mapping is recorded on the Stage 5 surface only.
BRIDGED_EVENTS: dict[PublicAnalyticsEventName, AnalyticsEventName] = {
    PublicAnalyticsEventName.GALLERY_OPEN: AnalyticsEventName.GALLERY_OPENED,
    PublicAnalyticsEventName.LISTING_SAVED: AnalyticsEventName.LISTING_SAVED,
    PublicAnalyticsEventName.MAIA_STARTED: AnalyticsEventName.MAIA_STARTED,
    PublicAnalyticsEventName.HANDOFF_CREATED: AnalyticsEventName.WHATSAPP_HANDOFF,
    PublicAnalyticsEventName.APPOINTMENT_REQUESTED: (
        AnalyticsEventName.APPOINTMENT_REQUESTED
    ),
}


@dataclass(frozen=True)
class PublicEventCommand:
    event_key: str
    name: PublicAnalyticsEventName
    surface: str
    occurred_at: datetime
    listing_id: uuid.UUID | None = None
    properties: dict[str, Any] | None = None
    #: An opaque per-browser reference the site minted. Pseudonymised before it
    #: reaches the analytics schema and never stored on the Stage 5 row.
    session_value: str = ""
    bot: bool = False
    internal: bool = False


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
        await self._bridge(command)
        await self._session.flush()
        return True

    async def _bridge(self, command: PublicEventCommand) -> None:
        """Also enqueue the Stage 8 domain event, when one corresponds.

        The Stage 5 event key is reused as the Stage 8 key, prefixed. That is
        what makes the bridge idempotent for free: the Stage 5 row is unique on
        its key, so a duplicate never reaches this method, and a replay through
        a different path still collides on the prefixed key.

        The attributes are filtered against the target event's declared schema
        rather than copied. Two Stage 5 names map to Stage 8 events that do not
        accept a ``surface`` at all, and passing one anyway would turn a
        successful public event into a refused bridge.
        """
        mapped = BRIDGED_EVENTS.get(command.name)
        if mapped is None:
            return
        schema = SCHEMAS[mapped]
        if schema.requires_listing and command.listing_id is None:
            # A gallery open with no Listing is not a measurable Stage 8 fact.
            # Recorded on the Stage 5 surface, dropped here, never invented.
            return
        attributes: dict[str, Any] = {}
        if "surface" in schema.allowed:
            attributes["surface"] = command.surface
        await AnalyticsEvents(self._session, self._actor).record(
            AnalyticsEvent(
                event_key=f"public:{command.event_key}",
                name=mapped,
                occurred_at=command.occurred_at,
                listing_id=command.listing_id,
                session_value=command.session_value,
                attributes=attributes,
                bot=command.bot,
                internal=command.internal,
            )
        )
