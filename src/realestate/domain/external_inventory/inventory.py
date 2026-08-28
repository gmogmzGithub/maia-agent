"""Deep Product module for indexing and searching external Listing candidates."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    ExternalCandidateState,
    ExternalInventoryScope,
    ExternalListingCandidate,
    ExternalOfferCandidate,
    FactsReviewState,
    InventorySourceHealthRecord,
    InventorySourceStatus,
    ListingAvailability,
)
from realestate.domain.audit import record_audit
from realestate.domain.commercial.actors import Actor, NotFound
from realestate.domain.external_inventory.mapping import (
    SOURCE,
    WITHDRAWAL_DELETION_WINDOW,
    MappedCandidate,
    initial_authority,
    map_easybroker,
)
from realestate.domain.external_inventory.ports import (
    InventorySource,
    InventorySourceError,
    SourceAccessDenied,
    SourceNotFound,
)
from realestate.domain.external_inventory.types import (
    AdministrationCandidateView,
    CandidateOfferView,
    ExternalCandidateView,
    InventorySearchCriteria,
    MatchQuality,
    RefreshResult,
    SERVICE_AREA,
    SyncResult,
)
from realestate.domain.clock import utc_now


class ExternalInventory:
    """Stable interface hiding source pagination, mapping and persistence."""

    def __init__(
        self,
        session: AsyncSession,
        actor: Actor,
        source: InventorySource,
    ) -> None:
        self._session = session
        self._actor = actor
        self._source = source

    async def search(
        self, criteria: InventorySearchCriteria
    ) -> tuple[ExternalCandidateView, ...]:
        """Search the local authorized index; never call a provider in a read path."""
        rows = list(
            await self._session.scalars(
                select(ExternalListingCandidate)
                .where(
                    ExternalListingCandidate.organization_id
                    == self._actor.organization_id,
                    ExternalListingCandidate.source == self._source.source_name,
                    ExternalListingCandidate.municipality == criteria.municipality,
                    ExternalListingCandidate.authority_state
                    == ExternalCandidateState.AUTHORIZED.value,
                    ExternalListingCandidate.commercial_review_state
                    == FactsReviewState.APPROVED.value,
                    ExternalListingCandidate.availability
                    == ListingAvailability.AVAILABLE.value,
                    ExternalListingCandidate.withdrawn_at.is_(None),
                    ExternalListingCandidate.cache_deleted_at.is_(None),
                    ExternalListingCandidate.freshness_deadline
                    > (criteria.at or utc_now()),
                )
                .order_by(
                    ExternalListingCandidate.title.nullslast(),
                    ExternalListingCandidate.source_listing_id,
                )
            )
        )
        results: list[ExternalCandidateView] = []
        for row in rows:
            offers = list(
                await self._session.scalars(
                    select(ExternalOfferCandidate)
                    .where(ExternalOfferCandidate.listing_candidate_id == row.id)
                    .order_by(ExternalOfferCandidate.source_offer_key)
                )
            )
            quality = _matches(row, offers, criteria)
            if quality is None:
                continue
            results.append(_view(row, offers, quality))
            if len(results) >= criteria.limit:
                break
        return tuple(results)

    async def list_for_administration(
        self,
    ) -> tuple[AdministrationCandidateView, ...]:
        self._actor.require_administrator()
        rows = list(
            await self._session.scalars(
                select(ExternalListingCandidate)
                .where(
                    ExternalListingCandidate.organization_id
                    == self._actor.organization_id,
                    ExternalListingCandidate.source == self._source.source_name,
                )
                .order_by(
                    ExternalListingCandidate.updated_at.desc(),
                    ExternalListingCandidate.source_listing_id,
                )
            )
        )
        views: list[AdministrationCandidateView] = []
        for row in rows:
            offers = list(
                await self._session.scalars(
                    select(ExternalOfferCandidate)
                    .where(ExternalOfferCandidate.listing_candidate_id == row.id)
                    .order_by(ExternalOfferCandidate.source_offer_key)
                )
            )
            views.append(
                AdministrationCandidateView(
                    listing_id=row.id,
                    source_listing_id=row.source_listing_id,
                    source_scope=row.source_scope,
                    title=row.title,
                    municipality=row.municipality,
                    availability=row.availability,
                    authority_state=row.authority_state,
                    authority_evidence=row.authority_evidence,
                    attribution=row.attribution,
                    collaboration_authorized=row.collaboration_authorized,
                    commission_known=row.commission_known,
                    commission=row.commission,
                    observed_at=row.observed_at,
                    freshness_deadline=row.freshness_deadline,
                    mapping_issues=tuple(row.mapping_issues),
                    changed_fields=tuple(row.changed_fields),
                    withdrawn_at=row.withdrawn_at,
                    deletion_due_at=row.deletion_due_at,
                    cache_deleted_at=row.cache_deleted_at,
                    offers=tuple(
                        CandidateOfferView(
                            source_offer_key=offer.source_offer_key,
                            operation=offer.operation,
                            price_amount=offer.price_amount,
                            price_currency=offer.price_currency,
                            price_unit=offer.price_unit,
                            availability=offer.availability,
                            terms=offer.terms,
                        )
                        for offer in offers
                    ),
                )
            )
        return tuple(views)

    async def synchronize(
        self,
        scope: ExternalInventoryScope = ExternalInventoryScope.COLLABORATOR,
        *,
        at: datetime,
        page_limit: int = 50,
        max_pages: int = 100,
    ) -> SyncResult:
        self._actor.require_administrator()
        health = await self._health(lock=True)
        health.credential_configured = self._source.credential_configured
        health.mls_access_confirmed = self._source.mls_access_confirmed
        health.retention_permission_confirmed = (
            self._source.retention_permission_confirmed
        )
        health.last_started_at = at
        health.last_completed_at = None
        health.last_error_code = None
        health.last_error_detail = None
        health.rate_limited_until = None
        if not self._source.retention_permission_confirmed:
            health.status = InventorySourceStatus.DISABLED.value
            health.last_completed_at = at
            health.last_error_code = "retention_not_confirmed"
            health.last_error_detail = (
                "External payload retention is disabled until its permission "
                "and deletion obligations are confirmed."
            )
            await record_audit(
                self._session,
                actor_type=self._actor.actor_type,
                actor_id=self._actor.label,
                action="ExternalInventorySynchronizationDenied",
                subject_type="InventorySource",
                subject_id=self._source.source_name,
                details={"scope": scope.value, "reason": health.last_error_code},
                commit=False,
            )
            await self._session.commit()
            return SyncResult(
                status=health.status,
                fetched=0,
                accepted=0,
                rejected=0,
                last_cursor=None,
                error_code=health.last_error_code,
            )
        await self._session.commit()

        fetched = accepted = rejected = 0
        cursor: str | None = None
        seen_cursors: set[str] = set()
        error: InventorySourceError | None = None
        partial = False
        for _ in range(max_pages):
            if cursor is not None:
                if cursor in seen_cursors:
                    error = InventorySourceError(
                        "cursor_loop", "EasyBroker repeated a pagination cursor."
                    )
                    partial = fetched > 0
                    break
                seen_cursors.add(cursor)
            try:
                page = await self._source.list_page(
                    scope, cursor=cursor, limit=min(max(page_limit, 1), 50)
                )
            except InventorySourceError as exc:
                error = exc
                partial = fetched > 0
                break
            for summary in page.records:
                source_id = _source_id(summary)
                fetched += 1
                if source_id is None:
                    rejected += 1
                    partial = True
                    continue
                try:
                    detail = await self._source.retrieve(scope, source_id)
                    mapped = map_easybroker(detail, scope, at, summary=summary)
                except (InventorySourceError, ValueError):
                    rejected += 1
                    partial = True
                    continue
                await self._store(mapped)
                if mapped.municipality in SERVICE_AREA and not mapped.withdrawn:
                    accepted += 1
                else:
                    rejected += 1
            await self._session.commit()
            cursor = page.next_cursor
            if cursor is None:
                break
        else:
            error = InventorySourceError(
                "page_limit", "The source exceeded the configured page safety limit."
            )
            partial = fetched > 0

        status = InventorySourceStatus.HEALTHY.value
        if error is not None and error.code == "rate_limited":
            status = InventorySourceStatus.RATE_LIMITED.value
        elif error is not None or partial:
            status = (
                InventorySourceStatus.PARTIAL.value
                if fetched > 0
                else InventorySourceStatus.FAILED.value
            )
        health = await self._health(lock=True)
        health.status = status
        health.last_completed_at = at
        health.last_success_at = at if status == InventorySourceStatus.HEALTHY.value else health.last_success_at
        health.last_cursor = cursor
        health.last_error_code = error.code if error else ("partial_records" if partial else None)
        health.last_error_detail = error.detail if error else (
            "Some source records could not be mapped or refreshed." if partial else None
        )
        health.fetched_count = fetched
        health.accepted_count = accepted
        health.rejected_count = rejected
        if error is not None and error.retry_after_seconds is not None:
            health.rate_limited_until = at + timedelta(seconds=error.retry_after_seconds)
        await record_audit(
            self._session,
            actor_type=self._actor.actor_type,
            actor_id=self._actor.label,
            action="ExternalInventorySynchronized",
            subject_type="InventorySource",
            subject_id=self._source.source_name,
            details={
                "scope": scope.value,
                "status": status,
                "fetched": fetched,
                "accepted": accepted,
                "rejected": rejected,
                "error_code": health.last_error_code,
            },
            commit=False,
        )
        await self._session.commit()
        return SyncResult(
            status=status,
            fetched=fetched,
            accepted=accepted,
            rejected=rejected,
            last_cursor=cursor,
            error_code=health.last_error_code,
        )

    async def refresh(
        self, source_listing_id: str, *, at: datetime
    ) -> RefreshResult:
        """Refresh under a row lock so a use-time decision cannot race a sync."""
        row = await self.refresh_for_use(source_listing_id, at=at)
        await record_audit(
            self._session,
            actor_type=self._actor.actor_type,
            actor_id=self._actor.label,
            action="ExternalListingRefreshed",
            subject_type="ExternalListingCandidate",
            subject_id=str(row.id),
            details={
                "source": row.source,
                "source_listing_id": row.source_listing_id,
                "changed_fields": row.changed_fields,
                "withdrawn": row.withdrawn_at is not None,
            },
            commit=False,
        )
        await self._session.commit()
        return RefreshResult(
            listing_id=row.id,
            source_listing_id=row.source_listing_id,
            withdrawn=row.withdrawn_at is not None,
            changed_fields=tuple(row.changed_fields),
            checksum=row.payload_checksum,
        )

    async def refresh_for_use(
        self, source_listing_id: str, *, at: datetime
    ) -> ExternalListingCandidate:
        """Refresh without committing; a caller may decide under the same lock."""
        if not self._source.retention_permission_confirmed:
            raise SourceAccessDenied("retention_not_confirmed")
        row = await self._candidate(source_listing_id, lock=True)
        scope = ExternalInventoryScope(row.source_scope)
        try:
            detail = await self._source.retrieve(scope, source_listing_id)
        except SourceNotFound:
            await self._withdraw(row, at, reason="source_not_found")
            return row
        return await self._store(map_easybroker(detail, scope, at), existing=row)

    async def confirm_evidence(
        self,
        listing_id: uuid.UUID,
        *,
        authority_evidence: str,
        attribution: str,
        collaboration_authorized: bool,
        commission: dict[str, Any] | None,
        availability: str,
        at: datetime,
    ) -> ExternalCandidateView:
        """Record human evidence; source presence alone never grants authority."""
        self._actor.require_administrator()
        row = await self._session.scalar(
            select(ExternalListingCandidate)
            .where(
                ExternalListingCandidate.id == listing_id,
                ExternalListingCandidate.organization_id
                == self._actor.organization_id,
            )
            .with_for_update()
        )
        if row is None:
            raise NotFound()
        evidence = authority_evidence.strip()
        named_attribution = attribution.strip()
        row.authority_evidence = evidence or None
        row.attribution = named_attribution or row.attribution
        row.collaboration_authorized = collaboration_authorized
        row.commission = commission
        row.commission_known = commission is not None
        row.availability = availability
        material_complete = bool(
            evidence
            and row.attribution
            and row.title
            and row.municipality in SERVICE_AREA
            and row.availability == ListingAvailability.AVAILABLE.value
            and row.withdrawn_at is None
            and (
                row.source_scope == ExternalInventoryScope.ORGANIZATION.value
                or (collaboration_authorized and commission is not None)
            )
        )
        row.authority_state = (
            ExternalCandidateState.AUTHORIZED.value
            if material_complete
            else ExternalCandidateState.PENDING.value
        )
        row.commercial_review_state = (
            FactsReviewState.APPROVED.value
            if material_complete
            else FactsReviewState.NEEDS_REVIEW.value
        )
        row.changed_fields = []
        row.updated_at = at
        await record_audit(
            self._session,
            actor_type=self._actor.actor_type,
            actor_id=self._actor.label,
            action="ExternalListingEvidenceConfirmed",
            subject_type="ExternalListingCandidate",
            subject_id=str(row.id),
            details={
                "source": row.source,
                "source_listing_id": row.source_listing_id,
                "authority_state": row.authority_state,
                "collaboration_authorized": collaboration_authorized,
                "commission_known": row.commission_known,
                "availability": row.availability,
            },
            commit=False,
        )
        await self._session.commit()
        offers = list(
            await self._session.scalars(
                select(ExternalOfferCandidate).where(
                    ExternalOfferCandidate.listing_candidate_id == row.id
                )
            )
        )
        return _view(row, offers, MatchQuality.EXACT)

    async def purge_due(self, *, at: datetime) -> int:
        """Remove cached provider content while retaining minimal audit identity."""
        rows = list(
            await self._session.scalars(
                select(ExternalListingCandidate)
                .where(
                    ExternalListingCandidate.organization_id
                    == self._actor.organization_id,
                    ExternalListingCandidate.deletion_due_at <= at,
                    ExternalListingCandidate.cache_deleted_at.is_(None),
                )
                .with_for_update()
            )
        )
        for row in rows:
            await self._session.execute(
                delete(ExternalOfferCandidate).where(
                    ExternalOfferCandidate.listing_candidate_id == row.id
                )
            )
            row.raw_payload = {}
            row.description = None
            row.public_location = None
            row.facts = {}
            row.source_agency = None
            row.source_agent = None
            row.source_url = None
            row.commission = None
            row.cache_deleted_at = at
            row.provenance = {
                "source": row.source,
                "source_listing_id": row.source_listing_id,
                "scope": row.source_scope,
                "withdrawn_at": row.withdrawn_at.isoformat() if row.withdrawn_at else None,
                "cache_deleted_at": at.isoformat(),
            }
            await record_audit(
                self._session,
                actor_type=self._actor.actor_type,
                actor_id=self._actor.label,
                action="ExternalListingCacheDeleted",
                subject_type="ExternalListingCandidate",
                subject_id=str(row.id),
                details={
                    "source": row.source,
                    "source_listing_id": row.source_listing_id,
                },
                commit=False,
            )
        await self._session.commit()
        return len(rows)

    async def _health(self, *, lock: bool) -> InventorySourceHealthRecord:
        statement = select(InventorySourceHealthRecord).where(
            InventorySourceHealthRecord.organization_id == self._actor.organization_id,
            InventorySourceHealthRecord.source == self._source.source_name,
        )
        if lock:
            statement = statement.with_for_update()
        row = await self._session.scalar(statement)
        if row is None:
            row = InventorySourceHealthRecord(
                organization_id=self._actor.organization_id,
                source=self._source.source_name,
                status=(
                    InventorySourceStatus.NEVER_SYNCED.value
                    if self._source.credential_configured
                    else InventorySourceStatus.DISABLED.value
                ),
                credential_configured=self._source.credential_configured,
                mls_access_confirmed=self._source.mls_access_confirmed,
                retention_permission_confirmed=(
                    self._source.retention_permission_confirmed
                ),
            )
            self._session.add(row)
            await self._session.flush()
        return row

    async def _candidate(
        self, source_listing_id: str, *, lock: bool
    ) -> ExternalListingCandidate:
        statement = select(ExternalListingCandidate).where(
            ExternalListingCandidate.organization_id == self._actor.organization_id,
            ExternalListingCandidate.source == self._source.source_name,
            ExternalListingCandidate.source_listing_id == source_listing_id,
        )
        if lock:
            statement = statement.with_for_update()
        row = await self._session.scalar(statement)
        if row is None:
            raise NotFound("No encontramos ese candidato de inventario externo.")
        return row

    async def _store(
        self,
        mapped: MappedCandidate,
        *,
        existing: ExternalListingCandidate | None = None,
    ) -> ExternalListingCandidate:
        row = existing
        if row is None:
            row = await self._session.scalar(
                select(ExternalListingCandidate)
                .where(
                    ExternalListingCandidate.organization_id
                    == self._actor.organization_id,
                    ExternalListingCandidate.source == SOURCE,
                    ExternalListingCandidate.source_listing_id
                    == mapped.source_listing_id,
                )
                .with_for_update()
            )
        old_offer_signature: tuple[tuple[object, ...], ...] = ()
        old_values: dict[str, object] = {}
        if row is not None:
            old_values = _candidate_signature(row)
            old_offers = list(
                await self._session.scalars(
                    select(ExternalOfferCandidate).where(
                        ExternalOfferCandidate.listing_candidate_id == row.id
                    )
                )
            )
            old_offer_signature = _offer_signature(old_offers)
        else:
            row = ExternalListingCandidate(
                organization_id=self._actor.organization_id,
                source=SOURCE,
                source_listing_id=mapped.source_listing_id,
                source_scope=mapped.source_scope,
                source_status=mapped.source_status,
                source_updated_at=mapped.source_updated_at,
                observed_at=mapped.observed_at,
                freshness_deadline=mapped.freshness_deadline,
                payload_checksum=mapped.payload_checksum,
                raw_payload=mapped.raw_payload,
                provenance=mapped.provenance,
                title=mapped.title,
                description=mapped.description,
                public_location=mapped.public_location,
                municipality=mapped.municipality,
                location_precision=mapped.location_precision,
                property_type=mapped.property_type,
                facts=mapped.facts,
                availability=mapped.availability,
                attribution=mapped.attribution,
                source_agency=mapped.source_agency,
                source_agent=mapped.source_agent,
                source_url=mapped.source_url,
                authority_state=initial_authority(mapped),
                collaboration_authorized=mapped.source_collaboration_authorized,
                commission_known=mapped.source_commission_known,
                commission=mapped.source_commission,
                commercial_review_state=FactsReviewState.PENDING.value,
                mapping_issues=list(mapped.mapping_issues),
                changed_fields=[],
            )
            self._session.add(row)
            await self._session.flush()

        row.source_scope = mapped.source_scope
        row.source_status = mapped.source_status
        row.source_updated_at = mapped.source_updated_at
        row.observed_at = mapped.observed_at
        row.freshness_deadline = mapped.freshness_deadline
        row.payload_checksum = mapped.payload_checksum
        row.raw_payload = mapped.raw_payload
        row.provenance = mapped.provenance
        row.title = mapped.title
        row.description = mapped.description
        row.public_location = mapped.public_location
        row.municipality = mapped.municipality
        row.location_precision = mapped.location_precision
        row.property_type = mapped.property_type
        row.facts = mapped.facts
        row.availability = mapped.availability
        row.source_agency = mapped.source_agency
        row.source_agent = mapped.source_agent
        row.source_url = mapped.source_url
        row.mapping_issues = list(mapped.mapping_issues)
        if mapped.attribution is not None:
            row.attribution = mapped.attribution
        if mapped.source_collaboration_authorized is not None:
            row.collaboration_authorized = mapped.source_collaboration_authorized
        if mapped.source_commission_known:
            row.commission_known = True
            row.commission = mapped.source_commission

        await self._session.execute(
            delete(ExternalOfferCandidate).where(
                ExternalOfferCandidate.listing_candidate_id == row.id
            )
        )
        await self._session.flush()
        for offer in mapped.offers:
            self._session.add(
                ExternalOfferCandidate(
                    organization_id=self._actor.organization_id,
                    listing_candidate_id=row.id,
                    source_offer_key=offer.source_offer_key,
                    operation=offer.operation,
                    price_amount=offer.price_amount,
                    price_currency=offer.price_currency,
                    price_unit=offer.price_unit,
                    availability=offer.availability,
                    terms=offer.terms,
                    raw_payload=offer.raw_payload,
                )
            )
        new_offer_signature = tuple(
            (
                offer.source_offer_key,
                offer.operation,
                offer.price_amount,
                offer.price_currency,
                offer.price_unit,
                offer.availability,
            )
            for offer in mapped.offers
        )
        changed = _changed_fields(old_values, row)
        if old_values and old_offer_signature != new_offer_signature:
            changed.append("offers")
        row.changed_fields = changed
        if mapped.withdrawn:
            await self._withdraw(row, mapped.observed_at, reason="source_withdrawn")
        elif mapped.municipality not in SERVICE_AREA:
            row.authority_state = ExternalCandidateState.DENIED.value
        elif mapped.source_collaboration_authorized is False:
            row.authority_state = ExternalCandidateState.DENIED.value
        elif "offers" in changed:
            row.authority_state = ExternalCandidateState.PENDING.value
            row.commercial_review_state = FactsReviewState.NEEDS_REVIEW.value
        row.updated_at = mapped.observed_at
        await self._session.flush()
        return row

    async def _withdraw(
        self, row: ExternalListingCandidate, at: datetime, *, reason: str
    ) -> None:
        row.withdrawn_at = row.withdrawn_at or at
        row.deletion_due_at = row.deletion_due_at or (at + WITHDRAWAL_DELETION_WINDOW)
        row.authority_state = ExternalCandidateState.DENIED.value
        row.availability = ListingAvailability.UNKNOWN.value
        row.commercial_review_state = FactsReviewState.NEEDS_REVIEW.value
        row.changed_fields = list(dict.fromkeys([*row.changed_fields, "withdrawn"]))
        row.mapping_issues = list(dict.fromkeys([*row.mapping_issues, reason]))
        await record_audit(
            self._session,
            actor_type=self._actor.actor_type,
            actor_id=self._actor.label,
            action="ExternalListingWithdrawn",
            subject_type="ExternalListingCandidate",
            subject_id=str(row.id),
            details={
                "source": row.source,
                "source_listing_id": row.source_listing_id,
                "deletion_due_at": row.deletion_due_at.isoformat(),
                "reason": reason,
            },
            commit=False,
        )


def _source_id(payload: dict[str, Any]) -> str | None:
    for field in ("public_id", "id"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _candidate_signature(row: ExternalListingCandidate) -> dict[str, object]:
    return {
        "title": row.title,
        "location": (row.public_location, row.municipality, row.location_precision),
        "facts": row.facts,
        "availability": row.availability,
        "attribution": row.attribution,
        "source_status": row.source_status,
    }


def _changed_fields(
    previous: dict[str, object], row: ExternalListingCandidate
) -> list[str]:
    if not previous:
        return []
    current = _candidate_signature(row)
    return [name for name, value in current.items() if previous.get(name) != value]


def _offer_signature(
    offers: list[ExternalOfferCandidate],
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        sorted(
            (
                row.source_offer_key,
                row.operation,
                row.price_amount,
                row.price_currency,
                row.price_unit,
                row.availability,
            )
            for row in offers
        )
    )


def _matches(
    row: ExternalListingCandidate,
    offers: list[ExternalOfferCandidate],
    criteria: InventorySearchCriteria,
) -> MatchQuality | None:
    approximate = False
    if criteria.property_type:
        if row.property_type is None:
            approximate = True
        elif row.property_type.casefold() != criteria.property_type.casefold():
            return None
    relevant = offers
    if criteria.operation:
        known = [offer for offer in offers if offer.operation is not None]
        matches = [offer for offer in known if offer.operation == criteria.operation]
        if matches:
            relevant = matches
        elif any(offer.operation is None for offer in offers):
            approximate = True
            relevant = [offer for offer in offers if offer.operation is None]
        else:
            return None
    if criteria.min_price is not None or criteria.max_price is not None:
        known_prices = [offer.price_amount for offer in relevant if offer.price_amount is not None]
        if not known_prices:
            approximate = True
        elif not any(_price_in_range(price, criteria) for price in known_prices):
            return None
    if criteria.min_bedrooms is not None:
        bedrooms = row.facts.get("bedrooms")
        if not isinstance(bedrooms, (int, float)) or isinstance(bedrooms, bool):
            approximate = True
        elif bedrooms < criteria.min_bedrooms:
            return None
    return MatchQuality.APPROXIMATE if approximate else MatchQuality.EXACT


def _price_in_range(price: Decimal, criteria: InventorySearchCriteria) -> bool:
    if criteria.min_price is not None and price < criteria.min_price:
        return False
    return criteria.max_price is None or price <= criteria.max_price


def _view(
    row: ExternalListingCandidate,
    offers: list[ExternalOfferCandidate],
    quality: MatchQuality,
) -> ExternalCandidateView:
    assert row.municipality is not None
    return ExternalCandidateView(
        listing_id=row.id,
        source=row.source,
        source_listing_id=row.source_listing_id,
        source_scope=row.source_scope,
        title=row.title,
        municipality=row.municipality,
        public_location=row.public_location,
        location_precision=row.location_precision,
        property_type=row.property_type,
        facts=row.facts,
        availability=row.availability,
        attribution=row.attribution,
        provenance=row.provenance,
        authority_state=row.authority_state,
        freshness_deadline=row.freshness_deadline,
        match_quality=quality,
        offers=tuple(
            CandidateOfferView(
                source_offer_key=offer.source_offer_key,
                operation=offer.operation,
                price_amount=offer.price_amount,
                price_currency=offer.price_currency,
                price_unit=offer.price_unit,
                availability=offer.availability,
                terms=offer.terms,
            )
            for offer in offers
        ),
    )
