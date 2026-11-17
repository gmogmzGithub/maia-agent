"""Transactional commercial actions requested by conversational tools."""

from django.db import transaction
from django.utils import timezone

from datalayer.errors import Superseded
from datalayer.inventory import public_inventory, public_property, search_inventory
from datalayer.models import Conversation, Prospect
from datalayer.prospects import is_paused, prepare_contact, record_interest, record_name
from datalayer.schemas import SearchCriteria, SearchRequest


def apply_tool(conversation_id, revision, name, arguments):
    with transaction.atomic():
        conversation = Conversation.objects.select_for_update().get(pk=conversation_id)
        if conversation.revision != revision or is_paused(conversation):
            raise Superseded
        if name == "stop_followup":
            from datalayer.followups import set_permission

            set_permission(conversation, False)
            return {
                "stopped": True,
                "detail": "No se enviarán más seguimientos. La persona puede seguir escribiendo.",
            }
        if name == "record_name":
            return record_name(conversation, arguments)
        if name == "record_interest":
            return record_interest(conversation, arguments)
        if name == "prepare_contact":
            return prepare_contact(conversation, arguments)
        if name == "search_properties":
            query = SearchRequest.model_validate(arguments)
            criteria = SearchCriteria.model_validate(
                {**conversation.criteria, **query.criteria_patch.model_dump(exclude_unset=True)}
            )
            result = search_inventory(criteria, query.offset)
            conversation.criteria = criteria.model_dump(mode="json")
            conversation.save(update_fields=["criteria", "updated_at"])
            from datalayer.followups import mark_intent

            if query.criteria_patch.model_dump(exclude_unset=True):
                mark_intent(conversation)
            Prospect.objects.filter(
                pk=conversation.prospect_id, criteria_source=conversation
            ).update(criteria=conversation.criteria, updated_at=timezone.now())
            return result
        if name == "get_property":
            if (
                not {"property_id"} <= set(arguments) <= {"property_id", "show_card", "show_again"}
                or type(arguments["property_id"]) is not int
                or type(arguments.get("show_card", True)) is not bool
                or type(arguments.get("show_again", False)) is not bool
            ):
                return {"error": "invalid_arguments"}
            prop = public_inventory().filter(pk=arguments["property_id"]).first()
            if not prop:
                return {"error": "property_not_available"}
            if not arguments.get("show_card", True):
                return {
                    "details": public_property(prop),
                    "presentation": "Responde exclusivamente al dato preguntado, en una frase breve. Para comparar, menciona solo las diferencias solicitadas. Los demás campos son contexto y no se enumeran. Un dato de inventario no se vuelve desconocido por ser una propiedad de prueba; indica esa condición brevemente sin inventar incertidumbre sobre su precio.",
                }
            return {"property": public_property(prop)}
        return {"error": "unknown_tool"}
