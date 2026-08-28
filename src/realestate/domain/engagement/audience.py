"""Explainable audience resolution for an explicit Development Campaign."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    CampaignAudienceMember,
    CampaignAudienceStatus,
    ChannelIdentityTrust,
    ContactChannelIdentity,
    Conversation,
    DevelopmentCampaign,
    PropertyNeed,
    SuppressionRecord,
)
from realestate.domain.commercial.actors import Actor, NotFound
from realestate.domain.commercial.needs import INTENT, SERVICE_AREA, PropertyNeeds
from realestate.domain.engagement.frequency import (
    FREQUENCY_CAP_REACHED,
    frequency_cap_reached,
)
from realestate.domain.engagement.consent import DEVELOPMENT_SCOPE, MarketingConsent
from realestate.domain.text import fold_phrase

AUDIENCE_RULE_VERSION = "development-audience-v1"


@dataclass(frozen=True)
class AudienceMemberView:
    reference: str
    property_need_id: uuid.UUID
    status: str
    reasons: tuple[str, ...]


def audience_reference(campaign_id: uuid.UUID, need_id: uuid.UUID) -> str:
    return hashlib.sha256(f"{campaign_id}:{need_id}".encode()).hexdigest()[:16]


async def latest_route(
    session: AsyncSession, *, contact_id: uuid.UUID
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    identity = await session.scalar(
        select(ContactChannelIdentity)
        .where(ContactChannelIdentity.contact_id == contact_id)
        .where(ContactChannelIdentity.channel == "WhatsApp")
        .where(ContactChannelIdentity.trust == ChannelIdentityTrust.VERIFIED.value)
        .where(ContactChannelIdentity.lead_id.is_not(None))
        .order_by(ContactChannelIdentity.first_seen_at.desc())
        .limit(1)
    )
    if identity is None or identity.lead_id is None:
        return None, None
    conversation_id = await session.scalar(
        select(Conversation.id)
        .where(Conversation.lead_id == identity.lead_id)
        .order_by(Conversation.created_at.desc())
        .limit(1)
    )
    return identity.lead_id, conversation_id


class Audience:
    """Resolve the same rules for preview, activation and execution."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor

    async def resolve(
        self,
        campaign_id: uuid.UUID,
        at: datetime,
        *,
        persist: bool = False,
    ) -> tuple[AudienceMemberView, ...]:
        campaign = await self._session.get(DevelopmentCampaign, campaign_id)
        if campaign is None:
            raise NotFound("No encontramos esa campaña.")
        self._actor.require_same_organization(campaign.organization_id)

        raw_ids = campaign.audience_criteria.get("property_need_ids", [])
        if not isinstance(raw_ids, list):
            raw_ids = []
        need_ids: list[uuid.UUID] = []
        for raw in raw_ids:
            try:
                parsed = uuid.UUID(str(raw))
            except ValueError:
                continue
            if parsed not in need_ids:
                need_ids.append(parsed)
        excluded_ids = {
            str(value)
            for value in campaign.audience_criteria.get("exclude_property_need_ids", [])
        }
        allowed_intents = {
            str(value)
            for value in campaign.audience_criteria.get("transaction_intents", ["Buy"])
        }
        required_area = str(
            campaign.audience_criteria.get("service_area_contains", "")
        ).strip()

        existing = {
            row.property_need_id: row
            for row in await self._session.scalars(
                select(CampaignAudienceMember).where(
                    CampaignAudienceMember.campaign_id == campaign.id
                )
            )
        }
        included = 0
        seen_contacts: set[uuid.UUID] = set()
        views: list[AudienceMemberView] = []
        for need_id in need_ids:
            need = await self._session.get(PropertyNeed, need_id)
            if need is None or need.organization_id != self._actor.organization_id:
                continue
            reference = audience_reference(campaign.id, need.id)
            reasons: list[str] = []
            snapshot = await PropertyNeeds(self._session).snapshot(need.id)
            if need.contact_id in seen_contacts:
                reasons.append("DuplicateContact")
            else:
                seen_contacts.add(need.contact_id)
            if str(need.id) in excluded_ids:
                reasons.append("ExcludedByAdministrator")
            if snapshot.is_stale:
                reasons.append("PropertyNeedStale")
            if snapshot.missing_required:
                reasons.append("ConfirmedCriteriaIncomplete")
            if snapshot.confirmed.get(INTENT) not in allowed_intents:
                reasons.append("TransactionIntentMismatch")
            if required_area and fold_phrase(required_area) not in fold_phrase(
                snapshot.confirmed.get(SERVICE_AREA, "")
            ):
                reasons.append("ServiceAreaMismatch")

            lead_id, conversation_id = await latest_route(
                self._session, contact_id=need.contact_id
            )
            if lead_id is None or conversation_id is None:
                reasons.append("VerifiedWhatsAppRouteMissing")
            else:
                suppressed = await self._session.scalar(
                    select(SuppressionRecord.id)
                    .where(SuppressionRecord.lead_id == lead_id)
                    .where(SuppressionRecord.revoked_at.is_(None))
                    .limit(1)
                )
                if suppressed is not None:
                    reasons.append("Suppressed")
                consent = await MarketingConsent(self._session).current(
                    lead_id=lead_id, scope=DEVELOPMENT_SCOPE, at=at
                )
                if not consent.granted:
                    reasons.append(consent.reason)

            if await frequency_cap_reached(
                self._session,
                organization_id=campaign.organization_id,
                contact_id=need.contact_id,
                at=at,
                window_days=campaign.frequency_window_days,
                cap=campaign.frequency_cap,
            ):
                reasons.append(FREQUENCY_CAP_REACHED)
            if not reasons and included >= campaign.max_recipients:
                reasons.append("AudienceLimitReached")

            status = (
                CampaignAudienceStatus.EXCLUDED.value
                if reasons
                else CampaignAudienceStatus.INCLUDED.value
            )
            if not reasons:
                included += 1
            view = AudienceMemberView(
                reference=reference,
                property_need_id=need.id,
                status=status,
                reasons=tuple(reasons),
            )
            views.append(view)
            if persist:
                row = existing.get(need.id)
                if row is None:
                    row = CampaignAudienceMember(
                        campaign_id=campaign.id,
                        organization_id=campaign.organization_id,
                        property_need_id=need.id,
                        contact_id=need.contact_id,
                        audience_reference=reference,
                        status=status,
                        reasons=reasons,
                        resolved_at=at,
                    )
                    self._session.add(row)
                if row.status in {
                    CampaignAudienceStatus.INCLUDED.value,
                    CampaignAudienceStatus.EXCLUDED.value,
                }:
                    row.lead_id = lead_id
                    row.conversation_id = conversation_id
                    row.status = status
                    row.reasons = reasons
                    row.resolved_at = at
        if persist:
            await self._session.flush()
        return tuple(views)
