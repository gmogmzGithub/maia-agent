import uuid
from decimal import Decimal
from typing import Annotated, Literal

from ninja import Schema
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from datalayer.capture_catalog import KINDS

Operation = Literal["rent", "sale"]
Kind = Literal[tuple(KINDS)]
Municipality = Annotated[str, Field(min_length=1, max_length=100)]


class SearchCriteria(Schema):
    model_config = ConfigDict(extra="forbid")
    operation: Operation | None = None
    kind: Kind | None = None
    municipality: Municipality | None = None
    state: str | None = Field(default=None, max_length=80)
    currency: Literal["MXN", "USD"] | None = None
    is_presale: bool | None = None
    neighborhood: str | None = Field(default=None, max_length=100)
    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)
    min_bedrooms: int | None = Field(default=None, ge=0, le=100)
    min_bathrooms: Decimal | None = Field(default=None, ge=0, le=100)
    min_parking: int | None = Field(default=None, ge=0, le=100)
    furnished: bool | None = None
    accepts_pets: bool | None = None
    near_schools: bool | None = None
    verified_only: bool = False

    @model_validator(mode="after")
    def valid_range(self):
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError("El presupuesto mínimo no puede superar el máximo")
        return self


class PropertyInput(Schema):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=3, max_length=180)
    operation: Operation
    kind: Kind
    subtype: str = Field(default="", max_length=80)
    state: str = Field(default="", max_length=80)
    currency: Literal["MXN", "USD"] = "MXN"
    is_presale: bool = False
    municipality: Municipality
    neighborhood: str = Field(min_length=1, max_length=100)
    price: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    public_address: str = Field(default="", max_length=240)
    bedrooms: int | None = Field(default=None, ge=0, le=100)
    bathrooms: Decimal | None = Field(default=None, ge=0, le=100)
    parking: int | None = Field(default=None, ge=0, le=100)
    area_m2: Decimal | None = Field(default=None, gt=0)
    furnished: bool | None = None
    accepts_pets: bool | None = None
    near_schools: bool | None = None
    description: str = Field(default="", max_length=5000)
    photos: list[HttpUrl] = Field(default_factory=list, max_length=30)
    internal_notes: str = Field(default="", max_length=5000)
    published: bool = False
    advisor_id: int | None = Field(default=None, gt=0)


class PublicationInput(Schema):
    model_config = ConfigDict(extra="forbid")
    published: bool


class PublicProperty(Schema):
    id: int
    reference: str
    title: str
    operation: Operation
    kind: Kind
    municipality: str
    neighborhood: str
    public_address: str
    price: str
    bedrooms: int | None
    bathrooms: str | None
    parking: int | None
    area_m2: str | None
    furnished: bool | None
    accepts_pets: bool | None
    near_schools: bool | None
    description: str
    photos: list[str]
    unconfirmed: list[str] = Field(default_factory=list)
    currency: Literal["MXN", "USD"] = "MXN"
    state: str = ""
    subtype: str = ""
    is_presale: bool = False
    public_location: dict = Field(default_factory=dict)
    details: dict = Field(default_factory=dict)


class ManagedProperty(PublicProperty):
    capture_id: str | None = None
    internal_notes: str
    published: bool
    advisor_id: int | None


class SearchResult(Schema):
    results: list[PublicProperty]
    total: int
    next_offset: int | None
    criteria: SearchCriteria


class MessageInput(Schema):
    text: str = Field(min_length=1, max_length=10000)
    client_message_id: uuid.UUID
    property_id: int | None = Field(default=None, gt=0, strict=True)


class ReplyPart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["text", "properties", "contact", "visit"]
    text: str = Field(default="", max_length=3000)
    property_ids: list[Annotated[int, Field(strict=True, gt=0)]] = Field(
        default_factory=list, max_length=3
    )
    proposal_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def matches_kind(self):
        if self.kind == "text":
            if not self.text.strip() or self.property_ids or self.proposal_id:
                raise ValueError("text requires only nonempty text")
        elif self.kind == "properties":
            if (
                not self.property_ids
                or self.text
                or self.proposal_id
                or any(type(i) is not int or i <= 0 for i in self.property_ids)
            ):
                raise ValueError("properties requires positive property_ids only")
        elif self.kind == "visit":
            if not self.proposal_id or self.text or self.property_ids:
                raise ValueError("visit requires proposal_id only")
        elif self.text or self.property_ids or self.proposal_id:
            raise ValueError("contact accepts no extra data")
        return self


class DialoguePending(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal[
        "name", "slot", "contact", "contact_confirmation", "visit_confirmation", "clarification"
    ]
    subject: str = Field(min_length=1, max_length=180)


class DialogueContinuity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: str = Field(min_length=1, max_length=180)
    pending: DialoguePending | None = None


class ReplyProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    blocks: list[ReplyPart] = Field(min_length=1, max_length=8)
    continuity: DialogueContinuity

    @model_validator(mode="after")
    def coherent_blocks(self):
        ids = [i for b in self.blocks for i in b.property_ids]
        controls = [b for b in self.blocks if b.kind in {"contact", "visit"}]
        if len(ids) > 3 or len(set(ids)) != len(ids) or len(controls) > 1:
            raise ValueError("at most three distinct properties and one active control")
        if not any(b.kind == "text" for b in self.blocks):
            raise ValueError("include a brief customer-facing text")
        return self


class MessageOutput(Schema):
    id: int
    role: str
    text: str
    properties: list[PublicProperty]
    is_error: bool
    delivery_status: str | None = None
    presentation: list[ReplyPart] | None = None


class ContactCandidate(Schema):
    phone: str
    name: str


class ConversationOutput(Schema):
    id: uuid.UUID
    criteria: SearchCriteria
    processing: bool
    messages: list[MessageOutput]
    pending_contact: ContactCandidate | None = None
    contact_registered: bool = False
    automation_paused: bool = False
    human_requested: bool = False
    has_interest: bool = False
    visit_proposal: dict | None = None
    appointments: list[dict] = Field(default_factory=list)
    visits_processing: bool = False
    followup_permission: bool | None = None
    structured_reply: bool = False
    active_control: Literal["contact", "visit"] | None = None
    active_proposal_id: uuid.UUID | None = None
    active_message_id: int | None = None


class Error(Schema):
    detail: str


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criteria_patch: SearchCriteria = Field(default_factory=SearchCriteria)
    offset: int = Field(default=0, ge=0, le=10000)


class InterestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    property_ids: list[int] = Field(default_factory=list, max_length=20)
    human_requested: bool = False
    summary: str = Field(default="", max_length=1000)
    name: str = Field(default="", max_length=120)


class ContactNameInput(Schema):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)


class ContactInput(Schema):
    model_config = ConfigDict(extra="forbid")
    phone: str = Field(min_length=7, max_length=40)
    name: str = Field(default="", max_length=120)


class ConfirmContactInput(Schema):
    phone: str = Field(min_length=7, max_length=40)
    name: str = Field(default="", max_length=120)
    confirmed: Literal[True]
    whatsapp_followup: bool = False


class AdvisorInput(Schema):
    name: str = Field(min_length=1, max_length=120)
    whatsapp: str = Field(default="", pattern=r"^(\+[1-9][0-9]{7,14})?$", max_length=16)
    telegram_chat_id: str = Field(default="", pattern=r"^([1-9][0-9]{0,19})?$", max_length=32)
    is_default: bool = False


class AdvisorOutput(AdvisorInput):
    id: int


class ProspectUpdate(Schema):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="", max_length=120)
    advisor_id: int | None = Field(default=None, gt=0)
    status: Literal["new", "attending", "not_interested", "scheduled"]
    criteria: SearchCriteria
    next_step: str = Field(default="", max_length=500)
    automation_paused: bool


class NotificationOutput(Schema):
    id: int
    reason: str
    summary: str
    status: str
    error_code: str
    attempts: int
    created_at: str


class CRMConversation(Schema):
    id: uuid.UUID
    prospect_id: int | None
    phone: str
    name: str
    human_requested: bool
    automation_paused: bool
    conversation_paused: bool
    advisor_id: int | None
    criteria: SearchCriteria
    property_ids: list[int]
    messages: list[MessageOutput]
    notifications: list[NotificationOutput]
    created_at: str
    channel: str = "website"
    deliveries: list[dict] = Field(default_factory=list)


class ProspectOutput(Schema):
    id: int
    phone: str
    name: str
    advisor_id: int | None
    status: Literal["new", "attending", "not_interested", "scheduled"]
    criteria: SearchCriteria
    next_step: str
    automation_paused: bool
    property_ids: list[int]
    created_at: str
    updated_at: str


class ProspectDetail(ProspectOutput):
    conversations: list[CRMConversation]
    events: list[dict]
    followup: dict = Field(default_factory=dict)


class PauseInput(Schema):
    automation_paused: bool
