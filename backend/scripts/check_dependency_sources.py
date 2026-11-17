"""Reject dependency locks that require a private registry or credentials in CI."""

import sys
import tomllib
from pathlib import Path
from urllib.parse import urlparse

lock = Path(__file__).resolve().parents[1] / "uv.lock"
packages = tomllib.loads(lock.read_text())["package"]
allowed = {"pypi.org", "files.pythonhosted.org"}
failures = []
for package in packages:
    source = package.get("source", {})
    urls = [source["registry"]] if "registry" in source else []
    urls.extend(
        artifact["url"]
        for artifact in [package.get("sdist", {}), *package.get("wheels", [])]
        if "url" in artifact
    )
    for value in urls:
        url = urlparse(value)
        if url.scheme != "https" or url.hostname not in allowed or url.username or url.password:
            failures.append(package["name"])
            break
if failures:
    print(f"Dependency lock needs non-public sources: {', '.join(sorted(set(failures)))}")
    sys.exit(1)
print(f"OK: {len(packages)} locked packages use public dependency sources.")
