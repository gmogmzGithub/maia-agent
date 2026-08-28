"""The municipalities Larevia serves, declared once.

CONTEXT.md defines the Service Area as the *initial* market, so expansion is
expected rather than hypothetical. Before this module the same three names were
spelled six ways — a ``frozenset`` for the public catalogue, another for external
inventory, a regex in the plugin contract, a slug map in the site process and a
canonicalisation table in the provider mapper. Opening a fourth municipality
meant finding all of them, and missing one failed silently: a zone that searches
but has no landing page, or a tool that refuses what the catalogue allows.

The site process and the standalone plugin package keep their own copies on
purpose. Both are separate deployables that must not import Product's domain,
so they receive the area through their contracts instead.
"""

from __future__ import annotations

SERVICE_AREA = frozenset({"Guadalajara", "Zapopan", "Tlaquepaque"})


def service_area_pattern() -> str:
    """An anchored alternation for schema validators that need a regex."""
    return f"^({'|'.join(sorted(SERVICE_AREA))})$"
