"""The source-controlled current-copy projection for Property Documents."""

from pathlib import Path

from realestate.domain.properties import CatalogStore


def test_catalog_replace_read_and_restore(tmp_path: Path) -> None:
    catalog = CatalogStore(tmp_path / "properties")

    assert catalog.read("casa-roble") is None
    assert catalog.replace("casa-roble", b"version one") is None
    assert catalog.read("casa-roble") == b"version one"

    previous = catalog.replace("casa-roble", b"version two")
    assert previous == b"version one"
    assert catalog.read("casa-roble") == b"version two"

    catalog.restore("casa-roble", previous)
    assert catalog.read("casa-roble") == b"version one"
    catalog.restore("casa-roble", None)
    assert catalog.read("casa-roble") is None
