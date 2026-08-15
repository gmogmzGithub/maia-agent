# Maia Real Estate Operations

Maia coordinates customer-facing property conversations with broker-controlled
inventory and availability. This glossary defines the language used across that
workflow.

## Language

**Administrator**:
An authorized internal human who submits Property facts and controls operational
availability.
_Avoid_: Lead, customer, model

**Administrative Instruction**:
An explicit natural-language request from an authenticated Administrator that Maia
may translate into one bounded, validated administrative operation.
_Avoid_: Model authority, arbitrary command, ambiguous request

**Property**:
A real-estate offering with a stable identity, approved facts, and an availability
state.
_Avoid_: Listing, house, unit

**Property Key**:
The immutable, human-readable identity assigned to one Property and shared by every
revision of its facts.
_Avoid_: Document version, filename, database UUID

**Property Document**:
The approved customer-safe facts about one Property from which Maia may answer
questions.
_Avoid_: Prompt, knowledge file, listing page

**Property Document Version**:
One immutable accepted revision of a Property Document; later corrections create a
new version without changing the Property Key.
_Avoid_: Property, duplicate Property, mutable file

**Property Catalog**:
The curated, public-safe collection of Property Documents eligible to be introduced
into Maia; it is not evidence of current availability.
_Avoid_: Fixtures, runtime folder, database

**Property Submission**:
Candidate customer-safe facts entered by an Administrator for validation before they
can become an accepted Property Document.
_Avoid_: EasyBroker sync, crawler result, direct database edit

**Accepted Property Submission**:
A validated submission explicitly finalized by an Administrator; a first acceptance
creates an Active Property, while a later acceptance adds a Property Document Version
without changing availability.
_Avoid_: Draft, automatic activation, in-place document edit

**Inventory**:
The Properties Maia currently knows about together with their operational
availability, regardless of whether each one can presently be offered.
_Avoid_: Property Catalog, listings folder

**Active Property**:
A Property currently permitted to be disclosed to customers and considered for new
visit bookings.
_Avoid_: Published Property, available document

**Inactive Property**:
A Property blocked from customer disclosure and new visit bookings, with a separate
Inactive Reason explaining why.
_Avoid_: Deleted Property, Sold Property

**Inactive Reason**:
The Administrator-confirmed explanation for an Inactive Property: Sold, Rented,
Reserved, Temporarily Unavailable, Withdrawn, or Unspecified.
_Avoid_: Availability state, customer-visible message

**Customer Availability Message**:
The approved wording derived from a Property's availability and Inactive Reason;
it never includes raw administrative notes.
_Avoid_: Inactive Reason, internal explanation, admin note

**Public Location**:
The customer-safe area used to describe where a Property is located, such as its
city, neighborhood, development, and approved nearby landmarks.
_Avoid_: Visit Address, exact coordinates

**Visit Address**:
The private exact destination for a confirmed property visit, disclosed only after
booking confirmation.
_Avoid_: Public Location, listing description

**Maintenance Terms**:
The Administrator-confirmed statement of whether maintenance charges exist, their
amount and currency when they do, and what the charges cover or why they are unknown.
_Avoid_: Blank maintenance field, assumed zero fee

**Property Characteristic**:
A fact intrinsic to the Property itself, such as whether a house has a private
garden.
_Avoid_: Community Amenity, free-form feature taxonomy

**Community Amenity**:
A shared service or facility belonging to the Property's gated community or
development and described under “Amenidades del coto.”
_Avoid_: Private garden, Property Characteristic

**Inactive Appointment Review**:
The manual follow-up required when an Inactive Property still has a future confirmed
visit; it is not an automatic cancellation.
_Avoid_: Cancelled appointment, status-change side effect
