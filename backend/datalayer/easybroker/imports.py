"""Apply fenced observations and explicit human reviews without changing local ownership."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from datalayer.closings import ClosingConflict
from datalayer.easybroker.connections import authorize, check_revision, remember, replay
from datalayer.easybroker.normalization import (
    STATUSES,
    identity,
    mapped,
    normalize,
    public_id,
    timestamp,
)
from datalayer.easybroker.sync import fenced
from datalayer.models import (
    Advisor,
    EasyBrokerConnection,
    EasyBrokerListing,
    EasyBrokerListingRevision,
    EasyBrokerOfferLink,
    ImportedOfferPolicy,
    ImportedPublicTextRevision,
    PhysicalProperty,
    Property,
    PropertyEvent,
)


def event(offer, action, *, actor=None, run=None, listing=None, reason="", before=None):
    source = (
        {
            "connection_id": str(listing.connection_id),
            "listing_id": str(listing.pk),
            "revision": listing.revision,
        }
        if listing
        else {}
    )
    if run:
        source.update(run_id=str(run.pk), initiator_email=run.initiator_email)
    PropertyEvent.objects.create(
        property=offer,
        actor=actor,
        actor_email=actor.email if actor else "",
        actor_kind="human" if actor else "process",
        action=action,
        reason=reason,
        source=source,
        snapshot={
            "before": before,
            "price": str(offer.price) if offer.price is not None else None,
            "currency": offer.currency,
            "published": offer.published,
        },
    )


def closed(offer):
    return offer.closing_periods.filter(period=offer.commercialization_round).exists()


def hide(offer, policy, *, reason, run=None, listing=None, actor=None):
    from datalayer.inventory import notify_unpublished

    was_published = offer.published
    offer.published = False
    offer.save(update_fields=["published", "updated_at"])
    policy.public_version += 1
    policy.save()
    if was_published:
        event(offer, "source_hidden", actor=actor, run=run, listing=listing, reason=reason)
        notify_unpublished(offer, was_published)


def block_connection(connection, *, actor=None):
    ids = (
        ImportedOfferPolicy.objects.filter(primary_link__listing__connection=connection)
        .order_by("offer_id")
        .values_list("offer_id", flat=True)
    )
    for offer in Property.objects.select_for_update().filter(pk__in=ids).order_by("pk"):
        policy = ImportedOfferPolicy.objects.get(offer=offer)
        policy.disconnected = True
        policy.review_required = True
        hide(
            offer,
            policy,
            reason="connection_changed",
            actor=actor,
            listing=policy.primary_link.listing,
        )


def apply_to_offer(listing, link, *, run=None):
    offer = Property.objects.select_for_update().get(pk=link.offer_id)
    if offer.origin != "easybroker" or link.role != "primary" or closed(offer):
        return
    policy = ImportedOfferPolicy.objects.get(offer=offer)
    values, issues = mapped(listing.facts, link.operation, listing.geography)
    policy.compatible = not issues
    if listing.status != "published":
        policy.source_block = True
    if issues or policy.review_required or policy.source_block or policy.disconnected:
        hide(offer, policy, reason="source_review_required", run=run, listing=listing)
    if issues:
        return
    before = {k: str(getattr(offer, k)) for k in values}
    changed = any(str(getattr(offer, k)) != str(v) for k, v in values.items())
    for key, value in values.items():
        setattr(offer, key, value)
    if changed:
        policy.public_version += 1
        offer.save()
        event(offer, "source_updated", run=run, listing=listing, before=before)
    if policy.expired:
        policy.expired = False
        if (
            policy.publish_requested
            and not any(
                [
                    policy.manual_block,
                    policy.review_required,
                    policy.source_block,
                    policy.disconnected,
                ]
            )
            and listing.status == "published"
            and not offer.withdrawn_at
        ):
            offer.published = True
            offer.save(update_fields=["published", "updated_at"])
            event(offer, "source_recovered", run=run, listing=listing, reason="fresh_again")
    policy.save()


@transaction.atomic
def observe(run_id, lease, status, raw=None):
    connection, run = fenced(run_id, lease)
    external_id = public_id(status.get("public_id"))
    status_time = timestamp(status.get("updated_at"))
    state = status.get("status")
    if state not in STATUSES:
        state = "unknown"
    listing, _ = EasyBrokerListing.objects.select_for_update().get_or_create(
        connection=connection, public_id=external_id
    )
    if listing.source_updated_at and status_time < listing.source_updated_at:
        raise ValueError("older_observation")
    if state == "published":
        if raw is None or raw.get("public_id") != external_id:
            raise ValueError("incomplete_detail")
        detail_time = timestamp(raw.get("updated_at"))
        if detail_time != status_time:
            # No atomic provider snapshot; retry this item instead of asserting freshness.
            raise ValueError("source_changed_during_read")
        facts, images = normalize(raw, listing.facts)
        facts["source_status"] = state
        old_facts = listing.facts
        if facts != old_facts:
            listing.revision += 1
            listing.facts = facts
            EasyBrokerListingRevision.objects.create(
                listing=listing, number=listing.revision, facts=facts, run=run
            )
            structural = bool(old_facts and identity(old_facts) != identity(facts))
            text_changed = any(old_facts.get(k) != facts.get(k) for k in ("title", "description"))
            privacy_changed = old_facts.get("show_prices") != facts.get("show_prices") or (
                old_facts.get("location") or {}
            ).get("show_exact_location") != facts["location"].get("show_exact_location")
            if structural:
                listing.geography = {}
                listing.geography_signature = ""
            if structural or text_changed or privacy_changed:
                for link in listing.links.filter(active=True, role="primary").order_by("offer_id"):
                    offer = Property.objects.select_for_update().get(pk=link.offer_id)
                    if offer.origin == "easybroker" and not closed(offer):
                        policy = ImportedOfferPolicy.objects.get(offer=offer)
                        policy.review_required = True
                        hide(offer, policy, reason="content_changed", run=run, listing=listing)
        if images is not None:
            listing.images = images
        listing.checked_at = timezone.now()
        listing.checked_generation = connection.generation
        listing.issues = []
        for operation in {
            "sale"
            if v.get("type") == "sale"
            else "rent"
            if v.get("type") == "rental"
            else "unsupported"
            for v in facts["operations"]
        }:
            _, issues = mapped(facts, operation, listing.geography)
            listing.issues.extend(f"{operation}:{issue}" for issue in issues)
    if state != "published" and listing.status != state:
        listing.revision += 1
        listing.facts = {**listing.facts, "source_status": state}
        EasyBrokerListingRevision.objects.create(
            listing=listing, number=listing.revision, facts=listing.facts, run=run
        )
    listing.status = state
    listing.source_updated_at = status_time
    listing.save()
    for link in listing.links.filter(active=True, role="primary").order_by("offer_id"):
        apply_to_offer(listing, link, run=run)
    return listing


def listing_output(row, *, history=False):
    links = list(row.links.filter(active=True).values("id", "operation", "offer_id", "role"))
    result = {
        "id": str(row.pk),
        "connection_id": str(row.connection_id),
        "connection_name": row.connection.name,
        "public_id": row.public_id,
        "status": row.status,
        "revision": row.revision,
        "checked_at": row.checked_at.isoformat() if row.checked_at else None,
        "facts": row.facts,
        "issues": row.issues,
        "geography": row.geography,
        "links": links,
    }
    if history:
        result["history"] = [
            {"revision": r.number, "facts": r.facts, "at": r.created_at.isoformat()}
            for r in row.revisions.order_by("number")
        ]
        result["link_history"] = list(
            row.links.values(
                "id", "operation", "offer_id", "role", "active", "actor_email", "reason"
            )
        )
    return result


@transaction.atomic
def review(actor, listing_id, value):
    actor = authorize(actor)
    payload = value.model_dump(mode="json")
    previous = replay(actor, value.request_id, str(listing_id), value.action, payload)
    if previous is not None:
        return previous
    connection_id = EasyBrokerListing.objects.values_list("connection_id", flat=True).get(
        pk=listing_id
    )
    listing_ids = {listing_id}
    connection_ids = {connection_id}
    if value.action == "primary":
        candidate = EasyBrokerOfferLink.objects.get(
            pk=value.link_id, listing_id=listing_id, active=True
        )
        current = ImportedOfferPolicy.objects.select_related("primary_link__listing").get(
            offer_id=candidate.offer_id
        )
        listing_ids.add(current.primary_link.listing_id)
        connection_ids.add(current.primary_link.listing.connection_id)
    locked_connections = list(
        EasyBrokerConnection.objects.select_for_update()
        .filter(pk__in=connection_ids)
        .order_by("pk")
    )
    connection = next(c for c in locked_connections if c.pk == connection_id)
    locked_listings = list(
        EasyBrokerListing.objects.select_for_update().filter(pk__in=listing_ids).order_by("pk")
    )
    row = next(r for r in locked_listings if r.pk == listing_id)
    if value.action == "primary":
        current = ImportedOfferPolicy.objects.select_related("primary_link").get(
            offer_id=candidate.offer_id
        )
        if current.primary_link.listing_id not in listing_ids:
            raise ClosingConflict("La fuente principal cambió. Actualiza sus vinculaciones.")
    check_revision(row, value.revision)
    if value.action == "approve":
        approve(actor, connection, row, value)
    elif value.action == "link":
        link_offer(actor, row, value)
    elif value.action == "primary":
        choose_primary(actor, row, value)
    elif value.action == "unlink":
        unlink_offer(actor, row, value)
    # Human configuration changes also invalidate stale reviews.
    row.revision += 1
    revision = row.revisions.order_by("-number").first()
    if revision:
        EasyBrokerListingRevision.objects.create(
            listing=row, number=row.revision, facts=row.facts, run=revision.run
        )
    row.save()
    result = listing_output(row)
    return remember(actor, value.request_id, str(row.pk), value.action, payload, result)


def approve(actor, connection, row, value):
    from datalayer.inventory import set_publication

    if (
        not connection.enabled
        or row.status != "published"
        or row.checked_generation != connection.generation
    ):
        raise ValidationError("Comprueba primero la disponibilidad vigente del origen.")
    from datetime import timedelta

    if not row.checked_at or row.checked_at <= timezone.now() - timedelta(hours=24):
        raise ValidationError("Actualiza el origen antes de aprobar.")
    geography = {k: getattr(value, k) for k in ("state", "municipality", "neighborhood")}
    values, issues = mapped(row.facts, value.operation, geography)
    if issues:
        raise ValidationError(
            "La operación sigue pendiente de compatibilidad: " + ", ".join(issues)
        )
    row.geography, row.geography_signature = geography, identity(row.facts)
    Advisor.objects.get(pk=value.advisor_id)
    link = row.links.filter(operation=value.operation, active=True).first()
    if link and (link.role != "primary" or link.offer.origin != "easybroker"):
        raise ValidationError(
            "La vinculación actual conserva una oferta local o secundaria. Revisa su fuente principal."
        )
    if not link:
        if not row.physical_property_id:
            row.physical_property = PhysicalProperty.objects.create()
        offer = Property.objects.create(
            origin="easybroker",
            title=value.title,
            **values,
            advisor_id=value.advisor_id,
            description=value.description,
            physical_property=row.physical_property,
        )
        link = EasyBrokerOfferLink.objects.create(
            listing=row,
            operation=value.operation,
            offer=offer,
            actor=actor,
            actor_email=actor.email,
            reason=value.reason,
        )
        policy = ImportedOfferPolicy.objects.create(offer=offer, primary_link=link)
    else:
        offer = Property.objects.select_for_update().get(pk=link.offer_id)
        if closed(offer) or offer.withdrawn_at:
            raise ValidationError("La oferta está cerrada o retirada; conserva su evidencia.")
        policy = ImportedOfferPolicy.objects.get(offer=offer)
        for key, field in values.items():
            setattr(offer, key, field)
        offer.title, offer.description, offer.advisor_id = (
            value.title,
            value.description,
            value.advisor_id,
        )
        offer.save()
    ImportedPublicTextRevision.objects.create(
        offer=offer,
        source_revision=row.revisions.get(number=row.revision),
        title=value.title,
        description=value.description,
        actor=actor,
        actor_email=actor.email,
        reason=value.reason,
    )
    policy.review_required, policy.disconnected, policy.source_block = False, False, False
    policy.compatible = True
    policy.approved_revision = row.revision
    policy.public_version += 1
    policy.save()
    row.save()
    # An approval does not silently clear a previous manual exclusion.
    if value.publish and not policy.manual_block:
        set_publication(offer.pk, True, actor=actor)
    event(offer, "source_approved", actor=actor, listing=row, reason=value.reason)


def link_offer(actor, row, value):
    offer = Property.objects.select_for_update().get(pk=value.offer_id)
    if offer.operation != value.operation:
        raise ValidationError("La operación de la oferta no coincide.")
    if row.physical_property_id and row.physical_property_id != offer.physical_property_id:
        raise ValidationError(
            "Vincula primero los inmuebles explícitamente; no se moverán operaciones."
        )
    row.physical_property_id = offer.physical_property_id
    EasyBrokerOfferLink.objects.create(
        listing=row,
        operation=value.operation,
        offer=offer,
        role="local" if offer.origin == "local" else "secondary",
        actor=actor,
        actor_email=actor.email,
        reason=value.reason,
    )
    event(offer, "source_linked", actor=actor, listing=row, reason=value.reason)


def choose_primary(actor, row, value):
    link = row.links.get(pk=value.link_id, active=True)
    offer = Property.objects.select_for_update().get(pk=link.offer_id)
    if offer.origin != "easybroker" or closed(offer):
        raise ValidationError("La oferta local o cerrada conserva su control actual.")
    policy = ImportedOfferPolicy.objects.get(offer=offer)
    if link.role != "secondary":
        raise ValidationError("Selecciona una fuente secundaria activa.")
    previous = policy.primary_link
    previous.active = False
    previous.save(update_fields=["active"])
    link.active = False
    link.save(update_fields=["active"])
    EasyBrokerOfferLink.objects.create(
        listing=previous.listing,
        operation=previous.operation,
        offer=offer,
        role="secondary",
        actor=actor,
        actor_email=actor.email,
        reason=value.reason,
    )
    principal = EasyBrokerOfferLink.objects.create(
        listing=row,
        operation=link.operation,
        offer=offer,
        role="primary",
        actor=actor,
        actor_email=actor.email,
        reason=value.reason,
    )
    policy.primary_link, policy.review_required = principal, True
    hide(offer, policy, reason="primary_changed", listing=row, actor=actor)
    event(offer, "source_primary", actor=actor, listing=row, reason=value.reason)


def unlink_offer(actor, row, value):
    link = row.links.get(pk=value.link_id, active=True)
    offer = Property.objects.select_for_update().get(pk=link.offer_id)
    if closed(offer):
        raise ValidationError("La oferta cerrada conserva su evidencia de origen.")
    link.active = False
    link.save(update_fields=["active"])
    if link.role == "primary":
        policy = ImportedOfferPolicy.objects.get(offer=offer)
        policy.review_required = True
        hide(offer, policy, reason="source_unlinked", listing=row, actor=actor)
    event(offer, "source_unlinked", actor=actor, listing=row, reason=value.reason)
