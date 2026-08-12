"""Property Document validation (P-047, P-048, P-052, PROPERTY-DOCUMENT-TEMPLATE.md).

Pure functions: no database, no filesystem, no network. Every check completes
before the caller writes an artifact or opens a transaction, so a rejected
upload persists nothing (ADR-0010).

The validator reports ambiguity instead of repairing it. `$1,5000` is an error,
never a guess at 15000 or 1500.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

import yaml

from realestate.domain.text import strip_diacritics

MAX_UPLOAD_BYTES = 100 * 1024
FRONT_MATTER_DELIMITER = "---"

# The exact Stage 0 key set, in template order. All 12 are required and no
# other key is permitted, so a typo is an error rather than silently ignored
# metadata.
REQUIRED_KEYS: tuple[str, ...] = (
    "property_id",
    "name",
    "location",
    "Tipo de inmueble",
    "Venta o Renta",
    "Colonia",
    "Price",
    "Cuartos",
    "Baños",
    "En Coto",
    "Amenidades",
    "Mantenimiento",
)

PROPERTY_KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# An unambiguous MXN amount: an optional $, digits either ungrouped or grouped
# in correct thousands, an optional two-decimal cents part, then MXN.
# "$1,5000 MXN" fails because 5000 is not a three-digit group.
MONEY_PATTERN = re.compile(
    r"^\$?\s*(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{1,2})?\s*MXN$"
)

PROPERTY_TYPES = ("Casa", "Departamento")
TRANSACTION_TYPES = ("En Venta", "En Renta")
GATED_VALUES = ("Sí", "No")

# Front-matter keys whose value must be one of a fixed set. Adding a fourth is a
# line here rather than another copy of the check.
_CONSTRAINED_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Tipo de inmueble", PROPERTY_TYPES),
    ("Venta o Renta", TRANSACTION_TYPES),
    ("En Coto", GATED_VALUES),
)
NO_AMENITIES = "Ninguna"
NOT_APPLICABLE = "No aplica"


class ValidationError(Exception):
    """Raised with the complete field-level error list for a rejected upload."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class PropertyDocument:
    """A validated Property Document, ready to become an immutable artifact."""

    property_key: str
    name: str
    normalized_name: str
    metadata: dict[str, str]
    body: str
    raw_bytes: bytes = field(repr=False)


def normalize_name(value: str) -> str:
    """Fold a Lead-facing name for uniqueness comparison (P-048).

    Ignores letter case, surrounding and repeated whitespace, and diacritics, so
    ``Casa Roble`` and ``cása  roble`` cannot identify different Properties.
    """
    return " ".join(strip_diacritics(value).split()).casefold()


class _StrictLoader(yaml.BaseLoader):
    """Load every scalar as a string and reject duplicate keys.

    ``BaseLoader`` is deliberate: YAML 1.1 would resolve the ``En Coto`` value
    ``No`` to boolean False and ``Sí`` to a string, so the two accepted values
    would arrive as different types. Validating the literal text keeps the
    contract honest.
    """


def _construct_mapping(loader: _StrictLoader, node: yaml.MappingNode) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in mapping:
            raise yaml.YAMLError(f"duplicate front-matter key: {key}")
        mapping[key] = loader.construct_object(value_node)
    return mapping


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def _split_front_matter(text: str) -> tuple[str, str]:
    """Return (front matter, body) or raise with the structural error."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONT_MATTER_DELIMITER:
        raise ValidationError(
            ["The document must begin with a YAML front-matter block delimited by ---."]
        )

    closing = next(
        (i for i in range(1, len(lines)) if lines[i].strip() == FRONT_MATTER_DELIMITER),
        None,
    )
    if closing is None:
        raise ValidationError(["The YAML front-matter block is never closed with ---."])

    body_lines = lines[closing + 1 :]
    # A second front-matter block is not permitted (P-052: exactly once).
    first_content = next((i for i, ln in enumerate(body_lines) if ln.strip()), None)
    if first_content is not None and body_lines[first_content].strip() == FRONT_MATTER_DELIMITER:
        raise ValidationError(
            ["The document contains more than one YAML front-matter block."]
        )

    return "\n".join(lines[1:closing]), "\n".join(body_lines)


def _validate_money(label: str, value: str, allow_not_applicable: bool) -> list[str]:
    if allow_not_applicable and value == NOT_APPLICABLE:
        return []
    if not MONEY_PATTERN.match(value):
        allowed = f" or exactly '{NOT_APPLICABLE}'" if allow_not_applicable else ""
        return [
            f"{label}: {value!r} is not an unambiguous amount denominated in MXN. "
            f"Use a form such as '$3,000,000 MXN'{allowed}."
        ]
    try:
        Decimal(value.replace("$", "").replace(",", "").replace("MXN", "").strip())
    except InvalidOperation:
        return [f"{label}: {value!r} is not a readable amount."]
    return []


def _validate_metadata(metadata: dict[str, str]) -> list[str]:
    errors: list[str] = []

    missing = [key for key in REQUIRED_KEYS if key not in metadata]
    if missing:
        errors.append(f"Missing required front-matter key(s): {', '.join(missing)}.")
    unexpected = [key for key in metadata if key not in REQUIRED_KEYS]
    if unexpected:
        errors.append(f"Unexpected front-matter key(s): {', '.join(sorted(unexpected))}.")

    for key, value in metadata.items():
        if key in REQUIRED_KEYS and not isinstance(value, str):
            errors.append(f"{key}: expected a text value.")
    if errors:
        return errors

    for key in REQUIRED_KEYS:
        if not metadata[key].strip():
            errors.append(f"{key}: must not be empty.")
    if errors:
        return errors

    property_key = metadata["property_id"].strip()
    if not PROPERTY_KEY_PATTERN.match(property_key):
        errors.append(
            f"property_id: {property_key!r} must be a lowercase slug of letters and "
            "digits separated by single hyphens, such as 'casa-roble'."
        )

    for key, allowed in _CONSTRAINED_KEYS:
        if metadata[key] not in allowed:
            # The accepted values are quoted: several carry accents ('Sí'), and
            # an unaccented retry is the most common mistake this catches, so the
            # exact spelling must be visually delimited from the message around it.
            expected = " or ".join(repr(value) for value in allowed)
            errors.append(
                f"{key}: must be exactly {expected}, not {metadata[key]!r}."
            )

    cuartos = metadata["Cuartos"].strip()
    if not re.match(r"^\d+$", cuartos):
        errors.append(f"Cuartos: {cuartos!r} must be a non-negative integer.")

    banos = metadata["Baños"].strip()
    try:
        value = Decimal(banos)
        if value < 0 or (value * 2) % 1 != 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        errors.append(
            f"Baños: {banos!r} must be a non-negative number in increments of 0.5."
        )

    errors.extend(_validate_money("Price", metadata["Price"].strip(), False))
    errors.extend(
        _validate_money("Mantenimiento", metadata["Mantenimiento"].strip(), True)
    )

    amenidades = metadata["Amenidades"].strip()
    if amenidades != NO_AMENITIES:
        items = [item.strip() for item in amenidades.split(",")]
        if any(not item for item in items):
            errors.append(
                f"Amenidades: must be a comma-separated list with no empty entries, "
                f"or exactly '{NO_AMENITIES}'."
            )

    return errors


def _validate_body(body: str, name: str) -> list[str]:
    stripped = body.strip()
    if not stripped:
        return ["The Markdown body must not be empty."]

    first_line = next(line for line in body.splitlines() if line.strip())
    # A "## " heading fails this too: it does not start with "# ".
    if not first_line.startswith("# "):
        return [
            "The body must begin with a level-one heading matching the front-matter "
            f"name, for example '# {name}'."
        ]

    heading = first_line[2:].strip()
    if heading != name.strip():
        return [
            f"The first heading {heading!r} does not match the front-matter name "
            f"{name.strip()!r}."
        ]
    return []


def validate_upload(filename: str, content: bytes) -> PropertyDocument:
    """Validate one uploaded file completely, or raise ``ValidationError``.

    Order matters: file-level checks first, then structure, then metadata, then
    the body. Nothing is written by this function under any outcome.
    """
    errors: list[str] = []

    if not filename.lower().endswith(".md"):
        errors.append(f"{filename!r} is not a .md file.")
    if len(content) > MAX_UPLOAD_BYTES:
        errors.append(
            f"The file is {len(content)} bytes; the maximum is {MAX_UPLOAD_BYTES}."
        )
    if not content:
        errors.append("The file is empty.")
    if errors:
        raise ValidationError(errors)

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise ValidationError(["The file is not valid UTF-8."]) from None

    front_matter, body = _split_front_matter(text)

    try:
        parsed = yaml.load(front_matter, Loader=_StrictLoader)
    except yaml.YAMLError as exc:
        raise ValidationError([f"The YAML front matter could not be parsed: {exc}."]) from None
    if not isinstance(parsed, dict):
        raise ValidationError(["The YAML front matter must be a set of key/value pairs."])

    errors = _validate_metadata(parsed)
    if errors:
        raise ValidationError(errors)

    errors = _validate_body(body, parsed["name"])
    if errors:
        raise ValidationError(errors)

    name = parsed["name"].strip()
    return PropertyDocument(
        property_key=parsed["property_id"].strip(),
        name=name,
        normalized_name=normalize_name(name),
        metadata={key: parsed[key].strip() for key in REQUIRED_KEYS},
        body=body,
        raw_bytes=content,
    )
