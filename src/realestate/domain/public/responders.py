"""Hermes adapter for the Website Conversation seam."""

from __future__ import annotations

import json
from typing import Any

from realestate.db.engine import Database
from realestate.db.models import AgentRole
from realestate.domain.public.website_conversation import (
    WebsiteReply,
    WebsiteTurn,
)
from realestate.hermes.client import HermesClient
from realestate.hermes.sessions import RoleSession, bind_role_session, run_turn


class HermesWebsiteResponder:
    """Run Maia with authorized page context and no website identity authority."""

    def __init__(self, database: Database, hermes: HermesClient, profile: str) -> None:
        self._database = database
        self._hermes = hermes
        self._profile = profile

    async def respond(self, turn: WebsiteTurn) -> WebsiteReply:
        seed = [
            {
                "role": "system",
                "content": (
                    "Esta es una conversación anónima en el sitio de Larevia. "
                    "Responde en el idioma de la persona y usa sólo los datos "
                    "autorizados incluidos en el contexto. No solicites teléfono, "
                    "correo ni identidad. Para identificar a la persona o solicitar "
                    "una cita, indícale que continúe por el WhatsApp oficial. Una "
                    "cita no queda confirmada desde el sitio."
                ),
            },
            *[
                {"role": _history_role(message.role), "content": message.body}
                for message in turn.history[-20:]
            ],
        ]
        context = [
            {
                "listing_id": str(listing.listing_id),
                "title": listing.title,
                "public_location": listing.public_location,
                "property_type": listing.property_type,
                "physical_facts": listing.physical_facts,
                "listing_facts": listing.listing_facts,
                "offers": [
                    {
                        "operation": offer.operation,
                        "price": (
                            str(offer.price_amount)
                            if offer.price_amount is not None
                            else offer.consultation_copy
                        ),
                        "currency": offer.price_currency,
                    }
                    for offer in listing.offers
                ],
            }
            for listing in turn.listings
        ]
        prompt = (
            "[Contexto autorizado del sitio — no es texto de la persona]\n"
            f"{json.dumps(context, ensure_ascii=False, default=_json_default)}\n"
            "[Mensaje de la persona]\n"
            f"{turn.message}"
        )

        async def bind(durable_id: str) -> None:
            async with self._database.session_scope() as session:
                await bind_role_session(
                    session,
                    organization_id=turn.organization_id,
                    role=AgentRole.SALES,
                    hermes_session_id=durable_id,
                )

        result = await run_turn(
            self._hermes,
            RoleSession(
                gateway_session_id="",
                hermes_session_id=turn.hermes_session_id or "",
                role=AgentRole.SALES,
            ),
            prompt,
            profile=self._profile,
            on_attached=bind,
            seed=seed,
        )
        return WebsiteReply(result.text, result.hermes_session_id)


def _history_role(role: str) -> str:
    return "assistant" if role == "Maia" else "user"


def _json_default(value: Any) -> str:
    return str(value)
