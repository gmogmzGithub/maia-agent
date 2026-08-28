"""Marketing-consent evidence used by Stage 7 outreach."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import ConsentCategory, ConsentRecord, ConsentState
from realestate.domain.commercial.actors import Actor

LISTING_MATCH_SCOPE = "ListingMatches"
DEVELOPMENT_SCOPE = "DevelopmentAnnouncements"
BROAD_REAL_ESTATE_SCOPE = "RealEstateMarketing"


@dataclass(frozen=True)
class ConsentDecision:
    granted: bool
    reason: str
    record_id: uuid.UUID | None = None


class MarketingConsent:
    """Read current consent and fail closed while capture has no legal basis."""

    def __init__(
        self, session: AsyncSession, *, capture_activated: bool = False
    ) -> None:
        self._session = session
        self._capture_activated = capture_activated

    async def current(
        self,
        *,
        lead_id: uuid.UUID,
        scope: str,
        at: datetime,
    ) -> ConsentDecision:
        row = await self._session.scalar(
            select(ConsentRecord)
            .where(ConsentRecord.lead_id == lead_id)
            .where(ConsentRecord.channel == "WhatsApp")
            .where(ConsentRecord.category == ConsentCategory.MARKETING.value)
            .order_by(ConsentRecord.recorded_at.desc(), ConsentRecord.id.desc())
            .limit(1)
        )
        if row is None or row.state != ConsentState.GRANTED.value:
            return ConsentDecision(False, "MarketingConsentMissing")
        if row.expires_at is not None and row.expires_at <= at:
            return ConsentDecision(False, "MarketingConsentExpired", row.id)
        if not all(
            (
                (row.business_name or "").strip(),
                (row.notice_version or "").strip(),
                (row.evidence_locator or "").strip(),
                (row.scope or "").strip(),
            )
        ):
            return ConsentDecision(False, "MarketingConsentEvidenceIncomplete", row.id)
        if row.scope not in {scope, BROAD_REAL_ESTATE_SCOPE}:
            return ConsentDecision(False, "MarketingConsentScopeMismatch", row.id)
        return ConsentDecision(True, "Granted", row.id)

    async def capture(
        self,
        actor: Actor,
        *,
        lead_id: uuid.UUID,
        scope: str,
        evidence: str,
    ) -> ConsentDecision:
        """The intended capture seam; deliberately Denied in the current product.

        A real form, approved privacy notice, evidence locator and legal review
        do not exist yet (SAN-010). An Administrator cannot substitute their
        own assertion for the Contact's opt-in.
        """
        actor.require_administrator()
        del lead_id, scope, evidence
        if not self._capture_activated:
            return ConsentDecision(False, "ConsentCaptureFoundationNotApproved")
        # The configuration flag is intentionally not exposed yet. Making this
        # branch reachable requires the approved collection command and schema,
        # not just changing a boolean.
        return ConsentDecision(False, "ConsentCapturePathNotImplemented")
