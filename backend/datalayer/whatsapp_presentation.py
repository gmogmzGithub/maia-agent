"""Read current, conversation-owned data for the WhatsApp presentation adapter."""

from django.conf import settings

from datalayer.appointments import visit_time
from datalayer.booking_tools import pending_visit_proposal
from harness.presentation.whatsapp import render_reply


def visit_snapshot(proposal):
    if not proposal:
        return None
    return {
        "id": str(proposal.pk), "action": proposal.action,
        "summary": (f"Tu visita a {proposal.property.title}\n"
                    f"{visit_time(proposal.start, proposal.end)}, hora de Guadalajara.\n"
                    f"Con {proposal.advisor.name} · "
                    f"{int((proposal.end - proposal.start).total_seconds() // 60)} minutos."),
    }


def structured_payload(conversation, blocks, cards):
    visit = (visit_snapshot(pending_visit_proposal(conversation.pk))
             if any(b["kind"] == "visit" for b in blocks) else None)
    return render_reply(blocks, cards, criteria=conversation.criteria,
                        base_url=settings.PUBLIC_BASE_URL, visit=visit)
