"""Versioned Property Document validation and generation.

Property Documents contain customer-safe structured facts plus approved narrative.
They deliberately exclude runtime availability, the private Visit Address, source
URLs, and every kind of image. Product validates the complete document before any
catalog, artifact, or database mutation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

import yaml

from realestate.domain.text import strip_diacritics

MAX_UPLOAD_BYTES = 100 * 1024
FRONT_MATTER_DELIMITER = "---"
SCHEMA_VERSION = 1

PROPERTY_KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PROPERTY_TYPES = ("House", "Apartment", "Land")
OPERATIONS = ("Sale", "Rental")
CURRENCIES = ("MXN", "USD")
MAINTENANCE_STATUSES = ("Fee", "None", "Unknown")

PRIVATE_CHARACTERISTICS = (
    "Jardín privado",
    "Bodega",
    "Cisterna",
    "Paneles solares",
    "Estacionamiento techado",
    "Alberca privada",
)

COMMUNITY_AMENITIES = (
    "Jardines comunes",
    "Alberca",
    "Gimnasio",
    "Jacuzzi",
    "Área de juegos infantiles",
    "Salón de usos múltiples",
    "Casa club",
    "Terraza",
    "Seguridad 24 horas",
    "Estacionamiento de visitas",
    "Centro de negocios",
)

REQUIRED_KEYS = (
    "schema_version",
    "property_id",
    "name",
    "property_type",
    "operation",
    "price_amount",
    "price_currency",
    "state",
    "city",
    "neighborhood",
    "half_bathrooms",
    "parking_spaces",
    "maintenance_status",
    "maintenance_description",
    "in_development",
)

OPTIONAL_KEYS = (
    "public_location_notes",
    "bedrooms",
    "full_bathrooms",
    "construction_m2",
    "land_m2",
    "floors",
    "year_built",
    "maintenance_amount",
    "maintenance_currency",
    "private_characteristics",
    "other_private_characteristic",
    "community_amenities",
    "other_community_amenity",
)

ALLOWED_KEYS = REQUIRED_KEYS + OPTIONAL_KEYS


class ValidationError(Exception):
    """Raised with every field-level reason a document cannot be accepted."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class PropertyDocument:
    """A validated Property Document ready for immutable acceptance."""

    property_key: str
    name: str
    normalized_name: str
    metadata: dict[str, Any]
    body: str
    raw_bytes: bytes = field(repr=False)


def normalize_name(value: str) -> str:
    """Fold a customer-facing name for uniqueness comparison."""
    return " ".join(strip_diacritics(value).split()).casefold()


def slugify_property_name(value: str) -> str:
    """Generate the readable immutable Property Key proposed by the admin form."""
    folded = strip_diacritics(value).casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")
    return slug[:120].rstrip("-")


class _StrictLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_mapping(loader: _StrictLoader, node: yaml.MappingNode) -> dict:
    mapping: dict = {}
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
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONT_MATTER_DELIMITER:
        raise ValidationError(
            ["The document must begin with YAML front matter delimited by ---."]
        )
    closing = next(
        (index for index in range(1, len(lines)) if lines[index].strip() == "---"),
        None,
    )
    if closing is None:
        raise ValidationError(["The YAML front matter is never closed with ---."])
    return "\n".join(lines[1:closing]), "\n".join(lines[closing + 1 :])


def _required_text(metadata: dict[str, Any], key: str, errors: list[str]) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{key}: must be non-empty text.")
        return ""
    return value.strip()


def _optional_text(metadata: dict[str, Any], key: str, errors: list[str]) -> str | None:
    if key not in metadata or metadata[key] is None:
        return None
    value = metadata[key]
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{key}: must be non-empty text when provided.")
        return None
    return value.strip()


def _decimal(
    metadata: dict[str, Any],
    key: str,
    errors: list[str],
    *,
    required: bool,
    positive: bool = False,
) -> Decimal | None:
    if key not in metadata or metadata[key] in (None, ""):
        if required:
            errors.append(f"{key}: is required.")
        return None
    value = metadata[key]
    if isinstance(value, bool):
        errors.append(f"{key}: must be a number.")
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        errors.append(f"{key}: must be a number.")
        return None
    if not number.is_finite() or number < 0 or (positive and number <= 0):
        qualifier = "greater than zero" if positive else "zero or greater"
        errors.append(f"{key}: must be {qualifier}.")
        return None
    return number


def _integer(
    metadata: dict[str, Any],
    key: str,
    errors: list[str],
    *,
    required: bool,
    positive: bool = False,
) -> int | None:
    number = _decimal(metadata, key, errors, required=required, positive=positive)
    if number is None:
        return None
    if number != number.to_integral_value():
        errors.append(f"{key}: must be a whole number.")
        return None
    return int(number)


def _choice(
    metadata: dict[str, Any], key: str, allowed: tuple[str, ...], errors: list[str]
) -> str:
    value = metadata.get(key)
    if value not in allowed:
        errors.append(f"{key}: must be one of {', '.join(allowed)}.")
        return ""
    return str(value)


def _string_list(
    metadata: dict[str, Any],
    key: str,
    allowed: tuple[str, ...],
    errors: list[str],
) -> list[str]:
    value = metadata.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        errors.append(f"{key}: must be a list of text values.")
        return []
    cleaned = [item.strip() for item in value]
    unknown = [item for item in cleaned if item not in allowed]
    if unknown:
        errors.append(f"{key}: unsupported value(s): {', '.join(unknown)}.")
    if len(cleaned) != len(set(cleaned)):
        errors.append(f"{key}: duplicate values are not allowed.")
    return cleaned


def _validate_metadata(metadata: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    missing = [key for key in REQUIRED_KEYS if key not in metadata]
    if missing:
        errors.append(f"Missing required front-matter key(s): {', '.join(missing)}.")
    unexpected = [key for key in metadata if key not in ALLOWED_KEYS]
    if unexpected:
        errors.append(f"Unexpected front-matter key(s): {', '.join(sorted(unexpected))}.")

    if metadata.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version: must be exactly {SCHEMA_VERSION}.")

    property_key = _required_text(metadata, "property_id", errors)
    name = _required_text(metadata, "name", errors)
    state = _required_text(metadata, "state", errors)
    city = _required_text(metadata, "city", errors)
    neighborhood = _required_text(metadata, "neighborhood", errors)
    maintenance_description = _required_text(
        metadata, "maintenance_description", errors
    )
    public_notes = _optional_text(metadata, "public_location_notes", errors)
    other_private = _optional_text(metadata, "other_private_characteristic", errors)
    other_community = _optional_text(metadata, "other_community_amenity", errors)

    if property_key and not PROPERTY_KEY_PATTERN.fullmatch(property_key):
        errors.append(
            "property_id: must use lowercase letters and digits separated by "
            "single hyphens."
        )

    property_type = _choice(metadata, "property_type", PROPERTY_TYPES, errors)
    operation = _choice(metadata, "operation", OPERATIONS, errors)
    price_currency = _choice(metadata, "price_currency", CURRENCIES, errors)
    maintenance_status = _choice(
        metadata, "maintenance_status", MAINTENANCE_STATUSES, errors
    )

    price_amount = _decimal(
        metadata, "price_amount", errors, required=True, positive=True
    )
    half_bathrooms = _integer(metadata, "half_bathrooms", errors, required=True)
    parking_spaces = _integer(metadata, "parking_spaces", errors, required=True)

    residential = property_type in {"House", "Apartment"}
    bedrooms = _integer(metadata, "bedrooms", errors, required=residential)
    full_bathrooms = _integer(
        metadata, "full_bathrooms", errors, required=residential
    )
    if property_type == "Land":
        if "bedrooms" in metadata:
            errors.append("bedrooms: must be omitted for Land.")
        if "full_bathrooms" in metadata:
            errors.append("full_bathrooms: must be omitted for Land.")

    construction_m2 = _decimal(
        metadata, "construction_m2", errors, required=False, positive=True
    )
    land_m2 = _decimal(
        metadata,
        "land_m2",
        errors,
        required=property_type == "Land",
        positive=True,
    )
    floors = _integer(metadata, "floors", errors, required=False, positive=True)
    year_built = _integer(metadata, "year_built", errors, required=False, positive=True)
    if year_built is not None and not 1000 <= year_built <= 2100:
        errors.append("year_built: must be between 1000 and 2100.")

    maintenance_amount = _decimal(
        metadata,
        "maintenance_amount",
        errors,
        required=maintenance_status == "Fee",
        positive=True,
    )
    maintenance_currency = metadata.get("maintenance_currency")
    if maintenance_status == "Fee":
        if maintenance_currency not in CURRENCIES:
            errors.append(
                f"maintenance_currency: must be one of {', '.join(CURRENCIES)}."
            )
    elif "maintenance_amount" in metadata or "maintenance_currency" in metadata:
        errors.append(
            "maintenance_amount and maintenance_currency must be omitted unless "
            "maintenance_status is Fee."
        )

    in_development = metadata.get("in_development")
    if not isinstance(in_development, bool):
        errors.append("in_development: must be true or false.")

    private_characteristics = _string_list(
        metadata,
        "private_characteristics",
        PRIVATE_CHARACTERISTICS,
        errors,
    )
    community_amenities = _string_list(
        metadata, "community_amenities", COMMUNITY_AMENITIES, errors
    )
    if in_development is False and (community_amenities or other_community):
        errors.append(
            "community amenities must be omitted when in_development is false."
        )

    normalized: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "property_id": property_key,
        "name": name,
        "property_type": property_type,
        "operation": operation,
        "price_amount": _plain_number(price_amount),
        "price_currency": price_currency,
        "state": state,
        "city": city,
        "neighborhood": neighborhood,
        "half_bathrooms": half_bathrooms,
        "parking_spaces": parking_spaces,
        "maintenance_status": maintenance_status,
        "maintenance_description": maintenance_description,
        "in_development": in_development,
    }
    optional_values = {
        "public_location_notes": public_notes,
        "bedrooms": bedrooms,
        "full_bathrooms": full_bathrooms,
        "construction_m2": _plain_number(construction_m2),
        "land_m2": _plain_number(land_m2),
        "floors": floors,
        "year_built": year_built,
        "maintenance_amount": _plain_number(maintenance_amount),
        "maintenance_currency": maintenance_currency
        if maintenance_status == "Fee"
        else None,
        "private_characteristics": private_characteristics or None,
        "other_private_characteristic": other_private,
        "community_amenities": community_amenities or None,
        "other_community_amenity": other_community,
    }
    normalized.update(
        {key: value for key, value in optional_values.items() if value is not None}
    )
    return errors, normalized


def _plain_number(number: Decimal | None) -> int | float | None:
    if number is None:
        return None
    if number == number.to_integral_value():
        return int(number)
    return float(number)


def _validate_body(body: str, name: str) -> list[str]:
    errors: list[str] = []
    lines = body.splitlines()
    first = next((line for line in lines if line.strip()), "")
    if first != f"# {name}":
        errors.append(
            "The body must begin with a level-one heading exactly matching name."
        )
    if "![" in body or re.search(r"<\s*img\b", body, re.IGNORECASE):
        errors.append("Property Documents must not contain images.")
    if not body.strip():
        errors.append("The Markdown body must not be empty.")
    return errors


def validate_upload(filename: str, content: bytes) -> PropertyDocument:
    """Validate one complete Markdown Property Document."""
    errors: list[str] = []
    if not filename.lower().endswith(".md"):
        errors.append(f"{filename!r} is not a .md file.")
    if not content:
        errors.append("The file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        errors.append(
            f"The file is {len(content)} bytes; the maximum is {MAX_UPLOAD_BYTES}."
        )
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
        raise ValidationError(
            [f"The YAML front matter could not be parsed: {exc}."]
        ) from None
    if not isinstance(parsed, dict):
        raise ValidationError(["The YAML front matter must be key/value pairs."])

    metadata_errors, normalized = _validate_metadata(parsed)
    body_errors = _validate_body(body, str(parsed.get("name") or "").strip())
    if metadata_errors or body_errors:
        raise ValidationError(metadata_errors + body_errors)

    name = str(normalized["name"])
    return PropertyDocument(
        property_key=str(normalized["property_id"]),
        name=name,
        normalized_name=normalize_name(name),
        metadata=normalized,
        body=body,
        raw_bytes=content,
    )


def render_property_document(
    metadata: dict[str, Any], *, general_description: str, distribution: str
) -> bytes:
    """Generate and self-validate the canonical Markdown representation."""
    description = general_description.strip()
    layout = distribution.strip()
    errors = []
    if not description:
        errors.append("general_description: must not be empty.")
    if not layout:
        errors.append("distribution: must not be empty.")
    metadata_errors, normalized = _validate_metadata(dict(metadata))
    errors.extend(metadata_errors)
    if errors:
        raise ValidationError(errors)

    sections = [f"# {normalized['name']}", "", description]
    sections.extend(["", "## Distribución y espacios", "", layout])

    characteristics = list(normalized.get("private_characteristics", []))
    if other := normalized.get("other_private_characteristic"):
        characteristics.append(str(other))
    if characteristics:
        sections.extend(
            ["", "## Características de la propiedad", ""]
            + [f"- {value}" for value in characteristics]
        )

    amenities = list(normalized.get("community_amenities", []))
    if other := normalized.get("other_community_amenity"):
        amenities.append(str(other))
    if normalized["in_development"] and amenities:
        sections.extend(
            ["", "## Amenidades del coto", ""]
            + [f"- {value}" for value in amenities]
        )

    sections.extend(["", "## Mantenimiento", "", _maintenance_text(normalized)])
    location = ", ".join(
        [normalized["neighborhood"], normalized["city"], normalized["state"]]
    )
    if notes := normalized.get("public_location_notes"):
        location = f"{location}. {notes}"
    sections.extend(["", "## Ubicación", "", location])

    front = yaml.safe_dump(
        normalized,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).strip()
    content = f"---\n{front}\n---\n\n" + "\n".join(sections).strip() + "\n"
    encoded = content.encode("utf-8")
    validate_upload(f"{normalized['property_id']}.md", encoded)
    return encoded


def _maintenance_text(metadata: dict[str, Any]) -> str:
    status = metadata["maintenance_status"]
    description = metadata["maintenance_description"]
    if status == "Fee":
        amount = _format_amount(metadata["maintenance_amount"])
        currency = metadata["maintenance_currency"]
        return f"Cuota de mantenimiento: ${amount} {currency}. {description}"
    if status == "None":
        return f"No tiene cuota de mantenimiento. {description}"
    return f"La cuota de mantenimiento está pendiente de confirmación. {description}"


def _format_amount(value: int | float) -> str:
    number = Decimal(str(value))
    if number == number.to_integral_value():
        return f"{int(number):,}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")
