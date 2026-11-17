"""Validate a complete reply against conversation-owned facts, without business writes."""

from django.db import transaction

from datalayer.booking_tools import pending_visit_proposal
from datalayer.memory import latest_reply
from datalayer.prospects import is_paused


def reply_projection(conversation):
    latest = latest_reply(conversation)
    if not latest:
        return {"structured_reply": True, "active_control": None, "active_proposal_id": None,
                "active_message_id": None}
    if latest.presentation is None:
        return {"structured_reply": False, "active_control": None, "active_proposal_id": None,
                "active_message_id": None}
    control = next((b for b in latest.presentation if b["kind"] in {"contact", "visit"}), None)
    if conversation.revision > conversation.answered_revision or is_paused(conversation):
        control = None
    kind, proposal_id = None, None
    if control and control["kind"] == "contact" and not conversation.declared_phone:
        kind = "contact"
    elif control and control["kind"] == "visit":
        proposal = pending_visit_proposal(conversation.pk)
        if proposal and str(proposal.pk) == control.get("proposal_id"):
            kind, proposal_id = "visit", proposal.pk
    return {"structured_reply": True, "active_control": kind, "active_proposal_id": proposal_id,
            "active_message_id": latest.pk}


def validate_reply(conversation_id, revision, value, available_cards):
    """Short snapshot read. Publishing repeats validation under the conversation lock."""
    from datalayer.errors import Superseded
    from datalayer.models import Conversation
    from datalayer.whatsapp_presentation import structured_payload
    from harness.replies.validation import ReplyFacts, validate_proposal

    with transaction.atomic():
        conversation = Conversation.objects.select_for_update().get(pk=conversation_id)
        if conversation.revision != revision or is_paused(conversation):
            raise Superseded
        visit = pending_visit_proposal(conversation.pk)
        facts = ReplyFacts(
            channel=conversation.channel,
            contact_name=conversation.contact_name or (
                conversation.prospect.name
                if conversation.channel == "whatsapp" and conversation.prospect_id else ""
            ),
            contact_registered=bool(conversation.declared_phone),
            interest_expressed=conversation.interest_expressed,
            human_requested=conversation.human_requested,
            visit_id=visit.pk if visit else None,
        )
        proposal, text, cards = validate_proposal(value, available_cards, facts)
        if conversation.channel == "whatsapp":
            structured_payload(conversation, proposal.model_dump(mode="json")["blocks"], cards)
        return proposal, text, cards
