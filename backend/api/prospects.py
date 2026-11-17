import uuid

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError
from ninja.security import SessionAuthIsStaff

from api.auth import BrowserAuth, browser_id
from datalayer.conversations import conversation_output
from datalayer.crm import crm_conversation, notification_output, prospect_output
from datalayer.models import Advisor, Conversation, Notification, Prospect
from datalayer.prospects import confirm_contact, prepare_contact, save_advisor, update_prospect
from datalayer.schemas import (
    AdvisorInput,
    AdvisorOutput,
    ConfirmContactInput,
    ContactInput,
    ConversationOutput,
    CRMConversation,
    NotificationOutput,
    PauseInput,
    ProspectDetail,
    ProspectOutput,
    ProspectUpdate,
)

crm = Router(auth=SessionAuthIsStaff())
chat = Router(auth=BrowserAuth())


@chat.post("/{conversation_id}/contact/prepare", response=ConversationOutput)
def prepare_website_contact(request, conversation_id: uuid.UUID, data: ContactInput):
    with transaction.atomic():
        conversation = get_object_or_404(
            Conversation.objects.select_for_update(),
            pk=conversation_id,
            browser_id=browser_id(request),
        )
        result = prepare_contact(conversation, data.model_dump())
        if result.get("error"):
            raise HttpError(
                409,
                result.get(
                    "detail", "Primero indica la propiedad que te interesa o solicita un asesor."
                ),
            )
        return conversation_output(conversation)


@chat.post("/{conversation_id}/contact/confirm", response=ConversationOutput)
def confirm_website_contact(request, conversation_id: uuid.UUID, data: ConfirmContactInput):
    get_object_or_404(Conversation, pk=conversation_id, browser_id=browser_id(request))
    return conversation_output(confirm_contact(conversation_id, browser_id(request), data))


@crm.get("/advisors", response=list[AdvisorOutput])
def advisors(request):
    return list(Advisor.objects.order_by("name"))


@crm.post("/advisors", response=AdvisorOutput)
def create_advisor(request, data: AdvisorInput):
    return save_advisor(data)


@crm.put("/advisors/{advisor_id}", response=AdvisorOutput)
def edit_advisor(request, advisor_id: int, data: AdvisorInput):
    return save_advisor(data, get_object_or_404(Advisor, pk=advisor_id))


@crm.get("/configuration", response=dict)
def configuration(request):
    return {"telegram_configured": bool(settings.TELEGRAM_BOT_TOKEN)}


@crm.get("/prospects", response=list[ProspectOutput])
def prospects(request):
    return [prospect_output(p) for p in Prospect.objects.order_by("-updated_at")]


@crm.get("/prospects/{prospect_id}", response=ProspectDetail)
def prospect_detail(request, prospect_id: int):
    return prospect_output(get_object_or_404(Prospect, pk=prospect_id), detail=True)


@crm.put("/prospects/{prospect_id}", response=ProspectDetail)
def edit_prospect(request, prospect_id: int, data: ProspectUpdate):
    get_object_or_404(Prospect, pk=prospect_id)
    return prospect_output(update_prospect(prospect_id, data, request.user), detail=True)


@crm.get("/requests", response=list[CRMConversation])
def human_requests(request):
    return [
        crm_conversation(c)
        for c in Conversation.objects.filter(human_requested=True, prospect__isnull=True).order_by(
            "-updated_at"
        )
    ]


@crm.get("/conversations/{conversation_id}", response=CRMConversation)
def staff_conversation(request, conversation_id: uuid.UUID):
    return crm_conversation(get_object_or_404(Conversation, pk=conversation_id))


@crm.put("/conversations/{conversation_id}/pause", response=CRMConversation)
def pause_anonymous_conversation(request, conversation_id: uuid.UUID, data: PauseInput):
    with transaction.atomic():
        conversation = get_object_or_404(
            Conversation.objects.select_for_update(), pk=conversation_id
        )
        if data.automation_paused != conversation.automation_paused:
            conversation.automation_paused = data.automation_paused
            conversation.revision += 1
            conversation.answered_revision = conversation.revision
            conversation.pending_since = None
            conversation.save(
                update_fields=[
                    "automation_paused",
                    "revision",
                    "answered_revision",
                    "pending_since",
                    "updated_at",
                ]
            )
        return crm_conversation(conversation)


@crm.post("/notifications/{notification_id}/retry", response=NotificationOutput)
def retry_notification(request, notification_id: int):
    from worker.dispatch import enqueue_notification

    with transaction.atomic():
        notification = get_object_or_404(
            Notification.objects.select_for_update(), pk=notification_id
        )
        if notification.status not in {"blocked", "failed"}:
            raise HttpError(
                409, "No se reenvían avisos entregados, en proceso o con resultado incierto."
            )
        notification.status = "pending"
        notification.save(update_fields=["status", "updated_at"])
        enqueue_notification(notification.pk)
        return notification_output(notification)
