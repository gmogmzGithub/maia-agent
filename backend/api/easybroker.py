"""Session and CSRF protected CRM endpoints. No synchronous provider requests."""

from functools import wraps

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.http import JsonResponse

from api.capture import body, endpoint
from datalayer.closings import ClosingConflict, staff
from datalayer.easybroker import connections, imports, schemas
from datalayer.models import EasyBrokerConnection, EasyBrokerListing, EasyBrokerSyncRun


def private(fn):
    @wraps(fn)
    def wrapped(request, *args, **kwargs):
        @endpoint
        def dispatch(request):
            try:
                staff(request.user)
                return fn(request, *args, **kwargs)
            except PermissionDenied as exc:
                return JsonResponse({"detail": str(exc)}, status=403)
            except ClosingConflict as exc:
                return JsonResponse({"detail": str(exc)}, status=409)
            except ObjectDoesNotExist:
                return JsonResponse({"detail": "No encontramos ese registro."}, status=404)

        response = dispatch(request)
        response["Cache-Control"] = "private, no-store"
        return response

    return wrapped


@private
def connection_list(request):
    if request.method == "GET":
        return JsonResponse(
            {
                "items": [
                    connections.connection_output(r)
                    for r in EasyBrokerConnection.objects.order_by("name")
                ],
                "admin": request.user.is_superuser,
                "public_enabled": settings.EASYBROKER_PUBLIC_ENABLED,
            }
        )
    if request.method == "POST":
        return JsonResponse(
            connections.create(
                request.user, schemas.CreateConnection.model_validate(body(request))
            ),
            status=201,
        )
    return JsonResponse({}, status=405)


@private
def connection_action(request, connection_id):
    if request.method != "POST":
        return JsonResponse({}, status=405)
    return JsonResponse(
        connections.configure(
            request.user, connection_id, schemas.connection_action.validate_python(body(request))
        )
    )


@private
def sync(request, connection_id):
    if request.method != "POST":
        return JsonResponse({}, status=405)
    return JsonResponse(
        connections.manual_sync(
            request.user, connection_id, schemas.Versioned.model_validate(body(request))
        ),
        status=202,
    )


@private
def run(request, run_id):
    if request.method != "GET":
        return JsonResponse({}, status=405)
    return JsonResponse(connections.run_output(EasyBrokerSyncRun.objects.get(pk=run_id)))


@private
def import_list(request):
    if request.method != "GET":
        return JsonResponse({}, status=405)
    rows = EasyBrokerListing.objects.select_related("connection").order_by(
        "connection__name", "public_id"
    )
    if request.GET.get("connection_id"):
        rows = rows.filter(connection_id=request.GET["connection_id"])
    offset = max(0, int(request.GET.get("offset", 0)))
    return JsonResponse(
        {
            "items": [imports.listing_output(r) for r in rows[offset : offset + 50]],
            "count": rows.count(),
            "next_offset": offset + 50 if rows.count() > offset + 50 else None,
        }
    )


@private
def import_detail(request, listing_id):
    if request.method != "GET":
        return JsonResponse({}, status=405)
    return JsonResponse(
        imports.listing_output(
            EasyBrokerListing.objects.select_related("connection").get(pk=listing_id), history=True
        )
    )


@private
def import_action(request, listing_id):
    if request.method != "POST":
        return JsonResponse({}, status=405)
    return JsonResponse(
        imports.review(
            request.user, listing_id, schemas.import_action.validate_python(body(request))
        )
    )
