"""Reviewed reactivation candidates created from explainable Listing matches."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.domain.clock import utc_now
from realestate.domain.platform.entitlements import Entitlements
from realestate.db.models import (
    Capability,
    ConsentCategory,
    Opportunity,
    OpportunityStage,
    PropertyNeed,
    ReactivationCandidate,
    ReactivationCandidateStatus,
)
from realestate.domain.audit import record_audit
from realestate.domain.catalog.eligibility import EligibilityPurpose
from realestate.domain.catalog.projection import (
    AuthorizedListing,
    AuthorizedListingQuery,
    CatalogProjection,
)
from realestate.domain.commercial.actors import (
    Actor,
    CommercialError,
    InvalidTransition,
    NotFound,
)
from realestate.domain.commercial.needs import PropertyNeeds
from realestate.domain.engagement.audience import latest_route
from realestate.domain.engagement.frequency import (
    FREQUENCY_CAP_REACHED,
    REACTIVATION_CAP,
    REACTIVATION_WINDOW_DAYS,
    frequency_cap_reached,
)
from realestate.domain.engagement.consent import LISTING_MATCH_SCOPE, MarketingConsent
from realestate.domain.engagement.matching import (
    MATCH_RULE_VERSION,
    InventoryMatching,
    ListingMatchInput,
)
from realestate.domain.engagement.templates import TemplateRegistry


class ReactivationDenied(CommercialError):
    message = "La reactivación no cumple las condiciones para contactar."


@dataclass(frozen=True)
class AuthorizeReactivation:
    candidate_id: uuid.UUID
    template_name: str
    template_language: str
    message_preview: str
    reason: str


@dataclass(frozen=True)
class RejectReactivation:
    candidate_id: uuid.UUID
    reason: str


@dataclass(frozen=True)
class RevokeReactivation:
    candidate_id: uuid.UUID
    reason: str


@dataclass(frozen=True)
class ReactivationCandidateView:
    candidate_id: uuid.UUID
    property_need_id: uuid.UUID
    listing_id: uuid.UUID
    listing_title: str
    status: str
    match_kind: str
    explanation: tuple[dict[str, str], ...]
    denial_reason: str | None


def _match_input(listing: AuthorizedListing) -> ListingMatchInput:
    return ListingMatchInput(
        listing_id=listing.listing_id,
        title=listing.title,
        public_location=listing.public_location,
        facts={**listing.physical_facts, **listing.listing_facts},
        operations=tuple(offer.operation for offer in listing.offers),
        prices=tuple(
            offer.price_amount
            for offer in listing.offers
            if offer.price_amount is not None
        ),
    )


class Reactivation:
    """Discover and review Candidates; dispatch remains Product-owned work."""

    def __init__(
        self,
        session: AsyncSession,
        actor: Actor,
        *,
        activation_approved: bool = False,
    ) -> None:
        self._session = session
        self._actor = actor
        self._activation_approved = activation_approved

    async def discover(
        self, listing_id: uuid.UUID, *, at: datetime | None = None
    ) -> tuple[ReactivationCandidateView, ...]:
        self._actor.require_administrator()
        await Entitlements(self._session).require(
            self._actor, Capability.REACTIVATION_CAMPAIGNS
        )
        moment = at or utc_now()
        listing = await CatalogProjection(
            self._session, self._actor
        ).get_authorized_listing(
            AuthorizedListingQuery(
                purpose=EligibilityPurpose.RECOMMEND,
                listing_id=listing_id,
                at=moment,
            )
        )
        need_ids = list(
            await self._session.scalars(
                select(Opportunity.property_need_id)
                .where(Opportunity.organization_id == self._actor.organization_id)
                .where(Opportunity.property_need_id.is_not(None))
                .where(
                    Opportunity.stage.not_in(
                        {OpportunityStage.WON.value, OpportunityStage.LOST.value}
                    )
                )
                .distinct()
            )
        )
        views: list[ReactivationCandidateView] = []
        for need_id in need_ids:
            if need_id is None:
                continue
            snapshot = await PropertyNeeds(self._session).snapshot(need_id)
            proposal = InventoryMatching.propose(snapshot, (_match_input(listing),))[0]
            if not proposal.eligible or proposal.kind is None:
                continue
            row = await self._session.scalar(
                select(ReactivationCandidate)
                .where(ReactivationCandidate.property_need_id == need_id)
                .where(ReactivationCandidate.listing_id == listing.listing_id)
                .where(ReactivationCandidate.rule_version == MATCH_RULE_VERSION)
            )
            if row is None:
                row = ReactivationCandidate(
                    organization_id=self._actor.organization_id,
                    property_need_id=need_id,
                    listing_id=listing.listing_id,
                    status=ReactivationCandidateStatus.PENDING.value,
                    match_kind=proposal.kind,
                    rule_version=proposal.rule_version,
                    explanation=[item.as_dict() for item in proposal.explanation],
                    created_at=moment,
                    updated_at=moment,
                )
                self._session.add(row)
                await self._session.flush()
                await self._audit(
                    "ProposeReactivationCandidate",
                    row,
                    {
                        "match_kind": proposal.kind,
                        "rule_version": proposal.rule_version,
                    },
                )
            views.append(self._view(row, listing.title))
        await self._session.flush()
        return tuple(views)

    async def authorize(
        self, command: AuthorizeReactivation, *, at: datetime | None = None
    ) -> ReactivationCandidate:
        self._actor.require_administrator()
        moment = at or utc_now()
        row = await self._locked(command.candidate_id)
        if row.status != ReactivationCandidateStatus.PENDING.value:
            raise InvalidTransition("Sólo un candidato pendiente puede autorizarse.")
        need = await self._session.get(PropertyNeed, row.property_need_id)
        if need is None:
            raise NotFound("No encontramos la necesidad del candidato.")
        snapshot = await PropertyNeeds(self._session).snapshot(need.id)
        listing = await CatalogProjection(
            self._session, self._actor
        ).get_authorized_listing(
            AuthorizedListingQuery(
                purpose=EligibilityPurpose.RECOMMEND,
                listing_id=row.listing_id,
                at=moment,
            )
        )
        proposal = InventoryMatching.propose(snapshot, (_match_input(listing),))[0]
        denial: str | None = None
        if not self._activation_approved:
            denial = "MarketingActivationNotApproved"
        if not proposal.eligible or proposal.kind is None:
            denial = "MatchNoLongerEligible"
        lead_id, conversation_id = await latest_route(
            self._session, contact_id=need.contact_id
        )
        if lead_id is None or conversation_id is None:
            denial = denial or "VerifiedWhatsAppRouteMissing"
        if lead_id is not None:
            consent = await MarketingConsent(self._session).current(
                lead_id=lead_id, scope=LISTING_MATCH_SCOPE, at=moment
            )
            if not consent.granted:
                denial = denial or consent.reason
        template = await TemplateRegistry(self._session).approved(
            organization_id=self._actor.organization_id,
            name=command.template_name,
            language=command.template_language,
            category=ConsentCategory.MARKETING,
            at=moment,
        )
        if template is None:
            denial = denial or "TemplateNotApproved"
        elif template.body_text.strip() != command.message_preview.strip():
            denial = denial or "TemplateContentMismatch"
        if await frequency_cap_reached(
            self._session,
            organization_id=self._actor.organization_id,
            contact_id=need.contact_id,
            at=moment,
            window_days=REACTIVATION_WINDOW_DAYS,
            cap=REACTIVATION_CAP,
        ):
            denial = denial or FREQUENCY_CAP_REACHED

        row.reviewed_by = self._actor.member_id
        row.reviewed_at = moment
        row.review_reason = denial or command.reason.strip()
        row.lead_id = lead_id
        row.conversation_id = conversation_id
        row.template_name = command.template_name
        row.template_language = command.template_language
        row.message_preview = (
            template.body_text if template is not None else command.message_preview
        )
        row.updated_at = moment
        row.status = (
            ReactivationCandidateStatus.DENIED.value
            if denial
            else ReactivationCandidateStatus.AUTHORIZED.value
        )
        await self._audit(
            "DenyReactivationCandidate" if denial else "AuthorizeReactivationCandidate",
            row,
            {"reason": row.review_reason, "rule_version": row.rule_version},
        )
        await self._session.flush()
        return row

    async def reject(
        self, command: RejectReactivation, *, at: datetime | None = None
    ) -> ReactivationCandidate:
        return await self._close(
            command.candidate_id,
            ReactivationCandidateStatus.REJECTED,
            command.reason,
            at,
        )

    async def revoke(
        self, command: RevokeReactivation, *, at: datetime | None = None
    ) -> ReactivationCandidate:
        return await self._close(
            command.candidate_id,
            ReactivationCandidateStatus.REVOKED,
            command.reason,
            at,
        )

    async def _close(
        self,
        candidate_id: uuid.UUID,
        target: ReactivationCandidateStatus,
        reason: str,
        at: datetime | None,
    ) -> ReactivationCandidate:
        self._actor.require_administrator()
        moment = at or utc_now()
        row = await self._locked(candidate_id)
        allowed = {
            ReactivationCandidateStatus.REJECTED: {
                ReactivationCandidateStatus.PENDING.value
            },
            ReactivationCandidateStatus.REVOKED: {
                ReactivationCandidateStatus.AUTHORIZED.value
            },
        }[target]
        if row.status not in allowed:
            raise InvalidTransition("Ese candidato ya no admite esa decisión.")
        row.status = target.value
        row.reviewed_by = self._actor.member_id
        row.reviewed_at = moment
        row.review_reason = reason.strip()
        row.updated_at = moment
        await self._audit(
            f"{target.value}ReactivationCandidate", row, {"reason": reason}
        )
        await self._session.flush()
        return row

    async def _locked(self, candidate_id: uuid.UUID) -> ReactivationCandidate:
        row = await self._session.scalar(
            select(ReactivationCandidate)
            .where(ReactivationCandidate.id == candidate_id)
            .with_for_update()
        )
        if row is None:
            raise NotFound("No encontramos ese candidato.")
        self._actor.require_same_organization(row.organization_id)
        return row

    def _view(
        self, row: ReactivationCandidate, title: str
    ) -> ReactivationCandidateView:
        return ReactivationCandidateView(
            candidate_id=row.id,
            property_need_id=row.property_need_id,
            listing_id=row.listing_id,
            listing_title=title,
            status=row.status,
            match_kind=row.match_kind,
            explanation=tuple(row.explanation),
            denial_reason=(row.review_reason if row.status == "Denied" else None),
        )

    async def _audit(
        self, action: str, row: ReactivationCandidate, details: dict[str, object]
    ) -> None:
        await record_audit(
            self._session,
            organization_id=self._actor.organization_id,
            actor_type=self._actor.actor_type,
            actor_id=self._actor.label,
            action=action,
            subject_type="ReactivationCandidate",
            subject_id=str(row.id),
            details=details,
            commit=False,
        )
