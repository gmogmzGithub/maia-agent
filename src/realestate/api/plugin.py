"""The authenticated local API the standalone Hermes plugin calls (ADR-0009).

The plugin is a thin adapter running inside the Hermes process. It holds no
business truth, no database handle, and no Calendar credential. It authenticates
to this application with a shared local token and forwards the runtime-supplied
trusted ``session_id`` / ``task_id``.

Actor, Role, and Conversation identity are resolved **here**, from the session
binding in PostgreSQL — never accepted as a model-generated argument. A tool
request whose session does not resolve to an authorised Role is ``forbidden``.
"""

from __future__ import annotations

import hmac
import logging
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.config import get_settings
from realestate.db.engine import Database
from realestate.db.models import (
    AgentRole,
    AgentSession,
    Conversation,
    InboxGroup,
    InboxGroupStatus,
    InboxMessage,
    PropertyInactiveReason,
    PropertyStatus,
)
from realestate.domain.administration import AdministrationService, Administrator
from realestate.domain.admin_work import ALLOWED_ACTIONS, AdminWorkService
from realestate.domain.appointments import AppointmentService
from realestate.domain.properties import PropertyService

router = APIRouter(prefix="/internal/plugin", tags=["plugin"])
logger = logging.getLogger(__name__)

SESSION_HEADER = "X-Hermes-Session-Id"
TASK_HEADER = "X-Hermes-Task-Id"
# The administrative message that triggered a mutation, for the audit record.
ORIGIN_HEADER = "X-Product-Origin-Message-Id"


def _safe_payload(payload: BaseModel) -> dict[str, object]:
    data = payload.model_dump(mode="json")
    if "attendee_name" in data and data["attendee_name"]:
        data["attendee_name"] = "<redacted>"
    return data


async def require_plugin_token(authorization: str = Header(default="")) -> None:
    expected = get_settings().plugin_api_token
    if not expected:
        logger.error("Plugin request rejected: PLUGIN_API_TOKEN is not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PLUGIN_API_TOKEN is not configured on the Product application.",
        )
    scheme, _, presented = authorization.partition(" ")
    # Compared as bytes: hmac.compare_digest raises TypeError on str inputs that
    # are not pure ASCII, which would turn a bad credential into a 500.
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        presented.encode("utf-8"), expected.encode("utf-8")
    ):
        logger.warning("Plugin request rejected: invalid credential")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid plugin credential.",
        )


async def _binding(
    session: AsyncSession, hermes_session_id: str
) -> AgentSession | None:
    """The AgentSession row the trusted Hermes session id is bound to, or None.

    Every authority decision in this module starts here (TC-008): the Role is
    read from the binding, never from a model argument. Keeping the query in one
    place means a change to what makes a binding valid cannot land in some
    resolvers and miss others.
    """
    if not hermes_session_id:
        logger.debug("Plugin trusted-context lookup skipped: no Hermes session id")
        return None
    binding = (
        await session.execute(
            select(AgentSession).where(
                AgentSession.hermes_session_id == hermes_session_id
            )
        )
    ).scalar_one_or_none()
    logger.debug(
        "Plugin trusted-context lookup (durable=%s, found=%s, role=%s)",
        hermes_session_id,
        binding is not None,
        binding.role if binding is not None else None,
    )
    return binding


async def resolve_role(request: Request, hermes_session_id: str) -> AgentRole | None:
    """Resolve the trusted Hermes session to a product Role, or None."""
    async with request.app.state.database.session_scope() as session:
        binding = await _binding(session, hermes_session_id)
    return AgentRole(binding.role) if binding is not None else None


@router.get("/health", dependencies=[Depends(require_plugin_token)])
async def plugin_health(
    request: Request,
    hermes_session_id: str = Header(default="", alias=SESSION_HEADER),
    hermes_task_id: str = Header(default="", alias=TASK_HEADER),
) -> dict[str, object]:
    """Prove the plugin -> Product application path, including trusted context."""
    database = await request.app.state.database.check_health()
    role = await resolve_role(request, hermes_session_id)
    logger.info(
        "Plugin health check (database=%s, durable=%s, role=%s, task=%s)",
        database.as_dict()["status"],
        hermes_session_id or "<none>",
        role.value if role else "<unbound>",
        hermes_task_id or "<none>",
    )
    return {
        "result": "ok",
        "application": "maia-agent",
        "checkpoint": 5,
        "database": database.as_dict()["status"],
        "trusted_context": {
            "session_id": hermes_session_id or None,
            "task_id": hermes_task_id or None,
            "role": role.value if role else None,
        },
        "product_tools": [
            "get_property_information",
            "get_available_slots",
            "book_appointment",
            "cancel_appointment",
            "set_property_status",
            "list_properties",
            "resolve_pending_admin_work",
            "list_pending_admin_work",
        ],
    }


async def resolve_admin(
    request: Request, hermes_session_id: str
) -> AgentSession | None:
    """Resolve an Administrative binding, or None.

    Separate from :func:`resolve_role` on purpose: an administrative mutation
    must never be reachable from a Sales session, and the check for that lives
    here rather than being a conditional inside each handler.
    """
    async with request.app.state.database.session_scope() as session:
        binding = await _binding(session, hermes_session_id)
    if binding is None or binding.role != AgentRole.ADMINISTRATIVE.value:
        return None
    return binding


class PropertyInformationRequest(BaseModel):
    """`get_property_information` model arguments (TOOL-CONTRACTS.md).

    Exactly one field. No UUID, lead_id, SQL, file path, chunk, offset, limit,
    or retrieval strategy is accepted — extra keys are rejected outright.
    """

    model_config = {"extra": "forbid"}

    reference: str = Field(min_length=1, max_length=200)


@router.post(
    "/tools/get_property_information", dependencies=[Depends(require_plugin_token)]
)
async def get_property_information(
    request: Request,
    payload: PropertyInformationRequest,
    hermes_session_id: str = Header(default="", alias=SESSION_HEADER),
) -> dict[str, object]:
    role = await resolve_role(request, hermes_session_id)
    logger.info(
        "Plugin tool request: get_property_information (durable=%s, role=%s, payload=%s)",
        hermes_session_id or "<none>",
        role.value if role else "<unbound>",
        _safe_payload(payload),
    )
    if role is None:
        # The trusted session is not bound to either Role.
        logger.warning(
            "Plugin tool forbidden: get_property_information (durable=%s)",
            hermes_session_id or "<none>",
        )
        return {"result": "forbidden"}

    async with request.app.state.database.session_scope() as session:
        service = PropertyService(session, request.app.state.artifacts)
        result = await service.get_property_information(
            payload.reference, role, actor_id=hermes_session_id
        )
        logger.debug(
            "Plugin tool result: get_property_information (durable=%s, result=%s)",
            hermes_session_id or "<none>",
            result.get("result"),
        )
        return result


class SetPropertyStatusRequest(BaseModel):
    """`set_property_status` model arguments (TOOL-CONTRACTS.md).

    No UUID, actor identity, Lead identity, SQL, file path, or arbitrary status
    text. The actor comes from the trusted Telegram session (P-065).

    Shape only. Whether a reason is required for the requested status is a
    policy question, and ``AdministrationService.set_property_status`` answers
    it with ``ambiguous`` plus the detail the Agent can act on — which a 422
    here would flatten into the plugin's ``temporarily_unavailable``.
    """

    # ``use_enum_values`` keeps the validated field a plain string, so the
    # domain still receives "Active"/"Inactive" while PropertyStatus stays the
    # single declaration of what those two states are.
    model_config = {"extra": "forbid", "use_enum_values": True}

    reference: str = Field(min_length=1, max_length=200)
    status: PropertyStatus
    inactive_reason: PropertyInactiveReason | None = None


@router.post("/tools/set_property_status", dependencies=[Depends(require_plugin_token)])
async def set_property_status(
    request: Request,
    payload: SetPropertyStatusRequest,
    hermes_session_id: str = Header(default="", alias=SESSION_HEADER),
) -> dict[str, object]:
    binding = await resolve_admin(request, hermes_session_id)
    logger.info(
        "Plugin tool request: set_property_status (durable=%s, admin=%s, payload=%s)",
        hermes_session_id or "<none>",
        binding is not None,
        _safe_payload(payload),
    )
    if binding is None:
        # Not an authenticated Administrative session. A Sales session lands
        # here too, and is refused for the same reason.
        logger.warning(
            "Plugin tool forbidden: set_property_status (durable=%s)",
            hermes_session_id or "<none>",
        )
        return {"result": "forbidden"}

    async with request.app.state.database.session_scope() as session:
        service = AdministrationService(session)
        result = await service.set_property_status(
            payload.reference,
            payload.status,
            Administrator(
                actor_id=binding.channel_key or hermes_session_id,
                origin_message_id=request.headers.get(ORIGIN_HEADER) or None,
            ),
            payload.inactive_reason,
        )
        logger.debug(
            "Plugin tool result: set_property_status (durable=%s, result=%s)",
            hermes_session_id or "<none>",
            result.get("result"),
        )
        return result


class NoArguments(BaseModel):
    model_config = {"extra": "forbid"}


@router.post("/tools/list_properties", dependencies=[Depends(require_plugin_token)])
async def list_properties(
    request: Request,
    payload: NoArguments,
    hermes_session_id: str = Header(default="", alias=SESSION_HEADER),
) -> dict[str, object]:
    role = await resolve_role(request, hermes_session_id)
    logger.info(
        "Plugin tool request: list_properties (durable=%s, role=%s)",
        hermes_session_id or "<none>",
        role.value if role else None,
    )
    if role not in {AgentRole.ADMINISTRATIVE, AgentRole.SALES}:
        logger.warning(
            "Plugin tool forbidden: list_properties (durable=%s)",
            hermes_session_id or "<none>",
        )
        return {"result": "forbidden"}

    async with request.app.state.database.session_scope() as session:
        service = AdministrationService(session)
        result = (
            await service.list_active_properties_for_sales()
            if role is AgentRole.SALES
            else await service.list_properties()
        )
        logger.debug(
            "Plugin tool result: list_properties (durable=%s, result=%s)",
            hermes_session_id or "<none>",
            result.get("result"),
        )
        return result


class ResolvePendingAdminWorkRequest(BaseModel):
    """One readable work reference and one fixed action; no hidden authority."""

    model_config = {"extra": "forbid"}

    reference: str = Field(min_length=1, max_length=40)
    action: str = Field(
        pattern="^(Confirm|Reject|MarkNotified|HandleManually|MarkComplete)$"
    )


@router.post(
    "/tools/resolve_pending_admin_work",
    dependencies=[Depends(require_plugin_token)],
)
async def resolve_pending_admin_work(
    request: Request,
    payload: ResolvePendingAdminWorkRequest,
    hermes_session_id: str = Header(default="", alias=SESSION_HEADER),
) -> dict[str, object]:
    binding = await resolve_admin(request, hermes_session_id)
    if binding is None:
        return {"result": "forbidden"}
    if payload.action not in ALLOWED_ACTIONS:
        return {"result": "invalid_action"}
    async with request.app.state.database.session_scope() as session:
        return await AdminWorkService(
            session,
            request.app.state.calendar,
            request.app.state.appointment_policy.schedule,
        ).resolve(
            payload.reference,
            payload.action,
            Administrator(
                actor_id=binding.channel_key or hermes_session_id,
                origin_message_id=request.headers.get(ORIGIN_HEADER) or None,
            ),
        )


@router.post(
    "/tools/list_pending_admin_work",
    dependencies=[Depends(require_plugin_token)],
)
async def list_pending_admin_work(
    request: Request,
    payload: NoArguments,
    hermes_session_id: str = Header(default="", alias=SESSION_HEADER),
) -> dict[str, object]:
    if await resolve_admin(request, hermes_session_id) is None:
        return {"result": "forbidden"}
    async with request.app.state.database.session_scope() as session:
        return await AdminWorkService(
            session,
            request.app.state.calendar,
            request.app.state.appointment_policy.schedule,
        ).list_pending()


# --- Sales appointment tools --------------------------------------------------


async def resolve_sales_conversation(
    request: Request, hermes_session_id: str
) -> Conversation | None:
    """The Conversation a Sales session belongs to, or None.

    Lead, Conversation, cycle, Broker, Calendar, duration, time zone, and
    idempotency identity all come from here — never from a model argument
    (P-061).
    """
    database: Database = request.app.state.database
    async with database.session_scope() as session:
        binding = await _binding(session, hermes_session_id)
        if binding is None or binding.role != AgentRole.SALES.value:
            return None
        if binding.cycle_id is None:
            return None
        # ``scalar`` rather than ``execute(...).scalar_one_or_none()``:
        # SQLAlchemy types the former, so the Conversation stays a Conversation
        # instead of decaying to Any at the boundary the Model talks to.
        conversation: Conversation | None = await session.scalar(
            select(Conversation).where(Conversation.cycle_id == binding.cycle_id)
        )
        return conversation


class AvailableSlotsRequest(BaseModel):
    """`get_available_slots` arguments (P-060).

    Exactly a reference plus optional ISO date and local HH:MM bounds. No
    natural-language filter, UUID, lead_id, limit, offset, cursor, duration,
    time zone, Calendar identifier, or search horizon.
    """

    model_config = {"extra": "forbid"}

    reference: str = Field(min_length=1, max_length=200)
    date_from: date | None = None
    date_to: date | None = None
    time_from: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    time_to: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")


def _clock(value: str | None) -> time | None:
    return time.fromisoformat(value) if value else None


@router.post("/tools/get_available_slots", dependencies=[Depends(require_plugin_token)])
async def get_available_slots(
    request: Request,
    payload: AvailableSlotsRequest,
    hermes_session_id: str = Header(default="", alias=SESSION_HEADER),
) -> dict[str, object]:
    conversation = await resolve_sales_conversation(request, hermes_session_id)
    logger.info(
        "Plugin tool request: get_available_slots (durable=%s, sales_conversation=%s, payload=%s)",
        hermes_session_id or "<none>",
        conversation.id if conversation is not None else "<none>",
        _safe_payload(payload),
    )
    if conversation is None:
        logger.warning(
            "Plugin tool forbidden: get_available_slots (durable=%s)",
            hermes_session_id or "<none>",
        )
        return {"result": "forbidden"}
    if payload.date_from and payload.date_to and payload.date_from > payload.date_to:
        logger.warning(
            "Plugin tool invalid date range: get_available_slots (date_from=%s, date_to=%s)",
            payload.date_from,
            payload.date_to,
        )
        return {"result": "temporarily_unavailable", "detail": "date_from is after date_to"}

    async with request.app.state.database.session_scope() as session:
        service = AppointmentService(
            session,
            request.app.state.calendar,
            request.app.state.appointment_policy,
        )
        result = await service.available_slots(
            conversation=await session.merge(conversation),
            reference=payload.reference,
            date_from=payload.date_from,
            date_to=payload.date_to,
            time_from=_clock(payload.time_from),
            time_to=_clock(payload.time_to),
        )
        logger.debug(
            "Plugin tool result: get_available_slots (durable=%s, result=%s)",
            hermes_session_id or "<none>",
            result.get("result"),
        )
        return result


class BookAppointmentRequest(BaseModel):
    """`book_appointment` arguments (P-061, plus amendment 3).

    No end, duration, time zone, UUID, lead_id, Calendar identifier, or
    idempotency key — all of those come from trusted state. ``attendee_name`` is
    display-only and carries no authority.
    """

    model_config = {"extra": "forbid"}

    reference: str = Field(min_length=1, max_length=200)
    start: datetime
    attendee_name: str | None = Field(default=None, max_length=200)


@router.post("/tools/book_appointment", dependencies=[Depends(require_plugin_token)])
async def book_appointment(
    request: Request,
    payload: BookAppointmentRequest,
    hermes_session_id: str = Header(default="", alias=SESSION_HEADER),
) -> dict[str, object]:
    conversation = await resolve_sales_conversation(request, hermes_session_id)
    logger.info(
        "Plugin tool request: book_appointment (durable=%s, sales_conversation=%s, payload=%s)",
        hermes_session_id or "<none>",
        conversation.id if conversation is not None else "<none>",
        _safe_payload(payload),
    )
    if conversation is None:
        logger.warning(
            "Plugin tool forbidden: book_appointment (durable=%s)",
            hermes_session_id or "<none>",
        )
        return {"result": "forbidden"}

    async with request.app.state.database.session_scope() as session:
        service = AppointmentService(
            session,
            request.app.state.calendar,
            request.app.state.appointment_policy,
        )
        result = await service.book(
            conversation=await session.merge(conversation),
            reference=payload.reference,
            start=payload.start,
            attendee_name=(payload.attendee_name or None),
        )
        logger.debug(
            "Plugin tool result: book_appointment (durable=%s, result=%s)",
            hermes_session_id or "<none>",
            result.get("result"),
        )
        return result


class CancelAppointmentRequest(BaseModel):
    """Lead-requested cancellation.

    The appointment is resolved from the trusted Sales conversation. A reference
    is optional because Stage 0 normally has one future appointment per lead,
    but when several exist the backend asks the model to disambiguate.
    """

    model_config = {"extra": "forbid"}

    reference: str | None = Field(default=None, min_length=1, max_length=40)


@router.post("/tools/cancel_appointment", dependencies=[Depends(require_plugin_token)])
async def cancel_appointment(
    request: Request,
    payload: CancelAppointmentRequest,
    hermes_session_id: str = Header(default="", alias=SESSION_HEADER),
) -> dict[str, object]:
    conversation = await resolve_sales_conversation(request, hermes_session_id)
    logger.info(
        "Plugin tool request: cancel_appointment (durable=%s, sales_conversation=%s, payload=%s)",
        hermes_session_id or "<none>",
        conversation.id if conversation is not None else "<none>",
        _safe_payload(payload),
    )
    if conversation is None:
        logger.warning(
            "Plugin tool forbidden: cancel_appointment (durable=%s)",
            hermes_session_id or "<none>",
        )
        return {"result": "forbidden"}

    async with request.app.state.database.session_scope() as session:
        merged = await session.merge(conversation)
        trigger_inbox_ids = tuple(
            (
                await session.execute(
                    select(InboxMessage.id)
                    .join(InboxGroup, InboxGroup.id == InboxMessage.group_id)
                    .where(InboxGroup.conversation_id == merged.id)
                    .where(
                        InboxGroup.status == InboxGroupStatus.PROCESSING.value
                    )
                    .order_by(InboxMessage.sent_at, InboxMessage.id)
                )
            )
            .scalars()
            .all()
        )
        service = AppointmentService(
            session,
            request.app.state.calendar,
            request.app.state.appointment_policy,
        )
        result = await service.cancel(
            conversation=merged,
            trigger_inbox_ids=trigger_inbox_ids,
            reference=payload.reference,
        )
        logger.debug(
            "Plugin tool result: cancel_appointment (durable=%s, result=%s)",
            hermes_session_id or "<none>",
            result.get("result"),
        )
        return result
