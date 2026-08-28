"""The one reading of "now" (UTC).

Every module that needed the current instant used to spell its own
``_now()``. They agreed, which is exactly why the duplication was invisible:
nothing would have failed if one of them had drifted to a naive datetime or to
local time. One function also gives the suites a single seam to move time at,
instead of a dozen private ones that must each be patched.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """The current instant, always timezone-aware and always UTC."""
    return datetime.now(tz=UTC)
