"""Factual recovery after exhausted output repair; never executes business tools."""

from datalayer.schemas import ReplyProposal


def recovery_reply(cards, control=None):
    blocks = [{"kind": "text", "text": (
        "Te comparto las opciones encontradas. Podemos continuar desde aquí."
        if cards else
        "Tu mensaje quedó guardado. No pude preparar la respuesta; puedes seguir escribiéndome."
    )}]
    if cards:
        blocks.append({"kind": "properties", "property_ids": [p["id"] for p in cards]})
    pending = None
    if control:
        blocks[0]["text"] = ("Revisa tu número y confírmalo aquí. Puedes seguir conversando."
                             if control["kind"] == "contact" else
                             "Revisa los datos y confirma aquí.")
        blocks.append(control)
        pending = {"kind": "contact_confirmation" if control["kind"] == "contact"
                   else "visit_confirmation", "subject": "confirmación pendiente"}
    return ReplyProposal.model_validate({"blocks": blocks, "continuity": {
        "purpose": "continuar desde los resultados comprobados", "pending": pending,
    }})
