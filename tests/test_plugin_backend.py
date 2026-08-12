"""The plugin -> Product application boundary (ADR-0009).

Checkpoint 0 requires "the standalone plugin package with a health-tested call
to the Product application". The live test below is that health test; the
offline ones prove the adapter degrades into a structured result instead of
raising inside the Hermes tool loop.
"""

from __future__ import annotations

import pytest

from realestate_hermes_plugin.backend import BackendConfig, check_backend
from tests.conftest import APP_BASE_URL, requires_app


def config(token: str, base_url: str = APP_BASE_URL) -> BackendConfig:
    return BackendConfig(base_url=base_url, token=token, timeout_seconds=5.0)


# --- Offline ----------------------------------------------------------------


def test_missing_credential_degrades_instead_of_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REALESTATE_PLUGIN_API_TOKEN", raising=False)

    result = check_backend()

    assert result["result"] == "temporarily_unavailable"
    assert "REALESTATE_PLUGIN_API_TOKEN" in result["detail"]


def test_unreachable_backend_degrades_instead_of_raising() -> None:
    result = check_backend(config=config(token="irrelevant", base_url="http://127.0.0.1:9"))

    assert result["result"] == "temporarily_unavailable"
    assert "not reachable" in result["detail"]


# --- Live -------------------------------------------------------------------


@requires_app
def test_plugin_reaches_the_product_application(plugin_token: str) -> None:
    result = check_backend(config=config(plugin_token))

    assert result["result"] == "ok", result
    assert result["application"] == "maia-agent"
    assert result["database"] == "ok"
    # The tools registered so far, and nothing beyond the frozen Stage 0 surface.
    import realestate_hermes_plugin as plugin

    assert result["product_tools"] == list(plugin.REGISTERED_TOOLS)
    assert set(result["product_tools"]) <= set(plugin.FROZEN_TOOL_SURFACE)


@requires_app
def test_trusted_session_context_is_forwarded(plugin_token: str) -> None:
    result = check_backend(
        session_id="hermes-session-abc",
        task_id="hermes-task-def",
        config=config(plugin_token),
    )

    assert result["trusted_context"] == {
        "session_id": "hermes-session-abc",
        "task_id": "hermes-task-def",
        # An unbound session resolves to no Role — identity is never inferred.
        "role": None,
    }


@requires_app
def test_a_wrong_plugin_credential_is_rejected() -> None:
    result = check_backend(config=config("not-the-real-token"))

    assert result["result"] == "forbidden"
