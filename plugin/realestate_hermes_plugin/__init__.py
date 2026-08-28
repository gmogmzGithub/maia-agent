"""Standalone product-owned Hermes plugin (ADR-0009, P-041).

Loaded into an unmodified upstream Hermes Runtime through the supported
``hermes_agent.plugins`` entry point. Hermes core is never forked or edited.

The model-facing surface is frozen at the Stage 0 contracts in TOOL-CONTRACTS.md
(P-069). Each is registered by the checkpoint that owns it; ``REGISTERED_TOOLS``
below is the running total and is asserted against the frozen set at load time,
so an accidental extra product tool is a startup failure rather than a silent
scope expansion.

The plugin also registers ``hermes realestate health``, a CLI subcommand that
exercises the plugin -> Product application path without adding anything the
Model can see.
"""

from __future__ import annotations

from typing import Any

import json
import logging
import os

from realestate_hermes_plugin import schemas, tools
from realestate_hermes_plugin.backend import check_backend

logger = logging.getLogger(__name__)

PLUGIN_NAME = "realestate"

# The frozen Stage 0 model-facing surface (P-069). Kept here as the single
# in-plugin declaration of what may ever be registered; each name is added as
# the checkpoint that owns it lands.
FROZEN_TOOL_SURFACE: tuple[str, ...] = (
    "get_property_information",
    "get_available_slots",
    "book_appointment",
    "cancel_appointment",
    "set_property_status",
    "list_properties",
    "resolve_pending_admin_work",
    "list_pending_admin_work",
    # Stage 3 (ADR-0029, ADR-0037). Two names the human-operation stage owns.
    # Neither could be expressed with the Stage 0 surface: an atomic reschedule
    # is not a cancel plus a booking, and asking a person to take over is an
    # operation with an alert and a deadline behind it, not a sentence.
    "reschedule_appointment",
    "request_human_handoff",
)

# The tools registered so far, as ``(name, schema, handler)``. Checkpoint 1 adds
# the first. This is the one place a tool is declared: ``REGISTERED_TOOLS`` and
# the registration loop in :func:`register` both derive from it, so a new tool
# cannot be half-added.
TOOLS: tuple[tuple[str, dict[str, Any], object], ...] = (
    (
        "get_property_information",
        schemas.GET_PROPERTY_INFORMATION,
        tools.get_property_information,
    ),
    ("get_available_slots", schemas.GET_AVAILABLE_SLOTS, tools.get_available_slots),
    ("book_appointment", schemas.BOOK_APPOINTMENT, tools.book_appointment),
    ("cancel_appointment", schemas.CANCEL_APPOINTMENT, tools.cancel_appointment),
    ("set_property_status", schemas.SET_PROPERTY_STATUS, tools.set_property_status),
    ("list_properties", schemas.LIST_PROPERTIES, tools.list_properties),
    (
        "resolve_pending_admin_work",
        schemas.RESOLVE_PENDING_ADMIN_WORK,
        tools.resolve_pending_admin_work,
    ),
    (
        "list_pending_admin_work",
        schemas.LIST_PENDING_ADMIN_WORK,
        tools.list_pending_admin_work,
    ),
    (
        "reschedule_appointment",
        schemas.RESCHEDULE_APPOINTMENT,
        tools.reschedule_appointment,
    ),
    (
        "request_human_handoff",
        schemas.REQUEST_HUMAN_HANDOFF,
        tools.request_human_handoff,
    ),
)

REGISTERED_TOOLS: tuple[str, ...] = tuple(name for name, _, _ in TOOLS)

TOOLSET = "realestate"


def _health_command(args: object) -> None:
    """Handler for ``hermes realestate health``."""
    result = check_backend()
    print(json.dumps(result, indent=2, ensure_ascii=False))


def _setup_argparse(subparser: object) -> None:
    subs = subparser.add_subparsers(dest="realestate_command")  # type: ignore[attr-defined]
    subs.add_parser("health", help="Check the connection to the Product application")
    subparser.set_defaults(func=_health_command)  # type: ignore[attr-defined]


def register(ctx: object) -> None:
    """Wire the plugin into the runtime.

    Any tool registered here must already appear in ``FROZEN_TOOL_SURFACE``;
    the assertion makes an accidental extra product tool a load-time failure
    rather than a silent scope expansion.
    """
    assert set(REGISTERED_TOOLS) <= set(FROZEN_TOOL_SURFACE), (
        "Attempted to register a tool outside the frozen Stage 0 surface"
    )
    level = getattr(logging, os.environ.get("LOG_LEVEL", "DEBUG").upper(), logging.DEBUG)
    if isinstance(level, int):
        logging.getLogger("realestate_hermes_plugin").setLevel(level)

    for name, schema, handler in TOOLS:
        # Availability is a prompt-caching concern; authority is not. The
        # Backend refuses an administrative mutation from a Sales session
        # regardless of which tools the Model can see (P-065).
        ctx.register_tool(  # type: ignore[attr-defined]
            name=name, toolset=TOOLSET, schema=schema, handler=handler
        )

    ctx.register_cli_command(  # type: ignore[attr-defined]
        name="realestate",
        help="Real-estate product operations",
        setup_fn=_setup_argparse,
        handler_fn=_health_command,
    )
    logger.info(
        "realestate plugin loaded (model tools registered: %d/%d)",
        len(REGISTERED_TOOLS),
        len(FROZEN_TOOL_SURFACE),
    )
