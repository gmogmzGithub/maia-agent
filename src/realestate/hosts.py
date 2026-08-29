"""The hostname vocabulary two processes share: the header, and how to read it.

Product resolves which Brokerage Organization a public request belongs to from a
hostname, and the site process tells Product which hostname it is serving. Both
therefore have to agree on what "the host" of ``https://larevia.mx:443/`` is, and
a second copy of three lines is exactly the kind of duplication that drifts —
one side stripping the port and the other not is a routing bug that only appears
behind a proxy.

It lives at the package root with no imports because of the process boundary:
:mod:`realestate.site` runs without database or provider credentials and must not
reach into :mod:`realestate.domain`, so a shared helper cannot live there.
"""

from __future__ import annotations

#: The header the site process sends on every Product call, carrying the public
#: hostname it serves. Product resolves the Organization from it rather than from
#: "the only Organization", so two brands can be served from one installation
#: without either one's catalog appearing on the other's pages (ADR-0050).
#:
#: The site process is configured for one public origin, so the value is constant
#: for that process's lifetime — a second brand runs a second site process, which
#: is a Stage 9 operating limit rather than a boundary.
#:
#: Named once here for the same reason as :func:`host_of`: the sender and the
#: reader live in different processes, and a casing or hyphen typo in a second
#: copy would not fail loudly — Product would silently fall back to the request's
#: own ``Host`` header and misroute behind a proxy.
SITE_HOST_HEADER = "X-Site-Host"


def host_of(origin: str) -> str:
    """The bare hostname of an origin: no scheme, no port, no path, lowercased.

    A comma-separated value — what a chain of proxies produces in a forwarded
    header — yields its first entry, which is the client-facing name.
    """
    without_scheme = origin.split("://", 1)[-1]
    first = without_scheme.split(",", 1)[0].strip()
    return first.split("/", 1)[0].rsplit(":", 1)[0].strip().lower()
