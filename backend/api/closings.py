"""Staff-only HTTP transport for the closing registry."""

from functools import wraps

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.db.models import F, Q
from django.http import JsonResponse

from api.capture import body, endpoint
from datalayer import closings
from datalayer.models import (
    Closing,
    ClosingRevision,
    PhysicalProperty,
    Property,
    SearchIntent,
)


def private(fn):
    @endpoint
    @wraps(fn)
    def wrapped(request, *args, **kwargs):
        try:
            closings.staff(request.user)
            response = fn(request, *args, **kwargs)
        except PermissionDenied as exc:
            response = JsonResponse({"detail": str(exc)}, status=403)
        except closings.ClosingConflict as exc:
            response = JsonResponse({"detail": str(exc)}, status=409)
        except ObjectDoesNotExist:
            response = JsonResponse({"detail": "No encontramos ese registro."}, status=404)
        response["Cache-Control"] = "private, no-store"
        return response

    return wrapped


@private
def listing(request):
    if request.method == "POST":
        value = body(request)
        return JsonResponse(
            closings.create_draft(
                request.user,
                request_id=value["request_id"],
                data=value.get("data", {}),
                origin=value.get("origin", "historical"),
                offer_id=value.get("offer_id"),
                physical_property_id=value.get("physical_property_id"),
            ),
            status=201,
        )
    if request.method != "GET":
        return JsonResponse({}, status=405)
    rows = ClosingRevision.objects.filter(number=F("closing__revision")).select_related("closing")
    for query, field in [
        ("status", "closing__status"),
        ("operation", "operation"),
        ("kind", "kind"),
        ("state", "state"),
        ("municipality", "municipality"),
        ("zone", "zone__icontains"),
        ("year", "year"),
    ]:
        if request.GET.get(query):
            rows = rows.filter(**{field: request.GET[query]})
    if request.GET.get("is_test") in {"true", "false"}:
        rows = rows.filter(is_test=request.GET["is_test"] == "true")
    offset = max(0, int(request.GET.get("offset", 0)))
    return JsonResponse(
        {
            "items": [
                closings.output(row.closing)
                for row in rows.order_by("-closing__created_at")[offset : offset + 50]
            ],
            "count": rows.count(),
            "can_confirm": closings.can_confirm(request.user),
            "admin": request.user.is_superuser,
            "user_id": request.user.pk,
        }
    )


@private
def detail(request, closing_id):
    if request.method == "GET":
        return JsonResponse(closings.output(Closing.objects.get(pk=closing_id), history=True))
    value = body(request)
    if request.method == "PUT":
        return JsonResponse(
            closings.update_draft(
                request.user, closing_id, revision=value["revision"], data=value["data"]
            )
        )
    if request.method == "DELETE":
        closings.delete_draft(request.user, closing_id, revision=value["revision"])
        return JsonResponse({"deleted": True})
    return JsonResponse({}, status=405)


@private
def summary(request, closing_id):
    if request.method != "GET":
        return JsonResponse({}, status=405)
    return JsonResponse(closings.preview(request.user, closing_id))


@private
def action(request, closing_id):
    if request.method != "POST":
        return JsonResponse({}, status=405)
    value = body(request)
    if value["action"] == "resolve_search":
        return JsonResponse(
            closings.resolve_search(
                request.user, closing_id, value["intent_id"], request_id=value["request_id"]
            )
        )
    return JsonResponse(
        closings.command(
            request.user,
            closing_id,
            action=value["action"],
            request_id=value["request_id"],
            revision=value["revision"],
            reason=value.get("reason", ""),
            data=value.get("data"),
            preview_token=value.get("preview_token"),
            reviewed_duplicates=value.get("reviewed_duplicates"),
            reversal_date=value.get("reversal_date"),
        )
    )


@private
def identities(request):
    if request.method == "POST":
        value = body(request)
        return JsonResponse(
            closings.link_identities(
                request.user,
                value["source_id"],
                value["target_id"],
                reason=value["reason"],
                request_id=value["request_id"],
            )
        )
    if request.method != "GET":
        return JsonResponse({}, status=405)
    term = request.GET.get("q", "").strip()[:100]
    rows = PhysicalProperty.objects.all()
    if term:
        rows = rows.filter(
            Q(offers__title__icontains=term)
            | Q(offers__reference__icontains=term)
            | Q(offers__neighborhood__icontains=term)
            | Q(offers__capture__data__private_address__icontains=term)
            | Q(closings__revisions__zone__icontains=term)
            | Q(closings__revisions__street__icontains=term)
        )
    items = []
    seen = set()
    for original in rows.distinct().order_by("-created_at")[:60]:
        canonical, members = closings.identity_group(original.pk)
        if canonical in seen:
            continue
        seen.add(canonical)
        row = PhysicalProperty.objects.get(pk=canonical)
        latest = (
            ClosingRevision.objects.filter(
                closing__physical_property_id__in=members, number=F("closing__revision")
            )
            .order_by("-created_at")
            .first()
        )
        offer = Property.objects.filter(physical_property_id__in=members).order_by("pk").first()
        label = (
            f"{latest.street or latest.rural_identification}, {latest.zone}, {latest.municipality}"
            if latest
            else f"{offer.reference} · {offer.title} · {offer.neighborhood}"
            if offer
            else str(row.pk)
        )
        items.append(
            {
                "id": str(row.pk),
                "label": label,
                "offers": list(
                    Property.objects.filter(physical_property_id__in=members).values(
                        "id", "reference", "operation"
                    )
                ),
            }
        )
    return JsonResponse({"items": items})


@private
def proposal(request, offer_id):
    if request.method != "GET":
        return JsonResponse({}, status=405)
    from datalayer.property_records import facts

    offer = Property.objects.get(pk=offer_id)
    return JsonResponse(
        {
            "data": facts(offer).model_dump(mode="json"),
            "address_to_review": facts(offer).address_text,
            "physical_property_id": str(offer.physical_property_id)
            if offer.physical_property_id
            else None,
        }
    )


@private
def property_result(request, offer_id):
    from datalayer import property_records

    if request.method == "GET":
        return JsonResponse(property_records.result(request.user, offer_id))
    if request.method != "POST":
        return JsonResponse({}, status=405)
    value = body(request)
    if value.get("action") == "prepare":
        return JsonResponse(property_records.prepare(request.user, offer_id, value))
    if value.get("action") == "withdraw":
        property_records.withdraw(request.user, offer_id, value.get("reason"), value.get("source"))
    elif value.get("action") == "restore":
        property_records.restore(request.user, offer_id, value.get("reason"), value.get("source"))
    else:
        raise ValueError("Selecciona el resultado de comercialización.")
    return JsonResponse(property_records.result(request.user, offer_id))


@private
def searches(request):
    from datalayer.followups import criteria_for

    if request.method != "GET":
        return JsonResponse({}, status=405)
    prospect_id = int(request.GET["prospect_id"])
    return JsonResponse(
        {
            "items": [
                {
                    "id": str(row.pk),
                    "started_at": row.started_at.isoformat(),
                    "criteria": criteria_for(row.cycle)
                    if getattr(row, "cycle", None)
                    else row.criteria,
                    "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
                    "conversation_id": str(row.conversation_id),
                }
                for row in SearchIntent.objects.filter(prospect_id=prospect_id).order_by(
                    "-started_at"
                )[:50]
            ]
        }
    )
