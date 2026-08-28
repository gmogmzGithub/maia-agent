"""Reading an operator surface the way a person does.

Both surface suites stripped markup with their own identical copy of these
regexes. One copy, so a change to what counts as "visible" cannot make one
suite's vocabulary guarantee weaker than the other's.
"""

from __future__ import annotations

import re

_TAGS = re.compile(r"<[^>]+>")
_DROPPED = re.compile(r"<(style|script)\b.*?</\1>", re.DOTALL | re.IGNORECASE)


def visible_text(html: str) -> str:
    """What a person actually reads, without markup or the stylesheet."""
    return _TAGS.sub(" ", _DROPPED.sub(" ", html))
