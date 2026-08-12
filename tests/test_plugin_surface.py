"""The standalone plugin's model-facing surface stays frozen (P-069, ADR-0009).

These assertions are the automated guard against the single most likely way this
project drifts: quietly adding an unreviewed product tool, or letting the Sales Role
see an Administrative one.
"""

from __future__ import annotations

import realestate_hermes_plugin as plugin

# Exactly the Stage 0 contracts in TOOL-CONTRACTS.md.
EXPECTED_FROZEN_SURFACE = {
    "get_property_information",
    "get_available_slots",
    "book_appointment",
    "cancel_appointment",
    "set_property_status",
    "list_properties",
    "resolve_pending_admin_work",
    "list_pending_admin_work",
}


def test_the_frozen_surface_is_exactly_the_stage_zero_contracts() -> None:
    assert set(plugin.FROZEN_TOOL_SURFACE) == EXPECTED_FROZEN_SURFACE
    assert len(plugin.FROZEN_TOOL_SURFACE) == 8


def test_no_tool_is_registered_outside_the_frozen_surface() -> None:
    assert set(plugin.REGISTERED_TOOLS) <= set(plugin.FROZEN_TOOL_SURFACE)


def test_checkpoint_five_registers_the_complete_frozen_surface() -> None:
    assert plugin.REGISTERED_TOOLS == (
        "get_property_information",
        "get_available_slots",
        "book_appointment",
        "cancel_appointment",
        "set_property_status",
        "list_properties",
        "resolve_pending_admin_work",
        "list_pending_admin_work",
    )


def test_the_status_tool_accepts_only_the_two_states() -> None:
    from realestate_hermes_plugin import schemas

    parameters = schemas.SET_PROPERTY_STATUS["parameters"]

    assert sorted(parameters["properties"]) == ["reference", "status"]
    assert parameters["properties"]["status"]["enum"] == ["Active", "Inactive"]
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
