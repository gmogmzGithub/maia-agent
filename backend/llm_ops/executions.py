"""Execution records and operational logs, independent of the customer journey."""

import logging

from datalayer.models import Execution

logger = logging.getLogger(__name__)


def start_execution(**values):
    return Execution.objects.create(**values)


def finish_execution(execution_id, status, usage, elapsed_ms, events, error_code):
    Execution.objects.filter(pk=execution_id).update(
        status=status,
        input_tokens=usage[0],
        output_tokens=usage[1],
        elapsed_ms=elapsed_ms,
        tool_events=events,
        error_code=error_code,
    )


def log_execution(conversation_id, execution_id, status, usage, elapsed_ms, error_code):
    logger.info(
        "conversation_run conversation=%s run=%s status=%s input_tokens=%s output_tokens=%s elapsed_ms=%s error=%s",
        conversation_id,
        execution_id,
        status,
        usage[0],
        usage[1],
        elapsed_ms,
        error_code,
    )
