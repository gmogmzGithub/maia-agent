"""Current closing facts come from the source, never stale materialized fields."""

from datalayer.closing_schemas import ClosingData
from datalayer.easybroker.normalization import mapped, number
from datalayer.models import ImportedOfferPolicy


def current_facts(offer):
    policy = ImportedOfferPolicy.objects.select_related("primary_link__listing").get(offer=offer)
    listing = policy.primary_link.listing
    raw = listing.facts
    values, _ = mapped(raw, policy.primary_link.operation, listing.geography)
    location = raw.get("location") or {}
    address = " ".join(
        str(location.get(k) or "") for k in ("street", "exterior_number", "interior_number")
    ).strip()
    characteristics = {}
    for source, target in [
        ("bedrooms", "bedrooms"),
        ("bathrooms", "bathrooms"),
        ("half_bathrooms", "half_bathrooms"),
        ("parking_spaces", "parking"),
    ]:
        value = number(
            raw.get(source), digits=4, places=1 if target == "bathrooms" else 0, zero=True
        )
        characteristics[target] = value if value is not None and value <= 100 else None
    return ClosingData.model_validate(
        {
            "operation": values.get("operation", ""),
            "kind": values.get("kind") or "",
            "state": listing.geography.get("state", ""),
            "municipality": listing.geography.get("municipality", ""),
            "zone": listing.geography.get("neighborhood", ""),
            "zone_type": "colonia",
            "currency": values.get("currency") or "",
            "address_text": address[:240],
            "land_m2": values.get("land_m2"),
            "construction_m2": values.get("area_m2"),
            "characteristics": characteristics,
            "responsible_id": offer.advisor_id,
        }
    )


def freeze_private_facts(offer):
    profile = current_facts(offer)
    offer.private_data = {
        "private_address": profile.address_text,
        "characteristics": profile.characteristics.model_dump(mode="json"),
    }
    offer.save(update_fields=["private_data"])
