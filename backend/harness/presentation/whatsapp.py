"""Pure WhatsApp formatting and length checks. No database, queue or network."""

from harness.presentation.properties import property_text


def render_reply(blocks, cards, *, criteria, base_url, visit=None):
    """Render exactly the accepted presentation. No implicit controls or truncation."""
    by_id = {card["id"]: card for card in cards}
    parts, proposal = [], None
    for block in blocks:
        if block["kind"] == "text":
            parts.append(block["text"])
        elif block["kind"] == "properties":
            parts.extend(property_text(by_id[i], criteria, base_url)
                         for i in block["property_ids"])
        elif block["kind"] == "contact":
            raise ValueError("website contact control cannot be sent to WhatsApp")
        elif block["kind"] == "visit":
            proposal = visit
            if not proposal or proposal["id"] != block["proposal_id"]:
                raise ValueError("visit proposal is no longer available")
    text = "\n\n".join(parts)
    if proposal:
        action = {"create": "Confirmar visita", "move": "Reprogramar visita",
                  "cancel": "Cancelar visita"}[proposal["action"]]
        summary = proposal["summary"]
        body = summary + "\n\n" + text
        if len(body) > 1024:
            raise ValueError("interactive WhatsApp reply exceeds 1024 characters; shorten text")
        return {"type": "interactive", "interactive": {"type": "button", "body": {"text": body},
                "action": {"buttons": [{"type": "reply", "reply": {
                    "id": "visit:" + proposal["id"], "title": action}}]}}}
    if len(text) > 4096:
        raise ValueError("WhatsApp reply exceeds 4096 characters; shorten text or show fewer cards")
    return {"type": "text", "text": {"body": text, "preview_url": False}}
