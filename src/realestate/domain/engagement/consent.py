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



def consent_expired(record: ConsentRecord, at: datetime) -> bool:
    """Whether a grant has lapsed by ``at``."""
    return record.expires_at is not None and record.expires_at <= at


def consent_evidence_complete(record: ConsentRecord) -> bool:
    """Whether the record names who collected the consent, under what notice.

    A grant without a business name, a scope, a notice version and a locator for
    the evidence is not something the operation could show a regulator, so it is
    not something Product will message on.
    """
    return all(
        (
            (record.business_name or "").strip(),
            (record.notice_version or "").strip(),
            (record.evidence_locator or "").strip(),
            (record.scope or "").strip(),
        )
    )


def consent_covers_scope(record: ConsentRecord, scope: str) -> bool:
    """Whether the recorded scope authorises this particular use."""
    return record.scope in {scope, BROAD_REAL_ESTATE_SCOPE}


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
        if consent_expired(row, at):
            return ConsentDecision(False, "MarketingConsentExpired", row.id)
        if not consent_evidence_complete(row):
            return ConsentDecision(False, "MarketingConsentEvidenceIncomplete", row.id)
        if not consent_covers_scope(row, scope):
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
