"""Short provider-result lifetimes, private references and conservative request quotas."""

import hashlib
import logging
from datetime import timedelta

import httpx
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from datalayer.capture_approval import commercial_data as commercial_data
from datalayer.capture_catalog import STATES
from datalayer.models import GoogleLocation, GoogleLocationUsage, GoogleSearchSession

TTL = timedelta(days=29)


class _ProviderLogFilter(logging.Filter):
    def filter(self, record):
        if "places.googleapis.com" in record.getMessage():
            record.msg, record.args = "Google Places request completed", ()
        return True


logging.getLogger("httpx").addFilter(_ProviderLogFilter())


class LocationUnavailable(Exception):
    pass


def configured():
    return bool(settings.GOOGLE_MAPS_BROWSER_KEY and settings.GOOGLE_MAPS_SERVER_KEY)


@transaction.atomic
def reserve(sku):
    month = timezone.now().strftime("%Y-%m")
    row, _ = GoogleLocationUsage.objects.get_or_create(month=month, sku=sku)
    row = GoogleLocationUsage.objects.select_for_update().get(pk=row.pk)
    limit = max(0, settings.GOOGLE_LOCATION_MONTHLY_LIMITS.get(sku, 0))
    if row.count >= limit:
        raise LocationUnavailable(
            "La búsqueda no está disponible ahora. Puedes completar la ubicación manualmente."
        )
    row.count += 1
    row.save(update_fields=["count"])


def google_post(path, payload, fields, sku):
    if not configured():
        raise LocationUnavailable(
            "La búsqueda de direcciones todavía no está disponible. Puedes escribirla manualmente."
        )
    reserve(sku)
    try:
        # Credentials use headers; provider bodies and URLs containing input are never logged.
        with httpx.Client(timeout=8, follow_redirects=False) as client:
            response = client.post(
                "https://places.googleapis.com/v1/" + path,
                json=payload,
                headers={
                    "X-Goog-Api-Key": settings.GOOGLE_MAPS_SERVER_KEY,
                    "X-Goog-FieldMask": fields,
                },
            )
        if response.status_code != 200:
            raise LocationUnavailable()
        return response.json()
    except (httpx.HTTPError, ValueError, LocationUnavailable):
        raise LocationUnavailable(
            "No pudimos consultar las direcciones. Puedes continuar manualmente."
        ) from None


def google_details(place_id, session=""):
    if not configured():
        raise LocationUnavailable("La búsqueda de direcciones no está disponible.")
    reserve("details")
    try:
        from urllib.parse import quote

        with httpx.Client(timeout=8, follow_redirects=False) as client:
            response = client.get(
                "https://places.googleapis.com/v1/places/" + quote(place_id, safe=""),
                params={
                    "languageCode": "es",
                    **({"sessionToken": str(session)} if session else {}),
                },
                headers={
                    "X-Goog-Api-Key": settings.GOOGLE_MAPS_SERVER_KEY,
                    "X-Goog-FieldMask": "id,addressComponents,location",
                },
            )
        if response.status_code != 200:
            raise LocationUnavailable()
        return response.json()
    except (httpx.HTTPError, ValueError, LocationUnavailable):
        raise LocationUnavailable(
            "No pudimos localizar esa dirección. Intenta de nuevo o usa la captura manual."
        ) from None


def search_session(owner, session_id=None, complete=False):
    with transaction.atomic():
        if session_id:
            row = (
                GoogleSearchSession.objects.select_for_update()
                .filter(pk=session_id, owner=owner, expires_at__gt=timezone.now(), completed=False)
                .first()
            )
            if row is None:
                raise ValidationError(
                    "La búsqueda venció. Escribe nuevamente para consultar la dirección."
                )
        else:
            row = GoogleSearchSession.objects.create(
                owner=owner, expires_at=timezone.now() + timedelta(minutes=15)
            )
        if complete:
            row.completed = True
            row.save(update_fields=["completed"])
        return row


def suggestions(owner, text, session_id=None):
    session = search_session(owner, session_id)
    result = google_post(
        "places:autocomplete",
        {
            "input": text,
            "sessionToken": str(session.pk),
            "languageCode": "es",
            "includedRegionCodes": ["mx"],
            "includeQueryPredictions": False,
            "locationBias": {
                "circle": {"center": {"latitude": 20.67, "longitude": -103.35}, "radius": 50000}
            },
        },
        "suggestions.placePrediction.placeId,suggestions.placePrediction.text.text",
        "autocomplete",
    )
    items = []
    for value in result.get("suggestions", [])[:5]:
        item = value.get("placePrediction", {})
        if item.get("placeId") and item.get("text", {}).get("text"):
            items.append({"id": item["placeId"], "label": item["text"]["text"]})
    return {"session": str(session.pk), "suggestions": items}


def components(result):
    values = {}
    for item in result.get("addressComponents", []):
        for kind in item.get("types", []):
            values.setdefault(kind, item.get("longText", ""))
    if not any(
        "country" in a.get("types", []) and a.get("shortText") == "MX"
        for a in result.get("addressComponents", [])
    ):
        raise ValidationError("Selecciona un inmueble en México.")
    # Do not substitute locality for municipality: these are different in Mexico.
    fields = {
        "private_address": " ".join(
            filter(None, [values.get("route"), values.get("street_number")])
        ),
        "state": values.get("administrative_area_level_1", ""),
        "municipality": values.get("administrative_area_level_2", ""),
        "neighborhood": values.get("neighborhood") or values.get("sublocality_level_1", ""),
    }
    from datalayer.models import normalize_zone

    aliases = {
        "mexico": "Estado de México",
        "distrito federal": "Ciudad de México",
        "michoacan de ocampo": "Michoacán",
        "coahuila de zaragoza": "Coahuila",
        "veracruz de ignacio de la llave": "Veracruz",
        "queretaro de arteaga": "Querétaro",
    }
    state = fields["state"]
    normalized = normalize_zone(state)
    fields["state"] = aliases.get(normalized) or next(
        (value for value in STATES if normalize_zone(value) == normalized), ""
    )
    return {key: value for key, value in fields.items() if value}


def resolve(owner, place_id, session_id):
    session = search_session(owner, session_id, complete=True)
    result = google_details(place_id, session.pk)
    fields = components(result)
    point = result.get("location", {})
    lat, lng = valid_point(point.get("latitude"), point.get("longitude"))
    row = GoogleLocation.objects.create(
        owner=owner,
        place_id=result.get("id") or place_id,
        latitude=lat,
        longitude=lng,
        expires_at=timezone.now() + TTL,
    )
    return {"fields": fields, "location": point_output(row)}


def valid_point(latitude, longitude):
    import math

    if isinstance(latitude, bool) or isinstance(longitude, bool):
        raise ValidationError("Punto inválido.")
    try:
        lat, lng = float(latitude), float(longitude)
    except (ValueError, TypeError):
        raise ValidationError("Punto inválido.") from None
    if (
        not math.isfinite(lat)
        or not math.isfinite(lng)
        or not (-90 <= lat <= 90 and -180 <= lng <= 180)
    ):
        raise ValidationError("Punto inválido.")
    return lat, lng


def map_point(owner, latitude, longitude):
    lat, lng = valid_point(latitude, longitude)
    # A map adjustment is not treated as a perpetual licence to Google-derived data.
    row = GoogleLocation.objects.create(
        owner=owner,
        source="map",
        latitude=lat,
        longitude=lng,
        expires_at=timezone.now() + TTL,
    )
    return point_output(row)


def point_output(row):
    fresh = row.expires_at > timezone.now() and row.latitude is not None
    return {
        "id": str(row.pk),
        "source": row.source,
        "expires_at": row.expires_at.isoformat(),
        "latitude": row.latitude if fresh else None,
        "longitude": row.longitude if fresh else None,
        "needs_confirmation": not fresh,
    }


def capture_point(capture):
    ref = capture.data.get("location_ref")
    if not ref:
        return None
    row = GoogleLocation.objects.filter(pk=ref, owner_id=capture.owner_id).first()
    return point_output(row) if row else None


def validate_reference(owner, data, complete=False):
    ref = data.get("location_ref")
    if ref:
        row = GoogleLocation.objects.filter(pk=ref, owner=owner).first()
        if not row:
            raise ValidationError("No encontramos la ubicación de esta cuenta.")
        if complete and (row.expires_at <= timezone.now() or row.latitude is None):
            raise ValidationError("Confirma nuevamente el punto del inmueble en el mapa.")


def public_point(prop):
    from datalayer import captures
    from datalayer.models import Capture

    capture = Capture.objects.filter(property_id=prop.pk).first()
    if not capture or not prop.published or not captures.active_agreement(capture):
        return None
    if not capture.data.get("location_ref"):
        return prop.public_location or None
    if capture.exact_location_approved:
        point = capture_point(capture)
        return (
            {"latitude": point["latitude"], "longitude": point["longitude"], "approximate": False}
            if point and point["latitude"] is not None
            else None
        )
    # Resolve a separately declared public zone. Never send the private place id or point.
    query = (
        ", ".join(
            str(getattr(prop, key))
            for key in ("neighborhood", "municipality", "state")
            if getattr(prop, key)
        )
        + ", México"
    )
    zone_key = hashlib.sha256(query.encode()).hexdigest()
    row = GoogleLocation.objects.filter(
        owner__isnull=True, zone_key=zone_key, expires_at__gt=timezone.now(), latitude__isnull=False
    ).first()
    if not row:
        result = google_post(
            "places:searchText",
            {"textQuery": query, "languageCode": "es", "regionCode": "MX", "pageSize": 1},
            "places.id,places.location",
            "zone",
        )
        places = result.get("places", [])
        if not places:
            return None
        lat, lng = valid_point(
            places[0].get("location", {}).get("latitude"),
            places[0].get("location", {}).get("longitude"),
        )
        row = GoogleLocation.objects.create(
            owner=None,
            zone_key=zone_key,
            place_id=places[0].get("id", ""),
            source="zone",
            latitude=lat,
            longitude=lng,
            expires_at=timezone.now() + TTL,
        )
    return {"latitude": row.latitude, "longitude": row.longitude, "approximate": True}


def maintain():
    from datalayer.models import Capture

    now = timezone.now()
    # Exclude already expired data first. In particular, never move an owner's adjustment.
    GoogleLocation.objects.filter(expires_at__lte=now).update(latitude=None, longitude=None)
    GoogleSearchSession.objects.filter(expires_at__lte=now).delete()
    if not configured():
        return
    refs = list(
        Capture.objects.filter(
            status__in=["draft", "submitted", "approved", "accepted", "published"]
        )
        .exclude(data__location_ref__isnull=True)
        .values_list("data__location_ref", flat=True)
    )
    rows = (
        GoogleLocation.objects.filter(
            pk__in=refs, source="google", expires_at__lte=now + timedelta(days=2)
        )
        .exclude(place_id="")
        .order_by("expires_at")[:30]
    )
    for row in rows:
        try:
            result = google_details(row.place_id)
            lat, lng = valid_point(
                result.get("location", {}).get("latitude"),
                result.get("location", {}).get("longitude"),
            )
        except (LocationUnavailable, ValidationError):
            continue
        GoogleLocation.objects.filter(pk=row.pk, source="google").update(
            latitude=lat, longitude=lng, expires_at=now + TTL, refreshed_at=now
        )
