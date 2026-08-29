"""The entrypoint must hand Hermes Maia's fixed tool surface, not a searchable one.

Asserts the whole emitted document rather than individual keys, so a stray or
renamed key fails here instead of silently changing how Hermes exposes tools.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

from tests.conftest import REPO_ROOT

ROLES = REPO_ROOT / "roles"
EXPECTED_MODELS = {
    "config.yaml": "test-admin-model",
    "profiles/sales/config.yaml": "test-sales-model",
    "profiles/admin/config.yaml": "test-admin-model",
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_entrypoint_pins_product_sessions_to_eager_maia_tools(tmp_path: Path) -> None:
    home = tmp_path / "hermes-home"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    hermes_stub = bin_dir / "hermes"
    hermes_stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hermes_stub.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "HERMES_HOME": str(home),
            "HERMES_DASHBOARD_SESSION_TOKEN": "test-session-token",
            "REALESTATE_PLUGIN_API_TOKEN": "test-plugin-token",
            "MODEL_PROVIDER": "anthropic",
            "SALES_MODEL": "test-sales-model",
            "ADMIN_MODEL": "test-admin-model",
            "MAIA_ROLES_ROOT": str(ROLES),
        }
    )

    # Output is left on the terminal: check=True reports only an exit code, so
    # capturing it would hide whichever required variable the script rejected.
    subprocess.run(
        ["bash", str(REPO_ROOT / "docker" / "hermes-entrypoint.sh")],
        env=env,
        check=True,
    )

    for relative, expected_model in EXPECTED_MODELS.items():
        assert yaml.safe_load(read(home / relative)) == {
            "model": {"default": expected_model, "provider": "anthropic"},
            "plugins": {"enabled": ["realestate"]},
            "tools": {"tool_search": False},
            "platform_toolsets": {"product": ["realestate"]},
        }, relative

    for role in ("sales", "admin"):
        assert read(home / "profiles" / role / "SOUL.md") == read(ROLES / role / "SOUL.md")
