"""The marketing frequency cap, counted in one place.

Three separate paths ask whether a Contact has already been messaged too
recently: campaign planning builds an audience from it, reactivation
authorisation refuses on it, and the worker re-checks it under a lock
immediately before sending. The whole purpose of a cap is that those three
agree, so the count and the comparison live here rather than beside each
caller — three copies could disagree, and the worker's copy is the one that
decides whether a message actually leaves.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import MarketingTouch

FREQUENCY_CAP_REACHED = "FrequencyCapReached"

# A reactivation may touch one Contact once a month; a campaign carries its own
# window and cap as columns, because an Administrator sets those per campaign.
REACTIVATION_WINDOW_DAYS = 30
REACTIVATION_CAP = 1


async def marketing_touches_since(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    contact_id: uuid.UUID,
    since: datetime,
) -> int:
    """How many marketing touches this Contact received on or after ``since``."""
    count = await session.scalar(
        select(func.count(MarketingTouch.id))
        .where(MarketingTouch.organization_id == organization_id)
        .where(MarketingTouch.contact_id == contact_id)
        .where(MarketingTouch.recorded_at >= since)
    )
    return count or 0


async def frequency_cap_reached(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    contact_id: uuid.UUID,
    at: datetime,
    window_days: int,
    cap: int,
) -> bool:
    """Whether another marketing message would exceed the cap for this window."""
    touches = await marketing_touches_since(
        session,
        organization_id=organization_id,
        contact_id=contact_id,
        since=at - timedelta(days=window_days),
    )
    return touches >= cap
