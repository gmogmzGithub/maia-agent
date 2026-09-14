"""Durable asynchronous execution for anonymous website conversation turns."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from realestate.db.engine import Database
from realestate.db.models import WebsiteTurnRequest, WebsiteTurnStatus
from realestate.domain.clock import utc_now
from realestate.domain.commercial.actors import Actor
from realestate.domain.public.responders import HermesWebsiteResponder
from realestate.domain.public.website_conversation import (
    WebsiteConversation,
    WebsiteConversationResult,
    WebsiteResponder,
)
from realestate.hermes.client import HermesClient

logger = logging.getLogger(__name__)


class WebsiteConversationWorker:
    """Claim one queued web turn per tick and persist its terminal result."""

    def __init__(
        self,
        database: Database,
        hermes: HermesClient,
        profile: str,
        *,
        responder: WebsiteResponder | None = None,
    ) -> None:
        self._database = database
        self._hermes = hermes
        self._profile = profile
        self._responder = responder

    async def tick(self) -> bool:
        async with self._database.session_scope() as session:
            request = await session.scalar(
                select(WebsiteTurnRequest)
                .where(WebsiteTurnRequest.status == WebsiteTurnStatus.PENDING.value)
                .order_by(WebsiteTurnRequest.created_at, WebsiteTurnRequest.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if request is None:
                return False
            request.status = WebsiteTurnStatus.RUNNING.value
            request.attempts += 1
            request.started_at = utc_now()
            request_id = request.id
            await session.commit()

        try:
            async with self._database.session_scope() as session:
                request = await session.get(WebsiteTurnRequest, request_id)
                if request is None:
                    return False
                result = await WebsiteConversation(
                    session,
                    Actor.product(request.organization_id, "WebsiteConversationWorker"),
                    self._responder
                    or HermesWebsiteResponder(
                        self._database, self._hermes, self._profile
                    ),
                ).perform_request(request, at=utc_now())
                request.status = WebsiteTurnStatus.COMPLETE.value
                request.result = _result_payload(result)
                request.error_message = None
                request.completed_at = utc_now()
                await session.commit()
                return True
        except Exception:
            logger.exception("Website conversation turn failed (turn=%s)", request_id)
            async with self._database.session_scope() as session:
                request = await session.get(WebsiteTurnRequest, request_id)
                if request is not None:
                    request.status = WebsiteTurnStatus.FAILED.value
                    request.error_message = (
                        "No pudimos completar la respuesta. Inténtalo de nuevo."
                    )
                    request.completed_at = utc_now()
                    await session.commit()
            return False


def _result_payload(result: WebsiteConversationResult) -> dict[str, Any]:
    return {
        "conversation_id": str(result.conversation_id),
        "reply": result.reply,
        "messages": [
            {
                "role": message.role,
                "body": message.body,
                "created_at": message.created_at.isoformat(),
            }
            for message in result.messages
        ],
        "requires_verified_channel": result.requires_verified_channel,
        "criteria": result.criteria,
        "listing_ids": [str(item) for item in result.listing_ids],
        "total": result.total,
        "public_url": result.public_url,
        "matches": list(result.matches),
    }
