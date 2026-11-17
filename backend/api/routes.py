import uuid

from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.shortcuts import get_object_or_404
from ninja import NinjaAPI, Query, Router
from ninja.errors import HttpError
from ninja.security import SessionAuthIsStaff

from api.appointments import chat as appointments_chat
from api.appointments import crm as appointments_crm
from api.auth import BrowserAuth, browser_id
from api.calendar_auth import router as calendar_auth
from api.followups import chat as followup_chat
from api.followups import crm as followup_crm
from api.prospects import chat as prospect_chat
from api.prospects import crm as prospect_crm
from datalayer.conversations import conversation_output, receive_message
from datalayer.inventory import (
    managed_property,
    public_inventory,
    public_property,
    save_property,
    search_inventory,
    set_publication,
)
from datalayer.models import Conversation, Property
from datalayer.schemas import (
    ConversationOutput,
    ManagedProperty,
    MessageInput,
    PropertyInput,
    PublicationInput,
    PublicProperty,
    SearchCriteria,
    SearchResult,
)
from worker.google_calendar import CalendarError

api = NinjaAPI(
    title="Maia",
    version="0.1.0",
    description="Inventario y búsqueda conversacional de una inmobiliaria",
)


@api.exception_handler(CalendarError)
def calendar_error(request, exc):
    return api.create_response(
        request,
        {
            "detail": "Google Calendar requiere revisión. La cita no está confirmada.",
            "error_code": exc.code,
        },
        status=409,
    )


@api.exception_handler(DatabaseError)
def database_error(request, exc):
    import logging

    logging.getLogger(__name__).error("database_error type=%s", type(exc).__name__)
    return api.create_response(
        request, {"detail": "No pudimos consultar la información. Intenta de nuevo."}, status=503
    )


@api.exception_handler(ValidationError)
def validation_error(request, exc):
    return api.create_response(
        request,
        {"detail": "Revisa los datos ingresados.", "errors": exc.message_dict},
        status=422,
    )


@api.get("/health", response={200: dict, 503: dict}, operation_id="core_api_health")
def health(request):
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return {"ok": True}


@api.get("/properties", response=SearchResult, operation_id="core_api_properties")
def properties(request, filters: Query[SearchCriteria], offset: int = 0):
    if offset < 0 or offset > 10000:
        raise HttpError(422, "Página inválida")
    return search_inventory(filters, offset)


@api.get(
    "/properties/{property_id}", response=PublicProperty, operation_id="core_api_property_detail"
)
def property_detail(request, property_id: int):
    return public_property(get_object_or_404(public_inventory(), pk=property_id))


crm = Router(auth=SessionAuthIsStaff())


@crm.get("/properties", response=list[ManagedProperty], operation_id="core_api_crm_properties")
def crm_properties(request):
    return [managed_property(prop) for prop in Property.objects.order_by("-updated_at")]


@crm.post("/properties", response=ManagedProperty, operation_id="core_api_create_property")
def create_property(request, data: PropertyInput):
    return managed_property(save_property(data))


@crm.put(
    "/properties/{property_id}", response=ManagedProperty, operation_id="core_api_update_property"
)
def update_property(request, property_id: int, data: PropertyInput):
    return managed_property(save_property(data, get_object_or_404(Property, pk=property_id)))


@crm.patch(
    "/properties/{property_id}/publication",
    response=ManagedProperty,
    operation_id="crm_property_publication",
)
def change_publication(request, property_id: int, data: PublicationInput):
    try:
        prop = set_publication(property_id, data.published)
    except Property.DoesNotExist:
        raise HttpError(404, "Propiedad no encontrada") from None
    return managed_property(prop)


api.add_router("/crm", crm)
chat = Router(auth=BrowserAuth())


@chat.post("", response=ConversationOutput, operation_id="core_api_create_conversation")
def create_conversation(request):
    return conversation_output(Conversation.objects.create(browser_id=browser_id(request)))


@chat.get(
    "/{conversation_id}", response=ConversationOutput, operation_id="core_api_get_conversation"
)
def get_conversation(request, conversation_id: uuid.UUID):
    conversation = get_object_or_404(
        Conversation, id=conversation_id, browser_id=browser_id(request)
    )
    return conversation_output(conversation)


@chat.post(
    "/{conversation_id}/messages", response=ConversationOutput, operation_id="core_api_post_message"
)
def post_message(request, conversation_id: uuid.UUID, data: MessageInput):
    if not data.text.strip():
        raise HttpError(422, "Escribe un mensaje")
    get_object_or_404(Conversation, id=conversation_id, browser_id=browser_id(request))
    return conversation_output(
        receive_message(
            conversation_id, browser_id(request), data.text, data.client_message_id,
            property_id=data.property_id,
        )
    )


api.add_router("/conversations", chat)

api.add_router("/conversations", prospect_chat)
api.add_router("/crm", prospect_crm)
api.add_router("/crm", appointments_crm)
api.add_router("/conversations", appointments_chat)
api.add_router("", calendar_auth)
api.add_router("/conversations", followup_chat)
api.add_router("/crm", followup_crm)
