"""Queue policy; the caller's database transaction also commits the queued job."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from procrastinate import exceptions


def enqueue_conversation(conversation_id):
    from worker.tasks import attend_conversation

    try:
        # A savepoint lets an existing queued job absorb another incoming message.
        with transaction.atomic():
            attend_conversation.configure(
                priority=10,
                lock=f"conversation:{conversation_id}",
                queueing_lock=f"conversation:{conversation_id}",
                schedule_at=timezone.now() + timedelta(seconds=3),
            ).defer(conversation_id=str(conversation_id))
    except exceptions.AlreadyEnqueued:
        pass


def enqueue_easybroker(run_id, *, at=None):
    from worker.tasks import sync_easybroker

    try:
        with transaction.atomic():
            sync_easybroker.configure(
                lock="easybroker-global", queueing_lock=f"easybroker:{run_id}",
                priority=-20, schedule_at=at or timezone.now(),
            ).defer(run_id=str(run_id))
    except exceptions.AlreadyEnqueued:
        pass


def enqueue_followup(attempt_id):
    from worker.tasks import process_followup

    try:
        with transaction.atomic():
            process_followup.configure(
                lock="followup-global", queueing_lock=f"followup:{attempt_id}", priority=-10
            ).defer(attempt_id=attempt_id)
    except exceptions.AlreadyEnqueued:
        pass


def enqueue_whatsapp_event(event_id):
    from worker.tasks import process_whatsapp_event

    try:
        with transaction.atomic():
            process_whatsapp_event.configure(
                lock=f"wa-event:{event_id}", queueing_lock=f"wa-event:{event_id}", priority=20
            ).defer(event_id=event_id)
    except exceptions.AlreadyEnqueued:
        pass


def enqueue_whatsapp_delivery(delivery_id):
    from worker.tasks import send_whatsapp

    try:
        with transaction.atomic():
            send_whatsapp.configure(
                lock=f"wa-delivery:{delivery_id}",
                queueing_lock=f"wa-delivery:{delivery_id}",
                priority=10,
            ).defer(delivery_id=str(delivery_id))
    except exceptions.AlreadyEnqueued:
        pass


def enqueue_notification(notification_id):
    from worker.tasks import deliver_telegram_notification

    try:
        with transaction.atomic():
            deliver_telegram_notification.configure(
                lock=f"notification:{notification_id}",
                queueing_lock=f"notification:{notification_id}",
            ).defer(notification_id=notification_id)
    except exceptions.AlreadyEnqueued:
        pass


def enqueue_appointment(operation_id):
    from worker.tasks import process_appointment

    try:
        with transaction.atomic():
            process_appointment.configure(
                lock=f"visit-op:{operation_id}", queueing_lock=f"visit-op:{operation_id}"
            ).defer(operation_id=str(operation_id))
    except exceptions.AlreadyEnqueued:
        pass


def enqueue_inspection(appointment_id):
    from worker.tasks import inspect_appointment

    try:
        with transaction.atomic():
            inspect_appointment.configure(
                lock=f"visit:{appointment_id}", queueing_lock=f"inspect:{appointment_id}"
            ).defer(appointment_id=str(appointment_id))
    except exceptions.AlreadyEnqueued:
        pass
