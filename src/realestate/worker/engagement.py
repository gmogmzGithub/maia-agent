"""Dispatch reviewed Stage 7 work through the existing outbound gate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.engine import Database
from realestate.db.models import (
    CampaignAudienceMember,
    CampaignAudienceStatus,
    ConsentCategory,
    Conversation,
    DevelopmentCampaign,
    DevelopmentCampaignStatus,
    MarketingTouch,
    OutboundInitiation,
    PropertyNeed,
    ReactivationCandidate,
    ReactivationCandidateStatus,
)
from realestate.domain.outbound import (
    Denied,
    OutboundIntent,
    OutboundMessaging,
    Purpose,
    Queued,
)


def outside_send_hours(
    moment: datetime, *, start: int, end: int, timezone: str
) -> bool:
    """Whether ``moment`` is in a campaign's quiet interval."""
    try:
        local_hour = moment.astimezone(ZoneInfo(timezone)).hour
    except ZoneInfoNotFoundError:
        return True
    if start == end:
        return True
    if start < end:
        return start <= local_hour < end
    return local_hour >= start or local_hour < end


class EngagementWorker:
    """At most one Candidate and one Campaign member per tick."""

    def __init__(
        self, database: Database, *, activation_approved: bool = False
    ) -> None:
        self._database = database
        self._activation_approved = activation_approved

    async def tick(self, *, now: datetime | None = None) -> int:
        if not self._activation_approved:
            return 0
        moment = now or datetime.now(tz=UTC)
        async with self._database.session_scope() as session:
            candidate = await self._candidate(session, moment)
            campaign = await self._campaign(session, moment)
            await session.commit()
        return candidate + campaign

    async def _candidate(self, session: AsyncSession, moment: datetime) -> int:
        row = await session.scalar(
            select(ReactivationCandidate)
            .where(
                ReactivationCandidate.status
                == ReactivationCandidateStatus.AUTHORIZED.value
            )
            .order_by(ReactivationCandidate.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            return 0
        # Candidate sends use the same conservative Larevia quiet hours as the
        # campaign default. They are a versioned business rule, not a Meta fact.
        if outside_send_hours(moment, start=20, end=9, timezone="America/Mexico_City"):
            return 0
        if row.conversation_id is None:
            row.status = ReactivationCandidateStatus.DENIED.value
            row.review_reason = "VerifiedWhatsAppRouteMissing"
            row.updated_at = moment
            return 1
        conversation = await session.get(Conversation, row.conversation_id)
        need = await session.get(PropertyNeed, row.property_need_id)
        if conversation is None or need is None:
            row.status = ReactivationCandidateStatus.DENIED.value
            row.review_reason = "VerifiedWhatsAppRouteMissing"
            row.updated_at = moment
            return 1
        result = await OutboundMessaging(session).request(
            OutboundIntent(
                conversation=conversation,
                body=row.message_preview or "",
                purpose=Purpose.REACTIVATION,
                initiation=OutboundInitiation.BUSINESS_INITIATED,
                idempotency_key=f"reactivation:{row.id}",
                requested_at=moment,
                template_id=row.template_name,
                template_category=ConsentCategory.MARKETING,
                template_language=row.template_language,
            )
        )
        row.decision_id = result.decision_id
        row.updated_at = moment
        if isinstance(result, Denied):
            row.status = ReactivationCandidateStatus.DENIED.value
            row.review_reason = result.reason.value
        else:
            assert isinstance(result, Queued)
            row.status = ReactivationCandidateStatus.QUEUED.value
            row.outbox_id = result.outbox_id
            session.add(
                MarketingTouch(
                    organization_id=row.organization_id,
                    contact_id=need.contact_id,
                    reactivation_candidate_id=row.id,
                    decision_id=result.decision_id,
                    outbox_id=result.outbox_id,
                    recorded_at=moment,
                )
            )
        await session.flush()
        return 1

    async def _campaign(self, session: AsyncSession, moment: datetime) -> int:
        campaign = await session.scalar(
            select(DevelopmentCampaign)
            .where(DevelopmentCampaign.status == DevelopmentCampaignStatus.ACTIVE.value)
            .order_by(DevelopmentCampaign.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if campaign is None:
            return 0
        if outside_send_hours(
            moment,
            start=campaign.quiet_hours_start,
            end=campaign.quiet_hours_end,
            timezone=campaign.timezone,
        ):
            return 0
        member = await session.scalar(
            select(CampaignAudienceMember)
            .where(CampaignAudienceMember.campaign_id == campaign.id)
            .where(
                CampaignAudienceMember.status == CampaignAudienceStatus.INCLUDED.value
            )
            .order_by(CampaignAudienceMember.resolved_at, CampaignAudienceMember.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if member is None:
            campaign.status = DevelopmentCampaignStatus.COMPLETED.value
            campaign.updated_at = moment
            return 0

        touches = await session.scalar(
            select(func.count(MarketingTouch.id))
            .where(MarketingTouch.organization_id == campaign.organization_id)
            .where(MarketingTouch.contact_id == member.contact_id)
            .where(
                MarketingTouch.recorded_at
                >= moment - timedelta(days=campaign.frequency_window_days)
            )
        )
        if (touches or 0) >= campaign.frequency_cap:
            member.status = CampaignAudienceStatus.DENIED.value
            member.reasons = ["FrequencyCapReached"]
            member.resolved_at = moment
            await session.flush()
            return 1
        if member.conversation_id is None:
            member.status = CampaignAudienceStatus.DENIED.value
            member.reasons = ["VerifiedWhatsAppRouteMissing"]
            member.resolved_at = moment
            return 1
        conversation = await session.get(Conversation, member.conversation_id)
        if conversation is None:
            member.status = CampaignAudienceStatus.DENIED.value
            member.reasons = ["VerifiedWhatsAppRouteMissing"]
            member.resolved_at = moment
            return 1
        result = await OutboundMessaging(session).request(
            OutboundIntent(
                conversation=conversation,
                body=campaign.content_preview,
                purpose=Purpose.DEVELOPMENT_CAMPAIGN,
                initiation=OutboundInitiation.BUSINESS_INITIATED,
                idempotency_key=f"campaign:{campaign.id}:{member.id}",
                requested_at=moment,
                template_id=campaign.template_name,
                template_category=ConsentCategory.MARKETING,
                template_language=campaign.template_language,
            )
        )
        member.decision_id = result.decision_id
        member.resolved_at = moment
        if isinstance(result, Denied):
            member.status = CampaignAudienceStatus.DENIED.value
            member.reasons = [result.reason.value]
        else:
            assert isinstance(result, Queued)
            member.status = CampaignAudienceStatus.QUEUED.value
            member.outbox_id = result.outbox_id
            session.add(
                MarketingTouch(
                    organization_id=campaign.organization_id,
                    contact_id=member.contact_id,
                    campaign_id=campaign.id,
                    decision_id=result.decision_id,
                    outbox_id=result.outbox_id,
                    recorded_at=moment,
                )
            )
        await session.flush()
        remaining = await session.scalar(
            select(func.count(CampaignAudienceMember.id))
            .where(CampaignAudienceMember.campaign_id == campaign.id)
            .where(
                CampaignAudienceMember.status == CampaignAudienceStatus.INCLUDED.value
            )
        )
        if not remaining:
            campaign.status = DevelopmentCampaignStatus.COMPLETED.value
            campaign.updated_at = moment
        return 1
