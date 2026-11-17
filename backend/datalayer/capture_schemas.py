from decimal import Decimal
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from datalayer.capture_catalog import AMENITIES, CONDITIONS, KINDS, STATES


class CaptureData(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    name: str = Field(default="", max_length=120)
    relationship: Literal["owner", "representative"] = "owner"
    operation: Literal["sale", "rent"] = "sale"
    is_presale: bool = False
    kind: str = "house"
    subtype: str = Field(default="", max_length=80)
    state: str = "Jalisco"
    municipality: str = Field(default="", max_length=100)
    neighborhood: str = Field(default="", max_length=100)
    subdivision: str = Field(default="", max_length=100)
    private_address: str = Field(default="", max_length=240)
    location_ref: UUID | None = None
    location_mode: Literal["address", "reference"] = "address"
    location_reference: str = Field(default="", max_length=500)
    location_confirmed: bool = False
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    title: str = Field(default="", max_length=180)
    price: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    currency: Literal["MXN", "USD"] = "MXN"
    maintenance: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    no_maintenance: bool = False
    bedrooms: int | None = Field(default=None, ge=0, le=100)
    bathrooms: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=1)
    half_bathrooms: int | None = Field(default=None, ge=0, le=100)
    parking: int | None = Field(default=None, ge=0, le=100)
    area_m2: Decimal | None = Field(default=None, gt=0, le=100000000)
    land_m2: Decimal | None = Field(default=None, gt=0, le=100000000)
    age_type: Literal["", "new", "years", "construction"] = ""
    age_years: int | None = Field(default=None, ge=0, le=1000)
    condition: str = ""
    storage_rooms: int | None = Field(default=None, ge=0, le=100)
    elevators: int | None = Field(default=None, ge=0, le=100)
    floors: int | None = Field(default=None, ge=0, le=200)
    description: str = Field(default="", max_length=5000)
    amenities: list[str] = Field(default_factory=list, max_length=40)
    videos: list[str] = Field(default_factory=list, max_length=10)
    tours: list[str] = Field(default_factory=list, max_length=5)
    valuation_requested: bool = False
    phone_confirmed: bool = False

    @field_validator("videos", "tours")
    @classmethod
    def valid_links(cls, values):
        for value in values:
            url = urlparse(value)
            if (
                len(value) > 2000
                or url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
            ):
                raise ValueError("Usa enlaces HTTPS completos, sin credenciales.")
        return values

    @model_validator(mode="after")
    def valid_catalog(self):
        if self.kind not in KINDS or (self.subtype and self.subtype not in KINDS[self.kind][1]):
            raise ValueError("Tipo o subtipo inválido")
        if self.state not in STATES or self.condition not in ["", *CONDITIONS]:
            raise ValueError("Estado o conservación inválidos")
        if set(self.amenities) - {x for group in AMENITIES.values() for x in group}:
            raise ValueError("Característica inválida")
        if self.is_presale and self.operation != "sale":
            raise ValueError("Preventa corresponde a una operación de venta")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Indica ambas coordenadas")
        if self.location_ref and self.latitude is not None:
            raise ValueError("No copies coordenadas temporales a los datos de la captación.")
        return self

    def check_complete(self):
        if not all([self.name, self.municipality, self.price]):
            raise ValueError("Completa nombre, ubicación, dirección y precio solicitado.")
        if self.location_mode == "reference":
            if self.kind not in {"land", "commercial_land", "industrial_land", "ranch", "orchard"}:
                raise ValueError(
                    "La ubicación por referencia corresponde a terrenos, ranchos o huertas."
                )
            if not self.location_reference or (not self.location_ref and self.latitude is None):
                raise ValueError("Indica una referencia escrita y el punto del inmueble.")
        elif not self.neighborhood or not self.private_address:
            raise ValueError(
                "Completa colonia y dirección, o usa ubicación por referencia si corresponde."
            )
        if not self.phone_confirmed:
            raise ValueError("Confirma que tu teléfono está bien escrito.")
        if self.location_ref and not self.location_confirmed:
            raise ValueError("Revisa y confirma los datos de ubicación para continuar.")
        if self.age_type == "years" and self.age_years is None:
            raise ValueError("Indica los años de antigüedad.")
