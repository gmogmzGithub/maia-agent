"""Tie inbound replies back to the queued Stage 7 decision."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    CampaignAudienceMember,
    CampaignAudienceStatus,
    ReactivationCandidate,
    ReactivationCandidateStatus,
)


@dataclass(frozen=True)
class EngagementOrigin:
    label: str


async def engagement_origin_for_lead(
    session: AsyncSession, lead_id: uuid.UUID
) -> EngagementOrigin | None:
    candidate = await session.scalar(
        select(ReactivationCandidate)
        .where(ReactivationCandidate.lead_id == lead_id)
        .where(ReactivationCandidate.status == ReactivationCandidateStatus.QUEUED.value)
        .order_by(ReactivationCandidate.updated_at.desc())
        .limit(1)
    )
    if candidate is not None:
        return EngagementOrigin(f"reactivation:{candidate.id}")
    campaign_id = await session.scalar(
        select(CampaignAudienceMember.campaign_id)
        .where(CampaignAudienceMember.lead_id == lead_id)
        .where(CampaignAudienceMember.status == CampaignAudienceStatus.QUEUED.value)
        .order_by(CampaignAudienceMember.resolved_at.desc())
        .limit(1)
    )
    return EngagementOrigin(f"campaign:{campaign_id}") if campaign_id else None


async def record_engagement_reply(
    session: AsyncSession, *, lead_id: uuid.UUID, at: datetime
) -> int:
    """Stop queued generic work as part of accepting the Contact's message."""
    changed = 0
    candidates = await session.scalars(
        select(ReactivationCandidate)
        .where(ReactivationCandidate.lead_id == lead_id)
        .where(ReactivationCandidate.status == ReactivationCandidateStatus.QUEUED.value)
        .with_for_update()
    )
    for row in candidates:
        row.status = ReactivationCandidateStatus.RESPONDED.value
        row.updated_at = at
        changed += 1
    members = await session.scalars(
        select(CampaignAudienceMember)
        .where(CampaignAudienceMember.lead_id == lead_id)
        .where(CampaignAudienceMember.status == CampaignAudienceStatus.QUEUED.value)
        .with_for_update()
    )
    for member in members:
        member.status = CampaignAudienceStatus.RESPONDED.value
        member.reasons = ["ContactReplied"]
        member.resolved_at = at
        changed += 1
    return changed
