#!/usr/bin/env python3
"""Install user login services for the local Maia pilot, without reading .env."""

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path


def run(*args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True)


def main():
    if sys.platform != "darwin":
        raise SystemExit("Este instalador requiere macOS.")
    home = Path.home()
    agents = home / "Library/LaunchAgents"
    logs = home / "Library/Logs/Maia"
    config = home / ".cloudflared/config.yml"
    docker = shutil.which("docker")
    cloudflared = shutil.which("cloudflared")
    if not docker or not cloudflared or not config.is_file():
        raise SystemExit("Faltan Docker, cloudflared o la configuración local del túnel.")
    if not Path("/Applications/OrbStack.app").is_dir():
        raise SystemExit("Este equipo requiere revisar el arranque de su motor Docker.")
    # Inspect only container IDs. Never print resolved Compose configuration.
    ids = run(
        docker, "--context", "orbstack", "ps", "-aq",
        "--filter", "label=com.docker.compose.project=maia-incremento1",
        "--filter", "label=com.docker.compose.oneoff=False",
    ).stdout.split()
    if len(ids) != 4:
        raise SystemExit("Se esperaban los cuatro contenedores existentes de Maia.")
    definitions = {
        "local.maia.awake": {
            "ProgramArguments": ["/usr/bin/caffeinate", "-is"],
            "KeepAlive": True,
        },
        "local.maia.tunnel": {
            "ProgramArguments": [
                cloudflared, "tunnel", "--config", str(config),
                "--loglevel", "warn", "run", "maia-sandbox",
            ],
            "KeepAlive": True,
        },
        "local.maia.engine": {
            "ProgramArguments": [
                "/usr/bin/open", "-g", "-a", "/Applications/OrbStack.app",
            ],
            "KeepAlive": {"SuccessfulExit": False},
        },
    }
    agents.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    run(docker, "--context", "orbstack", "update", "--restart", "unless-stopped", *ids)
    for label, definition in definitions.items():
        path = agents / f"{label}.plist"
        data = {
            "Label": label,
            "RunAtLoad": True,
            "ThrottleInterval": 15,
            "WorkingDirectory": str(home),
            "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
            "StandardOutPath": str(logs / f"{label}.log"),
            "StandardErrorPath": str(logs / f"{label}.log"),
            **definition,
        }
        encoded = plistlib.dumps(data)
        unchanged = path.is_file() and path.read_bytes() == encoded
        loaded = run("launchctl", "print", f"{domain}/{label}", check=False).returncode == 0
        if unchanged and loaded:
            print(f"Ya instalado: {label}")
            continue
        if loaded:
            run("launchctl", "bootout", f"{domain}/{label}")
        path.write_bytes(encoded)
        path.chmod(0o644)
        run("plutil", "-lint", str(path))
        run("launchctl", "enable", f"{domain}/{label}")
        run("launchctl", "bootstrap", domain, str(path))
        print(f"Instalado: {label}")
    print("Arranque al iniciar sesión. Tras reiniciar la Mac, desbloquear e iniciar sesión.")
    print("Mantener corriente, Internet y tapa abierta. La pantalla puede apagarse.")


if __name__ == "__main__":
    main()
