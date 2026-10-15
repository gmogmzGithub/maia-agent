# Customer journey: agreed requirements

These requirements were agreed during the fresh product review. They describe
intended behavior, not a claim that the current implementation provides it.
Agent responsibilities below do not select a runtime or deployment architecture.

## Discovery and sales

The website agent primarily presents and compares inventory options. Both the
website agent and selling agent answer property questions from authorized
inventory information. Asking for a property fact alone does not request outreach.

Customers can shortlist up to five properties per search need as an initial
pilot limit. Browsing remains available at that limit; adding another selection
offers replacement. Selections initially survive return visits on the same
browser without mandatory registration. Cross-device persistence remains open.

Each property offers “Consultar este inmueble”; the shortlist offers “Consultar
mis seleccionados”. An explicit request for assistance begins sales with the
relevant selection, stated requirements, and unanswered questions preserved.
Sales continues inside the website, with WhatsApp as an optional continuation.
Identified commercial relationships can retain the relevant selections; the
identity and channel-linking mechanism is not yet decided. An explicit handoff
carries the current selection and requirements; linking an ongoing relationship
requires verification of the relevant identity, never name matching or model
inference alone. Availability is
rechecked before acting on saved selections.

Incoming Meta conversations include Instagram, Facebook, and WhatsApp. Initial
contact handling also supports explicit customer requests for contact.
Broker-entered prospects are a separate workflow requiring a recorded reason
and permission to contact them.

## Visits and continued attention

Collect the customer's name and contact phone number when they request a visit;
discovery remains anonymous. A typed phone number is customer-provided until
verified and does not grant access to an existing customer's records.

Fragmented messages and corrections are reconciled into the current request.
Consequential actions validate the latest customer confirmation; redirecting a
model turn does not undo an already completed action.

Human takeover is explicit. The CRM control “Atención del asesor” pauses automated
replies and customer follow-up for that conversation while backend reminders
remain active. “Reactivar Maia” explicitly resumes automation.

An explicit request such as “Quiero hablar con Santiago” also pauses automated
replies and follow-up for this conversation and creates a CRM task for Santiago
in the pilot. Send one acknowledgement: “Claro, dejaré tu solicitud a Santiago
para que continúe contigo.” This does not promise immediate availability or
claim that a human has responded. The transition must suppress other pending
automatic replies; internal reminders remain active. Resumption stays explicit
through “Reactivar Maia”.

Brokers use their personal WhatsApp accounts for human customer conversations.
The initial design does not require those conversations to be stored or
synchronized into Maia. Brokers remain responsible for recording operational
progress in the CRM and use those controls for takeover and resumption. Maia
cannot infer those transitions or the broker's messages from an unobserved
personal conversation. Resumption uses confirmed CRM progress and known customer
requirements, without inventing the missing conversation.

Clearly stated criteria and corrections are automatically recorded as
customer-stated requirements without asking for a separate summary confirmation.
Clarify ambiguous interpretation. Requirements do not establish booking
acceptance, broker-confirmed milestones or tool-confirmed effects.

When a customer returns, requirements, shortlist, visits, and open pursuits remain
available as explicit business records that the customer or broker can correct.
The initial design does not require complete conversation transcripts. Retain
the business records needed for continuity and follow-up. The provisional recent
context lifetime is seven days after the last interaction; context size bounds
remain design work. Any conversational summary
does not establish prices, payments, appointments, or transaction milestones.

The selling agent helps arrange a visit using the responsible broker's available
calendar slots. Booking does not end customer support: Maia assists with
reminders, rescheduling, and continued discovery. The broker conducts the visit
and is responsible for recording customer progress and visit outcomes in the CRM.
Each distinct property pursuit has its own progress, appointments, and
transaction milestones; a shortlist does not create one pursuit per property.
Every property has an assigned responsible broker, who handles its visits.
For the pilot, EasyBroker properties are part of the brokerage's inventory and
Santiago is responsible by default. They do not require a separate assignment
request. Humans may change broker responsibility through the CRM.
For a shortlist involving different brokers, Maia coordinates the customer
conversation and records the property inquiries in the CRM. Each broker sees
the context relevant to their work; a second human coordinator is not initially
required.

Each property has an editable recurring weekly visit schedule in the CRM,
copied from a brokerage-wide default and interpreted in Guadalajara local time.
Visits occupy 60-minute slots entirely within both that schedule and the assigned
broker's calendar availability. A multi-property visit request produces one
appointment per property. Maia proposes a sequence for customer confirmation;
travel planning initially remains manual, with gaps requested by the customer
or broker.

## Transaction assistance

Transaction assistance begins at broker-confirmed intent to pursue a specific
property. Purchases and rentals have distinct journeys. Signed agreements,
payments, and completion are separate milestones rather than synonyms for intent.

Maia explains approved guidance and the broker-confirmed next step. Customer
reports remain distinct from broker-confirmed facts; discrepancies create a
verification task while useful general guidance remains available. Follow-up
must avoid assuming an outdated status.

Approved routine guidance may be delivered automatically when the triggering
milestone and contact permission are confirmed. Exceptions and statements about
transaction-specific obligations, payments, or deadlines require human review.
The communication policy, guidance sources, and detailed milestones remain open.
