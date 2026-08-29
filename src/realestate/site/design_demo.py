"""Local-only photography projection for the public-site design review.

This adapter serves a clearly labelled fictional catalog when
``SITE_DESIGN_DEMO`` is explicit, so the visual system can be reviewed without
importing mock Listings or photography into Product's authoritative records.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

from realestate.site.gateway import GatewayResponse, ProductSiteGateway

DEMO_PROPERTY_IMAGES = (
    "abby-rurenko-uOYak90r4L0-unsplash.jpg",
    "brian-babb-XbwHrt87mQ0-unsplash.jpg",
    "frames-for-your-heart-2d4lAQAlbDA-unsplash.jpg",
    "frames-for-your-heart-mR1CIDduGLc-unsplash.jpg",
    "johnson-U6Q6zVDgmSs-unsplash.jpg",
    "phil-hearing-IYfp2Ixe9nM-unsplash.jpg",
    "redd-francisco-sejLyCD2UQE-unsplash.jpg",
    "scott-webb-1ddol8rgUH8-unsplash.jpg",
    "todd-kent-178j8tJrNlc-unsplash.jpg",
    "vu-anh-TiVPTYCG_3E-unsplash.jpg",
    "webaliser-_TPTXZd9mOo-unsplash.jpg",
    "wes-fischer-g39p1kDjvSY-unsplash.jpg",
    "zac-gudakov-wwqZ8CM21gg-unsplash.jpg",
    "generated-interior-living.jpg",
    "generated-interior-kitchen.jpg",
)

_INTERIOR_START = 13
_MEDIA_NAMESPACE = uuid.UUID("19c32843-3a6d-411b-babf-64c5f5b4a95c")
_LISTING_NAMESPACE = uuid.UUID("39452599-b352-4bcb-8218-80356151cc6a")

_DEMO_PROPERTY_ROWS = (
    (
        "casa-nispero",
        "Casa Níspero",
        "Zapopan, Jalisco",
        "House",
        "Sale",
        3_850_000,
        "Larevia",
        3,
        2,
        164,
    ),
    (
        "loft-americana",
        "Loft Americana",
        "Guadalajara, Jalisco",
        "Apartment",
        "Rental",
        29_500,
        "Larevia",
        2,
        2,
        108,
    ),
    (
        "casa-patio",
        "Casa Patio",
        "Tlaquepaque, Jalisco",
        "House",
        "Sale",
        5_700_000,
        "Larevia",
        3,
        3,
        212,
    ),
    (
        "residencia-olivo",
        "Residencia Olivo",
        "Zapopan, Jalisco",
        "House",
        "Sale",
        9_800_000,
        "Premium",
        4,
        4,
        338,
    ),
    (
        "departamento-nube",
        "Departamento Nube",
        "Zapopan, Jalisco",
        "Apartment",
        "Sale",
        12_400_000,
        "Premium",
        3,
        3,
        245,
    ),
    (
        "casa-barranca",
        "Casa Barranca",
        "Guadalajara, Jalisco",
        "House",
        "Sale",
        15_900_000,
        "Premium",
        4,
        5,
        420,
    ),
    (
        "casa-loma-alta",
        "Casa Loma Alta",
        "Zapopan, Jalisco",
        "House",
        "Sale",
        24_500_000,
        "SuperPremium",
        4,
        6,
        610,
    ),
    (
        "penthouse-colomos",
        "Penthouse Colomos",
        "Guadalajara, Jalisco",
        "Apartment",
        "Sale",
        31_800_000,
        "SuperPremium",
        4,
        5,
        520,
    ),
    (
        "residencia-cañada",
        "Residencia Cañada",
        "Zapopan, Jalisco",
        "House",
        "Sale",
        46_000_000,
        "SuperPremium",
        5,
        7,
        890,
    ),
)


def project_design_media(value: Any) -> Any:
    """Copy a Product response and add the complete fictional photo set."""
    projected = copy.deepcopy(value)
    return _project(projected)


def _project(value: Any) -> Any:
    if isinstance(value, list):
        return [_project(item) for item in value]
    if not isinstance(value, dict):
        return value
    mapped = {key: _project(item) for key, item in value.items()}
    if mapped.get("listing_id") and "media" in mapped:
        mapped["media"] = _media(str(mapped.get("slug") or mapped["listing_id"]))
    return mapped


def _media(listing_key: str) -> list[dict[str, Any]]:
    exterior_count = _INTERIOR_START
    cover_index = sum(listing_key.encode("utf-8")) % exterior_count
    ordered = (
        DEMO_PROPERTY_IMAGES[cover_index:exterior_count]
        + DEMO_PROPERTY_IMAGES[:cover_index]
        + DEMO_PROPERTY_IMAGES[_INTERIOR_START:]
    )
    return [
        {
            "media_id": str(uuid.uuid5(_MEDIA_NAMESPACE, f"{listing_key}:{filename}")),
            "url": f"/assets/demo/properties/{filename}",
            "is_cover": index == 0,
            "sort_order": index,
            "space_group": "Interiores"
            if filename.startswith("generated-")
            else "Propiedad",
        }
        for index, filename in enumerate(ordered)
    ]


def _demo_listings() -> list[dict[str, Any]]:
    listings: list[dict[str, Any]] = []
    for (
        slug,
        title,
        location,
        property_type,
        operation,
        amount,
        tier,
        bedrooms,
        bathrooms,
        construction_m2,
    ) in _DEMO_PROPERTY_ROWS:
        listing_id = str(uuid.uuid5(_LISTING_NAMESPACE, slug))
        listings.append(
            {
                "listing_id": listing_id,
                "slug": slug,
                "property_id": str(uuid.uuid5(_LISTING_NAMESPACE, f"property:{slug}")),
                "title": title,
                "physical_name": title,
                "public_location": location,
                "property_type": property_type,
                "physical_facts": {
                    "bedrooms": bedrooms,
                    "bathrooms": bathrooms,
                    "parking_spaces": max(1, bedrooms - 1),
                    "construction_m2": construction_m2,
                    "land_m2": round(construction_m2 * 1.35),
                },
                "listing_facts": {
                    "description": (
                        "Una propiedad ficticia preparada para revisar jerarquía, "
                        "fotografía y ritmo editorial en la experiencia Larevia."
                    )
                },
                "source_kind": "DesignDemo",
                "source_name": "Fixture local de diseño",
                "attribution": "Propiedad, precio e imágenes ficticias para revisión visual.",
                "presentation_tier": tier,
                "gallery_url": f"/propiedades/{slug}/galeria",
                "technical_sheet_url": f"/propiedades/{slug}",
                "offers": [
                    {
                        "offer_id": str(
                            uuid.uuid5(_LISTING_NAMESPACE, f"offer:{slug}")
                        ),
                        "operation": operation,
                        "price_amount": str(amount),
                        "price_currency": "MXN",
                        "price_visibility": "Visible",
                        "consultation_copy": None,
                        "terms": {},
                    }
                ],
                "media": _media(slug),
                "updated_at": "2026-08-29T12:00:00Z",
            }
        )
    return listings


DEMO_LISTINGS = _demo_listings()


def _catalog(params: dict[str, Any] | None) -> dict[str, Any]:
    query = dict(params or {})
    listings = list(DEMO_LISTINGS)
    if operation := query.get("operation"):
        listings = [
            item
            for item in listings
            if any(offer.get("operation") == operation for offer in item["offers"])
        ]
    if zone := query.get("zone"):
        listings = [item for item in listings if str(zone) in item["public_location"]]
    if property_type := query.get("property_type"):
        listings = [
            item for item in listings if item.get("property_type") == property_type
        ]
    minimum = _number(query.get("minimum_price"))
    maximum = _number(query.get("maximum_price"))
    if minimum is not None:
        listings = [item for item in listings if _listing_price(item) >= minimum]
    if maximum is not None:
        listings = [item for item in listings if _listing_price(item) <= maximum]
    sort = query.get("sort")
    if sort == "price_asc":
        listings.sort(key=_listing_price)
    elif sort == "price_desc":
        listings.sort(key=_listing_price, reverse=True)
    page_size = _positive_int(query.get("page_size"), default=12)
    page = _positive_int(query.get("page"), default=1)
    start = (page - 1) * page_size
    return {
        "query": query,
        "listings": copy.deepcopy(listings[start : start + page_size]),
        "total": len(listings),
        "has_more": start + page_size < len(listings),
    }


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _positive_int(value: Any, *, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def _listing_price(listing: dict[str, Any]) -> float:
    return float(listing["offers"][0]["price_amount"])


def _demo_get(path: str, params: dict[str, Any] | None) -> GatewayResponse | None:
    data: dict[str, Any] | None = None
    if path == "/internal/public-site/catalog":
        data = _catalog(params)
    elif path.startswith("/internal/public-site/listings/"):
        slug = path.rsplit("/", 1)[-1]
        listing = next((item for item in DEMO_LISTINGS if item["slug"] == slug), None)
        if listing:
            data = {"listing": copy.deepcopy(listing)}
    elif path.startswith("/internal/public-site/discovery/"):
        listing_id = path.rsplit("/", 1)[-1]
        listing = next(
            (item for item in DEMO_LISTINGS if item["listing_id"] == listing_id),
            None,
        )
        if listing:
            data = {
                "title": f"{listing['title']} · Larevia",
                "description": str(listing["listing_facts"]["description"]),
                "structured_data": {
                    "@context": "https://schema.org",
                    "@type": "RealEstateListing",
                    "name": listing["title"],
                    "url": listing["technical_sheet_url"],
                    "image": [item["url"] for item in listing["media"]],
                },
            }
    if data is None:
        return None
    return GatewayResponse(
        status_code=200,
        data=data,
        content=b"",
        content_type="application/json",
        headers={},
    )


class DesignDemoGateway:
    """Provide Site-only fixtures without changing Product or its side effects."""

    def __init__(self, product: ProductSiteGateway) -> None:
        self._product = product

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        token_header: tuple[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> GatewayResponse:
        if method == "GET":
            fixture = _demo_get(path, params)
            if fixture is not None:
                return fixture
        response = await self._product.request(
            method,
            path,
            params=params,
            body=body,
            token_header=token_header,
            headers=headers,
        )
        if method != "GET" or response.data is None:
            return response
        return GatewayResponse(
            status_code=response.status_code,
            data=project_design_media(response.data),
            content=response.content,
            content_type=response.content_type,
            headers=response.headers,
        )

    async def aclose(self) -> None:
        await self._product.aclose()
