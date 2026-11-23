from procrastinate.contrib.django import app


@app.task(name="sync_easybroker", queue="easybroker")
def sync_easybroker(run_id: str):
    from worker.easybroker import process

    process(run_id)


@app.periodic(cron="* * * * *")
@app.task(name="maintain_easybroker", queue="maintenance", queueing_lock="maintain-easybroker")
def maintain_easybroker(timestamp: int):
    from datalayer.easybroker.publication import expire_imports
    from datalayer.easybroker.sync import maintain

    expire_imports()
    maintain()


@app.periodic(cron="17 * * * *")
@app.task(
    name="maintain_google_locations", queue="maintenance", queueing_lock="maintain-google-locations"
)
def maintain_google_locations(timestamp: int):
    from datalayer.google_locations import maintain

    maintain()


@app.task(name="attend_conversation", queue="conversations")
async def attend_conversation(conversation_id: str):
    from harness.runtime import attend

    await attend(conversation_id)


@app.task(name="deliver_telegram_notification", queue="notifications")
def deliver_telegram_notification(notification_id: int):
    from worker.telegram import deliver_notification

    deliver_notification(notification_id)


@app.task(name="process_appointment", queue="appointments")
def process_appointment(operation_id: str):
    from worker.appointments import process

    process(operation_id)


@app.task(name="inspect_appointment", queue="appointments")
def inspect_appointment(appointment_id: str):
    from worker.appointments import inspect_appointment as inspect

    inspect(appointment_id)


@app.periodic(cron="* * * * *")
@app.task(name="maintain_appointments", queue="appointments", queueing_lock="maintain-appointments")
def maintain_appointments(timestamp: int):
    from worker.appointments import maintain

    maintain()


@app.periodic(cron="* * * * *")
@app.task(name="maintain_followups", queue="followups", queueing_lock="maintain-followups")
def maintain_followups(timestamp: int):
    from datalayer.followups import maintain
    from worker.whatsapp import recover

    maintain()
    recover()


@app.task(name="process_followup", queue="followups")
def process_followup(attempt_id: int):
    from worker.followups import process

    process(attempt_id)


@app.task(name="process_whatsapp_event", queue="whatsapp")
def process_whatsapp_event(event_id: int):
    from datalayer.whatsapp import process_event

    process_event(event_id)


@app.task(name="send_whatsapp", queue="whatsapp")
def send_whatsapp(delivery_id: str):
    from worker.whatsapp import deliver

    deliver(delivery_id)


@app.task(name="deliver_capture_message", queue="notifications")
def deliver_capture_message(delivery_id: int):
    from worker.capture_delivery import deliver

    deliver(delivery_id)


@app.periodic(cron="* * * * *")
@app.task(name="maintain_captures", queue="notifications", queueing_lock="maintain-captures")
def maintain_captures(timestamp: int):
    from datetime import timedelta

    from django.utils import timezone

    from datalayer.captures import expire
    from datalayer.models import AccountThrottle, Capture, CaptureDelivery

    for capture_id in Capture.objects.filter(status__in=["accepted", "published"]).values_list(
        "pk", flat=True
    ):
        expire(capture_id)
    CaptureDelivery.objects.filter(
        status="sending", updated_at__lt=timezone.now() - timedelta(minutes=10)
    ).update(status="uncertain", error_code="interrupted_send")
    AccountThrottle.objects.filter(started_at__lt=timezone.now() - timedelta(days=1)).delete()
