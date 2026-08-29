"""What an analytics event is allowed to be.

The taxonomy is a closed list with a declared schema per name. That is the whole
protection against a measurement surface growing free-text attributes: an event
whose name is unknown, whose schema version is not the one Product supports, or
which carries an attribute nobody declared, is refused rather than stored and
sorted out later.

Attribute values are restricted to numbers and booleans plus a very small set of
enumerated strings. There is no attribute anywhere in this module that can hold a
phone number, a message, a search phrase or a user agent, because the cheapest
way to keep personal data out of the analytics schema is to have no column it
would fit in.
"""

from __future__ import annotations

from dataclasses import dataclass

from realestate.db.models import AnalyticsEventName, HarmSignalKind, SponsoredSurface

#: Every declared schema is version 1 today. The field exists so a later change
#: to one event's attributes is a version bump on that event, not a silent
#: reinterpretation of rows already stored.
SCHEMA_VERSION = 1

#: Enumerated attribute values, spelled once. A value outside its set is
#: refused; that is what keeps ``surface`` from becoming free text.
ALLOWED_VALUES: dict[str, frozenset[str]] = {
    "surface": frozenset(item.value for item in SponsoredSurface)
    | frozenset({"TechnicalSheet", "Gallery", "Saved", "Maia", "WhatsApp"}),
    "outcome": frozenset({"Won", "Lost", "Dormant"}),
    "attendance": frozenset({"Attended", "Missed"}),
    "harm_kind": frozenset(item.value for item in HarmSignalKind),
    "origin": frozenset({"Sponsored", "Organic"}),
}


@dataclass(frozen=True)
class EventSchema:
    """One event name's declared shape."""

    name: AnalyticsEventName
    schema_version: int
    #: Attributes the event must carry.
    required: frozenset[str]
    #: Attributes the event may carry.
    optional: frozenset[str] = frozenset()
    #: Whether the event describes a paid exposure and therefore needs a
    #: campaign. A funnel step reached after a Sponsored Placement carries the
    #: campaign too, which is how attribution stays campaign-scoped without
    #: anybody re-deriving it from timing.
    requires_campaign: bool = False
    #: Whether the event needs a Listing to mean anything.
    requires_listing: bool = False

    @property
    def allowed(self) -> frozenset[str]:
        return self.required | self.optional


def _schema(
    name: AnalyticsEventName,
    *,
    required: tuple[str, ...] = (),
    optional: tuple[str, ...] = (),
    requires_campaign: bool = False,
    requires_listing: bool = False,
) -> EventSchema:
    return EventSchema(
        name=name,
        schema_version=SCHEMA_VERSION,
        required=frozenset(required),
        optional=frozenset(optional),
        requires_campaign=requires_campaign,
        requires_listing=requires_listing,
    )


SCHEMAS: dict[AnalyticsEventName, EventSchema] = {
    schema.name: schema
    for schema in (
        _schema(
            AnalyticsEventName.SPONSORED_SERVED_IMPRESSION,
            required=("surface",),
            optional=("position",),
            requires_campaign=True,
            requires_listing=True,
        ),
        _schema(
            AnalyticsEventName.SPONSORED_VISIBLE_IMPRESSION,
            required=("surface", "visible_fraction", "continuous_milliseconds"),
            optional=("position",),
            requires_campaign=True,
            requires_listing=True,
        ),
        _schema(
            AnalyticsEventName.LISTING_OPENED,
            required=("surface",),
            optional=("origin",),
            requires_listing=True,
        ),
        _schema(
            AnalyticsEventName.GALLERY_OPENED,
            required=(),
            optional=("origin",),
            requires_listing=True,
        ),
        _schema(
            AnalyticsEventName.GALLERY_DEPTH_REACHED,
            required=("photographs", "gallery_fraction"),
            optional=("origin",),
            requires_listing=True,
        ),
        _schema(
            AnalyticsEventName.SIGNIFICANT_GALLERY_EXPLORATION,
            required=("photographs", "gallery_fraction"),
            optional=("origin",),
            requires_listing=True,
        ),
        _schema(AnalyticsEventName.LISTING_SAVED, optional=("origin",), requires_listing=True),
        _schema(AnalyticsEventName.SELECTION_SHARED, optional=("count",)),
        _schema(AnalyticsEventName.MAIA_STARTED, optional=("surface",)),
        _schema(AnalyticsEventName.WHATSAPP_HANDOFF, optional=("surface",)),
        _schema(AnalyticsEventName.APPOINTMENT_REQUESTED, optional=("origin",)),
        _schema(AnalyticsEventName.APPOINTMENT_VERIFIED, optional=("origin",)),
        _schema(
            AnalyticsEventName.APPOINTMENT_ATTENDED,
            required=("attendance",),
            optional=("origin",),
        ),
        _schema(AnalyticsEventName.OPPORTUNITY_OUTCOME_KNOWN, required=("outcome",)),
        _schema(
            AnalyticsEventName.FIRST_RESPONSE_RECORDED,
            required=("response_minutes",),
        ),
        _schema(AnalyticsEventName.OPPORTUNITY_QUALIFIED),
        _schema(AnalyticsEventName.HARM_SIGNAL_RECORDED, required=("harm_kind",)),
    )
}

#: Which funnel step each event name satisfies. ``SavedOrShared`` is one step
#: reached by either of two events, which is why the mapping is not the identity.
FUNNEL_STEP_FOR_EVENT: dict[AnalyticsEventName, str] = {
    AnalyticsEventName.SPONSORED_VISIBLE_IMPRESSION: "SponsoredVisibleImpression",
    AnalyticsEventName.LISTING_OPENED: "ListingOpened",
    AnalyticsEventName.GALLERY_OPENED: "GalleryOpened",
    AnalyticsEventName.SIGNIFICANT_GALLERY_EXPLORATION: (
        "SignificantGalleryExploration"
    ),
    AnalyticsEventName.LISTING_SAVED: "SavedOrShared",
    AnalyticsEventName.SELECTION_SHARED: "SavedOrShared",
    AnalyticsEventName.MAIA_STARTED: "MaiaStarted",
    AnalyticsEventName.WHATSAPP_HANDOFF: "WhatsAppHandoff",
    AnalyticsEventName.APPOINTMENT_REQUESTED: "AppointmentRequested",
    AnalyticsEventName.APPOINTMENT_VERIFIED: "AppointmentVerified",
    AnalyticsEventName.APPOINTMENT_ATTENDED: "AppointmentAttended",
    AnalyticsEventName.OPPORTUNITY_OUTCOME_KNOWN: "OpportunityOutcomeKnown",
}
