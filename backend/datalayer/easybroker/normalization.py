"""Versioned, allowlisted facts from the ordinary API, never partner payloads."""

import hashlib
import json
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from django.utils.dateparse import parse_datetime

KINDS = {
    "Casa": "house",
    "Departamento": "apartment",
    "Terreno": "land",
    "Casa en condominio": "condominium",
    "Terreno comercial": "commercial_land",
    "Terreno industrial": "industrial_land",
    "Oficina": "office",
    "Bodega comercial": "warehouse",
    "Local comercial": "retail",
    "Nave industrial": "industrial",
    "Edificio": "building",
    "Rancho": "ranch",
    "Quinta": "country_house",
    "Villa": "villa",
}
STATUSES = {
    "published",
    "not_published",
    "reserved",
    "sold",
    "rented",
    "suspended",
    "flagged",
    "disapproved",
}
FACT_FIELDS = {
    "public_id",
    "title",
    "description",
    "private_description",
    "property_type",
    "show_prices",
    "bedrooms",
    "bathrooms",
    "half_bathrooms",
    "parking_spaces",
    "construction_size",
    "lot_size",
    "age",
    "conservation_state",
    "features",
}
LOCATION_FIELDS = {
    "name",
    "street",
    "exterior_number",
    "interior_number",
    "postal_code",
    "latitude",
    "longitude",
    "show_exact_location",
    "hide_exact_location",
}
OPERATION_FIELDS = {"type", "amount", "currency", "unit", "period", "active"}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("invalid_timestamp")
    parsed = parse_datetime(value)
    if not parsed or parsed.tzinfo is None:
        raise ValueError("invalid_timestamp")
    return parsed


def public_id(value):
    import re

    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", value):
        raise ValueError("invalid_public_id")
    return value


def normalize(raw, previous=None):
    """Omission preserves a known fact; explicit null withdraws it."""
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("location"), dict)
        or not isinstance(raw.get("operations"), list)
        or type(raw.get("show_prices")) is not bool
    ):
        raise ValueError("incomplete_detail")
    public_id(raw.get("public_id"))
    timestamp(raw.get("updated_at"))
    if len(raw["operations"]) > 20:
        raise ValueError("invalid_operations")
    result = dict(previous or {})
    for key in FACT_FIELDS:
        if key in raw:
            if (
                key != "features"
                and raw[key] is not None
                and not isinstance(raw[key], (str, int, float, bool))
            ):
                raise ValueError("invalid_fact")
            result[key] = raw[key]
    if result.get("features") is not None and (
        not isinstance(result["features"], list)
        or not all(isinstance(v, str) and len(v) <= 500 for v in result["features"])
    ):
        raise ValueError("invalid_features")
    location = dict(result.get("location") or {})
    location.update({k: v for k, v in raw["location"].items() if k in LOCATION_FIELDS})
    if type(location.get("show_exact_location")) is not bool:
        raise ValueError("incomplete_privacy")
    if any(
        value is not None and not isinstance(value, (str, int, float, bool))
        for value in location.values()
    ):
        raise ValueError("invalid_location")
    result["location"] = location
    operations = []
    for item in raw["operations"]:
        if not isinstance(item, dict):
            raise ValueError("invalid_operations")
        if any(
            value is not None and not isinstance(value, (str, int, float, bool))
            for key, value in item.items()
            if key in OPERATION_FIELDS
        ):
            raise ValueError("invalid_operations")
        operations.append({k: v for k, v in item.items() if k in OPERATION_FIELDS})
    # Array order is not operation identity. Keep ambiguous operations for review.
    result["operations"] = sorted(operations, key=lambda x: json.dumps(x, sort_keys=True))
    if len(json.dumps(result, ensure_ascii=False)) > 100_000:
        raise ValueError("detail_too_large")
    images = None
    if "property_images" in raw:
        if not isinstance(raw["property_images"], list) or len(raw["property_images"]) > 200:
            raise ValueError("invalid_images")
        images = []
        for item in raw["property_images"]:
            url = item.get("url") if isinstance(item, dict) else None
            if isinstance(url, str) and len(url) <= 8192:
                parts = urlsplit(url)
                if (
                    parts.scheme == "https"
                    and parts.hostname
                    and not parts.username
                    and not parts.password
                ):
                    images.append(url)
    return result, images


def number(value, *, digits=14, places=2, zero=False):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or (not zero and number == 0):
            return None
        if number >= Decimal(10) ** (digits - places) or number != number.quantize(
            Decimal(10) ** -places
        ):
            return None
        return number
    except (InvalidOperation, ValueError):
        return None


def mapped(facts, operation, geography):
    issues = []
    matches = [
        v
        for v in facts.get("operations", [])
        if {"sale": "sale", "rental": "rent"}.get(v.get("type")) == operation
    ]
    if len(matches) != 1:
        return {}, ["ambiguous_or_missing_operation"]
    item = matches[0]
    hidden = facts.get("show_prices") is False
    amount = number(item.get("amount"))
    currency = item.get("currency")
    if item.get("unit") != "total" or item.get("active") is False:
        issues.append("unsupported_unit_or_operation")
    if currency not in {"MXN", "USD"} and (currency is not None or not hidden):
        issues.append("unsupported_currency")
    if amount is None and (item.get("amount") is not None or not hidden):
        issues.append("invalid_amount")
    kind = KINDS.get(facts.get("property_type"))
    if not kind:
        issues.append("unsupported_property_type")
    if not all(geography.get(k) for k in ("state", "municipality", "neighborhood")):
        issues.append("geography_review_required")
    values = {
        "operation": operation,
        "kind": kind,
        "price": amount,
        "currency": currency if currency in {"MXN", "USD"} else None,
        "price_visible": not hidden,
        **{k: geography.get(k, "") for k in ("state", "municipality", "neighborhood")},
    }
    for source, field in [("construction_size", "area_m2"), ("lot_size", "land_m2")]:
        value = facts.get(source)
        values[field] = number(value, digits=10 if field == "area_m2" else 14)
        if value is not None and value != 0 and values[field] is None:
            issues.append(f"invalid_{source}")
    for source, field in [
        ("bedrooms", "bedrooms"),
        ("bathrooms", "bathrooms"),
        ("parking_spaces", "parking"),
    ]:
        value = facts.get(source)
        parsed = number(value, digits=4, places=1 if field == "bathrooms" else 0, zero=True)
        values[field] = (
            parsed if field == "bathrooms" else int(parsed) if parsed is not None else None
        )
        if parsed is not None and parsed > 100 or value is not None and parsed is None:
            issues.append(f"invalid_{source}")
    return values, issues


def identity(facts):
    return digest(
        {
            "location": {
                k: v
                for k, v in (facts.get("location") or {}).items()
                if k not in {"show_exact_location", "hide_exact_location"}
            },
            "operations": sorted(v.get("type", "") for v in facts.get("operations", [])),
            "kind": facts.get("property_type"),
        }
    )
