"""Claim, draft and deliver one scheduled follow-up without network under SQL locks."""

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from datalayer.followups import context, due_date, eligible, snapshot, template_options
from datalayer.models import FollowupAttempt, Message, WhatsAppDelivery
from harness.followups import select_template
from llm_ops.executions import start_execution


def skip(attempt, reason, status="skipped"):
    attempt.status, attempt.reason = status, reason
    attempt.save(update_fields=["status", "reason", "updated_at"])


def current(attempt):
    if due_date(attempt.cycle, attempt.day) != attempt.due_at:
        return "schedule_changed"
    if timezone.now() >= attempt.expires_at:
        return "expired"
    return eligible(attempt.cycle, timezone.now())


def process(attempt_id, *, model=None, transport=None):
    from worker.whatsapp import deliver

    with transaction.atomic():
        attempt = (
            FollowupAttempt.objects.select_for_update()
            .select_related("cycle__conversation", "cycle__prospect")
            .get(pk=attempt_id)
        )
        if attempt.delivery_id:
            delivery_id = attempt.delivery_id
        elif attempt.status != "queued":
            return
        else:
            reason = current(attempt)
            if reason:
                skip(attempt, reason)
                return
            options = template_options(attempt.cycle)
            if not options:
                skip(attempt, "no_approved_contextual_template", "review")
                return
            attempt.snapshot = snapshot(attempt.cycle)
            attempt.status = "preparing"
            attempt.execution = start_execution(
                conversation=attempt.cycle.conversation,
                revision=attempt.cycle.conversation.revision,
                model=settings.ANTHROPIC_MODEL,
                purpose="followup",
            )
            attempt.save()
            data = context(attempt.cycle)
            delivery_id = None
    if delivery_id is not None:
        deliver(delivery_id, client=transport)
        return
    try:
        selected = select_template(data, options, attempt.execution, client=model)
    except Exception:
        FollowupAttempt.objects.filter(pk=attempt_id, status="preparing").update(
            status="review", reason="invalid_or_failed_generation", updated_at=timezone.now()
        )
        return
    with transaction.atomic():
        attempt = (
            FollowupAttempt.objects.select_for_update()
            .select_related("cycle__conversation", "cycle__prospect")
            .get(pk=attempt_id)
        )
        if attempt.status != "preparing":
            return
        reason = current(attempt)
        if reason or snapshot(attempt.cycle) != attempt.snapshot:
            skip(attempt, reason or "context_changed")
            return
        if selected not in template_options(attempt.cycle):
            skip(attempt, "template_changed", "review")
            return
        msg = Message.objects.create(
            conversation=attempt.cycle.conversation, role="assistant", text=selected["text"]
        )
        delivery = WhatsAppDelivery.objects.create(
            conversation=attempt.cycle.conversation,
            message=msg,
            event_key=f"followup:{attempt.cycle_id}:{attempt.day}",
            recipient=attempt.cycle.prospect.phone.lstrip("+"),
            payload={
                "type": "template",
                "template": {
                    "name": selected["name"],
                    "language": {"code": selected["language"]},
                    "components": [
                        {
                            "type": "body",
                            "parameters": [{"type": "text", "text": v} for v in selected["values"]],
                        }
                    ],
                },
            },
        )
        attempt.delivery, attempt.status = delivery, "prepared"
        attempt.save(update_fields=["delivery", "status", "updated_at"])
    deliver(delivery.pk, client=transport)
