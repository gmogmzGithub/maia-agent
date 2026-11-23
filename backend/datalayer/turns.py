"""Short turn transactions: acquire a snapshot, then atomically publish a reply."""

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from datalayer.memory import read_memory
from datalayer.models import Conversation, Message
from datalayer.prospects import is_paused
from llm_ops.executions import finish_execution, log_execution, start_execution


async def pending_turn_delay(conversation_id):
    conversation = await Conversation.objects.aget(pk=conversation_id)
    latest = await conversation.messages.filter(role="user").alast()
    if not latest or not conversation.pending_since:
        return 0
    quiet_until = latest.created_at.timestamp() + 3
    ceiling = conversation.pending_since.timestamp() + 10
    return min(quiet_until, ceiling) - timezone.now().timestamp()


def load_turn(conversation_id):
    with transaction.atomic():
        conversation = Conversation.objects.select_for_update(no_key=True).get(pk=conversation_id)
        if conversation.revision <= conversation.answered_revision or is_paused(conversation):
            return None
        snapshot = read_memory(conversation)
        execution = start_execution(
            conversation=conversation,
            revision=conversation.revision,
            model=settings.ANTHROPIC_MODEL,
        )
        return {**snapshot, "execution_id": execution.pk}


def finish_turn(
    conversation_id,
    turn,
    text,
    cards,
    status,
    usage,
    elapsed_ms,
    events,
    error_code="",
    *,
    reply=None,
):
    with transaction.atomic():
        conversation = Conversation.objects.select_for_update(no_key=True).get(pk=conversation_id)
        if (
            conversation.revision != turn["revision"]
            or conversation.answered_revision >= turn["revision"]
            or is_paused(conversation)
        ):
            status = "superseded"
        else:
            from datalayer.public_history import accept_reply

            accepted = accept_reply(conversation, turn, text, cards, reply)
            if accepted.validation_failed:
                events.append({"tool": "reply_validation", "outcome": "state_changed"})
            message = Message.objects.create(
                conversation=conversation,
                role="assistant",
                is_error=status == "failed",
                **accepted.message_fields,
            )
            conversation.answered_revision = turn["revision"]
            conversation.pending_since = None
            conversation.save(update_fields=["answered_revision", "pending_since", "updated_at"])
            if conversation.channel == "whatsapp":
                from datalayer.whatsapp import queue_reply

                queue_reply(conversation, message)
        finish_execution(turn["execution_id"], status, usage, elapsed_ms, events, error_code)
    log_execution(conversation_id, turn["execution_id"], status, usage, elapsed_ms, error_code)
