"""Stable rejection reasons. Never persist model text or validation input values."""

from pydantic import ValidationError

_REASONS = {
    "generation truncated; no calls executed": "generation_truncated",
    "finish using propose_reply, not free text": "missing_final_tool",
    "unexpected stop reason for a tool batch": "unexpected_stop_reason",
    "propose_reply must be the only tool in its response": "mixed_final_batch",
    "output repair cannot execute business tools": "repair_business_tool",
    "property reference not authorized for presentation this turn": "unauthorized_card",
    "leave property facts in cards, not repeated in text": "repeated_card_details",
    "name is already known": "known_name_requested",
    "contact control not available in this conversation": "contact_unavailable",
    "contact control must match the next interaction": "contact_pending_mismatch",
    "visit control requires the current conversation-owned proposal": "visit_unavailable",
    "visit control must match the next interaction": "visit_pending_mismatch",
    "confirmation requires its corresponding control": "missing_confirmation_control",
    "website contact control cannot be sent to WhatsApp": "wrong_channel_control",
    "visit proposal is no longer available": "visit_expired",
    "interactive WhatsApp reply exceeds 1024 characters; shorten text": "interactive_too_long",
    "WhatsApp reply exceeds 4096 characters; shorten text or show fewer cards": "text_too_long",
}


def rejection_reason(error):
    if isinstance(error, ValidationError):
        return "invalid_reply_schema"
    return _REASONS.get(str(error), "invalid_reply")
