"""Validated historical facts. Provider results never belong to this contract."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from datalayer.capture_catalog import AMENITIES, CONDITIONS, KINDS, STATES


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Charge(Input):
    concept: str = Field(min_length=1, max_length=120)
    amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    currency: Literal["MXN", "USD"]


class Characteristics(Input):
    bedrooms: int | None = Field(default=None, ge=0, le=100)
    bathrooms: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=1)
    half_bathrooms: int | None = Field(default=None, ge=0, le=100)
    parking: int | None = Field(default=None, ge=0, le=100)
    age_type: Literal["", "new", "years", "construction"] = ""
    age_years: int | None = Field(default=None, ge=0, le=1000)
    condition: str = ""
    amenities: list[str] | None = Field(default=None, max_length=40)
    not_applicable: list[
        Literal["bedrooms", "bathrooms", "half_bathrooms", "parking", "age_years"]
    ] = Field(default_factory=list)

    @model_validator(mode="after")
    def known_values(self):
        if self.condition and self.condition not in CONDITIONS:
            raise ValueError("Conservación inválida.")
        if self.amenities is not None and set(self.amenities) - {
            v for group in AMENITIES.values() for v in group
        }:
            raise ValueError("Amenidad inválida.")
        if any(getattr(self, key) is not None for key in self.not_applicable):
            raise ValueError("Un dato no aplicable no puede tener un valor.")
        if self.age_type != "years" and self.age_years is not None:
            raise ValueError("Indica antigüedad en años para guardar su valor.")
        return self


class ClosingData(Input):
    operation: Literal["", "sale", "rent"] = ""
    price: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    currency: Literal["", "MXN", "USD"] = ""
    year: int | None = Field(default=None, ge=1, le=9999)
    month: int | None = Field(default=None, ge=1, le=12)
    day: int | None = Field(default=None, ge=1, le=31)
    kind: str = Field(default="", max_length=24)
    subtype: str = Field(default="", max_length=80)
    state: str = Field(default="", max_length=80)
    municipality: str = Field(default="", max_length=100)
    zone_type: Literal["", "colonia", "barrio", "localidad"] = ""
    zone: str = Field(default="", max_length=100)
    address_mode: Literal["urban", "rural"] = "urban"
    street: str = Field(default="", max_length=240)
    address_text: str = Field(default="", max_length=240)
    exterior_number: str = Field(default="", max_length=40)
    interior_number: str = Field(default="", max_length=40)
    interior_applicable: bool | None = None
    rural_identification: str = Field(default="", max_length=500)
    rural_reference: str = Field(default="", max_length=500)
    access_notes: str = Field(default="", max_length=500)
    land_m2: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    construction_m2: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    private_m2: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    characteristics: Characteristics = Field(default_factory=Characteristics)
    charges_status: Literal["unknown", "none", "itemized"] = "unknown"
    charges: list[Charge] = Field(default_factory=list, max_length=30)
    notes: str = Field(default="", max_length=2000)
    responsible_id: int | None = Field(default=None, gt=0)
    buyer_id: int | None = Field(default=None, gt=0)
    is_test: bool = False

    @model_validator(mode="after")
    def consistent(self):
        if self.kind and self.kind not in KINDS:
            raise ValueError("Tipo de inmueble inválido.")
        if self.subtype and (not self.kind or self.subtype not in KINDS[self.kind][1]):
            raise ValueError("Subtipo de inmueble inválido.")
        if self.state and self.state not in STATES:
            raise ValueError("Estado inválido.")
        if (
            self.month is not None
            and self.year is None
            or self.day is not None
            and self.month is None
        ):
            raise ValueError("Completa primero año y mes, sin inventar la fecha.")
        if self.day is not None:
            date(self.year, self.month, self.day)
        if (
            self.charges_status != "itemized"
            and self.charges
            or self.charges_status == "itemized"
            and not self.charges
        ):
            raise ValueError("Revisa el estado y el desglose de cargos.")
        if self.interior_applicable is False and self.interior_number:
            raise ValueError("El interior está marcado como no aplicable.")
        return self

    def missing_required(self):
        required = [
            "operation",
            "price",
            "currency",
            "year",
            "month",
            "day",
            "kind",
            "state",
            "municipality",
            "zone_type",
            "zone",
            "responsible_id",
        ]
        if self.address_mode == "urban":
            if not self.address_text:
                required += ["street", "exterior_number"]
                if self.interior_applicable is None:
                    required.append("interior_applicable")
                elif self.interior_applicable:
                    required.append("interior_number")
        else:
            required += ["rural_identification", "rural_reference"]
        return [key for key in required if getattr(self, key) is None or getattr(self, key) == ""]

    def missing_characteristics(self):
        missing = [key for key in ("land_m2", "construction_m2") if getattr(self, key) is None]
        if self.kind == "apartment" and self.private_m2 is None:
            missing.append("private_m2")
        traits = self.characteristics
        for key in ("bedrooms", "bathrooms", "half_bathrooms", "parking"):
            if getattr(traits, key) is None and key not in traits.not_applicable:
                missing.append(f"characteristics.{key}")
        if not traits.age_type or traits.age_type == "years" and traits.age_years is None:
            missing.append("characteristics.age_years")
        if not traits.condition:
            missing.append("characteristics.condition")
        if traits.amenities is None:
            missing.append("characteristics.amenities")
        return missing
