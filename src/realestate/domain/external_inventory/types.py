"""Stable Product-side vocabulary for external inventory sources."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


class IntendedAction(str, enum.Enum):
    RECOMMEND = "Recommend"
    SHARE = "Share"
    APPOINTMENT = "Appointment"


class MatchQuality(str, enum.Enum):
    EXACT = "Exact"
    APPROXIMATE = "Approximate"


SERVICE_AREA = frozenset({"Guadalajara", "Zapopan", "Tlaquepaque"})


@dataclass(frozen=True)
class InventorySearchCriteria:
    municipality: str
    at: datetime | None = None
    operation: str | None = None
    property_type: str | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    min_bedrooms: int | None = None
    limit: int = 20

    def __post_init__(self) -> None:
        if self.municipality not in SERVICE_AREA:
            raise ValueError(
                "La búsqueda debe limitarse a Guadalajara, Zapopan o Tlaquepaque."
            )
        if self.limit < 1 or self.limit > 50:
            raise ValueError("El límite debe estar entre 1 y 50.")


@dataclass(frozen=True)
class SourcePage:
    records: tuple[dict[str, Any], ...]
    next_cursor: str | None


@dataclass(frozen=True)
class CandidateOfferView:
    source_offer_key: str
    operation: str | None
    price_amount: Decimal | None
    price_currency: str | None
    price_unit: str | None
    availability: str
    terms: dict[str, Any]


@dataclass(frozen=True)
class ExternalCandidateView:
    listing_id: uuid.UUID
    source: str
    source_listing_id: str
    source_scope: str
    title: str | None
    municipality: str
    public_location: str | None
    location_precision: str
    property_type: str | None
    facts: dict[str, Any]
    availability: str
    attribution: str | None
    provenance: dict[str, Any]
    authority_state: str
    freshness_deadline: datetime
    match_quality: MatchQuality
    offers: tuple[CandidateOfferView, ...]


@dataclass(frozen=True)
class SyncResult:
    status: str
    fetched: int
    accepted: int
    rejected: int
    last_cursor: str | None
    error_code: str | None = None


@dataclass(frozen=True)
class RefreshResult:
    listing_id: uuid.UUID
    source_listing_id: str
    withdrawn: bool
    changed_fields: tuple[str, ...]
    checksum: str


@dataclass(frozen=True)
class RevalidationDecision:
    listing_id: uuid.UUID
    intended_action: IntendedAction
    outcome: str
    reasons: tuple[str, ...]
    evaluated_at: datetime
    snapshot_checksum: str


@dataclass(frozen=True)
class SourceHealthView:
    source: str
    status: str
    credential_configured: bool
    mls_access_confirmed: bool
    retention_permission_confirmed: bool
    last_started_at: datetime | None
    last_completed_at: datetime | None
    last_success_at: datetime | None
    last_cursor: str | None
    last_error_code: str | None
    last_error_detail: str | None
    fetched_count: int
    accepted_count: int
    rejected_count: int
    rate_limited_until: datetime | None


@dataclass(frozen=True)
class InventorySearchHit:
    listing_id: uuid.UUID
    source_kind: str
    source_name: str
    source_listing_id: str | None
    title: str | None
    municipality: str
    public_location: str | None
    match_quality: MatchQuality
    attribution: str
    provenance: dict[str, Any]
    offers: tuple[CandidateOfferView, ...]
    requires_use_time_revalidation: bool


@dataclass(frozen=True)
class AdministrationCandidateView:
    listing_id: uuid.UUID
    source_listing_id: str
    source_scope: str
    title: str | None
    municipality: str | None
    availability: str
    authority_state: str
    authority_evidence: str | None
    attribution: str | None
    collaboration_authorized: bool | None
    commission_known: bool
    commission: dict[str, Any] | None
    observed_at: datetime
    freshness_deadline: datetime
    mapping_issues: tuple[str, ...]
    changed_fields: tuple[str, ...]
    withdrawn_at: datetime | None
    deletion_due_at: datetime | None
    cache_deleted_at: datetime | None
    offers: tuple[CandidateOfferView, ...]
