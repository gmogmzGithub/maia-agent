"""Pure mapping rules: preserve source facts and invent nothing."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from realestate.db.models import ExternalInventoryScope
from realestate.domain.external_inventory.mapping import map_easybroker
from tests.fixtures.external_inventory import easybroker_property

NOW = datetime(2026, 8, 28, 18, 0, tzinfo=UTC)


def test_maps_listing_offer_identity_timestamps_and_provenance() -> None:
    mapped = map_easybroker(
        easybroker_property(), ExternalInventoryScope.COLLABORATOR, NOW
    )

    assert mapped.source_listing_id == "EB-FAKE-001"
    assert mapped.source_scope == "Collaborator"
    assert mapped.municipality == "Zapopan"
    assert mapped.location_precision == "Approximate"
    assert mapped.provenance["source_listing_id"] == "EB-FAKE-001"
    assert mapped.source_updated_at == datetime(2026, 8, 28, 16, 30, tzinfo=UTC)
    assert mapped.facts["bedrooms"] == 3
    assert mapped.offers[0].operation == "Sale"
    assert mapped.offers[0].price_amount == Decimal("5750000")
    assert mapped.offers[0].price_currency == "MXN"
    assert mapped.source_commission_known


def test_missing_null_and_unknown_values_stay_unknown() -> None:
    payload = {
        "public_id": "EB-MISSING",
        "title": None,
        "status": "published",
        "updated_at": None,
        "location": {"name": "Zona no confirmada"},
        "operations": [
            {"type": "something-new", "amount": None, "currency": None}
        ],
    }

    mapped = map_easybroker(payload, ExternalInventoryScope.COLLABORATOR, NOW)

    assert mapped.title is None
    assert mapped.municipality is None
    assert mapped.availability == "Unknown"
    assert mapped.source_updated_at is None
    assert mapped.attribution is None
    assert mapped.offers[0].operation is None
    assert mapped.offers[0].price_amount is None
    assert mapped.offers[0].price_currency is None
    assert {
        "missing_title",
        "missing_or_unknown_municipality",
        "unknown_availability",
        "missing_or_invalid_updated_at",
        "missing_attribution",
        "operation_0_unknown_type",
        "operation_0_missing_or_invalid_price",
        "operation_0_missing_currency",
    } <= set(mapped.mapping_issues)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Guadalajara", "Guadalajara"),
        ("Zapopan", "Zapopan"),
        ("San Pedro Tlaquepaque", "Tlaquepaque"),
        ("Tlaquepaque", "Tlaquepaque"),
        ("Tlajomulco de Zúñiga", None),
        ("Zona Metropolitana de Guadalajara", None),
    ],
)
def test_service_area_mapping_is_strict(value: str, expected: str | None) -> None:
    payload = easybroker_property(municipality=value)

    assert (
        map_easybroker(payload, ExternalInventoryScope.COLLABORATOR, NOW).municipality
        == expected
    )


def test_a_source_record_without_an_identifier_is_rejected() -> None:
    payload = easybroker_property()
    del payload["public_id"]

    with pytest.raises(ValueError, match="source identifier"):
        map_easybroker(payload, ExternalInventoryScope.COLLABORATOR, NOW)


def test_summary_identity_and_legacy_commission_are_preserved() -> None:
    payload = easybroker_property()
    del payload["public_id"]
    payload.pop("shared_commission_percentage")
    payload["share_commission"] = {"kind": "percentage", "value": "2.5"}

    mapped = map_easybroker(
        payload,
        ExternalInventoryScope.ORGANIZATION,
        NOW,
        summary={"id": "EB-SUMMARY"},
    )

    assert mapped.source_listing_id == "EB-SUMMARY"
    assert mapped.source_commission == {"kind": "percentage", "value": "2.5"}


def test_non_list_operations_and_scalar_location_stay_unknown() -> None:
    payload = easybroker_property()
    payload["operations"] = None
    payload["location"] = "Ubicación sin municipio confirmado"

    mapped = map_easybroker(payload, ExternalInventoryScope.COLLABORATOR, NOW)

    assert mapped.offers == ()
    assert mapped.public_location == "Ubicación sin municipio confirmado"
    assert mapped.municipality is None
    assert "missing_operations" in mapped.mapping_issues


def test_location_fallback_and_timestamps_do_not_invent_precision() -> None:
    payload = easybroker_property()
    payload["location"] = {
        "neighborhood": "Americana",
        "city": {"name": "Guadalajara"},
        "state": "Jalisco",
        "street": "Calle sintética",
    }
    payload["updated_at"] = "2026-08-28T16:30:00"

    mapped = map_easybroker(payload, ExternalInventoryScope.COLLABORATOR, NOW)

    assert mapped.public_location == "Americana, Jalisco"
    assert mapped.municipality == "Guadalajara"
    assert mapped.location_precision == "Exact"
    assert mapped.source_updated_at == datetime(2026, 8, 28, 16, 30, tzinfo=UTC)


def test_invalid_timestamp_and_non_numeric_commission_remain_unknown() -> None:
    payload = easybroker_property()
    payload["updated_at"] = "not-a-date"
    payload["shared_commission_percentage"] = True

    mapped = map_easybroker(payload, ExternalInventoryScope.COLLABORATOR, NOW)

    assert mapped.source_updated_at is None
    assert mapped.source_commission is None
    assert mapped.source_commission_known is False
