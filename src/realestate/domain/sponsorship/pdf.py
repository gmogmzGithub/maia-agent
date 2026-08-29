"""A minimal PDF writer, because a buyer report has to be a file.

ADR-0044 requires the campaign report as an exportable PDF. Every general PDF
library available would be a new dependency carrying font handling, image
decoding and a much larger attack surface than one page of text needs, so this
module writes the format directly.

The scope is deliberately tiny: one page size, one built-in font, left-aligned
text lines, and nothing else. No images, no embedded fonts, no external
resources, no JavaScript — a document that can only contain the characters
somebody passed in is a document that cannot leak anything they did not.

The escaping is the part worth reading. PDF string literals treat ``(``, ``)``
and ``\\`` as syntax, so an unescaped Spanish property title with a parenthesis
in it would produce a corrupt file rather than an error.
"""

from __future__ import annotations

from dataclasses import dataclass

#: US Letter in points, the default the operator's printer expects.
PAGE_WIDTH = 612
PAGE_HEIGHT = 792
MARGIN = 56
LINE_HEIGHT = 14
TITLE_SIZE = 16
HEADING_SIZE = 12
BODY_SIZE = 10

#: Lines per page at body size, leaving room for the margins.
CONTENT_TOP = PAGE_HEIGHT - 86
CONTENT_BOTTOM = 58

#: Characters per line before wrapping. Helvetica is proportional, so an exact
#: width would need font metrics this module deliberately does not carry; the
#: conservative count keeps the widest plausible line inside the margins
#: instead. Without it a long Spanish disclosure would simply run off the page,
#: because PDF text does not wrap on its own.
CHARACTERS_PER_LINE = 92

#: WinAnsiEncoding covers the Latin-1 range, which is every character Mexican
#: Spanish needs. Anything outside it is transliterated rather than dropped
#: silently: a report reading "Zapopan" is better than one reading "Zapopa".
_FALLBACK = {
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
    "…": "...",
    " ": " ",
    "·": "-",
}


class Style(str):
    """Which font size and weight one line uses."""

    TITLE = "title"
    HEADING = "heading"
    BODY = "body"
    METRIC = "metric"
    NOTE = "note"


@dataclass(frozen=True)
class Line:
    text: str
    style: str = Style.BODY


def _encoded(text: str) -> bytes:
    for source, target in _FALLBACK.items():
        text = text.replace(source, target)
    return text.encode("latin-1", errors="replace")


def _escaped(text: str) -> bytes:
    body = _encoded(text)
    for source, target in ((b"\\", b"\\\\"), (b"(", b"\\("), (b")", b"\\)")):
        body = body.replace(source, target)
    return body


def _size(style: str) -> int:
    if style == Style.TITLE:
        return TITLE_SIZE
    if style == Style.HEADING:
        return HEADING_SIZE
    if style == Style.METRIC:
        return 11
    if style == Style.NOTE:
        return 8
    return BODY_SIZE


def _font(style: str) -> str:
    return "F2" if style in (Style.TITLE, Style.HEADING, Style.METRIC) else "F1"


def wrapped(lines: list[Line]) -> list[Line]:
    """Break each line at word boundaries, preserving its style and order.

    Applied before pagination, because a wrapped paragraph changes how many
    lines a page holds. A word longer than the limit is split rather than
    allowed to overflow: a truncated URL is readable, an invisible one is not.
    """
    out: list[Line] = []
    for line in lines:
        if len(line.text) <= CHARACTERS_PER_LINE:
            out.append(line)
            continue
        indent = " " * (len(line.text) - len(line.text.lstrip()))
        room = max(1, CHARACTERS_PER_LINE - len(indent))
        current = ""
        for word in line.text.split():
            while len(word) > room:
                out.append(Line(indent + word[:room], line.style))
                word = word[room:]
            candidate = f"{current} {word}".strip()
            if len(candidate) > room:
                out.append(Line(indent + current, line.style))
                current = word
            else:
                current = candidate
        if current:
            out.append(Line(indent + current, line.style))
    return out


def _line_height(line: Line) -> int:
    if not line.text:
        return 8
    if line.style == Style.TITLE:
        return 28
    if line.style == Style.HEADING:
        return 25
    if line.style == Style.METRIC:
        return 30
    if line.style == Style.NOTE:
        return 11
    return LINE_HEIGHT


def _pages(lines: list[Line]) -> list[list[Line]]:
    pages: list[list[Line]] = [[]]
    used = 0
    available = CONTENT_TOP - CONTENT_BOTTOM
    for index, line in enumerate(lines):
        height = _line_height(line)
        following = _line_height(lines[index + 1]) if index + 1 < len(lines) else 0
        keep_height = following if line.style == Style.HEADING else 0
        if line.style == Style.HEADING:
            block_height = height
            for following_line in lines[index + 1 :]:
                if following_line.style == Style.HEADING:
                    break
                block_height += _line_height(following_line)
            if block_height <= available:
                keep_height = block_height - height
        if pages[-1] and used + height + keep_height > available:
            pages.append([])
            used = 0
        pages[-1].append(line)
        used += height
    return pages


def _text(parts: list[bytes], text: str, *, font: str, size: int, x: int, y: int) -> None:
    parts.extend(
        (
            b"BT",
            f"/{font} {size} Tf".encode("latin-1"),
            f"1 0 0 1 {x} {y} Tm".encode("latin-1"),
            b"(" + _escaped(text) + b") Tj",
            b"ET",
        )
    )


def _content_stream(
    lines: list[Line], *, page_number: int, page_count: int
) -> bytes:
    parts = [b"0.985 0.978 0.955 rg", f"0 0 {PAGE_WIDTH} {PAGE_HEIGHT} re f".encode()]
    parts.extend((b"0.08 0.16 0.20 rg", b"56 744 500 1 re f"))
    _text(parts, "LAREVIA  |  REPORTE PATROCINADA", font="F2", size=9, x=MARGIN, y=758)
    _text(
        parts,
        f"Página {page_number} de {page_count}",
        font="F1",
        size=8,
        x=PAGE_WIDTH - 110,
        y=32,
    )
    y = CONTENT_TOP
    for line in lines:
        height = _line_height(line)
        y -= height
        if not line.text:
            continue
        size = _size(line.style)
        if line.style == Style.HEADING:
            parts.extend(
                (
                    b"0.91 0.86 0.71 rg",
                    f"{MARGIN - 6} {y - 4} 506 20 re f".encode("latin-1"),
                    b"0.08 0.16 0.20 rg",
                )
            )
            _text(parts, line.text, font=_font(line.style), size=size, x=MARGIN, y=y + 1)
        elif line.style == Style.METRIC:
            parts.extend(
                (
                    b"0.95 0.93 0.86 rg",
                    f"{MARGIN} {y - 3} 500 24 re f".encode("latin-1"),
                    b"0.08 0.16 0.20 rg",
                )
            )
            _text(parts, line.text, font=_font(line.style), size=size, x=MARGIN + 10, y=y + 4)
        else:
            parts.append(b"0.12 0.14 0.15 rg")
            _text(parts, line.text, font=_font(line.style), size=size, x=MARGIN, y=y)
    return b"\n".join(parts)


def render(lines: list[Line]) -> bytes:
    """One PDF document containing *lines*, paginated at a fixed line count.

    Objects are emitted in a fixed order and the cross-reference table is built
    from the byte offsets as they are produced. Writing the xref from measured
    offsets rather than computed ones is what keeps the file valid when a line's
    escaping changes its length.
    """
    flowed = wrapped(lines)
    pages = _pages(flowed) or [[]]

    # Object numbering: 1 catalog, 2 pages tree, 3 and 4 the two fonts, then a
    # page object and a content stream per page.
    page_ids = [5 + index * 2 for index in range(len(pages))]
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            "<< /Type /Pages /Count {count} /Kids [{kids}] >>".format(
                count=len(pages),
                kids=" ".join(f"{identifier} 0 R" for identifier in page_ids),
            ).encode("latin-1")
        ),
        3: (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>"
        ),
        4: (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
            b"/Encoding /WinAnsiEncoding >>"
        ),
    }
    for index, (identifier, page_lines) in enumerate(zip(page_ids, pages)):
        stream = _content_stream(
            page_lines, page_number=index + 1, page_count=len(pages)
        )
        objects[identifier] = (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
            "/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
            "/Contents {contents} 0 R >>".format(
                width=PAGE_WIDTH,
                height=PAGE_HEIGHT,
                contents=identifier + 1,
            ).encode("latin-1")
        )
        objects[identifier + 1] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1")
            + stream
            + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.7\n")
    offsets: dict[int, int] = {}
    for identifier in sorted(objects):
        offsets[identifier] = len(out)
        out += f"{identifier} 0 obj\n".encode("latin-1")
        out += objects[identifier]
        out += b"\nendobj\n"
    xref_at = len(out)
    highest = max(objects) + 1
    out += f"xref\n0 {highest}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for identifier in range(1, highest):
        offset = offsets.get(identifier, 0)
        out += f"{offset:010d} 00000 n \n".encode("latin-1")
    out += (
        f"trailer\n<< /Size {highest} /Root 1 0 R >>\nstartxref\n{xref_at}\n"
        "%%EOF\n"
    ).encode("latin-1")
    return bytes(out)
