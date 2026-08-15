"""Translate the small Markdown subset Hermes may emit into WhatsApp markup.

Hermes writes natural replies using common Markdown conventions, while the
WhatsApp Cloud API expects its own lightweight markup. In particular, Markdown
bold is ``**text**`` but WhatsApp bold is ``*text*``. This conversion belongs
at the outbound WhatsApp boundary so Product truth, Hermes history, and other
channels keep the original assistant text.

Single asterisks are intentionally preserved: they are already the WhatsApp
bold marker and are ambiguous between Markdown italics and WhatsApp bold. The
Sales role is instructed to use underscores for italics, which is valid in both
the requested output contract and WhatsApp.
"""

from __future__ import annotations

import re


_BOLD_MARKDOWN = re.compile(r"(?<!\*)\*\*(?!\s)(.+?)(?<!\s)\*\*(?!\*)", re.DOTALL)
_BOLD_UNDERSCORE_MARKDOWN = re.compile(
    r"(?<!_)__(?!\s)(.+?)(?<!\s)__(?!_)", re.DOTALL
)
_STRIKE_MARKDOWN = re.compile(r"(?<!~)~~(?!\s)(.+?)(?<!\s)~~(?!~)", re.DOTALL)


def to_whatsapp_markup(text: str) -> str:
    """Return *text* with common Markdown emphasis mapped to WhatsApp syntax.

    The substitutions are deliberately narrow. They do not interpret list
    bullets, headings, URLs, or single-star spans, so ordinary conversational
    punctuation cannot accidentally become formatting.
    """
    if not text:
        return text

    text = _BOLD_MARKDOWN.sub(lambda match: f"*{match.group(1)}*", text)
    text = _BOLD_UNDERSCORE_MARKDOWN.sub(lambda match: f"*{match.group(1)}*", text)
    return _STRIKE_MARKDOWN.sub(lambda match: f"~{match.group(1)}~", text)
