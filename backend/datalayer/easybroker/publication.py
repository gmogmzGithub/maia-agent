"""A single availability guard shared by every public consumer."""

from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from datalayer.models import ImportedOfferPolicy


def eligible_imports():
    if not settings.EASYBROKER_PUBLIC_ENABLED:
        return Q(pk__in=[])
    prefix = "import_policy__primary_link__"
    return Q(
        origin="easybroker",
        advisor__isnull=False,
        import_policy__publish_requested=True,
        import_policy__manual_block=False,
        import_policy__review_required=False,
        import_policy__source_block=False,
        import_policy__disconnected=False,
        import_policy__compatible=True,
        **{
            prefix + "active": True,
            prefix + "role": "primary",
            prefix + "listing__connection__enabled": True,
            prefix + "listing__connection__continuity_verified": True,
            prefix + "listing__checked_at__gt": timezone.now() - timedelta(hours=24),
            prefix + "listing__checked_generation": F(prefix + "listing__connection__generation"),
            prefix + "listing__status": "published",
        },
    )


def public_projection(prop, result):
    from datalayer.inventory import public_inventory

    if not public_inventory().filter(pk=prop.pk).exists():
        raise ValidationError("La oferta importada no está disponible para el público.")
    policy = ImportedOfferPolicy.objects.select_related("primary_link__listing").get(offer=prop)
    # Neither exact coordinates nor unreviewed free text/JSON are public fallbacks.
    result.update(
        public_location={},
        details={},
        public_address="",
        photos=policy.primary_link.listing.images,
        public_revision=str(policy.public_version),
    )
    if not prop.price_visible:
        result.update(price=None, currency=None)
    return result


def set_imported_publication(prop, published, *, actor=None):
    from datalayer.inventory import notify_unpublished

    policy = ImportedOfferPolicy.objects.get(offer=prop)
    if published:
        link = policy.primary_link
        listing = link.listing
        connection = listing.connection
        if (
            not link.active
            or link.role != "primary"
            or not connection.enabled
            or not connection.continuity_verified
            or listing.status != "published"
            or listing.checked_generation != connection.generation
            or not listing.checked_at
            or listing.checked_at <= timezone.now() - timedelta(hours=24)
        ):
            raise ValidationError("Actualiza y revisa el origen antes de publicar.")
        if (
            policy.review_required
            or policy.disconnected
            or policy.source_block
            or not policy.compatible
        ):
            raise ValidationError("Revisa la ficha de EasyBroker antes de publicar.")
        if (
            prop.withdrawn_at
            or prop.closing_periods.filter(period=prop.commercialization_round).exists()
        ):
            raise ValidationError("La oferta está retirada o cerrada.")
    was_published = prop.published
    if (
        policy.publish_requested == published
        and policy.manual_block == (not published)
        and was_published == published
    ):
        return prop
    policy.publish_requested = published
    policy.manual_block = not published
    policy.public_version += 1
    policy.save()
    prop.published = published
    prop.save(update_fields=["published", "updated_at"])
    notify_unpublished(prop, was_published)
    from datalayer.easybroker.imports import event

    event(
        prop,
        "source_publication",
        actor=actor,
        listing=policy.primary_link.listing,
        reason="publicar" if published else "despublicar",
    )
    return prop


def source_evidence(offer):
    if offer.origin == "easybroker":
        period = offer.closing_periods.filter(period=offer.commercialization_round).first()
        if period:
            confirmed = period.closing.revisions.filter(action="confirm").first()
            if confirmed:
                return confirmed.source_evidence.get("external_source")
    policy = (
        ImportedOfferPolicy.objects.select_related("primary_link__listing")
        .filter(offer=offer)
        .first()
    )
    if not policy:
        return None
    link = policy.primary_link
    return {
        "connection_id": str(link.listing.connection_id),
        "listing_id": str(link.listing_id),
        "public_id": link.listing.public_id,
        "source_revision": link.listing.revision,
        "link_id": link.pk,
        "operation": link.operation,
    }


def expire_imports():
    now = timezone.now()
    from datalayer.easybroker.imports import hide
    from datalayer.models import ImportedOfferPolicy, Property

    overdue = ImportedOfferPolicy.objects.filter(
        expired=False, primary_link__listing__checked_at__lte=now - timedelta(hours=24)
    ).values_list("offer_id", flat=True)
    for offer_id in overdue:
        with transaction.atomic():
            offer = Property.objects.select_for_update().get(pk=offer_id)
            policy = ImportedOfferPolicy.objects.select_related("primary_link__listing").get(
                offer=offer
            )
            if policy.primary_link.listing.checked_at <= timezone.now() - timedelta(hours=24):
                policy.expired = True
                hide(offer, policy, reason="source_expired", listing=policy.primary_link.listing)
