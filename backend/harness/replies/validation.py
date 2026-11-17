"""Pure reply acceptance from authorized facts. No ORM, writes or channel delivery."""

from dataclasses import dataclass
from uuid import UUID

from datalayer.schemas import ReplyProposal
from harness.presentation.properties import repeats_card_details


@dataclass(frozen=True)
class ReplyFacts:
    channel: str
    contact_name: str
    contact_registered: bool
    interest_expressed: bool
    human_requested: bool
    visit_id: UUID | None


def validate_proposal(value, available_cards, facts):
    proposal = ReplyProposal.model_validate(value)
    by_id = {card["id"]: card for card in available_cards}
    ids = [i for b in proposal.blocks for i in b.property_ids]
    if not set(ids) <= by_id.keys():
        raise ValueError("property reference not authorized for presentation this turn")
    cards = [by_id[i] for i in ids]
    text = "\n\n".join(b.text.strip() for b in proposal.blocks if b.kind == "text")
    if available_cards and repeats_card_details(text, available_cards):
        raise ValueError("leave property facts in cards, not repeated in text")
    pending = proposal.continuity.pending
    if pending and pending.kind == "name":
        known_name = facts.contact_name
        if known_name:
            raise ValueError("name is already known")
    control = next((b for b in proposal.blocks if b.kind in {"contact", "visit"}), None)
    if control and control.kind == "contact":
        if (facts.channel != "website" or facts.contact_registered
                or not (facts.interest_expressed or facts.human_requested)):
            raise ValueError("contact control not available in this conversation")
        if not pending or pending.kind not in {"contact", "contact_confirmation"}:
            raise ValueError("contact control must match the next interaction")
    if control and control.kind == "visit":
        visit = facts.visit_id
        if not visit or visit != control.proposal_id or not facts.contact_registered:
            raise ValueError("visit control requires the current conversation-owned proposal")
        if not pending or pending.kind != "visit_confirmation":
            raise ValueError("visit control must match the next interaction")
    if pending and pending.kind in {"contact_confirmation", "visit_confirmation"}:
        expected = "contact" if pending.kind == "contact_confirmation" else "visit"
        if not control or control.kind != expected:
            raise ValueError("confirmation requires its corresponding control")
    return proposal, text, cards
