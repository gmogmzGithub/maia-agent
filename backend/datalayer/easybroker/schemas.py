"""Write-only credentials and typed, versioned CRM commands."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from datalayer.capture_catalog import STATES


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)
    request_id: UUID


class CreateConnection(Input):
    name: str = Field(min_length=1, max_length=100)
    environment: Literal["sandbox", "production"]
    advisor_id: int = Field(gt=0)
    key: str = Field(min_length=1, max_length=1024, repr=False)


class Versioned(Input):
    revision: int = Field(ge=0)


class Configure(Versioned):
    action: Literal["configure"]
    name: str = Field(min_length=1, max_length=100)
    advisor_id: int = Field(gt=0)


class Credential(Versioned):
    action: Literal["credential"]
    key: str = Field(min_length=1, max_length=1024, repr=False)


class Toggle(Versioned):
    action: Literal["disconnect", "reconnect"]


connection_action = TypeAdapter(
    Annotated[Configure | Credential | Toggle, Field(discriminator="action")]
)


class Review(Versioned):
    reason: str = Field(min_length=1, max_length=1000)


class Approve(Review):
    action: Literal["approve"]
    operation: Literal["sale", "rent"]
    title: str = Field(min_length=1, max_length=180)
    description: str = Field(max_length=5000)
    state: str = Field(min_length=1, max_length=80)
    municipality: str = Field(min_length=1, max_length=100)
    neighborhood: str = Field(min_length=1, max_length=100)
    advisor_id: int = Field(gt=0)
    publish: bool = False

    @field_validator("state")
    @classmethod
    def supported_state(cls, value):
        if value not in STATES:
            raise ValueError("Selecciona un estado del catálogo.")
        return value


class Link(Review):
    action: Literal["link"]
    operation: Literal["sale", "rent"]
    offer_id: int = Field(gt=0)


class Primary(Review):
    action: Literal["primary"]
    link_id: int = Field(gt=0)


class Unlink(Review):
    action: Literal["unlink"]
    link_id: int = Field(gt=0)


import_action = TypeAdapter(
    Annotated[Approve | Link | Primary | Unlink, Field(discriminator="action")]
)
