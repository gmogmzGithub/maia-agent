"""References for imported cards; reproject or suppress old public assertions."""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from datalayer.inventory import public_inventory, public_property
from datalayer.models import Property

CHANGED = "La información de estas propiedades cambió. Consulta las opciones vigentes."


def message_fields(conversation, cards=(), *, observed=None):
    """Store references and their sources together, never imported image snapshots."""
    return {
        "properties": persist_cards(cards),
        "public_sources": {**sources_for(conversation, cards), **versions(observed or {})},
    }


@dataclass(frozen=True)
class AcceptedReply:
    message_fields: dict
    validation_failed: bool


def accept_reply(conversation, turn, text, cards, reply):
    """Accept the entire reply under the caller's conversation transaction.

    Offer locks remain held until the caller stores the accepted message. Text,
    presentation and continuity must all describe the same public revision.
    """
    from datalayer.replies import validate_reply
    from datalayer.schemas import ReplyProposal

    expected = {**turn.get("public_sources", {}), **turn.get("observed_public_sources", {})}
    list(
        Property.objects.select_for_update()
        .filter(pk__in=set(expected) | {str(c["id"]) for c in cards})
        .order_by("pk")
    )
    visible = {p.pk: p for p in public_inventory().filter(pk__in=[c["id"] for c in cards])}
    refreshed = [
        public_property(visible[c["id"]], c.get("unconfirmed")) for c in cards if c["id"] in visible
    ]
    changed = refreshed != cards or versions(expected) != expected
    if changed:
        text = "El inventario cambió mientras buscaba. ¿Revisamos las opciones de nuevo?"
        cards, reply = [], None
    else:
        cards = refreshed

    def neutral(message, purpose):
        return ReplyProposal.model_validate(
            {
                "blocks": [{"kind": "text", "text": message}],
                "continuity": {"purpose": purpose, "pending": None},
            }
        )

    if reply is None or not cards and any(b.property_ids for b in reply.blocks):
        reply = neutral(text, "continuar la atención")
    failed = False
    try:
        reply, text, cards = validate_reply(
            conversation.pk, turn["revision"], reply.model_dump(mode="json"), cards
        )
    except ValueError:
        text = "Los datos cambiaron mientras respondía. Revisemos tu solicitud de nuevo."
        cards, failed = [], True
        reply = neutral(text, "revisar datos actuales")
    return AcceptedReply(
        {
            "text": text,
            **message_fields(conversation, cards, observed=expected),
            "presentation": reply.model_dump(mode="json")["blocks"],
            "continuity": {
                "version": 1,
                **reply.continuity.model_dump(mode="json"),
                "revision": turn["revision"],
                "input_message_id": turn["input_message_id"],
            },
        },
        failed,
    )


def versions(ids):
    ids = [int(i) for i in ids]
    imported = set(
        Property.objects.filter(pk__in=ids, origin="easybroker").values_list("pk", flat=True)
    )
    visible = dict(
        public_inventory()
        .filter(pk__in=imported)
        .values_list("pk", "import_policy__public_version")
    )
    return {str(i): str(visible[i]) if i in visible else "unavailable" for i in imported}


def conversation_sources(conversation):
    message = (
        conversation.messages.exclude(public_sources={})
        .only("public_sources")
        .order_by("-pk")
        .first()
    )
    return versions(message.public_sources) if message else {}


def sources_for(conversation, cards=()):
    sources = conversation_sources(conversation)
    sources.update(versions([c["id"] for c in cards]))
    return sources


def persist_cards(cards):
    imported = set(
        Property.objects.filter(pk__in=[c["id"] for c in cards], origin="easybroker").values_list(
            "pk", flat=True
        )
    )
    return [
        {"id": c["id"], "public_revision": c["public_revision"]} if c["id"] in imported else c
        for c in cards
    ]


def project_cards(cards):
    result = []
    for card in cards:
        if card.get("public_revision") is not None:
            prop = public_inventory().filter(pk=card["id"]).first()
            if prop:
                try:
                    result.append(public_property(prop))
                except ValidationError:
                    pass
        else:
            result.append(card)
    return result


@transaction.atomic
def message_projection(message):
    list(Property.objects.select_for_update().filter(pk__in=message.public_sources).order_by("pk"))
    changed = bool(
        message.public_sources and versions(message.public_sources) != message.public_sources
    )
    return {
        "text": CHANGED if changed else message.text,
        "properties": [] if changed else project_cards(message.properties),
        "presentation": [{"kind": "text", "text": CHANGED}] if changed else message.presentation,
        "changed": changed,
    }


def public_title(prop):
    if prop.origin == "easybroker" and not public_inventory().filter(pk=prop.pk).exists():
        return f"Propiedad {prop.reference}"
    return prop.title
