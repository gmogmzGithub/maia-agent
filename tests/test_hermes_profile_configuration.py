from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml


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
            "MAIA_ROLES_ROOT": str(Path("roles").resolve()),
        }
    )

    subprocess.run(
        ["bash", "docker/hermes-entrypoint.sh"],
        cwd=Path.cwd(),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    for profile, expected_model in (
        ("sales", "test-sales-model"),
        ("admin", "test-admin-model"),
    ):
        config = yaml.safe_load(
            (home / "profiles" / profile / "config.yaml").read_text(
                encoding="utf-8"
            )
        )
        assert config["model"] == {
            "default": expected_model,
            "provider": "anthropic",
        }
        assert config["plugins"]["enabled"] == ["realestate"]
        assert config["tools"]["tool_search"] is False
        assert config["platform_toolsets"] == {"product": ["realestate"]}
        assert (home / "profiles" / profile / "SOUL.md").read_text(
            encoding="utf-8"
        ) == (Path("roles") / profile / "SOUL.md").read_text(encoding="utf-8")

    root_config = yaml.safe_load(
        (home / "config.yaml").read_text(encoding="utf-8")
    )
    assert root_config["tools"]["tool_search"] is False
    assert root_config["platform_toolsets"] == {"product": ["realestate"]}
