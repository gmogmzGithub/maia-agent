"""Staff-only read models. None of these projections are returned to the public chat."""

from datalayer.conversations import message_output
from datalayer.prospects import is_paused


def crm_conversation(conversation):
    return {
        "id": conversation.pk,
        "prospect_id": conversation.prospect_id,
        "phone": conversation.declared_phone,
        "name": conversation.contact_name,
        "human_requested": conversation.human_requested,
        "automation_paused": is_paused(conversation),
        "conversation_paused": conversation.automation_paused,
        "advisor_id": conversation.prospect.advisor_id
        if conversation.prospect_id
        else conversation.advisor_id,
        "criteria": conversation.criteria,
        "property_ids": list(conversation.interests.values_list("pk", flat=True)),
        "messages": [message_output(m) for m in conversation.messages.all()],
        "notifications": [
            notification_output(n) for n in conversation.notifications.order_by("-created_at")
        ],
        "created_at": conversation.created_at.isoformat(),
        "channel": conversation.channel,
        "deliveries": [
            {
                "id": str(d.pk),
                "status": d.status,
                "error_code": d.error_code,
                "message_id": d.message_id,
                "created_at": d.created_at.isoformat(),
            }
            for d in conversation.whatsapp_deliveries.order_by("created_at")
        ],
    }


def notification_output(notification):
    return {
        "id": notification.pk,
        "reason": notification.reason,
        "summary": notification.summary,
        "status": notification.status,
        "error_code": notification.error_code,
        "attempts": notification.attempts,
        "created_at": notification.created_at.isoformat(),
    }


def prospect_output(prospect, detail=False):
    result = {
        "id": prospect.pk,
        "phone": prospect.phone,
        "name": prospect.name,
        "advisor_id": prospect.advisor_id,
        "status": prospect.status,
        "criteria": prospect.criteria,
        "next_step": prospect.next_step,
        "automation_paused": prospect.automation_paused,
        "property_ids": list(prospect.properties.values_list("pk", flat=True)),
        "created_at": prospect.created_at.isoformat(),
        "updated_at": prospect.updated_at.isoformat(),
    }
    if detail:
        from datalayer.followups import output

        result["followup"] = output(prospect)
        result["conversations"] = [
            crm_conversation(c) for c in prospect.conversations.order_by("-created_at")
        ]
        result["events"] = [
            {
                "description": e.description,
                "actor": e.actor.email if e.actor_id else "Maia",
                "created_at": e.created_at.isoformat(),
            }
            for e in prospect.events.select_related("actor").order_by("-created_at")
        ]
    return result
