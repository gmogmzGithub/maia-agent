"""Telegram delivery. A send with an uncertain result is never blindly retried."""

import logging

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from datalayer.models import Advisor, Conversation, Notification, Prospect

logger = logging.getLogger(__name__)
REASONS = {
    "new_prospect": "Nuevo prospecto",
    "new_interest": "Nuevo interés",
    "human_request": "Solicita atención humana",
    "paused_message": "Mensaje recibido con Maia pausada",
    "appointment": "Cita y seguimiento de visita",
}


def claim_notification(notification_id):
    with transaction.atomic():
        event = Notification.objects.select_for_update().get(pk=notification_id)
        if event.status not in {"pending", "failed", "blocked"}:
            return None
        conversation = (
            Conversation.objects.select_for_update(of=("self",))
            .select_related("advisor")
            .get(pk=event.conversation_id)
        )
        owner = (
            Prospect.objects.select_for_update(of=("self",))
            .select_related("advisor")
            .get(pk=conversation.prospect_id)
            if conversation.prospect_id
            else conversation
        )
        advisor = event.advisor if event.reason == "appointment" else owner.advisor
        if advisor is None:
            advisor = Advisor.objects.filter(is_default=True).first()
            if advisor:
                owner.advisor = advisor
                owner.save(update_fields=["advisor", "updated_at"])
        event.advisor = advisor
        if not settings.TELEGRAM_BOT_TOKEN or not advisor or not advisor.telegram_chat_id:
            event.status = "blocked"
            event.error_code = (
                "telegram_not_configured"
                if not settings.TELEGRAM_BOT_TOKEN
                else "advisor_not_configured"
            )
            event.save(update_fields=["advisor", "status", "error_code", "updated_at"])
            logger.warning(
                "telegram_delivery notification=%s status=blocked error=%s",
                event.pk,
                event.error_code,
            )
            return None
        titles = list(conversation.interests.values_list("title", flat=True))
        summary = (
            event.summary
            or conversation.messages.filter(role="user")
            .order_by("-id")
            .values_list("text", flat=True)
            .first()
            or "Sin resumen disponible."
        )
        link = f"{settings.PUBLIC_BASE_URL}/crm?conversation={conversation.pk}"
        visit = event.payload.get("_visit")
        attention = event.reason in {"human_request", "paused_message"} or bool(
            visit and visit["attention"]
        )
        heading = visit["headline"] if visit else REASONS.get(event.reason, event.reason)
        lines = [heading, "Requiere atención" if attention else "Información"]
        if visit:
            lines.extend([visit["property"], visit["when"] + ", hora de Guadalajara"])
            if visit["attention"]:
                lines.append(summary[:1000])
        else:
            lines.append(summary[:1000])
            if titles:
                lines.append("Propiedades: " + ", ".join(titles)[:1200])
        if conversation.contact_name:
            lines.append("Cliente: " + conversation.contact_name)
        if conversation.declared_phone:
            lines.append("Contacto: " + conversation.declared_phone)
            if conversation.channel != "whatsapp":
                lines.append("Celular declarado en website; identidad sin verificar.")
        lines.append("Abrir conversación en CRM: " + link)
        outgoing = {
            "chat_id": advisor.telegram_chat_id,
            "text": "\n".join(lines),
            "link_preview_options": {"is_disabled": True},
        }
        event.payload = {**outgoing, **({"_visit": visit} if visit else {})}
        event.status = "sending"
        event.error_code = ""
        event.attempts += 1
        event.save(
            update_fields=["advisor", "payload", "status", "error_code", "attempts", "updated_at"]
        )
        return outgoing


def finish_notification(notification_id, status, error_code="", message_id=""):
    Notification.objects.filter(pk=notification_id, status="sending").update(
        status=status,
        error_code=error_code,
        telegram_message_id=str(message_id),
        updated_at=timezone.now(),
    )
    logger.info(
        "telegram_delivery notification=%s status=%s error=%s", notification_id, status, error_code
    )


def deliver_notification(notification_id, client=None):
    payload = claim_notification(notification_id)
    if payload is None:
        return
    owned = client is None
    client = client or httpx.Client(timeout=12, follow_redirects=False)
    sending = False
    try:
        base = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"
        # Validate a private destination before transmitting any customer information.
        check = client.post(base + "/getChat", json={"chat_id": payload["chat_id"]})
        chat = check.json()
        if not chat.get("ok"):
            finish_notification(notification_id, "failed", "private_chat_unavailable")
            return
        if chat["result"].get("type") != "private" or str(chat["result"].get("id")) != str(
            payload["chat_id"]
        ):
            finish_notification(notification_id, "failed", "private_chat_required")
            return
        sending = True
        response = client.post(base + "/sendMessage", json=payload)
        data = response.json()
        if data.get("ok") and data.get("result", {}).get("message_id"):
            finish_notification(notification_id, "sent", message_id=data["result"]["message_id"])
        elif data.get("ok") is False and 400 <= data.get("error_code", 0) < 500:
            finish_notification(notification_id, "failed", f"telegram_{data['error_code']}")
        else:
            finish_notification(notification_id, "uncertain", "send_result_unknown")
    except httpx.ConnectError:
        finish_notification(notification_id, "failed", "connection_failed")
    except Exception as exc:
        # Never log the exception text: provider URLs contain the bot token.
        finish_notification(
            notification_id, "uncertain" if sending else "failed", type(exc).__name__
        )
    finally:
        if owned:
            client.close()
