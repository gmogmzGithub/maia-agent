"""Lossless EasyBroker payload mapping into non-authoritative candidates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from realestate.domain.text import strip_diacritics
from realestate.db.models import (
    ExternalCandidateState,
    ExternalInventoryScope,
    ListingAvailability,
    ListingOfferOperation,
    OfferAvailability,
)

SOURCE = "EasyBroker"
FRESHNESS_WINDOW = timedelta(minutes=30)
# The provider terms require cached withdrawn content to be removed within 24
# hours. A fifteen-minute margin lets the paced cleanup worker finish before the
# contractual maximum rather than merely becoming eligible exactly at it.
WITHDRAWAL_DELETION_WINDOW = timedelta(hours=23, minutes=45)


@dataclass(frozen=True)
class MappedOffer:
    source_offer_key: str
    operation: str | None
    price_amount: Decimal | None
    price_currency: str | None
    price_unit: str | None
    availability: str
    terms: dict[str, Any]
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class MappedCandidate:
    source_listing_id: str
    source_scope: str
    source_status: str | None
    source_updated_at: datetime | None
    observed_at: datetime
    freshness_deadline: datetime
    payload_checksum: str
    raw_payload: dict[str, Any]
    provenance: dict[str, Any]
    title: str | None
    description: str | None
    public_location: str | None
    municipality: str | None
    location_precision: str
    property_type: str | None
    facts: dict[str, Any]
    availability: str
    attribution: str | None
    source_agency: str | None
    source_agent: str | None
    source_url: str | None
    source_collaboration_authorized: bool | None
    source_commission: dict[str, Any] | None
    mapping_issues: tuple[str, ...]
    withdrawn: bool
    offers: tuple[MappedOffer, ...]

    @property
    def source_commission_known(self) -> bool:
        """Whether the source stated a commission this mapping could read.

        Derived rather than stored: it was only ever true when a commission
        survived ``_commission``, and a second field could disagree with it.
        """
        return self.source_commission is not None


def map_easybroker(
    payload: dict[str, Any],
    scope: ExternalInventoryScope,
    observed_at: datetime,
    *,
    summary: dict[str, Any] | None = None,
) -> MappedCandidate:
    raw = {"detail": payload, "summary": summary or {}}
    source_id = _text(payload.get("public_id")) or _text(payload.get("id"))
    if source_id is None and summary is not None:
        source_id = _text(summary.get("public_id")) or _text(summary.get("id"))
    if source_id is None:
        raise ValueError("EasyBroker record has no source identifier")

    issues: list[str] = []
    title = _text(payload.get("title"))
    if title is None:
        issues.append("missing_title")
    location = payload.get("location")
    public_location, municipality, precision = _location(location)
    if municipality is None:
        issues.append("missing_or_unknown_municipality")
    description = _text(payload.get("description"))
    source_status = _text(payload.get("status")) or _text(payload.get("listing_status"))
    availability = _availability(source_status)
    if availability == ListingAvailability.UNKNOWN.value:
        issues.append("unknown_availability")

    source_updated_at = _datetime(payload.get("updated_at"))
    if source_updated_at is None:
        issues.append("missing_or_invalid_updated_at")
    agency = _party_name(payload.get("agency"))
    agent = _party_name(payload.get("agent"))
    attribution = " · ".join(part for part in (agency, agent) if part) or None
    if attribution is None:
        issues.append("missing_attribution")

    operations = payload.get("operations")
    offers: list[MappedOffer] = []
    if isinstance(operations, list):
        for position, operation_payload in enumerate(operations):
            if not isinstance(operation_payload, dict):
                issues.append(f"operation_{position}_invalid")
                continue
            offers.append(_offer(operation_payload, position, issues))
    else:
        issues.append("missing_operations")

    facts = _facts(payload)
    commission_value = payload.get("shared_commission_percentage")
    if commission_value is None:
        commission_value = payload.get("share_commission")
    commission = _commission(commission_value)
    collaboration = payload.get("collaboration_authorized")
    source_collaboration_authorized = (
        collaboration if isinstance(collaboration, bool) else None
    )
    status_key = _key(source_status)
    withdrawn = status_key in {"deleted", "unpublished", "withdrawn", "cancelled"}

    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)
    checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return MappedCandidate(
        source_listing_id=source_id,
        source_scope=scope.value,
        source_status=source_status,
        source_updated_at=source_updated_at,
        observed_at=observed_at,
        freshness_deadline=observed_at + FRESHNESS_WINDOW,
        payload_checksum=checksum,
        raw_payload=raw,
        provenance={
            "source": SOURCE,
            "source_listing_id": source_id,
            "scope": scope.value,
            "observed_at": observed_at.isoformat(),
            "source_updated_at": (
                source_updated_at.isoformat() if source_updated_at else None
            ),
        },
        title=title,
        description=description,
        public_location=public_location,
        municipality=municipality,
        location_precision=precision,
        property_type=_text(payload.get("property_type")),
        facts=facts,
        availability=availability,
        attribution=attribution,
        source_agency=agency,
        source_agent=agent,
        source_url=_text(payload.get("url")),
        source_collaboration_authorized=source_collaboration_authorized,
        source_commission=commission,
        mapping_issues=tuple(dict.fromkeys(issues)),
        withdrawn=withdrawn,
        offers=tuple(offers),
    )


def initial_authority(mapped: MappedCandidate) -> str:
    if mapped.withdrawn or mapped.municipality is None:
        return ExternalCandidateState.DENIED.value
    return ExternalCandidateState.PENDING.value


def _offer(
    raw: dict[str, Any], position: int, issues: list[str]
) -> MappedOffer:
    raw_operation = _text(raw.get("type")) or _text(raw.get("operation_type"))
    operation = {
        "sale": ListingOfferOperation.SALE.value,
        "rental": ListingOfferOperation.RENTAL.value,
        "rent": ListingOfferOperation.RENTAL.value,
        "temporary_rental": ListingOfferOperation.RENTAL.value,
        "presale": ListingOfferOperation.PRESALE.value,
    }.get(_key(raw_operation))
    if operation is None:
        issues.append(f"operation_{position}_unknown_type")
    amount = _decimal(raw.get("amount"))
    if amount is None:
        issues.append(f"operation_{position}_missing_or_invalid_price")
    currency = _text(raw.get("currency"))
    if currency is None:
        issues.append(f"operation_{position}_missing_currency")
    source_key = _text(raw.get("id")) or raw_operation or f"position-{position}"
    return MappedOffer(
        source_offer_key=source_key,
        operation=operation,
        price_amount=amount,
        price_currency=currency,
        price_unit=_text(raw.get("unit")),
        availability=(
            OfferAvailability.AVAILABLE.value
            if operation is not None and amount is not None
            else OfferAvailability.UNKNOWN.value
        ),
        terms={
            key: value
            for key, value in raw.items()
            if key not in {"id", "type", "operation_type", "amount", "currency", "unit"}
        },
        raw_payload=raw,
    )


def _facts(payload: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "bedrooms",
        "bathrooms",
        "half_bathrooms",
        "parking_spaces",
        "construction_size",
        "lot_size",
        "floors",
        "age",
        "property_features",
    )
    return {field: payload[field] for field in fields if payload.get(field) is not None}


def _location(value: object) -> tuple[str | None, str | None, str]:
    if not isinstance(value, dict):
        return (_text(value), None, "Unknown")
    city_value = value.get("municipality") or value.get("city")
    if isinstance(city_value, dict):
        city_value = city_value.get("name")
    municipality = _canonical_municipality(_text(city_value))
    public = _text(value.get("name")) or _text(value.get("full_name"))
    if public is None:
        parts = [
            _text(value.get(name))
            for name in ("neighborhood", "municipality", "city", "state")
        ]
        public = ", ".join(part for part in parts if part) or None
    exact = any(value.get(key) not in (None, "") for key in ("street", "latitude", "longitude"))
    precision = "Exact" if exact else "Approximate" if public else "Unknown"
    return public, municipality, precision


def _canonical_municipality(value: str | None) -> str | None:
    normalized = _key(value)
    return {
        "guadalajara": "Guadalajara",
        "zapopan": "Zapopan",
        "san pedro tlaquepaque": "Tlaquepaque",
        "tlaquepaque": "Tlaquepaque",
    }.get(normalized)


def _availability(value: str | None) -> str:
    return {
        "active": ListingAvailability.AVAILABLE.value,
        "available": ListingAvailability.AVAILABLE.value,
        "reserved": ListingAvailability.RESERVED.value,
        "sold": ListingAvailability.SOLD.value,
        "rented": ListingAvailability.RENTED.value,
        "temporarily unavailable": ListingAvailability.TEMPORARILY_UNAVAILABLE.value,
    }.get(_key(value), ListingAvailability.UNKNOWN.value)


def _commission(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return {"source_value": value}
    return None


def _party_name(value: object) -> str | None:
    if isinstance(value, dict):
        return _text(value.get("name"))
    return _text(value)


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() and result > 0 else None


def _datetime(value: object) -> datetime | None:
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _key(value: str | None) -> str:
    """Fold a source label for comparison, treating ``_`` and ``-`` as spaces.

    The accent and case folds come from :mod:`realestate.domain.text` so a
    character taught there is understood here too; only the separator rule is
    specific to the provider's slug-shaped labels.
    """
    if value is None:
        return ""
    folded = strip_diacritics(value).casefold().replace("_", " ").replace("-", " ")
    return " ".join(folded.split())
