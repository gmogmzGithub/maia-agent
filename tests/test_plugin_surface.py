"""The standalone plugin's model-facing surface stays frozen (P-069, ADR-0009).

These assertions are the automated guard against the single most likely way this
project drifts: quietly adding an unreviewed product tool, or letting a Role see
data outside its approved view.

"Frozen" means a name enters the surface only with the stage that owns it and a
reason that is written down. Stage 3 adds exactly two: an atomic reschedule,
which cannot be expressed as a cancel followed by a booking without breaking the
ADR-0037 guarantee that a failure preserves the original visit, and a human
handoff, which is an operation with an alert and a deadline behind it rather
than something the Model can do by writing a sentence (ADR-0029).
"""

from __future__ import annotations

import realestate_hermes_plugin as plugin

# The Stage 0 contracts in TOOL-CONTRACTS.md.
STAGE_ZERO_SURFACE = {
    "get_property_information",
    "get_available_slots",
    "book_appointment",
    "cancel_appointment",
    "set_property_status",
    "list_properties",
    "resolve_pending_admin_work",
    "list_pending_admin_work",
}

# Stage 3 (ADR-0029, ADR-0037).
STAGE_THREE_ADDITIONS = {
    "reschedule_appointment",
    "request_human_handoff",
}

EXPECTED_FROZEN_SURFACE = STAGE_ZERO_SURFACE | STAGE_THREE_ADDITIONS


def test_the_frozen_surface_is_exactly_the_reviewed_contracts() -> None:
    assert set(plugin.FROZEN_TOOL_SURFACE) == EXPECTED_FROZEN_SURFACE
    assert len(plugin.FROZEN_TOOL_SURFACE) == 10


def test_stage_three_added_exactly_two_names() -> None:
    """A guard on the guard: the surface grew by two, and by which two."""
    assert set(plugin.FROZEN_TOOL_SURFACE) - STAGE_ZERO_SURFACE == (
        STAGE_THREE_ADDITIONS
    )


def test_no_tool_is_registered_outside_the_frozen_surface() -> None:
    assert set(plugin.REGISTERED_TOOLS) <= set(plugin.FROZEN_TOOL_SURFACE)


def test_every_frozen_tool_is_registered() -> None:
    assert plugin.REGISTERED_TOOLS == (
        "get_property_information",
        "get_available_slots",
        "book_appointment",
        "cancel_appointment",
        "set_property_status",
        "list_properties",
        "resolve_pending_admin_work",
        "list_pending_admin_work",
        "reschedule_appointment",
        "request_human_handoff",
    )


def test_the_status_tool_accepts_only_the_two_states() -> None:
    from realestate_hermes_plugin import schemas

    parameters = schemas.SET_PROPERTY_STATUS["parameters"]

    assert sorted(parameters["properties"]) == [
        "inactive_reason",
        "reference",
        "status",
    ]
    assert parameters["properties"]["status"]["enum"] == ["Active", "Inactive"]
    assert parameters["properties"]["inactive_reason"]["enum"] == [
        "Sold",
        "Rented",
        "Reserved",
        "TemporarilyUnavailable",
        "Withdrawn",
        "Unspecified",
    ]
    assert parameters["additionalProperties"] is False


def test_the_inventory_tool_takes_no_arguments() -> None:
    from realestate_hermes_plugin import schemas

    parameters = schemas.LIST_PROPERTIES["parameters"]

    # No search, filter, sort, status, limit, cursor, offset, or pagination.
    assert parameters["properties"] == {}
    assert parameters["additionalProperties"] is False


def _register() -> tuple[list[str], list[str]]:
    registered_tools: list[str] = []
    registered_cli: list[str] = []

    class FakeContext:
        def register_tool(self, name: str, **_: object) -> None:
            registered_tools.append(name)

        def register_cli_command(self, name: str, **_: object) -> None:
            registered_cli.append(name)

    plugin.register(FakeContext())
    return registered_tools, registered_cli


def test_register_matches_the_declared_tool_list() -> None:
    registered_tools, registered_cli = _register()

    assert registered_tools == list(plugin.REGISTERED_TOOLS)
    assert registered_cli == ["realestate"]


def test_the_registered_schema_accepts_only_a_reference() -> None:
    from realestate_hermes_plugin import schemas

    parameters = schemas.GET_PROPERTY_INFORMATION["parameters"]

    assert list(parameters["properties"]) == ["reference"]
    assert parameters["required"] == ["reference"]
    # No UUID, lead_id, SQL, path, pagination, or retrieval control (P-053).
    assert parameters["additionalProperties"] is False
