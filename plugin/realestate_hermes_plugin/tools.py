"""Tool handlers.

Each handler is a pass-through: it forwards the Model's typed arguments plus the
runtime-supplied trusted ``session_id`` / ``task_id`` to the Product application
and returns the structured result verbatim. No handler interprets business
meaning, applies policy, or decides authorisation — that is the Backend's job.

Handlers never raise: an exception escaping into the Hermes tool loop would turn
a recoverable backend problem into a failed turn.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from realestate_hermes_plugin.backend import call_backend
from realestate_hermes_plugin.schemas import (
    PROPERTY_INACTIVE_REASONS,
    PROPERTY_STATUSES,
)

logger = logging.getLogger(__name__)


def _result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _safe_body(body: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = dict(body)
    if "attendee_name" in safe:
        safe["attendee_name"] = "<redacted>"
    return safe


def _forward(tool: str, body: dict[str, Any], kwargs: dict[str, Any]) -> str:
    """Forward one validated call to the Backend and return its result verbatim.

    ``call_backend`` already reports transport, credential and protocol problems
    as structured results, so the ``except`` here only covers a genuinely
    unexpected raise: an exception escaping into the Hermes tool loop would turn
    a recoverable backend problem into a failed turn.
    """
    try:
        logger.info(
            "Hermes tool handler forwarding to Product (tool=%s, session=%s, task=%s, body=%s)",
            tool,
            kwargs.get("session_id") or "<none>",
            kwargs.get("task_id") or "<none>",
            _safe_body(body),
        )
        payload = call_backend(
            "POST",
            f"/internal/plugin/tools/{tool}",
            # Trusted context comes from the runtime, never from the Model.
            session_id=kwargs.get("session_id"),
            task_id=kwargs.get("task_id"),
            json_body=body,
        )
    except Exception as exc:  # defensive: the tool loop must never see a raise
        logger.exception("Hermes tool handler failed before returning structured result")
        return _result(
            {
                "result": "temporarily_unavailable",
                "detail": f"{type(exc).__name__}: {exc}",
            }
        )
    logger.debug(
        "Hermes tool handler returning Product result (tool=%s, result=%s, keys=%s)",
        tool,
        payload.get("result"),
        sorted(payload.keys()),
    )
    return _result(payload)


def _text(args: dict[str, Any], key: str) -> str | None:
    """The trimmed string *key*, or None when the Model omitted or blanked it."""
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def get_property_information(args: dict[str, Any], **kwargs: Any) -> str:
    reference = _text(args, "reference")
    if reference is None:
        logger.warning("Tool call rejected locally: get_property_information missing reference")
        return _result(
            {
                "result": "not_found",
                "detail": "A property key or exact property name is required.",
            }
        )
    return _forward("get_property_information", {"reference": reference}, kwargs)


def set_property_status(args: dict[str, Any], **kwargs: Any) -> str:
    reference = _text(args, "reference")
    status = args.get("status")
    inactive_reason = args.get("inactive_reason")
    if reference is None:
        logger.warning("Tool call rejected locally: set_property_status missing reference")
        return _result(
            {"result": "not_found", "detail": "A property key or name is required."}
        )
    if status not in PROPERTY_STATUSES:
        logger.warning("Tool call rejected locally: set_property_status invalid status=%r", status)
        return _result(
            {
                "result": "ambiguous",
                "detail": "status must be exactly 'Active' or 'Inactive'.",
            }
        )
    if status == "Inactive" and inactive_reason not in PROPERTY_INACTIVE_REASONS:
        return _result(
            {
                "result": "ambiguous",
                "detail": "inactive_reason is required for an Inactive property.",
            }
        )
    if status == "Active" and inactive_reason is not None:
        return _result(
            {
                "result": "ambiguous",
                "detail": "inactive_reason must be omitted for an Active property.",
            }
        )
    body = {"reference": reference, "status": status}
    if inactive_reason is not None:
        body["inactive_reason"] = inactive_reason
    return _forward(
        "set_property_status", body, kwargs
    )


def list_properties(args: dict[str, Any], **kwargs: Any) -> str:
    return _forward("list_properties", {}, kwargs)


def list_pending_admin_work(args: dict[str, Any], **kwargs: Any) -> str:
    return _forward("list_pending_admin_work", {}, kwargs)


def resolve_pending_admin_work(args: dict[str, Any], **kwargs: Any) -> str:
    reference = _text(args, "reference")
    action = args.get("action")
    if reference is None:
        return _result(
            {"result": "not_found", "detail": "A work reference is required."}
        )
    if action not in {
        "Confirm",
        "Reject",
        "MarkNotified",
        "HandleManually",
        "MarkComplete",
    }:
        return _result({"result": "invalid_action"})
    return _forward(
        "resolve_pending_admin_work",
        {"reference": reference, "action": action},
        kwargs,
    )


def get_available_slots(args: dict[str, Any], **kwargs: Any) -> str:
    reference = _text(args, "reference")
    if reference is None:
        logger.warning("Tool call rejected locally: get_available_slots missing reference")
        return _result({"result": "not_found", "detail": "A property is required."})

    body: dict[str, Any] = {"reference": reference}
    for key in ("date_from", "date_to", "time_from", "time_to"):
        if (value := _text(args, key)) is not None:
            body[key] = value
    return _forward("get_available_slots", body, kwargs)


def book_appointment(args: dict[str, Any], **kwargs: Any) -> str:
    reference = _text(args, "reference")
    start = _text(args, "start")
    if reference is None:
        logger.warning("Tool call rejected locally: book_appointment missing reference")
        return _result({"result": "not_found", "detail": "A property is required."})
    if start is None:
        logger.warning("Tool call rejected locally: book_appointment missing start")
        return _result(
            {"result": "invalid_candidate", "detail": "An exact candidate start is required."}
        )

    body: dict[str, Any] = {"reference": reference, "start": start}
    if (name := _text(args, "attendee_name")) is not None:
        body["attendee_name"] = name
    return _forward("book_appointment", body, kwargs)


def cancel_appointment(args: dict[str, Any], **kwargs: Any) -> str:
    body: dict[str, Any] = {}
    if (reference := _text(args, "reference")) is not None:
        body["reference"] = reference
    return _forward("cancel_appointment", body, kwargs)


def reschedule_appointment(args: dict[str, Any], **kwargs: Any) -> str:
    body: dict[str, Any] = {"start": _text(args, "start")}
    reference = _text(args, "reference")
    if reference:
        body["reference"] = reference
    return _forward("reschedule_appointment", body, kwargs)


def request_human_handoff(args: dict[str, Any], **kwargs: Any) -> str:
    body: dict[str, Any] = {}
    reason = _text(args, "reason")
    if reason:
        body["reason"] = reason
    return _forward("request_human_handoff", body, kwargs)


def search_inventory(args: dict[str, Any], **kwargs: Any) -> str:
    municipality = args.get("municipality")
    if municipality not in {"Guadalajara", "Zapopan", "Tlaquepaque"}:
        return _result(
            {
                "result": "ambiguous",
                "detail": "municipality must be Guadalajara, Zapopan, or Tlaquepaque.",
            }
        )
    body: dict[str, Any] = {"municipality": municipality}
    for key in (
        "operation",
        "property_type",
        "min_price",
        "max_price",
        "min_bedrooms",
    ):
        if args.get(key) is not None:
            body[key] = args[key]
    return _forward("search_inventory", body, kwargs)


def revalidate_external_listing(args: dict[str, Any], **kwargs: Any) -> str:
    reference = _text(args, "reference")
    action = args.get("intended_action")
    if reference is None:
        return _result(
            {"result": "not_found", "detail": "A source reference is required."}
        )
    if action not in {"Recommend", "Share", "Appointment"}:
        return _result({"result": "invalid_action"})
    return _forward(
        "revalidate_external_listing",
        {"reference": reference, "intended_action": action},
        kwargs,
    )
