"""The plugin's tool handlers: a thin, non-raising pass-through (ADR-0009).

The plugin holds no business truth. What it *does* hold is the promise that a
handler never raises into the Hermes tool loop, and never invents an argument
the Model did not supply. Both are asserted here against a stubbed Backend, so
they hold whether or not the Product application is running.

The other thing worth pinning is what the handler refuses locally. A blank
``reference`` is not forwarded as an empty string — the Backend would answer
``not_found`` anyway, but the round trip is pointless and the result the Model
reads should say what is actually wrong.
"""

from __future__ import annotations

import json

import httpx
import pytest

import realestate_hermes_plugin as plugin
import realestate_hermes_plugin.tools as tools
from realestate_hermes_plugin.backend import (
    SESSION_HEADER,
    TASK_HEADER,
    BackendConfig,
    BackendNotConfigured,
    call_backend,
)


@pytest.fixture
def forwarded(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Capture what each handler forwards instead of making an HTTP call."""
    calls: list[dict] = []

    def fake_call_backend(method: str, path: str, **kwargs: object) -> dict:
        calls.append({"method": method, "path": path, **kwargs})
        return {"result": "ok"}

    monkeypatch.setattr(tools, "call_backend", fake_call_backend)
    return calls


def decoded(raw: str) -> dict:
    return json.loads(raw)


# -- Forwarding ----------------------------------------------------------------


def test_a_property_lookup_forwards_only_the_reference(forwarded) -> None:
    result = decoded(
        tools.get_property_information(
            {"reference": "  casa-roble  "},
            session_id="hermes-1",
            task_id="task-1",
        )
    )

    assert result == {"result": "ok"}
    assert forwarded[0]["path"] == "/internal/plugin/tools/get_property_information"
    assert forwarded[0]["json_body"] == {"reference": "casa-roble"}
    # Trusted context comes from the runtime, never from the Model.
    assert forwarded[0]["session_id"] == "hermes-1"
    assert forwarded[0]["task_id"] == "task-1"


def test_the_inventory_tool_forwards_an_empty_body(forwarded) -> None:
    """It takes no arguments at all; anything the Model passes is dropped here."""
    decoded(tools.list_properties({"limit": 5}, session_id="hermes-1"))

    assert forwarded[0]["json_body"] == {}
    assert forwarded[0]["path"] == "/internal/plugin/tools/list_properties"


def test_stage_six_inventory_tools_forward_only_bounded_product_arguments(
    forwarded,
) -> None:
    decoded(
        tools.search_inventory(
            {
                "municipality": "Zapopan",
                "operation": "Sale",
                "min_price": 1_000_000,
                "ignored": "never forwarded",
            },
            session_id="hermes-1",
        )
    )
    decoded(
        tools.revalidate_external_listing(
            {"reference": " EB-FAKE-001 ", "intended_action": "Recommend"},
            session_id="hermes-1",
        )
    )

    assert forwarded[0]["json_body"] == {
        "municipality": "Zapopan",
        "operation": "Sale",
        "min_price": 1_000_000,
    }
    assert forwarded[1]["json_body"] == {
        "reference": "EB-FAKE-001",
        "intended_action": "Recommend",
    }


def test_stage_six_inventory_tools_fail_closed_locally(forwarded) -> None:
    assert decoded(tools.search_inventory({"municipality": "Monterrey"}))[
        "result"
    ] == "ambiguous"
    assert decoded(tools.revalidate_external_listing({"intended_action": "Share"}))[
        "result"
    ] == "not_found"
    assert decoded(
        tools.revalidate_external_listing(
            {"reference": "EB-1", "intended_action": "Publish"}
        )
    )["result"] == "invalid_action"
    assert forwarded == []


def test_reschedule_and_handoff_forward_only_present_optional_values(forwarded) -> None:
    decoded(
        tools.reschedule_appointment(
            {"reference": " APT-1 ", "start": " 2026-08-10T16:00:00-06:00 "}
        )
    )
    decoded(tools.reschedule_appointment({"start": "2026-08-11T16:00:00-06:00"}))
    decoded(tools.request_human_handoff({"reason": " Quiero asesor "}))
    decoded(tools.request_human_handoff({}))

    assert forwarded[0]["json_body"] == {
        "reference": "APT-1",
        "start": "2026-08-10T16:00:00-06:00",
    }
    assert forwarded[1]["json_body"] == {"start": "2026-08-11T16:00:00-06:00"}
    assert forwarded[2]["json_body"] == {"reason": "Quiero asesor"}
    assert forwarded[3]["json_body"] == {}


def test_a_status_change_forwards_the_reference_status_and_reason(forwarded) -> None:
    decoded(
        tools.set_property_status(
            {
                "reference": "casa-roble",
                "status": "Inactive",
                "inactive_reason": "Sold",
            },
            session_id="hermes-1",
        )
    )

    assert forwarded[0]["json_body"] == {
        "reference": "casa-roble",
        "status": "Inactive",
        "inactive_reason": "Sold",
    }


def test_reactivation_omits_the_inactive_reason(forwarded) -> None:
    decoded(
        tools.set_property_status(
            {"reference": "casa-roble", "status": "Active"},
            session_id="hermes-1",
        )
    )

    assert forwarded[0]["json_body"] == {
        "reference": "casa-roble",
        "status": "Active",
    }


def test_a_slot_query_forwards_only_the_bounds_the_model_supplied(forwarded) -> None:
    decoded(
        tools.get_available_slots(
            {
                "reference": "casa-roble",
                "date_from": "2026-08-10",
                "time_from": "16:00",
                "date_to": "   ",
                "time_to": None,
            },
            session_id="hermes-1",
        )
    )

    assert forwarded[0]["json_body"] == {
        "reference": "casa-roble",
        "date_from": "2026-08-10",
        "time_from": "16:00",
    }


def test_a_booking_forwards_the_attendee_name_only_when_given(forwarded) -> None:
    decoded(
        tools.book_appointment(
            {"reference": "casa-roble", "start": "2026-08-10T16:00:00-06:00"},
            session_id="hermes-1",
        )
    )
    decoded(
        tools.book_appointment(
            {
                "reference": "casa-roble",
                "start": "2026-08-10T16:00:00-06:00",
                "attendee_name": " Cliente Demo ",
            },
            session_id="hermes-1",
        )
    )

    assert "attendee_name" not in forwarded[0]["json_body"]
    assert forwarded[1]["json_body"]["attendee_name"] == "Cliente Demo"


def test_the_cancel_tool_forwards_only_the_optional_reference(forwarded) -> None:
    decoded(tools.cancel_appointment({"reference": " APT-123 "}, session_id="hermes-1"))

    assert forwarded[0]["path"] == "/internal/plugin/tools/cancel_appointment"
    assert forwarded[0]["json_body"] == {"reference": "APT-123"}


def test_the_cancel_tool_accepts_no_argument_for_the_current_appointment(
    forwarded,
) -> None:
    decoded(tools.cancel_appointment({}, session_id="hermes-1"))

    assert forwarded[0]["path"] == "/internal/plugin/tools/cancel_appointment"
    assert forwarded[0]["json_body"] == {}


def test_every_handler_returns_json_the_model_can_read(forwarded) -> None:
    raw = tools.get_property_information({"reference": "casa-roble"})

    assert isinstance(raw, str)
    assert decoded(raw) == {"result": "ok"}


def test_accents_survive_the_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ensure_ascii=False``: the Model reads Spanish, not escape sequences."""
    monkeypatch.setattr(
        tools, "call_backend", lambda *a, **k: {"name": "Casa Roble Zapopan ñ"}
    )

    assert "ñ" in tools.list_properties({})


# -- Local refusals ------------------------------------------------------------


@pytest.mark.parametrize("reference", [None, "", "   ", 42, {"key": "value"}])
def test_a_missing_property_reference_is_refused_without_a_round_trip(
    forwarded, reference: object
) -> None:
    result = decoded(tools.get_property_information({"reference": reference}))

    assert result["result"] == "not_found"
    assert forwarded == []


def test_a_status_change_without_a_reference_is_refused(forwarded) -> None:
    result = decoded(tools.set_property_status({"status": "Active"}))

    assert result["result"] == "not_found"
    assert forwarded == []


@pytest.mark.parametrize("status", [None, "active", "Sold", "", "ACTIVE", 1])
def test_only_the_two_accepted_states_are_forwarded(forwarded, status: object) -> None:
    """The Backend refuses these too; refusing here keeps the reason readable."""
    result = decoded(
        tools.set_property_status({"reference": "casa-roble", "status": status})
    )

    assert result["result"] == "ambiguous"
    assert "Active" in result["detail"] and "Inactive" in result["detail"]
    assert forwarded == []


def test_inactive_requires_an_accepted_reason(forwarded) -> None:
    result = decoded(
        tools.set_property_status(
            {"reference": "casa-roble", "status": "Inactive"}
        )
    )

    assert result["result"] == "ambiguous"
    assert "inactive_reason" in result["detail"]
    assert forwarded == []


def test_active_rejects_an_inactive_reason(forwarded) -> None:
    result = decoded(
        tools.set_property_status(
            {
                "reference": "casa-roble",
                "status": "Active",
                "inactive_reason": "Sold",
            }
        )
    )

    assert result["result"] == "ambiguous"
    assert forwarded == []


def test_pending_admin_tools_validate_and_forward(forwarded) -> None:
    decoded(tools.list_pending_admin_work({"ignored": True}, session_id="hermes-1"))
    assert forwarded[-1]["path"].endswith("/list_pending_admin_work")

    assert decoded(tools.resolve_pending_admin_work({}))["result"] == "not_found"
    assert decoded(
        tools.resolve_pending_admin_work(
            {"reference": "APT-1", "action": "DeleteEverything"}
        )
    )["result"] == "invalid_action"

    decoded(
        tools.resolve_pending_admin_work(
            {"reference": "APT-1", "action": "Confirm"},
            session_id="hermes-1",
        )
    )
    assert forwarded[-1]["json_body"] == {
        "reference": "APT-1",
        "action": "Confirm",
    }


def test_a_slot_query_without_a_property_is_refused(forwarded) -> None:
    assert decoded(tools.get_available_slots({}))["result"] == "not_found"
    assert forwarded == []


def test_a_booking_without_a_property_is_refused(forwarded) -> None:
    assert decoded(tools.book_appointment({"start": "2026-08-10T16:00:00"}))[
        "result"
    ] == "not_found"
    assert forwarded == []


def test_a_booking_without_an_exact_start_is_refused(forwarded) -> None:
    """No start means no candidate; the Backend must never guess one."""
    result = decoded(tools.book_appointment({"reference": "casa-roble"}))

    assert result["result"] == "invalid_candidate"
    assert forwarded == []


# -- Nothing escapes into the tool loop ----------------------------------------


def test_an_unexpected_raise_becomes_a_structured_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exception here would turn a recoverable backend problem into a failed
    turn."""

    def explode(*args: object, **kwargs: object) -> dict:
        raise RuntimeError("nobody expected this")

    monkeypatch.setattr(tools, "call_backend", explode)

    result = decoded(tools.get_property_information({"reference": "casa-roble"}))

    assert result["result"] == "temporarily_unavailable"
    assert "RuntimeError: nobody expected this" in result["detail"]


# -- The HTTP boundary ---------------------------------------------------------


def config(token: str = "plugin-token", base_url: str = "http://product.test") -> BackendConfig:
    return BackendConfig(base_url=base_url, token=token, timeout_seconds=1.0)


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch):
    """Route ``httpx.request`` through a mock transport, recording each request."""
    seen: list[httpx.Request] = []
    handlers: list = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handlers[0](request)

    def fake_request(method: str, url: str, **kwargs: object) -> httpx.Response:
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            return client.request(method, url, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("realestate_hermes_plugin.backend.httpx.request", fake_request)

    def answer(handler) -> list[httpx.Request]:  # noqa: ANN001
        handlers.clear()
        handlers.append(handler)
        return seen

    return answer


def test_the_call_carries_the_credential_and_the_trusted_context(transport) -> None:
    seen = transport(lambda request: httpx.Response(200, json={"result": "ok"}))

    call_backend(
        "POST",
        "/internal/plugin/tools/list_properties",
        session_id="hermes-1",
        task_id="task-1",
        json_body={},
        config=config(),
    )

    assert seen[0].headers["Authorization"] == "Bearer plugin-token"
    assert seen[0].headers[SESSION_HEADER] == "hermes-1"
    assert seen[0].headers[TASK_HEADER] == "task-1"


def test_absent_trusted_context_sends_no_empty_headers(transport) -> None:
    seen = transport(lambda request: httpx.Response(200, json={"result": "ok"}))

    call_backend("GET", "/internal/plugin/health", config=config())

    assert SESSION_HEADER not in seen[0].headers
    assert TASK_HEADER not in seen[0].headers


def test_a_rejected_credential_is_forbidden_not_temporarily_unavailable(
    transport,
) -> None:
    """The distinction matters: one is worth retrying and the other never is."""
    transport(lambda request: httpx.Response(401, json={"detail": "nope"}))

    result = call_backend("GET", "/internal/plugin/health", config=config())

    assert result["result"] == "forbidden"


@pytest.mark.parametrize("status_code", [400, 403, 404, 422, 500, 503])
def test_any_other_error_status_degrades_rather_than_raises(
    transport, status_code: int
) -> None:
    transport(lambda request: httpx.Response(status_code, json={}))

    result = call_backend("GET", "/internal/plugin/health", config=config())

    assert result["result"] == "temporarily_unavailable"
    assert str(status_code) in result["detail"]


def test_a_non_json_body_degrades(transport) -> None:
    transport(lambda request: httpx.Response(200, text="<html>"))

    result = call_backend("GET", "/internal/plugin/health", config=config())

    assert result["result"] == "temporarily_unavailable"
    assert "non-JSON" in result["detail"]


@pytest.mark.parametrize("body", ["null", "[]", '"text"', "42"])
def test_an_unexpected_json_shape_degrades(transport, body: str) -> None:
    transport(
        lambda request: httpx.Response(
            200, content=body, headers={"Content-Type": "application/json"}
        )
    )

    result = call_backend("GET", "/internal/plugin/health", config=config())

    assert result["result"] == "temporarily_unavailable"
    assert "unexpected JSON shape" in result["detail"]


def test_an_unreachable_product_application_degrades(transport) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    transport(refuse)

    result = call_backend("GET", "/internal/plugin/health", config=config())

    assert result["result"] == "temporarily_unavailable"
    assert "not reachable" in result["detail"]


# -- Configuration from the Hermes Runtime environment ------------------------


def test_the_config_is_read_from_the_runtime_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REALESTATE_PLUGIN_API_TOKEN", "  from-env  ")
    monkeypatch.setenv("REALESTATE_BACKEND_URL", "http://127.0.0.1:8080/")
    monkeypatch.setenv("REALESTATE_BACKEND_TIMEOUT", "3.5")

    resolved = BackendConfig.from_env()

    assert resolved.token == "from-env"
    assert resolved.base_url == "http://127.0.0.1:8080"
    assert resolved.timeout_seconds == 3.5


def test_the_defaults_are_the_local_stage_0_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REALESTATE_PLUGIN_API_TOKEN", "from-env")
    monkeypatch.delenv("REALESTATE_BACKEND_URL", raising=False)
    monkeypatch.delenv("REALESTATE_BACKEND_TIMEOUT", raising=False)

    resolved = BackendConfig.from_env()

    assert resolved.base_url == "http://127.0.0.1:8080"
    assert resolved.timeout_seconds == 15.0


@pytest.mark.parametrize("value", ["", "   "])
def test_a_blank_credential_is_not_configured(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("REALESTATE_PLUGIN_API_TOKEN", value)

    with pytest.raises(BackendNotConfigured, match="REALESTATE_PLUGIN_API_TOKEN"):
        BackendConfig.from_env()


# -- Registration ---------------------------------------------------------------


class FakeContext:
    def __init__(self) -> None:
        self.tools: list[dict] = []
        self.cli: list[dict] = []

    def register_tool(self, **kwargs: object) -> None:
        self.tools.append(kwargs)

    def register_cli_command(self, **kwargs: object) -> None:
        self.cli.append(kwargs)


def test_registration_wires_every_declared_tool_into_one_toolset() -> None:
    ctx = FakeContext()

    plugin.register(ctx)

    assert [entry["name"] for entry in ctx.tools] == list(plugin.REGISTERED_TOOLS)
    assert {entry["toolset"] for entry in ctx.tools} == {plugin.TOOLSET}
    assert all(callable(entry["handler"]) for entry in ctx.tools)


def test_no_tool_outside_the_frozen_stage_0_surface_can_be_registered() -> None:
    """An accidental extra product tool is a load-time failure, not a silent
    scope expansion (P-069)."""
    assert set(plugin.REGISTERED_TOOLS) <= set(plugin.FROZEN_TOOL_SURFACE)
    # Eight Stage 0 contracts, two human-operation tools, and two Stage 6
    # Product-owned inventory tools.
    assert len(plugin.FROZEN_TOOL_SURFACE) == 12


def test_each_registered_schema_names_the_tool_it_belongs_to() -> None:
    for name, schema, _ in plugin.TOOLS:
        assert schema["name"] == name
        assert schema["parameters"]["type"] == "object"
        # No tool may quietly accept an argument the contract does not list.
        assert schema["parameters"].get("additionalProperties") is False


def test_the_cli_health_command_is_registered_without_a_model_facing_tool() -> None:
    ctx = FakeContext()

    plugin.register(ctx)

    assert [entry["name"] for entry in ctx.cli] == ["realestate"]
    assert "realestate" not in plugin.FROZEN_TOOL_SURFACE


def test_the_cli_health_command_prints_the_backend_report(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(plugin, "check_backend", lambda: {"result": "ok"})

    plugin._health_command(None)

    assert json.loads(capsys.readouterr().out) == {"result": "ok"}


def test_the_cli_subcommand_is_wired_to_the_same_handler() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    subparser = parser.add_subparsers().add_parser("realestate")

    plugin._setup_argparse(subparser)

    assert parser.parse_args(["realestate", "health"]).func is plugin._health_command
