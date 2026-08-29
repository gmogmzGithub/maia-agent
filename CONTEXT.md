# Maia Real Estate Operations

Maia coordinates customer-facing property conversations with broker-controlled
inventory and availability. This glossary defines the language used across that
workflow.

## Language

### People and commercial work

**Brokerage Organization**:
The real-estate business that owns its operating relationships, team membership,
customer records, Opportunities, consent records, and configurations.
_Avoid_: Tenant, account, Santiago, deployment

**Brokerage Brand**:
The public customer-facing identity of the Brokerage Organization. Its working
name is **Larevia**, pending formal trademark clearance.
_Avoid_: Maia Agent, platform brand, legal entity by assumption

**Maia Agent**:
The named conversational operator that serves Contacts across authorized customer
channels while the Platform's deterministic authority controls business truth.
_Avoid_: Brokerage Brand, Hermes, complete platform

**Product Interface Language**:
Mexican Spanish used for every human-visible product and operational surface,
including the public site, CRM, notifications, forms, statuses, validation and
error messages, and reports.
_Avoid_: Conversation Language, English UI, untranslated internal labels

**Conversation Language**:
The language a Contact uses or explicitly requests for a conversation with Maia;
it may be any language Maia can support faithfully and is independent of the
Product Interface Language.
_Avoid_: Product Interface Language, customer nationality, permanent preference
by inference

**Website Conversation**:
An anonymous-by-default customer conversation with Maia on the public site that
may qualify a need, answer from authorized Listing facts, recommend Listings, and
lead toward a verified WhatsApp handoff or Property Visit Appointment.
_Avoid_: Customer account, website support chat, unrestricted Maia role

**Verified WhatsApp Handoff**:
The explicit transition from the public site to the Brokerage Organization's
official WhatsApp channel using a short-lived opaque reference and confirmed
channel identity; it is required before confirming a Property Visit Appointment.
_Avoid_: Password account, phone number in URL, automatic identity linkage

**Appointment Handoff**:
The boundary created when Maia confirms an appointment and the Real Estate
Advisor becomes responsible for subsequent customer service and commercial work;
Maia may continue only with Appointment Logistics.
_Avoid_: Translation relay, negotiation by Maia, completed transaction

**Appointment Logistics**:
The bounded work of confirming, reminding, rescheduling, or cancelling an
appointment against authoritative Advisor availability without conducting the
visit or advancing the commercial negotiation.
_Avoid_: Post-visit follow-up, offer negotiation, closing work

**Property Visit Appointment**:
A confirmed 90-minute meeting connecting one Contact, one Real Estate Advisor,
and one Property at an authoritative available time.
_Avoid_: Soft appointment, multi-property tour, phone call, calendar suggestion

**Cancelled Appointment**:
An appointment ended before it occurred at the Contact's or operation's request;
it does not determine the Opportunity's stage or outcome.
_Avoid_: Lost Opportunity, Dormant Opportunity, deleted appointment

**Missed Appointment**:
An appointment that the Advisor confirms did not occur without a prior
cancellation; it may justify one authorized rescheduling invitation but does not
itself determine the Opportunity's outcome.
_Avoid_: Cancelled Appointment, Lost Opportunity, automatic reactivation

**Platform Brand**:
The future B2B commercial identity for the complete CRM, agent, workflow,
catalog, scheduling, integration, and analytics platform. It is deliberately
unnamed and invisible to consumers during the brokerage MVP.
_Avoid_: Maia Agent, Brokerage Brand, internal Product label as customer-facing copy

**Service Area**:
The geographic market in which the Brokerage Organization can responsibly assign
an Advisor, conduct visits, and operate transactions. The initial Service Area is
the Guadalajara Metropolitan Area limited to Guadalajara, Zapopan, and
Tlaquepaque.
_Avoid_: Every location returned by EasyBroker, all of Mexico, marketing reach

**Organization Administrator**:
An authorized member with organization-wide operational visibility and authority
to manage Properties, Advisor access, assignments, and Advisor Absences.
_Avoid_: Property Expert, unrestricted database user, Maia

**Organization Member**:
One authorized human inside a Brokerage Organization, holding exactly one role
and, separately, whether they may own Opportunities. It is the record
authorization resolves an authenticated credential to; a credential with no
active member is refused.
_Avoid_: Basic-auth account, environment variable, implicit administrator

**Contact**:
A person known to the real-estate operation across time, independently of how
many searches, conversations, or transactions they pursue.
_Avoid_: Lead, customer record, phone number

**Customer Experience**:
The quality of service a Contact receives from the Brokerage Organization across
the real-estate journey, regardless of whether that Contact is buying, renting,
selling, or offering a Property for rent.
_Avoid_: Buyer experience, lead conversion, Maia conversation quality

**Transaction Participant Role**:
The capacity in which a Contact participates in one real-estate transaction,
such as buyer, renter, seller, or landlord; it does not redefine the person.
_Avoid_: Contact type, permanent customer segment, separate Customer record

**Channel Identity**:
One addressable identifier through which a Contact reaches the operation, with
how well Product knows it is theirs. The same trusted identifier presented again
resolves to the same Contact; identifiers that merely look alike never do.
_Avoid_: Contact, phone number as identity, normalized number

**Opportunity Exception**:
The recorded, attributed reason an active Opportunity legitimately has no Next
Action right now. It is the alternative the follow-up promise allows, and it
clears when the reason stops applying.
_Avoid_: Missing Next Action, Dormant Opportunity, silent gap

**Follow-up Coverage**:
The share of active Opportunities that have a Responsible Advisor, an explicit
commercial stage, and either a Next Action that is not overdue or an
Opportunity Exception. The target is 100 percent; conversion and harm are
measured separately.
_Avoid_: Advisor performance score, conversion rate, win rate

**Property Need**:
One Contact's coherent real-estate intent and constraints, such as buying a home
within a budget and area with required characteristics.
_Avoid_: Prompt, chat memory, search string

**Stale Property Need**:
A Property Need that has not been confirmed for 90 days and may be used only to
identify a possible reactivation, never as current customer truth.
_Avoid_: Active search, deleted history, confirmed preference

**Opportunity**:
One bounded commercial pursuit connecting a Contact to a Property Need, with an
owner, next action, status, and eventual outcome.
_Avoid_: Contact, conversation, generic lead

**Qualified Opportunity**:
An Opportunity whose transaction intent, acceptable area, economic range,
approximate horizon, essential requirements, and legitimate contact path are
known well enough for an Advisor to advance it.
_Avoid_: Completed questionnaire, guaranteed buyer, message received

**Demand Opportunity**:
An Opportunity in which a Contact seeks to buy or rent real estate.
_Avoid_: Listing Acquisition Opportunity, Property Need alone, conversation

**Listing Acquisition Opportunity**:
An Opportunity in which a property owner seeks the Brokerage Organization's help
to sell or rent real estate; in the MVP it is qualified and handed to the Admin
for human continuation.
_Avoid_: Demand Opportunity, accepted Listing, automatic valuation

**Next Action**:
The specific future action owed for an active Opportunity, with a responsible
party and due time.
_Avoid_: Follow up eventually, model memory, generic reminder

**Assignment Queue**:
The Admin-visible set of Opportunities that lack an eligible Responsible Advisor
and therefore require manual assignment.
_Avoid_: Assigned Opportunity, forgotten lead, round-robin backlog

**Dormant Opportunity**:
An Opportunity that cannot advance now but has a recorded condition under which
it may legitimately be reconsidered.
_Avoid_: Lost Opportunity, Do Not Contact, forgotten lead

**Lost Opportunity**:
An Opportunity known to have ended without a completed transaction, with a
recorded reason or an explicit Unknown reason.
_Avoid_: Dormant Opportunity, silence, expired conversation

**Do Not Contact**:
A communication restriction that suppresses outreach to a Contact; it is not an
Opportunity stage or a reason to erase commercial history.
_Avoid_: Lost Opportunity, Dormant Opportunity, no recent reply

**Suppression Record**:
The durable evidence that a Contact or channel must not receive outreach, retained
as needed to enforce the restriction even after conversation content expires.
_Avoid_: Lost Opportunity, deleted Contact, temporary delivery failure

**Outbound Eligibility Decision**:
The recorded answer to whether Product may send one specific message to one
Contact at one moment, including the reason when it may not. Every outbound
message has exactly one, and a refusal is kept as durable evidence rather than
discarded.
_Avoid_: Outbox row, delivery failure, model judgement, log line

**Message Initiation**:
Whether an outbound message answers concrete messages the Contact just sent
(Reactive) or the operation reaching out on its own (Business-Initiated). It is
a property of why the message exists, not of what it says.
_Avoid_: Outbox kind, message category, appointment state

**Customer Service Window**:
The 24 hours after a Contact's last message, during which Product may send
free-form text on WhatsApp. Outside it, only an approved template may be sent.
_Avoid_: Conversational Session, engagement cycle, business hours

**Consent Record**:
One dated statement that a Contact granted or revoked permission to be
contacted on one channel for one message category. A later record supersedes an
earlier one rather than replacing it.
_Avoid_: Suppression Record, privacy notice acceptance, inferred permission

**Approved Template**:
A WhatsApp message template Meta has approved for a named Business Account and
category. Product may only send one it has been told about; it never invents a
template or assumes approval.
_Avoid_: Approved copy, message body, draft, product wording

**Template Observation**:
The dated provider evidence for one exact WhatsApp template name, language,
category, component checksum, lifecycle state, and quality signal. It expires as
operational authority and can be replaced or retired only by newer provider
truth, never by an Administrator's local approval.
_Avoid_: Approved Template by name alone, permanent registry entry, editable copy

**Inventory Match**:
A versioned comparison between one current, confirmed Property Need and one
authorized Listing, with an exact or approximate result and criterion-by-criterion
explanation. A known contradiction excludes the Listing; there is no hidden
predictive score.
_Avoid_: Recommendation score, similarity guess, automatic outreach

**Reactivation Candidate**:
An Inventory Match attached to a workable or Dormant Opportunity for an
Organization Administrator to review. It cannot request outbound contact until
the Administrator authorizes the exact Listing, template, language, content and
reason, and every live eligibility gate still passes.
_Avoid_: Reactivated Opportunity, queued message, automatic follow-up

**Development Campaign**:
A versioned, pausable plan for announcing one reviewed Development to an explicit
set of Property Needs, with exact content and language, audience criteria,
exclusions, quiet hours, frequency budget and result states.
_Avoid_: Send to all, contact list, automated broadcast, Development Listing

**Audience Snapshot**:
The explainable Included or Excluded decision for one explicit Property Need at
one moment under one Campaign rule version. Human surfaces use an opaque Product
reference and reasons, not names, phone numbers or message content.
_Avoid_: Contact export, permanent eligibility, inferred demographic segment

**Marketing Touch**:
One marketing Outbox request that the Outbound Eligibility Gate queued for a
Contact, retained to enforce deduplication and frequency limits. A denied or
excluded audience member is not a Marketing Touch.
_Avoid_: Delivered message, campaign member, provider impression

**Follow-up Policy Version**:
The named, versioned cadence hypothesis a follow-up attempt was produced under,
retained so a later report can explain why a given day was chosen after the
hypothesis changes.
_Avoid_: Next Action, product truth, validated cadence

**Conversational Session**:
The bounded message context Hermes may use to continue one interaction; it expires
after 90 consecutive days without interaction and is not the commercial record.
_Avoid_: Contact, Opportunity history, permanent memory

**Conversation Handling Mode**:
The explicit authority state that determines whether Maia may converse, a human
is handling the Contact, the operation is awaiting the Contact, or Admin review is
required. Exactly one authority holds a Conversation at a time, and a human mode
always names the person holding it.
_Avoid_: Advisor assignment, Opportunity stage, model guess

**Human Handling Request**:
One unmet request for a person on one Conversation, with who was alerted and when
the Organization Administrator must be told if nobody has taken it. It is
resolved by a human taking or releasing the Conversation, never by time passing.
_Avoid_: Conversation Handling Mode, Opportunity reassignment, service-level
promise

**Internal Operational Alert**:
One durable notice to a member of the Brokerage Organization on its own private
channel, with its delivery state retained. It is not outreach to a Contact and
does not pass the outbound eligibility gate; a recipient with no configured
channel produces a notice that is visible but undelivered rather than one that is
lost.
_Avoid_: Outbox row, customer message, log line

**Visit Reminder**:
One deterministic Contact-facing notice a confirmed Property Visit Appointment
owes before it happens, scheduled when the visit is confirmed and settled exactly
once. The cadence is an unvalidated hypothesis, so a reminder may be withheld
with a recorded reason rather than sent.
_Avoid_: Follow-up, sales message, model-composed text

**Real Estate Advisor**:
A human member of a Brokerage Organization who can own Opportunities, work with
Contacts, and conduct Property visits. Advisors initially provide human service
in Spanish even when Maia conversed with the Contact in another language.
_Avoid_: Organization Administrator, Maia, sales session

**Responsible Advisor**:
The Real Estate Advisor accountable for advancing one Opportunity and ensuring
its next action and outcome are recorded.
_Avoid_: Property Expert, Maia, unassigned queue

**Property Expert**:
A Real Estate Advisor explicitly designated as the Brokerage Organization's
primary specialist for a Property and eligible to receive Property-specific
consultations or visits; other Advisors may be designated as backups. The public
site labels the team `Especialistas inmobiliarios` and presents this role as `Tu
especialista en esta propiedad` rather than exposing the internal term.
_Avoid_: Responsible Advisor, property owner, listing source

**Advisor Absence**:
A declared period during which a Real Estate Advisor is ineligible for new
Opportunity assignments and new visit bookings. Only an Organization
Administrator may record, change, or end it. It never reassigns an existing
Opportunity or cancels an existing appointment; those are surfaced for review.
_Avoid_: Deactivated Advisor, automatic reassignment, deleted calendar event

**Authoritative Advisor Calendar**:
The external calendar that decides one Real Estate Advisor's real availability. An
Advisor without one has no availability the Platform may quote and cannot receive
a visit; a calendar that cannot be read is likewise not an empty one.
_Avoid_: Weekly Bookable Schedule, empty calendar, shared brokerage calendar

**External Collaborator**:
An agent or agency outside the Brokerage Organization that participates in a
Property or transaction without becoming a member of its internal team.
_Avoid_: Real Estate Advisor, platform user, employee

**Commercial Attribution**:
The record of which internal and external participants sourced, advised on, or
closed an Opportunity and under which known commission conditions.
_Avoid_: Commission payment, payroll, automatic settlement

**Commercial Outcome**:
The recorded conclusion of an Opportunity, including a completed transaction or
a specific reason it did not proceed.
_Avoid_: Conversation closed, cycle expired, no reply

**Won Opportunity**:
An Opportunity that an Organization Administrator has explicitly concluded in a
legally completed sale, a signed rental agreement, or an accepted binding presale
contract; intermediate interest, visits, offers, and reservations are not wins.
_Avoid_: Offer accepted, visit completed, model inference

**Transaction**:
The completed or completing commercial deal produced by an Opportunity, linking
the Contact, Listing or Property, participants, dates, known price, attribution,
and known commission facts.
_Avoid_: Opportunity, appointment, conversation, commission payment

**Transaction Journey**:
The Product-authoritative course of a real-estate deal after an authorized member
explicitly starts its formal processing, tracking the confirmed work owed through
completion, cancellation, and aftercare.
_Avoid_: Won Opportunity, chat workflow, inferred sale, legal advice

**Transaction Journey Template Version**:
One frozen, approved arrangement of milestones, dependencies, responsibilities,
and customer communications from which a Transaction Journey is created.
_Avoid_: Mutable checklist, universal legal process, Hermes prompt

**Transaction Milestone**:
One evidence-bearing step in a Transaction Journey, with an explicit responsible
party, state, due time when applicable, and human-confirmed outcome.
_Avoid_: Opportunity stage, message, model inference, generic task

**Purchase Profile**:
One purpose-bound, dated set of buyer facts recorded for a Demand Opportunity,
separate from the Contact's durable identity and from profiles for other roles.
_Avoid_: Contact type, permanent demographic truth, behavioural profile

### Market intelligence

**Market Intelligence**:
The Product context that accumulates manually recorded facts from completed and
in-progress real-estate deals so the business can compare Properties, prices,
buyers, and areas across time.
_Avoid_: Product analytics, external-data warehouse, advertising profile

**Market Sale Record**:
The dated analytical record of one sale pursued through the Platform, preserving
the Property facts relevant to comparison and the known Paid Price, Published
Price, and Appraisal Value without requiring all three.
_Avoid_: Commercial Transaction, Listing, automated valuation, imported comparable

**Market Sale Record in Preparation**:
A Market Sale Record opened with a Transaction Journey and completed manually as
the Brokerage Organization learns the appraisal, agreement, and closing facts.
_Avoid_: Completed Sale, comparable sale, published Listing

**Completed Market Sale Record**:
A Market Sale Record an Organization Administrator has confirmed with a Paid
Price, currency, completion date, and the minimum Property facts required for
comparison.
_Avoid_: Won Opportunity alone, sale in progress, asking-price observation

**Paid Price**:
The final amount the parties paid for a completed sale, recorded from the
Brokerage Organization's own transaction evidence.
_Avoid_: Published Price, Appraisal Value, estimated market price

**Published Price**:
The asking price at which the Property was publicly offered for the sale whose
Market Sale Record is being described.
_Avoid_: Paid Price, Appraisal Value, current Listing price after the sale

**Appraisal Value**:
The value stated by the appraisal used for the sale when the Brokerage
Organization knows it.
_Avoid_: Paid Price, Published Price, automated valuation

**Shared Market Dataset**:
The Platform-wide analytical collection produced from Market Sale Records and
Purchase Profiles contributed by Brokerage Organizations, separate from their
operational records and customer conversations.
_Avoid_: Cross-Organization CRM access, shared Contact directory, external feed

**Market Contribution**:
The durable, replayable transfer of analytical fields from one Organization's
Market Sale Record and Purchase Profile into the Shared Market Dataset, carrying
no Contact identity, documents, or conversation content.
_Avoid_: Cross-Organization query, customer export, external data import

**Resolved Market Sale**:
The single shared sale represented by one or more Market Contributions that a
Market Intelligence Analyst has confirmed describe the same completed deal.
_Avoid_: Deleted duplicate, automatic address match, individual contribution

**Market Record Correction**:
A database-attributed replacement of an incorrect current Market Sale Record or
Purchase Profile value that preserves the prior value and republishes the fact.
_Avoid_: Silent overwrite, correction UI, editing the shared copy directly

**Market Intelligence Analyst**:
An internal Platform role allowed to analyze the Shared Market Dataset but
refused access to each Brokerage Organization's operational CRM records.
_Avoid_: Organization Administrator, superadmin, support grant

**Comparable Sale**:
A Completed Market Sale Record selected by explicit report criteria as relevant
to a subject Property; an unfinished deal is never a Comparable Sale.
_Avoid_: Property for sale, appraisal, automatic valuation, sale in preparation

**Commission Record**:
The manually recorded expected, earned, and collected gross commission facts for
a Transaction, without calculating participant payouts, taxes, or invoices.
_Avoid_: Payroll, automated split, revenue assumption

### Property operations

**Administrative Instruction**:
An explicit natural-language request from an authenticated Organization
Administrator that Maia may translate into one bounded, validated administrative
operation.
_Avoid_: Model authority, arbitrary command, ambiguous request

**Property**:
The physical real-estate asset or unit that may be represented by one or more
commercial Listings.
_Avoid_: Listing, advertisement, source record

**Property Submission**:
A property owner's private request for the Brokerage Organization to evaluate a
Property for sale or rent; it is not a Listing and grants no publication authority.
_Avoid_: Published Listing, automatic valuation, public property upload

**Listing**:
One source-specific commercial offering of a Property, with its own authority,
attribution, media, publication state, and one or more sale or rental Offers.
_Avoid_: Property, physical unit, duplicated truth

**Listing Offer**:
The sale or rental terms within one Listing, including operation, manually entered
price, currency, Public Price Visibility, and offer-specific availability. One
Listing may contain both a sale Offer and a rental Offer.
_Avoid_: Listing, Property, duplicated advertisement

**Public Price Visibility**:
The Administrator-controlled choice to show a Listing Offer's exact price or
replace it publicly with an approved consultation message while retaining the
authoritative price internally.
_Avoid_: Missing price, automatic concealment, unknown price

**Listing Media**:
Administrator-approved static photographs associated with one Listing, with
known provenance and publication authority; they are managed by the Platform and
presented by the public site, never selected or interpreted by Maia Agent.
_Avoid_: Property Document, chat attachment, unverified external image

**Listing Gallery**:
The public, mobile-first visual experience for one Listing's approved Listing
Media, reachable through its own shareable URL.
_Avoid_: Listing Technical Sheet, WhatsApp media dump, administrative gallery

**Listing Technical Sheet**:
The public structured presentation of one Listing's authorized facts, price,
availability, characteristics, and next-step actions, reachable through its own
URL.
_Avoid_: Listing Gallery, Property Document source, contract

**Saved Collection**:
A customer-controlled set of saved Listings held authoritatively by Product,
usable anonymously and optionally linked to a verified Contact for recovery and
cross-device continuity.
_Avoid_: Browser-only favorites, inferred Property Need, automatic lead capture

**Anonymous Collection Session**:
An opaque first-party identifier that lets one browser access a Saved Collection
without an account or personal identity.
_Avoid_: Contact identity, advertising tracker, public sharing token

**Protected Saved Collection**:
A Saved Collection explicitly linked through the Contact's verified WhatsApp
channel for recovery and cross-device continuity without a password-based account.
_Avoid_: Anonymous Collection Session, automatic Contact linkage, public profile

**Shared Selection**:
A revocable, opaque, read-only snapshot of chosen saved Listings that contains no
Contact identity, conversation, or editing authority.
_Avoid_: Protected Saved Collection, public customer profile, collaborative editing

**Sponsored Placement**:
A paid, visibly labeled position for an otherwise authorized and available Listing
on a defined public discovery surface; it is distinct from organic relevance,
Presentation Tier, Maia recommendation, and publication authority.
_Avoid_: Hidden promotion, guaranteed sale, Premium appearance, organic ranking

**Sponsorship Campaign**:
The bounded commercial agreement that connects one paying party, one eligible
source Listing, defined sponsored surfaces, price and currency, paid active days,
status, and measured delivery.
_Avoid_: Sponsored Placement, Listing Offer, guaranteed lead package

**Sponsored Exposure**:
A measured instance in which an eligible Sponsored Placement was actually visible
on a defined surface, with campaign, Listing, position, time, and non-sensitive
context retained for deduplication and reporting.
_Avoid_: Page request, guaranteed attention, Contact identity

**Sponsored Engagement**:
A measured customer action following a Sponsored Exposure, such as opening the
Listing, exploring its Gallery, saving it, starting with Maia, continuing through
WhatsApp, or reaching an appointment milestone.
_Avoid_: Causal proof, conversation content, invisible behavioral profile

**Visible Impression**:
A Sponsored Exposure for which at least 50 percent of the placement is visible for
one continuous second under the current versioned measurement rule.
_Avoid_: Served impression, unique person, guaranteed attention

**Significant Gallery Exploration**:
A versioned analytics milestone reached initially after at least five photographs
or 30 percent of one Listing Gallery is viewed; it is stronger than a Gallery open
but does not itself prove purchase intent.
_Avoid_: Gallery open, qualified Opportunity, appointment request

**Follow-up Data Completeness**:
The share of appointments and Opportunities whose required human-owned outcome
fields have been recorded, shown independently from commercial conversion.
_Avoid_: Advisor performance score, win rate, assumed negative outcome

**Sponsorship Comparable Cohort**:
An aggregate group of campaigns aligned by operation, municipality, property type,
Commercial Price Band, Presentation Tier, and sponsored surface, with period and
sample size disclosed.
_Avoid_: Guaranteed forecast, individual competitor report, causal control group

**Commercial Price Band**:
An analytics grouping based on a Listing's manually entered asking price or
monthly rent; it describes the Listing, never the Contact.
_Avoid_: Presentation Tier, inferred customer wealth, automatic valuation

**Presentation Tier**:
The Platform-assigned fixed visual template for a house or apartment Listing:
Larevia, Premium, or Super Premium. Product derives it automatically from
configured price and currency rules and permits an Administrator override.
_Avoid_: Commercial Price Band, customer segment, service-quality level

**Presentation Readiness**:
A deterministic check that a Listing has the required cover, approved media, and
authorized facts for its Presentation Tier; an Administrator may override the
result explicitly.
_Avoid_: AI aesthetic judgment, Listing Authority, customer qualification

**Unit Model**:
A repeatable configuration offered within a Development before or independently
of identifying every physical Property that may satisfy it.
_Avoid_: Property, Development, fictitious unit

**Organization Listing**:
A Listing controlled directly by the Brokerage Organization.
_Avoid_: Collaborator Listing, every Listing in the organization account

**Collaborator Listing**:
A Listing sourced from an External Collaborator that the Brokerage Organization
may use only within the collaboration's current authority, attribution, and
commercial conditions.
_Avoid_: Organization Listing, unrestricted MLS listing

**External Listing Candidate**:
A source-specific record that may become a Collaborator Listing only after its
identity, service area, availability, authority, attribution and commercial
conditions are confirmed. Its presence in an external platform is not Product
authority.
_Avoid_: Listing, imported inventory, MLS property, duplicate Property

**Listing Revalidation**:
The recorded use-time decision that an External Listing Candidate is Eligible,
Pending or Denied for one specific recommendation, share or appointment based on
fresh source and authority evidence.
_Avoid_: sync timestamp, permanent approval, model confidence

**Inventory Source Health**:
The operational state of one external inventory source, including its last
complete or partial synchronization and sanitized failure state; it does not say
that any individual candidate is authorized.
_Avoid_: Listing Freshness, API key, provider uptime claim

**Listing Freshness**:
The recency and success of source verification for a Listing's availability,
price, authority, attribution, and commercial terms.
_Avoid_: Local cache timestamp, permanent validity, model confidence

**Listing Availability**:
The market state of a Listing: Available, Reserved, Sold, Rented, Temporarily
Unavailable, or Unknown.
_Avoid_: Publication State, Listing Authority, Property existence

**Listing Publication State**:
Whether a Listing is Draft, Published, or Unpublished on a particular surface.
_Avoid_: Listing Availability, Listing Authority, source freshness

**Listing Authority**:
Whether the Brokerage Organization's permission to use a Listing is Authorized,
Pending, Expired, or Revoked.
_Avoid_: Listing Availability, publication visibility, EasyBroker presence

**Development**:
A commercially related collection of multiple houses, apartments, or lots that
may be offered in volume and may have different characteristics.
_Avoid_: Property, Listing, identical unit type

**Opportunity Origin**:
The preserved commercial provenance of an Opportunity, including its first known
source, channel, campaign, advertisement, Listing, referral, and participant when
available.
_Avoid_: Latest channel only, overwritten attribution, model guess

**Pending Criterion**:
A possible Property Need constraint inferred or normalized by Maia that must be
confirmed before it becomes current commercial truth.
_Avoid_: Required criterion, explicit customer statement, hidden assumption

**Property Key**:
The immutable, human-readable identity assigned to one Property and shared by every
revision of its facts.
_Avoid_: Document version, filename, database UUID

**Property Document**:
An immutable legacy source artifact retained as provenance and narrative for one
Property. Product projects customer answers from the authorized Listing and its
Offers; the document's operation and price are not editable commercial truth.
_Avoid_: Catalog authority, current Offer, Listing publication state

**Property Document Version**:
One immutable accepted revision of a Property Document; later corrections create a
new version without changing the Property Key.
_Avoid_: Property, duplicate Property, mutable file

**Property Catalog**:
The legacy source-controlled collection of current Property Document copies used
only by the compatibility ingestion path. The authoritative catalog is PostgreSQL
Property, Listing, Offer and Listing Media state.
_Avoid_: Authorized Inventory, editable commercial truth, public site

**Authorized Inventory**:
The Listings a Brokerage Organization is currently permitted to present or
recommend, including Organization Listings and eligible Collaborator Listings
with preserved provenance, current authority, availability, reviewed terms and
purpose-specific eligibility.
_Avoid_: All properties in Mexico, scraped catalog, permanent data lake

**Property Submission**:
Candidate customer-safe facts entered by an Organization Administrator for
validation before they can become an accepted Property Document.
_Avoid_: EasyBroker sync, crawler result, direct database edit

**Accepted Property Submission**:
A validated submission explicitly finalized by an Organization Administrator; a
first acceptance creates an Active Property, while a later acceptance adds a
Property Document Version without changing availability.
_Avoid_: Draft, automatic activation, in-place document edit

**Inventory**:
The Properties Maia currently knows about together with their operational
availability, regardless of whether each one can presently be offered.
_Avoid_: Property Catalog, listings folder

**Active Property**:
The legacy compatibility status projected into Listing and Offer availability by
the remaining Stage 0 administration path. It cannot authorize disclosure or a
new visit by itself; Listing Eligibility still decides.
_Avoid_: Listing Availability, Listing Authority, publication permission

**Inactive Property**:
A fail-closed legacy compatibility status that blocks customer disclosure and new
visit bookings while preserving existing appointments and records. Its reason is
written through to authoritative Listing and Offer state.
_Avoid_: Deleted Property, automatic appointment cancellation

**Inactive Reason**:
The Organization Administrator-confirmed explanation for an Inactive Property:
Sold, Rented, Reserved, Temporarily Unavailable, Withdrawn, or Unspecified.
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
The Organization Administrator-confirmed statement of whether maintenance charges
exist, their amount and currency when they do, and what the charges cover or why
they are unknown.
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

### Measurement and paid visibility

**Analytics Event**:
One immutable, idempotent, pseudonymous record of something that happened, named
by the versioned domain-event taxonomy and carrying only numeric, boolean or
enumerated attributes.
_Avoid_: Log line, free-text payload, behavioural profile, Contact record

**Analytics Outbox**:
The durable queue Product writes an emitted Analytics Event to, separate from the
customer-facing Outbox and from every operational side effect.
_Avoid_: Outbox Message, conversation delivery queue, in-memory buffer

**Analytics Projection**:
The re-runnable pass that drains the Analytics Outbox into the event store,
classifies traffic, and recomputes the versioned aggregates and materialized
views for every period it touched.
_Avoid_: Incrementing counter, one-way ETL, live query over raw events

**Measurement Definition Version**:
One stored, frozen set of counting rules — visibility thresholds, exploration
thresholds, funnel order, attribution windows, delivery ratios and caps — that a
historic report resolves so it stays reproducible.
_Avoid_: Constant in code, current threshold, undated rule change

**Served Impression**:
A Sponsored Placement that Product actually delivered in a surface's response;
it is Product's own fact and says nothing about what anybody saw.
_Avoid_: Visible Impression, page request, guaranteed attention

**Pseudonymous Reference**:
A salted digest standing in for a session or a subject inside the analytics
schema, stable enough to follow a funnel and not reversible into an identity.
_Avoid_: Contact id, phone number, advertising identifier, browser fingerprint

**Invalid Traffic**:
Measured activity excluded from a reported metric because it is a bot, internal
or administrative use, synthetic test data, or an implausible event rate; it is
always stored, always classified, and always reported as excluded volume.
_Avoid_: Deleted event, silent filter, unexplained gap between raw and reported

**Sponsorship Price Catalog Version**:
An Administrator-managed set of package prices that may only be published with a
written reference to the pilot traffic that justifies it, and of which exactly one
version is published at a time.
_Avoid_: Invented first price, live price edit, rate card without evidence

**Sponsorship Quote**:
A seven-day priced offer that preserves its catalog version and amounts, may
carry a manual discount only with a written reason, and reserves no capacity
while it lives.
_Avoid_: Reservation, invoice, auction bid, price that moves after issue

**Sponsorship Capacity Reservation**:
One accepted campaign's hold on one sponsored surface for a date range, taken
under a lock so concurrent acceptances cannot oversell the surface.
_Avoid_: Quote, delivery ratio, exclusivity by zone or property type

**Sponsorship Delivery Day**:
One service date recorded against a campaign, marked as consuming a paid day only
when delivery actually happened; a paused day is preserved, not spent.
_Avoid_: Calendar day, elapsed day, refund

**External Collection State**:
The Administrator's record of what happened with payment outside Product, which
issues no invoice, charges nothing and moves no money.
_Avoid_: Payment, invoice, billing status, auto-renewal

**Buyer Report Link**:
An expiring, revocable, read-only token that opens one campaign's aggregate
report and nothing else; it is stored only as a digest and is never a CRM
account.
_Avoid_: CRM login, permanent URL, shared password, account invitation

**Harm Signal**:
An Administrator-recorded pilot stop-condition event — wrong information, a
complaint, an untimely message, an assignment failure, an incorrect appointment
or operational overload — with written evidence and a moment.
_Avoid_: Advisor performance score, complaint ticket, automatic pause trigger

### The managed platform

**Managed Platform**:
The service on which several Brokerage Organizations operate the same product,
each isolated to its own data, credentials and configuration, onboarded with
accompaniment rather than by self-service signup.
_Avoid_: Tenant system, marketplace, SaaS signup, dedicated deployment per
customer

**Founding Organization**:
The one Brokerage Organization whose numbers, tokens, calendars and behaviour the
process environment describes, named explicitly in configuration. It is the only
Organization permitted to read a process setting as a bootstrap; every other one
is refused.
_Avoid_: Default organization, fallback tenant, primary account, the only
organization

**Channel Binding**:
The recorded claim of one external identifier — a WhatsApp phone number id, a
WhatsApp Business Account id, a Telegram bot id, a public hostname — by exactly
one Brokerage Organization. An unbound identifier is refused, never resolved to a
default.
_Avoid_: Routing guess, implicit ownership, shared number, fallback organization

**Organization Configuration Version**:
One immutable, checksummed, numbered document stating how a Brokerage
Organization operates — brand, service area, bookable hours, default Advisor,
channel identifiers, expected integrations and permitted operational limits —
with a written reason for its existence. It never contains a credential.
_Avoid_: Settings row, environment variable, editable preferences, secret store

**Secret Reference**:
The recorded *name* of the place one Brokerage Organization's provider credential
lives, with a fingerprint of what that name last resolved to. Product never
stores, logs, exports or displays the credential itself.
_Avoid_: Access token, API key, credential value, password field

**Credential Rotation**:
Recording a new Secret Reference for a provider while the outgoing one is kept as
history, proved by a changed fingerprint. It does not verify that the provider
accepts the new value.
_Avoid_: Overwritten secret, verified credential, tested integration

**Entitlement**:
One append-only statement of whether a Brokerage Organization may use one named
capability, with an optional numeric ceiling, a source, a written reason and an
author. A capability with no recorded entitlement is refused.
_Avoid_: Feature flag, permission, plan field, price, invoice line

**Seat Tier**:
The named band describing how large a Brokerage Organization's Advisor team may
be, together with its monthly conversation allowance. It carries no price.
_Avoid_: Price plan, subscription, billing tier, contract

**Support Access Grant**:
One temporary, read-only, expiring permission for an internal engineer to read a
single Brokerage Organization's records, carrying a written reason, an optional
request reference and a recorded use count, visible to that Organization's own
Administrator.
_Avoid_: Superadmin, impersonation, platform-wide access, permanent support login

**Platform Operator**:
An authenticated internal operator of the Managed Platform, authorized by its own
credential to provision, configure, entitle and measure Brokerage Organizations,
and refused by every surface that reads a Brokerage Organization's records.
_Avoid_: Organization Administrator, superadmin, support engineer with data access

**Provisioning Run**:
One named, resumable, individually reversible sequence of steps that brings a
Brokerage Organization into existence; the Organization is not operable until the
final step completes.
_Avoid_: Signup, setup script, one-shot migration, tenant creation

**Organization Import**:
The initial migration of a Brokerage Organization's existing records, requiring a
dry run over the identical source before any apply, producing one finding per
incoming record with the source's own reference, and rolling back by stored
identifier.
_Avoid_: Bulk upload, silent sync, catalog publication, verified inventory

**Retention Hold**:
A recorded obligation — legal, contractual or a dispute — that forbids deleting a
Brokerage Organization's data, with a named authority. A deletion request meeting
a live hold is refused outright rather than partially applied.
_Avoid_: Soft delete, deferred deletion, partial compliance, archive flag

**Organization Data Export**:
One artifact containing everything a Brokerage Organization owns, with per-table
row counts, a checksum, and every withheld column named — salts, credential
fingerprints, live token digests and model session handles.
_Avoid_: Database dump, complete backup, unredacted extract

**Scoping Table**:
The written classification of every database table as one Brokerage
Organization's data or as deliberately platform-wide with a stated reason, read by
the export, by deletion and by the isolation tests.
_Avoid_: Documentation, naming convention, implicit tenancy, ORM inheritance
