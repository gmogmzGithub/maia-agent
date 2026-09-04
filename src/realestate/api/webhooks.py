"""Authenticated Meta customer-channel webhooks (ADR-0005, TC-003, TC-006).

Two routes on one path:

* ``GET`` — Meta's subscription handshake. Echoes ``hub.challenge`` only when
  the verify token matches.
* ``POST`` — inbound messages and delivery statuses. The body is authenticated
  with Meta's signature over the **raw bytes**, then persisted, and only then
  acknowledged. If persistence fails the endpoint must not answer 200: Meta
  should retry rather than have the message silently lost.

This route deliberately does not share the Developer Basic credential that
protects the upload page; it authenticates with Meta's signature instead
(P-051).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import PlainTextResponse

from realestate.channels.messaging import InboundCustomerMessage
from realestate.channels.instagram.payload import parse_webhook as parse_instagram_webhook
from realestate.channels.messenger.payload import parse_webhook as parse_messenger_webhook
from realestate.channels.whatsapp.payload import parse_webhook as parse_whatsapp_webhook
from realestate.channels.whatsapp.signature import SIGNATURE_HEADER, is_valid_signature
from realestate.config import get_settings
from realestate.domain.commercial.actors import CommercialError
from realestate.domain.inbox import InboxService
from realestate.domain.outbox import OutboxService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])

WEBHOOK_PATH = "/webhooks/whatsapp"
MESSENGER_WEBHOOK_PATH = "/webhooks/messenger"
INSTAGRAM_WEBHOOK_PATH = "/webhooks/instagram"


@router.get(WEBHOOK_PATH, response_class=PlainTextResponse)
@router.get(MESSENGER_WEBHOOK_PATH, response_class=PlainTextResponse)
@router.get(INSTAGRAM_WEBHOOK_PATH, response_class=PlainTextResponse)
async def verify_webhook(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
) -> Response:
    """Meta's subscription handshake."""
    settings = get_settings()
    expected = settings.meta_verify_token
    if hub_mode == "subscribe" and expected and hub_verify_token == expected:
        return PlainTextResponse(hub_challenge)
    logger.warning("Rejected a webhook verification attempt (mode=%r)", hub_mode)
    return PlainTextResponse("forbidden", status_code=status.HTTP_403_FORBIDDEN)


@router.post(WEBHOOK_PATH)
async def receive_webhook(request: Request, response: Response) -> dict[str, object]:
    settings = get_settings()
    raw_body = await request.body()

    if not is_valid_signature(
        settings.meta_app_secret, raw_body, request.headers.get(SIGNATURE_HEADER)
    ):
        # Never persist or acknowledge an unauthenticated body.
        logger.warning("Rejected a webhook payload with an invalid signature")
        response.status_code = status.HTTP_403_FORBIDDEN
        return {"result": "invalid_signature"}

    try:
        body = await request.json()
    except ValueError:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return {"result": "invalid_json"}

    parsed = parse_whatsapp_webhook(body)
    accepted = 0
    duplicates = 0
    unroutable = 0

    async with request.app.state.database.session_scope() as session:
        inbox = InboxService(session)
        for message in parsed.messages:
            try:
                result = await inbox.accept(message)
            except CommercialError as exc:
                # The phone number id is not bound to a Brokerage Organization,
                # or its Organization is not operating. Counted and logged, and
                # deliberately *not* an error status: Meta would retry the same
                # body forever, and the fix is a configuration change here rather
                # than a redelivery. What must never happen is the alternative —
                # attributing the message to whichever Organization happens to
                # exist (ADR-0050).
                unroutable += 1
                logger.error(
                    "Refused an inbound WhatsApp message on phone number id %r: %s",
                    message.phone_number_id,
                    exc.message,
                )
                continue
            if result.duplicate:
                duplicates += 1
                logger.info("Duplicate webhook for %s ignored", message.wamid)
            else:
                accepted += 1
                if result.cycle_created:
                    logger.info("Opened a new Lead Engagement Cycle %s", result.cycle_id)

        outbox = OutboxService(session)
        for update in parsed.statuses:
            try:
                # Routed inside the service, exactly as the message loop above
                # routes inside ``InboxService.accept``: the same refusal, in the
                # same layer, so a fix reaches both paths.
                await outbox.record_delivery_status(
                    phone_number_id=update.phone_number_id,
                    provider_message_id=update.provider_message_id,
                    status=update.status,
                    occurred_at=update.occurred_at,
                    raw=update.raw,
                )
            except CommercialError as exc:
                unroutable += 1
                logger.error(
                    "Refused a delivery status on phone number id %r: %s",
                    update.phone_number_id,
                    exc.message,
                )

    # Reached only when every accepted message is durably stored. An exception
    # above propagates as a 500 and Meta retries.
    return {
        "result": "ok",
        "accepted": accepted,
        "duplicates": duplicates,
        "statuses": len(parsed.statuses),
        "unroutable": unroutable,
    }


@router.post(MESSENGER_WEBHOOK_PATH)
async def receive_messenger_webhook(
    request: Request, response: Response
) -> dict[str, object]:
    """Authenticate, persist, then acknowledge Facebook Page messages."""
    settings = get_settings()
    raw_body = await request.body()
    if not is_valid_signature(
        (settings.meta_messenger_app_secret or settings.meta_app_secret),
        raw_body,
        request.headers.get(SIGNATURE_HEADER),
    ):
        logger.warning("Rejected a Messenger webhook payload with an invalid signature")
        response.status_code = status.HTTP_403_FORBIDDEN
        return {"result": "invalid_signature"}

    try:
        body = await request.json()
    except ValueError:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return {"result": "invalid_json"}

    messages = parse_messenger_webhook(body)
    accepted, duplicates, unroutable = await _accept_customer_messages(
        request, messages, provider_label="Messenger"
    )
    return {
        "result": "ok",
        "accepted": accepted,
        "duplicates": duplicates,
        "statuses": 0,
        "unroutable": unroutable,
    }


@router.post(INSTAGRAM_WEBHOOK_PATH)
async def receive_instagram_webhook(
    request: Request, response: Response
) -> dict[str, object]:
    """Authenticate, persist, then acknowledge Instagram messages."""
    settings = get_settings()
    raw_body = await request.body()
    if not is_valid_signature(
        (settings.meta_instagram_app_secret or settings.meta_app_secret),
        raw_body,
        request.headers.get(SIGNATURE_HEADER),
    ):
        logger.warning("Rejected an Instagram webhook payload with an invalid signature")
        response.status_code = status.HTTP_403_FORBIDDEN
        return {"result": "invalid_signature"}

    try:
        body = await request.json()
    except ValueError:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return {"result": "invalid_json"}

    messages = parse_instagram_webhook(body)
    accepted, duplicates, unroutable = await _accept_customer_messages(
        request, messages, provider_label="Instagram"
    )
    return {
        "result": "ok",
        "accepted": accepted,
        "duplicates": duplicates,
        "statuses": 0,
        "unroutable": unroutable,
    }


async def _accept_customer_messages(
    request: Request,
    messages: Sequence[InboundCustomerMessage],
    *,
    provider_label: str,
) -> tuple[int, int, int]:
    accepted = 0
    duplicates = 0
    unroutable = 0
    async with request.app.state.database.session_scope() as session:
        inbox = InboxService(session)
        for message in messages:
            try:
                result = await inbox.accept(message)
            except CommercialError as exc:
                unroutable += 1
                logger.error(
                    "Refused an inbound %s message on channel account %r: %s",
                    provider_label,
                    message.channel_account_id,
                    exc.message,
                )
                continue
            if result.duplicate:
                duplicates += 1
                logger.info(
                    "Duplicate %s webhook for %s ignored",
                    provider_label,
                    message.provider_message_id,
                )
            else:
                accepted += 1
                if result.cycle_created:
                    logger.info("Opened a new Lead Engagement Cycle %s", result.cycle_id)
    return accepted, duplicates, unroutable
