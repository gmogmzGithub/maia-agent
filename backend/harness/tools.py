"""Commercial tool dispatch and working results scoped to one turn."""

from asgiref.sync import sync_to_async
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from pydantic import ValidationError

from datalayer.booking_tools import visit_tool
from datalayer.schemas import SearchCriteria, SearchRequest
from datalayer.tool_actions import apply_tool
from worker.google_calendar import CalendarError


class TurnTools:
    """Own search protections, available cards and recovery controls, not model retries."""

    def __init__(self, conversation_id, turn):
        self.turn = turn
        self.conversation_id = conversation_id
        self.revision = turn["revision"]
        self.initial_criteria = turn["criteria"]
        self.shown_ids = set(turn["shown_property_ids"])
        self.search_criteria = None
        self.cards = []
        self.recovery_control = None

    async def execute(self, call):
        try:
            if call["name"] == "search_properties":
                requested = SearchRequest.model_validate(call["input"])
                candidate = SearchCriteria.model_validate({
                    **(self.search_criteria or self.initial_criteria),
                    **requested.criteria_patch.model_dump(exclude_unset=True),
                }).model_dump(mode="json")
                if self.search_criteria is not None and candidate != self.search_criteria:
                    result = {"error": "ask_permission", "detail": "Propón el cambio de requisitos y espera otro mensaje del prospecto."}
                else:
                    result = await sync_to_async(apply_tool)(
                        self.conversation_id, self.revision, call["name"], call["input"]
                    )
                    self.search_criteria = result["criteria"]
            elif call["name"] in {"visit_slots", "prepare_visit", "request_visit_help"}:
                result = await sync_to_async(visit_tool)(
                    self.conversation_id, self.revision, call["name"], call["input"]
                )
            else:
                result = await sync_to_async(apply_tool)(
                    self.conversation_id, self.revision, call["name"], call["input"]
                )
        except CalendarError as exc:
            result = {"error": exc.code, "detail": "Google Calendar requiere revisión; no confirmes cita. Ofrece registrar la solicitud para el asesor."}
        except (ValidationError, DjangoValidationError, ValueError, TypeError, KeyError, ObjectDoesNotExist):
            result = {"error": "invalid_criteria", "detail": "Revisa los criterios y aclara la petición si es necesario."}
        # Track every imported fact read by the model, including show_card=False.
        observed = self.turn.setdefault("observed_public_sources", {})
        candidates = list(result.get("results", []))
        candidates.extend(result[k] for k in ("property", "details") if isinstance(result.get(k), dict))
        for prop in candidates:
            if prop.get("public_revision") is not None:
                observed[str(prop["id"])] = prop["public_revision"]
        if "results" in result:
            self.cards = [p for p in result["results"] if p["id"] not in self.shown_ids][:3]
        if "property" in result:
            prop = result["property"]
            if prop["id"] not in self.shown_ids or call["input"].get("show_again"):
                old = next((i for i, p in enumerate(self.cards) if p["id"] == prop["id"]), None)
                if old is None and len(self.cards) < 3:
                    self.cards.append(prop)
                elif old is not None:
                    prop["unconfirmed"] = [k for k in self.cards[old].get("unconfirmed", []) if prop.get(k) is None]
                    self.cards[old] = prop
            else:
                result["details"] = result.pop("property")
        result["presentation_property_ids"] = [p["id"] for p in self.cards]
        if result.get("proposal"):
            self.recovery_control = {"kind": "visit", "proposal_id": str(result["proposal"]["id"])}
        elif result.get("pending_confirmation"):
            self.recovery_control = {"kind": "contact"}
        return result
