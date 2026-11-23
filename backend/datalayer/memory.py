"""Authorized memory reads. No model formatting, execution records or business writes."""

from datalayer.models import Conversation


def visible_messages(conversation):
    return conversation.messages.exclude(
        whatsappdelivery__status__in=[
            "queued",
            "sending",
            "blocked",
            "failed",
            "uncertain",
            "skipped",
        ]
    )



def latest_reply(conversation):
    return visible_messages(conversation).filter(role="assistant").last()


def read_memory(conversation):
    """Read under the caller's turn lock; preserve channel and session scope."""
    origin_history = None
    origin_sources = {}
    from datalayer.public_history import conversation_sources, message_projection, versions

    history = [
        {"role": message.role, "text": public["text"],
         "properties": [{key: card.get(key) for key in ("id", "reference", "title")}
                        for card in public["properties"]]}
        for message in visible_messages(conversation).filter(is_error=False)
        for public in [message_projection(message)]
    ]
    latest = conversation.messages.filter(role="user").last()
    from datalayer.appointments import proposal_output
    from datalayer.booking_tools import pending_visit_proposal

    previous = latest_reply(conversation)
    from django.db.models import Q

    from datalayer.models import SearchIntent

    search = SearchIntent.objects.filter(
        Q(conversation_id=conversation.pk) | Q(conversation_id=conversation.context_origin_id),
        prospect_id=conversation.prospect_id,
    ).order_by("-started_at", "-pk").first()
    proposal = pending_visit_proposal(conversation.pk)
    shown_property_ids = sorted({
        card["id"]
        for message in visible_messages(conversation).exclude(display_kind="hidden")
        for card in message.properties if "id" in card
    })
    if conversation.channel == "whatsapp" and conversation.context_origin_id:
        origin = Conversation.objects.filter(
            pk=conversation.context_origin_id, prospect_id=conversation.prospect_id
        ).first()
        if origin:
            origin_sources = conversation_sources(origin)
            origin_history = [{"role": m.role, "text": message_projection(m)["text"]}
                              for m in visible_messages(origin).filter(is_error=False)]
    return {
        "revision": conversation.revision,
        "public_sources": {**origin_sources, **conversation_sources(conversation), **versions([proposal.property_id] if proposal else [])},
        "search_attended": bool(search and search.resolved_at),
        "input_message_id": latest.pk if latest else None,
        "continuity": previous.continuity if previous and not message_projection(previous)["changed"] else None,
        "visit_proposal": proposal_output(proposal) if proposal else None,
        "messages": history,
        "origin_history": origin_history,
        "shown_property_ids": shown_property_ids,
        "interest_action": message_projection(latest)["properties"][0] if latest and latest.kind == "property_interest" and message_projection(latest)["properties"] else None,
        "name_requested": conversation.name_requested,
        "criteria": conversation.criteria,
        "contact_registered": bool(conversation.declared_phone),
        "interest_expressed": conversation.interest_expressed,
        "contact_name": conversation.contact_name
        or (
            conversation.prospect.name
            if conversation.channel == "whatsapp" and conversation.prospect_id
            else ""
        ),
        "human_requested": conversation.human_requested,
        "pending_contact": bool(conversation.contact_candidate),
        "appointments": [
            {
                "id": str(a.pk),
                "property_id": a.property_id,
                "status": a.status,
                "start": a.start.isoformat(),
                "end": a.end.isoformat(),
            }
            for a in conversation.appointments.all()
        ],
        "channel": conversation.channel,
    }
