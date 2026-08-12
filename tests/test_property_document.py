"""Property Document validation (PROPERTY-DOCUMENT-TEMPLATE.md, P-047, P-048, P-052).

Pure validation: no database, no filesystem. The central property under test is
that the validator *rejects* ambiguity rather than repairing it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from realestate.domain.property_document import (
    MAX_UPLOAD_BYTES,
    REQUIRED_KEYS,
    ValidationError,
    normalize_name,
    validate_upload,
)

FIXTURES = Path(__file__).parent / "fixtures"
VALID = (FIXTURES / "casa-roble.md").read_bytes()


def with_field(field: str, value: str, source: bytes = VALID) -> bytes:
    """Return the fixture with one front-matter value replaced."""
    lines = source.decode("utf-8").split("\n")
    for index, line in enumerate(lines):
        if line.startswith(f"{field}:"):
            lines[index] = f"{field}: {value}"
            break
    else:  # pragma: no cover - a typo in a test would land here
        raise AssertionError(f"{field} not present in the fixture")
    return "\n".join(lines).encode("utf-8")


def errors_for(content: bytes, filename: str = "casa-roble.md") -> list[str]:
    with pytest.raises(ValidationError) as caught:
        validate_upload(filename, content)
    return caught.value.errors


# --- The canonical document -------------------------------------------------


def test_the_template_document_is_accepted() -> None:
    document = validate_upload("casa-roble.md", VALID)

    assert document.property_key == "casa-roble"
    assert document.name == "Casa Roble"
    assert document.metadata["Price"] == "$3,000,000 MXN"
    assert document.metadata["En Coto"] == "Sí"
    assert set(document.metadata) == set(REQUIRED_KEYS)
    # The accepted bytes are preserved exactly, so the checksum stays stable.
    assert document.raw_bytes == VALID


def test_en_coto_no_stays_the_string_no() -> None:
    # YAML 1.1 would resolve a bare `No` to boolean False. The two accepted
    # values must arrive as the same type or the contract is not enforceable.
    document = validate_upload("x.md", with_field("En Coto", "No"))

    assert document.metadata["En Coto"] == "No"


# --- File-level rules -------------------------------------------------------


def test_a_non_markdown_extension_is_rejected() -> None:
    assert "not a .md file" in errors_for(VALID, filename="casa-roble.txt")[0]


def test_an_oversized_file_is_rejected() -> None:
    padded = VALID + b"\n" + b"x" * MAX_UPLOAD_BYTES

    assert "maximum is" in errors_for(padded)[0]


def test_invalid_utf8_is_rejected() -> None:
    assert errors_for(b"---\n" + b"\xff\xfe" + b"\n---\n\n# x\n") == [
        "The file is not valid UTF-8."
    ]


def test_an_empty_file_is_rejected() -> None:
    assert errors_for(b"") == ["The file is empty."]


# --- Structure --------------------------------------------------------------


def test_a_document_without_front_matter_is_rejected() -> None:
    assert "must begin with a YAML front-matter block" in errors_for(
        b"# Casa Roble\n\nTexto.\n"
    )[0]


def test_an_unclosed_front_matter_block_is_rejected() -> None:
    assert "never closed" in errors_for(b"---\nproperty_id: casa-roble\n")[0]


def test_a_second_front_matter_block_is_rejected() -> None:
    doubled = VALID.replace(b"\n# Casa Roble", b"\n---\nextra: 1\n---\n\n# Casa Roble", 1)

    assert "more than one YAML front-matter block" in errors_for(doubled)[0]


def test_an_empty_body_is_rejected() -> None:
    header = VALID.decode("utf-8").split("---")[1]
    empty = f"---{header}---\n\n".encode()

    assert errors_for(empty) == ["The Markdown body must not be empty."]


def test_a_heading_that_does_not_match_the_name_is_rejected() -> None:
    mismatched = VALID.replace(b"# Casa Roble", b"# Casa Encino", 1)

    assert "does not match the front-matter name" in errors_for(mismatched)[0]


def test_a_body_that_does_not_start_with_a_level_one_heading_is_rejected() -> None:
    demoted = VALID.replace(b"# Casa Roble\n", b"## Casa Roble\n", 1)

    assert "level-one heading" in errors_for(demoted)[0]


# --- Metadata ---------------------------------------------------------------


@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_every_key_is_required(key: str) -> None:
    without = b"\n".join(
        line
        for line in VALID.split(b"\n")
        if not line.startswith(key.encode("utf-8") + b":")
    )

    assert f"Missing required front-matter key(s): {key}" in errors_for(without)[0]


def test_an_unexpected_key_is_rejected() -> None:
    extra = VALID.replace(b"location: Zapopan", b"location: Zapopan\nComision: 3%", 1)

    assert "Unexpected front-matter key(s): Comision" in errors_for(extra)[0]


def test_a_duplicate_key_is_rejected() -> None:
    duplicated = VALID.replace(
        b"location: Zapopan", b"location: Zapopan\nlocation: Tlaquepaque", 1
    )

    assert "duplicate front-matter key" in errors_for(duplicated)[0]


@pytest.mark.parametrize("value", ["Casa Roble", "CASA-ROBLE", "casa--roble", "casa_roble", "-casa"])
def test_a_malformed_property_key_is_rejected(value: str) -> None:
    assert "lowercase slug" in " ".join(errors_for(with_field("property_id", value)))


@pytest.mark.parametrize("value", ["Terreno", "casa", "Departamento pequeño"])
def test_an_unaccepted_property_type_is_rejected(value: str) -> None:
    assert "Tipo de inmueble" in " ".join(errors_for(with_field("Tipo de inmueble", value)))


def test_trailing_whitespace_around_a_value_is_not_significant() -> None:
    # YAML strips it from a plain scalar, so `Casa ` is the accepted `Casa`.
    document = validate_upload("x.md", with_field("Tipo de inmueble", "Casa   "))

    assert document.metadata["Tipo de inmueble"] == "Casa"


@pytest.mark.parametrize("value", ["Venta", "en venta", "En venta"])
def test_an_unaccepted_transaction_type_is_rejected(value: str) -> None:
    assert "Venta o Renta" in " ".join(errors_for(with_field("Venta o Renta", value)))


@pytest.mark.parametrize("value", ["Si", "SÍ", "true", "yes"])
def test_an_unaccepted_gated_value_is_rejected(value: str) -> None:
    assert "En Coto" in " ".join(errors_for(with_field("En Coto", value)))


@pytest.mark.parametrize("value", ["-1", "3.5", "cuatro"])
def test_a_non_integer_room_count_is_rejected(value: str) -> None:
    assert "Cuartos" in " ".join(errors_for(with_field("Cuartos", value)))


@pytest.mark.parametrize("value", ["1.25", "-0.5", "dos"])
def test_a_bathroom_count_off_the_half_step_is_rejected(value: str) -> None:
    assert "Baños" in " ".join(errors_for(with_field("Baños", value)))


@pytest.mark.parametrize("value", ["0", "1", "2.5", "3.0"])
def test_valid_bathroom_counts_are_accepted(value: str) -> None:
    assert validate_upload("x.md", with_field("Baños", value)).metadata["Baños"] == value


@pytest.mark.parametrize(
    "value",
    [
        "$1,5000 MXN",  # the exact ambiguity the decision names
        "$3,000,000",  # no currency
        "3000000 pesos",  # wrong currency
        "$3,00,000 MXN",  # malformed grouping
        "MXN",  # no amount
        "aproximadamente $3,000,000 MXN",
    ],
)
def test_an_ambiguous_price_is_rejected_not_guessed(value: str) -> None:
    message = " ".join(errors_for(with_field("Price", value)))

    assert "Price" in message
    assert "unambiguous" in message


@pytest.mark.parametrize("value", ["$3,000,000 MXN", "3000000 MXN", "$1,500.50 MXN"])
def test_unambiguous_prices_are_accepted(value: str) -> None:
    assert validate_upload("x.md", with_field("Price", value)).metadata["Price"] == value


def test_mantenimiento_accepts_the_not_applicable_form() -> None:
    document = validate_upload("x.md", with_field("Mantenimiento", "No aplica"))

    assert document.metadata["Mantenimiento"] == "No aplica"


def test_mantenimiento_rejects_an_ambiguous_amount() -> None:
    assert "Mantenimiento" in " ".join(
        errors_for(with_field("Mantenimiento", "$1,5000 MXN"))
    )


def test_amenidades_accepts_the_none_form() -> None:
    document = validate_upload("x.md", with_field("Amenidades", "Ninguna"))

    assert document.metadata["Amenidades"] == "Ninguna"


def test_amenidades_rejects_an_empty_entry() -> None:
    assert "Amenidades" in " ".join(errors_for(with_field("Amenidades", "Gym,,Alberca")))


def test_every_error_is_reported_together() -> None:
    broken = with_field("Cuartos", "cuatro")
    broken = with_field("En Coto", "Si", source=broken)
    broken = with_field("Price", "$1,5000 MXN", source=broken)

    errors = errors_for(broken)

    assert len(errors) == 3, errors


# --- Name normalisation (P-048) ---------------------------------------------


@pytest.mark.parametrize(
    "variant", ["Casa Roble", "casa roble", "cása  roble", "  CASA   ROBLE  "]
)
def test_name_variants_normalise_together(variant: str) -> None:
    assert normalize_name(variant) == normalize_name("Casa Roble")


def test_distinct_names_do_not_normalise_together() -> None:
    assert normalize_name("Casa Roble") != normalize_name("Casa Encino")


# --- Front matter that is not a set of text fields ---------------------------


def with_front_matter(front_matter: str) -> bytes:
    body = VALID.decode("utf-8").split("---\n", 2)[2]
    return f"---\n{front_matter}\n---\n{body}".encode("utf-8")


@pytest.mark.parametrize(
    "front_matter",
    ["- casa-roble\n- Casa Roble", "just a string", "42"],
)
def test_front_matter_that_is_not_key_value_pairs_is_rejected(
    front_matter: str,
) -> None:
    assert errors_for(with_front_matter(front_matter)) == [
        "The YAML front matter must be a set of key/value pairs."
    ]


def test_empty_front_matter_is_rejected_as_not_key_value_pairs() -> None:
    """``---\\n---`` parses to None, which is not a mapping."""
    assert errors_for(with_front_matter("")) == [
        "The YAML front matter must be a set of key/value pairs."
    ]


@pytest.mark.parametrize(
    "value", ["\n  - Casa Roble\n  - Casa Encino", "\n  es: Casa Roble"]
)
def test_a_structured_value_where_text_belongs_is_rejected(value: str) -> None:
    """Every scalar loads as a string, so only a nested list or mapping can
    arrive here — and neither is a name."""
    errors = errors_for(with_field("name", value))

    assert errors == ["name: expected a text value."]


def test_the_type_error_is_reported_before_anything_that_assumes_text() -> None:
    # Reported alone: the checks below it call .strip() and would raise.
    errors = errors_for(with_field("property_id", "\n  - casa-roble"))

    assert errors == ["property_id: expected a text value."]


@pytest.mark.parametrize("blank", ['""', "''", '"   "'])
def test_a_present_but_empty_required_value_is_rejected(blank: str) -> None:
    errors = errors_for(with_field("name", blank))

    assert errors == ["name: must not be empty."]


def test_every_empty_required_value_is_reported_at_once() -> None:
    """One upload, one complete list — not a field at a time."""
    content = with_field("name", '""')
    content = with_field("Colonia", '""', source=content)

    errors = errors_for(content)

    assert sorted(errors) == ["Colonia: must not be empty.", "name: must not be empty."]


def test_the_empty_check_short_circuits_the_value_checks_below_it() -> None:
    # An empty property_id must not also be reported as a malformed slug.
    errors = errors_for(with_field("property_id", '""'))

    assert errors == ["property_id: must not be empty."]
