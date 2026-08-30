"""The versioned Property Document contract used by manual administration."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from realestate.domain.property_document import (
    MAX_UPLOAD_BYTES,
    ValidationError,
    normalize_name,
    render_property_document,
    slugify_property_name,
    validate_upload,
)

VALID = (Path(__file__).parents[1] / "fixtures" / "casa-roble.md").read_bytes()


def errors_for(content: bytes, filename: str = "casa-roble.md") -> list[str]:
    with pytest.raises(ValidationError) as caught:
        validate_upload(filename, content)
    return caught.value.errors


def replace(value: bytes, replacement: bytes, source: bytes = VALID) -> bytes:
    assert value in source
    return source.replace(value, replacement, 1)


def without_line(prefix: str, source: bytes = VALID) -> bytes:
    lines = source.decode().splitlines()
    return ("\n".join(line for line in lines if not line.startswith(prefix)) + "\n").encode()


def test_the_template_document_is_accepted() -> None:
    document = validate_upload("casa-roble.md", VALID)

    assert document.property_key == "casa-roble"
    assert document.name == "Casa Roble"
    assert document.metadata["price_amount"] == 3_000_000
    assert document.metadata["half_bathrooms"] == 1
    assert document.metadata["parking_spaces"] == 2
    assert "Dirección" not in document.metadata


def test_normalized_names_ignore_accents_case_and_whitespace() -> None:
    assert normalize_name("  CÁSA   Roble ") == "casa roble"


@pytest.mark.parametrize(
    ("name", "slug"),
    [("Casa Reserva Real", "casa-reserva-real"), ("  Ático #2 ", "atico-2"), ("***", "")],
)
def test_property_key_generation(name: str, slug: str) -> None:
    assert slugify_property_name(name) == slug


@pytest.mark.parametrize("filename", ["property.txt", "property", "property.MD.txt"])
def test_only_markdown_filenames_are_accepted(filename: str) -> None:
    assert "not a .md" in errors_for(VALID, filename)[0]


def test_empty_oversized_and_non_utf8_files_are_rejected() -> None:
    assert errors_for(b"") == ["The file is empty."]
    assert "maximum" in errors_for(b"x" * (MAX_UPLOAD_BYTES + 1))[0]
    assert errors_for(b"\xff") == ["The file is not valid UTF-8."]


def test_front_matter_must_open_close_and_be_a_mapping() -> None:
    assert "must begin" in errors_for(b"# Casa\n")[0]
    assert "never closed" in errors_for(b"---\nname: Casa\n")[0]
    assert "key/value pairs" in errors_for(b"---\n- one\n- two\n---\n# Casa\n")[0]


def test_malformed_yaml_and_duplicate_keys_are_rejected() -> None:
    malformed = replace(b"name: Casa Roble", b"name: [Casa")
    assert "could not be parsed" in errors_for(malformed)[0]
    duplicate = replace(b"name: Casa Roble", b"name: Casa Roble\nname: Otra")
    assert "duplicate front-matter key" in errors_for(duplicate)[0]


def test_required_and_unexpected_keys_are_reported() -> None:
    missing = without_line("price_amount:")
    assert "price_amount" in " ".join(errors_for(missing))
    extra = replace(b"name: Casa Roble", b"name: Casa Roble\nsource_url: https://example.com")
    assert "source_url" in errors_for(extra)[0]


@pytest.mark.parametrize("key", ["source_url", "image_url", "images", "visit_address"])
def test_external_sources_images_and_private_addresses_are_not_document_fields(key: str) -> None:
    changed = replace(b"name: Casa Roble", f"name: Casa Roble\n{key}: forbidden".encode())
    assert key in " ".join(errors_for(changed))


@pytest.mark.parametrize("value", ["Casa Roble", "CASA-ROBLE", "casa--roble", "casa_roble", "-casa"])
def test_property_keys_are_lowercase_hyphenated_slugs(value: str) -> None:
    changed = replace(b"property_id: casa-roble", f"property_id: {value}".encode())
    assert "single hyphens" in " ".join(errors_for(changed))


@pytest.mark.parametrize(
    ("field", "bad"),
    [("property_type", "Villa"), ("operation", "Lease"), ("price_currency", "EUR"), ("maintenance_status", "Maybe")],
)
def test_enumerated_fields_are_closed(field: str, bad: str) -> None:
    changed = replace(f"{field}: ".encode(), f"{field}: {bad} # ".encode())
    assert field in " ".join(errors_for(changed))


@pytest.mark.parametrize("field", ["half_bathrooms", "parking_spaces"])
@pytest.mark.parametrize("value", ["-1", "1.5", "many"])
def test_required_counts_are_nonnegative_whole_numbers(field: str, value: str) -> None:
    current = b"1" if field == "half_bathrooms" else b"2"
    changed = replace(f"{field}: ".encode() + current, f"{field}: {value}".encode())
    assert field in " ".join(errors_for(changed))


def test_zero_half_bathrooms_and_parking_are_valid() -> None:
    changed = replace(b"half_bathrooms: 1", b"half_bathrooms: 0")
    changed = replace(b"parking_spaces: 2", b"parking_spaces: 0", changed)
    document = validate_upload("zero.md", changed)
    assert document.metadata["half_bathrooms"] == 0
    assert document.metadata["parking_spaces"] == 0


def test_house_requires_bedrooms_and_full_bathrooms() -> None:
    changed = without_line("bedrooms:")
    changed = without_line("full_bathrooms:", changed)
    errors = " ".join(errors_for(changed))
    assert "bedrooms" in errors and "full_bathrooms" in errors


def test_land_requires_land_measurements_and_omits_residential_counts() -> None:
    changed = replace(b"property_type: House", b"property_type: Land")
    errors = " ".join(errors_for(changed))
    assert "land_m2" in errors
    assert "land_front_m" in errors
    assert "land_depth_m" in errors
    assert "bedrooms, full_bathrooms, half_bathrooms, parking_spaces" in errors


def test_a_valid_land_document_is_accepted() -> None:
    changed = replace(b"property_type: House", b"property_type: Land")
    changed = without_line("bedrooms:", changed)
    changed = without_line("full_bathrooms:", changed)
    changed = without_line("half_bathrooms:", changed)
    changed = without_line("parking_spaces:", changed)
    changed = without_line("construction_m2:", changed)
    changed = without_line("private_characteristics:", changed)
    changed = without_line("- Estacionamiento techado", changed)
    changed = replace(b"maintenance_status: Fee", b"maintenance_status: Unknown", changed)
    changed = without_line("maintenance_amount:", changed)
    changed = without_line("maintenance_currency:", changed)
    changed = without_line("maintenance_description:", changed)
    changed = replace(
        b"in_development: true",
        b"land_m2: 160.1\nland_front_m: 8.01\nland_depth_m: 20.01\nin_development: true",
        changed,
    )
    document = validate_upload("land.md", changed)
    assert document.metadata["land_m2"] == 160.1
    assert document.metadata["land_front_m"] == 8.01
    assert document.metadata["land_depth_m"] == 20.01
    assert "half_bathrooms" not in document.metadata
    assert "parking_spaces" not in document.metadata


def test_fee_requires_amount_and_currency() -> None:
    changed = without_line("maintenance_amount:")
    changed = without_line("maintenance_currency:", changed)
    errors = " ".join(errors_for(changed))
    assert "maintenance_amount" in errors and "maintenance_currency" in errors


@pytest.mark.parametrize("status", ["None", "Unknown"])
def test_non_fee_maintenance_omits_fee_only_fields(status: str) -> None:
    changed = replace(b"maintenance_status: Fee", f"maintenance_status: {status}".encode())
    changed = without_line("maintenance_amount:", changed)
    changed = without_line("maintenance_currency:", changed)
    changed = without_line("maintenance_description:", changed)
    assert validate_upload("maintenance.md", changed).metadata["maintenance_status"] == status


def test_non_fee_rejects_stale_maintenance_fields() -> None:
    changed = replace(b"maintenance_status: Fee", b"maintenance_status: None")
    errors = " ".join(errors_for(changed))
    assert "maintenance_amount and maintenance_currency must be omitted" in errors
    assert "maintenance_description must be omitted" in errors


def test_community_amenities_require_a_development() -> None:
    changed = replace(b"in_development: true", b"in_development: false")
    assert "community amenities" in " ".join(errors_for(changed))


def test_unsupported_and_duplicate_checkbox_values_are_rejected() -> None:
    unsupported = replace(b"- Alberca\n", b"- Campo de golf\n")
    assert "unsupported" in " ".join(errors_for(unsupported))
    duplicated = replace(b"- Alberca\n", b"- Alberca\n- Alberca\n")
    assert "duplicate" in " ".join(errors_for(duplicated))


def test_in_development_must_be_boolean() -> None:
    changed = replace(b"in_development: true", b"in_development: yes-please")
    assert "true or false" in " ".join(errors_for(changed))


@pytest.mark.parametrize("image", [b"![Casa](casa.jpg)", b"<img src='casa.jpg'>"])
def test_markdown_body_images_are_rejected(image: bytes) -> None:
    assert "must not contain images" in " ".join(errors_for(VALID + image))


def test_body_requires_matching_heading_and_content() -> None:
    mismatch = replace(b"# Casa Roble", b"# Otra Casa")
    assert "heading" in " ".join(errors_for(mismatch))
    front = VALID.decode().split("---", 2)[1]
    assert "not be empty" in " ".join(errors_for(f"---{front}---\n".encode()))


def test_render_generates_canonical_sections_and_validates_itself() -> None:
    document = validate_upload("casa-roble.md", VALID)
    rendered = render_property_document(
        document.metadata,
        general_description="Descripción aprobada.",
        distribution="Distribución aprobada.",
    ).decode()
    assert "## Distribución y espacios" in rendered
    assert "## Características de la propiedad" in rendered
    assert "## Amenidades del coto" in rendered
    assert "## Mantenimiento" in rendered
    assert "## Ubicación" in rendered
    assert "source_url" not in rendered and "image" not in rendered.casefold()


def test_rendered_land_includes_land_measurements() -> None:
    changed = replace(b"property_type: House", b"property_type: Land")
    for prefix in (
        "bedrooms:",
        "full_bathrooms:",
        "half_bathrooms:",
        "parking_spaces:",
        "construction_m2:",
        "maintenance_amount:",
        "maintenance_currency:",
        "maintenance_description:",
        "private_characteristics:",
        "- Estacionamiento techado",
    ):
        changed = without_line(prefix, changed)
    changed = replace(b"maintenance_status: Fee", b"maintenance_status: Unknown", changed)
    changed = replace(
        b"in_development: true",
        b"land_m2: 160.1\nland_front_m: 8.01\nland_depth_m: 20.01\nin_development: true",
        changed,
    )
    metadata = validate_upload("land.md", changed).metadata

    rendered = render_property_document(
        metadata,
        general_description="Terreno en venta en coto.",
        distribution="Frente y fondo regulares.",
    ).decode()

    assert "## Medidas del terreno" in rendered
    assert "- Superficie: 160.1 m²" in rendered
    assert "- Frente: 8.01 m" in rendered
    assert "- Fondo: 20.01 m" in rendered


def test_render_requires_both_narratives() -> None:
    metadata = validate_upload("casa-roble.md", VALID).metadata
    with pytest.raises(ValidationError) as caught:
        render_property_document(metadata, general_description="", distribution="")
    assert len(caught.value.errors) == 2


def test_optional_private_and_community_sections_are_omitted_when_empty() -> None:
    metadata = validate_upload("casa-roble.md", VALID).metadata
    metadata.pop("private_characteristics")
    metadata.pop("community_amenities")
    metadata["in_development"] = False
    rendered = render_property_document(
        metadata, general_description="General.", distribution="Espacios."
    ).decode()
    assert "## Características de la propiedad" not in rendered
    assert "## Amenidades del coto" not in rendered


def test_yaml_render_preserves_spanish_text_and_is_parseable() -> None:
    document = validate_upload("casa-roble.md", VALID)
    rendered = render_property_document(
        document.metadata, general_description="Jardín privado.", distribution="Sala."
    )
    front = rendered.decode().split("---", 2)[1]
    parsed = yaml.safe_load(front)
    assert parsed["private_characteristics"] == ["Estacionamiento techado"]


def test_optional_text_must_be_nonempty_text_when_present() -> None:
    changed = replace(
        b"name: Casa Roble", b"name: Casa Roble\npublic_location_notes: []"
    )
    assert "public_location_notes" in " ".join(errors_for(changed))


def test_boolean_is_not_accepted_as_a_number() -> None:
    changed = replace(b"price_amount: 3000000", b"price_amount: true")
    assert "must be a number" in " ".join(errors_for(changed))


def test_checkbox_collections_must_be_lists_of_text() -> None:
    changed = replace(
        b"private_characteristics:\n- Estacionamiento techado",
        b"private_characteristics: null",
    )
    assert "private_characteristics" not in validate_upload(
        "none.md", changed
    ).metadata

    changed = replace(
        b"private_characteristics:\n- Estacionamiento techado",
        "private_characteristics: Jardín privado".encode(),
    )
    assert "must be a list" in " ".join(errors_for(changed))


def test_schema_version_and_year_bounds_are_enforced() -> None:
    changed = replace(b"schema_version: 1", b"schema_version: 2")
    changed = replace(
        b"name: Casa Roble", b"name: Casa Roble\nyear_built: 999", changed
    )
    errors = " ".join(errors_for(changed))
    assert "schema_version" in errors and "year_built" in errors


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("None", "No tiene cuota de mantenimiento."),
        ("Unknown", "pendiente de confirmación"),
    ],
)
def test_rendered_non_fee_maintenance_copy(status: str, expected: str) -> None:
    metadata = validate_upload("casa-roble.md", VALID).metadata
    metadata["maintenance_status"] = status
    metadata.pop("maintenance_amount")
    metadata.pop("maintenance_currency")
    metadata.pop("maintenance_description")
    rendered = render_property_document(
        metadata, general_description="General.", distribution="Espacios."
    ).decode()
    assert expected in rendered


def test_render_includes_optional_public_notes_other_amenity_and_decimal_amount() -> None:
    metadata = validate_upload("casa-roble.md", VALID).metadata
    metadata["public_location_notes"] = "A dos cuadras del parque"
    metadata["other_community_amenity"] = "Cancha de pádel"
    metadata["construction_m2"] = 123.45
    metadata["maintenance_amount"] = 1500.5
    rendered = render_property_document(
        metadata, general_description="General.", distribution="Espacios."
    ).decode()
    assert "Cancha de pádel" in rendered
    assert "A dos cuadras del parque" in rendered
    assert "$1,500.5 MXN" in rendered
    assert "construction_m2: 123.45" in rendered
