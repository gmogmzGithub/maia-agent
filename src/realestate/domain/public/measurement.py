"""Public funnel facts that need a threshold applied, not just recorded.

Two events cannot be taken at face value from a browser. A Listing open is
Product's own fact — it served the Technical Sheet — so it is recorded on the
server. Gallery depth is only observable in the page, but whether that depth
constitutes a *Significant Gallery Exploration* is a versioned product
definition, so the page reports the two raw numbers and this module decides.

That split is the point. If the page decided, the milestone would mean whatever
the last deployed script believed, and a report reproduced from stored
definitions would silently disagree with itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import AnalyticsEventName
from realestate.domain.analytics.definitions import MeasurementDefinitions
from realestate.domain.analytics.events import AnalyticsEvent, AnalyticsEvents
from realestate.domain.analytics.pseudonyms import Pseudonyms, Purpose
from realestate.domain.commercial.actors import Actor


@dataclass(frozen=True)
class GalleryDepth:
    """One reported gallery-depth observation."""

    event_key: str
    listing_id: uuid.UUID
    photographs: int
    gallery_fraction: float
    occurred_at: datetime
    campaign_id: uuid.UUID | None = None
    session_value: str = ""
    bot: bool = False
    internal: bool = False


@dataclass(frozen=True)
class ListingOpen:
    """One served Technical Sheet."""

    event_key: str
    listing_id: uuid.UUID
    surface: str
    occurred_at: datetime
    campaign_id: uuid.UUID | None = None
    session_value: str = ""
    bot: bool = False
    internal: bool = False


@dataclass(frozen=True)
class DepthOutcome:
    depth_recorded: bool
    significant: bool


class PublicMeasurement:
    """Record the two public events whose meaning depends on a definition."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor

    async def listing_open(self, command: ListingOpen) -> bool:
        event_key = command.event_key
        if command.session_value:
            session_reference = await Pseudonyms(
                self._session, self._actor.organization_id
            ).reference(Purpose.SESSION, command.session_value)
            day = command.occurred_at.astimezone(UTC).date().isoformat()
            event_key = f"open:{command.listing_id}:{session_reference}:{day}"
        return (
            await AnalyticsEvents(self._session, self._actor).record(
                AnalyticsEvent(
                    event_key=event_key,
                    name=AnalyticsEventName.LISTING_OPENED,
                    occurred_at=command.occurred_at,
                    listing_id=command.listing_id,
                    campaign_id=command.campaign_id,
                    session_value=command.session_value,
                    attributes={"surface": command.surface},
                    bot=command.bot,
                    internal=command.internal,
                )
            )
        ).created

    async def gallery_depth(
        self, command: GalleryDepth, *, definition_version: str | None = None
    ) -> DepthOutcome:
        """Record the depth, and the milestone only if the version says so.

        Two events rather than one flagged event: the depth is raw evidence that
        stays comparable across definition versions, while the milestone is
        version-specific. Re-projecting under a new definition can therefore
        recount the milestone from the depth without the raw observation having
        been lost.
        """
        definition = await MeasurementDefinitions(self._session).resolve(
            definition_version
        )
        events = AnalyticsEvents(self._session, self._actor)
        attributes = {
            "photographs": command.photographs,
            "gallery_fraction": command.gallery_fraction,
        }
        depth = await events.record(
            AnalyticsEvent(
                event_key=f"depth:{command.event_key}",
                name=AnalyticsEventName.GALLERY_DEPTH_REACHED,
                occurred_at=command.occurred_at,
                listing_id=command.listing_id,
                campaign_id=command.campaign_id,
                session_value=command.session_value,
                attributes=attributes,
                bot=command.bot,
                internal=command.internal,
            )
        )
        significant = definition.significant_exploration(
            photographs=command.photographs,
            gallery_fraction=command.gallery_fraction,
        )
        if significant:
            await events.record(
                AnalyticsEvent(
                    event_key=f"significant:{command.event_key}",
                    name=AnalyticsEventName.SIGNIFICANT_GALLERY_EXPLORATION,
                    occurred_at=command.occurred_at,
                    listing_id=command.listing_id,
                    campaign_id=command.campaign_id,
                    session_value=command.session_value,
                    attributes=attributes,
                    bot=command.bot,
                    internal=command.internal,
                )
            )
        return DepthOutcome(depth_recorded=depth.created, significant=significant)
