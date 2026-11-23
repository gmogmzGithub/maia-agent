"""HTTP boundary for address search. Responses containing results must not be cached."""

import uuid

from django.conf import settings
from django.http import JsonResponse

from api.capture import body, endpoint, require_owner, throttle
from datalayer import google_locations as locations
from datalayer.models import Capture


def response(value, status=200):
    result = JsonResponse(value, status=status)
    result["Cache-Control"] = "private, no-store"
    return result


@endpoint
def config(request):
    if request.method != "GET":
        return response({}, 405)
    return response({"enabled": locations.configured()})


@endpoint
def map_session(request):
    if request.method != "POST":
        return response({}, 405)
    blocked = throttle(request, "location-map", 180)
    if blocked:
        return blocked
    if not settings.GOOGLE_MAPS_BROWSER_KEY:
        return response({"detail": "El mapa todavía no está disponible."}, 503)
    try:
        locations.reserve("maps")
        return response(
            {"key": settings.GOOGLE_MAPS_BROWSER_KEY, "map_id": settings.GOOGLE_MAPS_MAP_ID}
        )
    except locations.LocationUnavailable as exc:
        return response({"detail": str(exc)}, 503)


@endpoint
def search(request):
    if request.method != "POST":
        return response({}, 405)
    denied = (
        None if request.user.is_authenticated and request.user.is_staff else require_owner(request)
    )
    if denied:
        return denied
    blocked = throttle(request, f"location-search:{request.user.pk}", 100)
    if blocked:
        return blocked
    value = body(request)
    owner = request.user
    if value.get("capture_id"):
        if not request.user.is_staff:
            return response({"detail": "Se requiere acceso del equipo."}, 403)
        owner = Capture.objects.get(pk=uuid.UUID(value["capture_id"])).owner
    action = value.get("action")
    try:
        if action == "suggest":
            text = str(value.get("text", "")).strip()
            if not 3 <= len(text) <= 240:
                raise ValueError("Escribe al menos tres caracteres de la dirección.")
            session = uuid.UUID(value["session"]) if value.get("session") else None
            return response(locations.suggestions(owner, text, session))
        if action == "resolve":
            place_id = str(value.get("place_id", ""))
            if not place_id or len(place_id) > 255:
                raise ValueError("Selecciona una dirección de la lista.")
            return response(locations.resolve(owner, place_id, uuid.UUID(value["session"])))
        if action == "point":
            return response(
                {
                    "location": locations.map_point(
                        owner, value.get("latitude"), value.get("longitude")
                    )
                }
            )
        raise ValueError("Acción inválida.")
    except locations.LocationUnavailable as exc:
        return response({"detail": str(exc)}, 503)


@endpoint
def property_location(request, property_id):
    if request.method != "GET":
        return response({}, 405)
    blocked = throttle(request, "location-public", 180)
    if blocked:
        return blocked
    from datalayer.inventory import public_inventory

    prop = public_inventory().get(pk=property_id)
    if prop.origin == "easybroker":
        return response({"location": None})
    try:
        point = locations.public_point(prop)
    except locations.LocationUnavailable:
        point = None
    # Private identifiers and provider references are never included.
    return response({"location": point})


@endpoint
def point(request, point_id):
    from datalayer.models import GoogleLocation

    if request.method != "GET":
        return response({}, 405)
    denied = (
        None if request.user.is_authenticated and request.user.is_staff else require_owner(request)
    )
    if denied:
        return denied
    row = GoogleLocation.objects.get(
        pk=point_id, **({} if request.user.is_staff else {"owner": request.user})
    )
    return response({"location": locations.point_output(row)})
