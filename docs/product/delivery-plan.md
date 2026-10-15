# Maia delivery plan: small, testable features

Status: design draft. The first WhatsApp inquiry-to-confirmed-visit flow and
later valuation stage are agreed. Detailed feature decomposition and subsequent
ordering below are proposed. No implementation is authorized or claimed by this
plan; the current conversation remains design-only.

## Planning rules

- One modular backend, with background workers where needed.
- One conversational engine with discovery, sales and transaction-assistance
  role configurations; start by implementing the sales role's complete flow.
- A small owned harness using a standard provider SDK is the primary candidate;
  Hermes remains a comparison. A fork requires a concrete justification.
- Each feature has an observable result and focused acceptance cases. Package
  moves, empty abstractions and broad rewrites are not standalone user features.
- Use synthetic or authorized non-public fixtures. Never commit real customer
  conversations, private inventory, credentials or runtime state.
- Preserve brokerage isolation, trusted routing and credential safeguards
  throughout later implementation. A single pilot does not justify a default
  organization or shared customer memory across brokerages.
- Working behavior is evidence for regression checks, not an architecture
  selection constraint. Runtime/database deletion is not a delivery prerequisite.

## Stage 0 — Settle contracts and validate the engine candidate

Outcome: a small set of agreed cases and a defensible runtime choice before a
larger implementation commitment.

The first search turn's context, search result, lifecycle and observability
contracts are accepted. Its proposed
[small implementation sequence](../review/first-harness-implementation-sequence.md)
provides feature gates for the later runtime experiment. Acceptance remains
design-only; it does not authorize coding or provider access.

| Feature | Reviewable result | Acceptance criteria |
| --- | --- | --- |
| S0.1 Synthetic customer cases | Spanish/English inquiries with expected criteria and replies | Include budget clarification, desired versus mandatory rooms, neighborhood alternatives, missing facts and separate pursuits; no private records |
| S0.2 Search ranking contract | Ordered sample results with reasons | Customer fit precedes source preference; own listings win when suitability is comparable; explicit hard limits always hold; unknown facts stay unknown |
| S0.3 Booking and takeover contracts | Documented confirmed, refused, pending and superseded examples | Show a last-minute correction, a slot conflict, takeover during work and an uncertain external outcome without false confirmation |
| S0.4 Bounded runtime comparison | Later experiment comparing owned harness and upstream Hermes with equivalent tasks | Record quality, corrections, recovery, scope, latency and cost; choose from evidence, not repository size; no full fork implementation required |

Selected model baseline: Claude Haiku 5.5 through a hosted API for all three
conversational roles, using the direct Anthropic API. Compare runtimes with this model where supported; verify
provider protocol compatibility rather than assuming it.

Accepted provisional pilot settings: bounded recent conversational context for
seven days after the last interaction; external inventory refresh every 30
minutes subject to provider feasibility; useful property answers within 10
seconds and appointment options within 20 seconds under the agreed workload.
Acknowledgements do not count as useful answers. These targets are not measured
performance claims.

Anthropic API spending ceiling: USD 100 per day. This is a maximum, not expected
spend or a workload estimate. Budget optimization is deferred during the current
architecture discussion.

Open inputs: representative scale,
external-data staleness limits, and approved
procedure guidance. These are planning inputs, not permission to access private
accounts or install/run candidates during this design session.

## Stage 1 — Minimum operating inventory and CRM

Outcome: the team can maintain trustworthy stock and the system can find options
without an LLM being responsible for catalog truth.

| Feature | Observable result | Acceptance criteria |
| --- | --- | --- |
| S1.1 Broker and calendar configuration | A broker has a product identity and calendar reference | Credentials stay outside configuration documents and model context; an unconfigured broker is not bookable; unrelated brokerages cannot use the configuration |
| S1.2 Own-property form | Create/edit price, operation, location, characteristics and approved description | Distinguish unknown values from zero; explicit currency and rental period; persist verified values and authorized publication state |
| S1.3 Broker assignment and property visit schedule | A property has a responsible broker and an editable weekly window | Santiago is the default for directly registered and EasyBroker stock; humans may reassign in CRM; copy the brokerage schedule initially; full 60-minute visits must fit the window |
| S1.4 Approved nearby-colonia lists | Team maintains names, aliases and approved relationships | Scope names by municipality; no recorded relation means no unsupported proximity claim |
| S1.5 EasyBroker synchronization | Authorized external stock enters a local search projection | Verify real payload mapping, pagination, refresh and removal behavior; preserve source identity and unknowns; credentials and access are tested in an authorized environment |
| S1.6 Combined inventory and duplicate resolution | Own and authorized external stock appear in one search | Administrator or responsible broker confirms links to external identifiers; similar wording cannot merge listings; own published facts prevail; exclude unverified external options during outages without treating the outage as zero matches |
| S1.7 Ranked structured search | Criteria produce properties with explicit match differences | Respect price cap and indispensable features; rank location and characteristics using the agreed policy; show actual values and explain alternatives |
| S1.8 Minimal customer/pursuit record | CRM retains requirements, interests, responsible work and next step | Record clear criteria/corrections as customer-stated facts without separate confirmation; clarify ambiguity; separate independent needs; a shortlist does not create a pursuit per property; contact details do not grant access to existing records |
| S1.9 Inventory management access and withdrawal | Administrators manage brokerage inventory and brokers manage assigned listings in one CRM area | Submitter and responsible broker are distinct; administrator can reassign; broker may publish assigned brokerage-created or accepted submissions; administrator accepts and assigns public submissions first; withdrawal removes discovery/new booking eligibility while preserving history and requiring explicit resolution of existing appointments |

Gate: a synthetic inventory can be created, synchronized and ranked consistently
through the product interface, including missing facts and connector failure.

## Stage 2 — First complete WhatsApp sales-and-visit flow

Outcome: a customer asks naturally and reaches a truthfully confirmed visit.

| Feature | Observable result | Acceptance criteria |
| --- | --- | --- |
| S2.1 Incoming text inquiry | An authorized WhatsApp message starts or continues a sales conversation | Trusted routing identifies brokerage; duplicate message does not create duplicate work; non-text goes to broker attention |
| S2.2 Shared engine with sales role | Spanish/English requests become grounded clarification and answers | Ask for missing price range and ambiguous operation; tools enforce authority; corrections update current requirements; no unconstrained loop |
| S2.3 Property options and information | Customer receives concise options, links and factual answers | Results derive from authorized stock; missing characteristics trigger confirmation rather than invention; empty results differ from source failure |
| S2.4 Slot offering | Customer sees actual available 60-minute choices | Intersect responsible broker calendar with property window; recheck EasyBroker listing before bookable options; Santiago is responsible by default without a separate external-property assignment task |
| S2.5 Visit confirmation | Customer accepts a slot and gets its authoritative result | Collect name/contact phone; revalidate current confirmation and slot; record broker/property/time; do not claim success before confirmed outcome |
| S2.6 Conflict and uncertain-outcome recovery | A lost slot or provider timeout produces a truthful next step | Offer updated slots after a conflict; reconcile uncertain remote effects before retry; repeated processing cannot create duplicate product commands |
| S2.7 Human request and CRM takeover/resumption | Customer can request a human; broker can use “Atención del asesor” and “Reactivar Maia” | Explicit customer request pauses automation with one acknowledgement and Santiago task; preserve internal reminders; suppress obsolete drafts; explicit CRM resumption uses known requirements/progress without assuming access to personal messages; failure tasks alone do not switch ownership |
| S2.8 Visit outcome and continued search | Broker records attended, missed, canceled or continued interest | Follow-up reflects actual CRM facts; customer can reschedule or search again without losing the relevant pursuit |
| S2.9 Conversational failure notice and broker task | A request that cannot be completed remains visible and actionable | After bounded recovery fails, use a backend-generated notice on the website or short WhatsApp message when delivery is available; create a CRM task with known request and failure; do not automatically change ownership; uncertain bookings retain factual pending status |
| S2.10 Inquiry observability | A synthetic inquiry can be followed through model, tools, business state and delivery | Correlate bounded turns and linked work; record sanitized outcomes, usage and latency; distinguish model completion from booking/delivery; default exported telemetry excludes raw conversations and secrets; runtime comparison includes observability |

Gate: the complete inquiry-to-visit case works end to end, with a correction,
duplicate inbound message, conflicting slot, restart and human takeover case.
Measure useful answers and confirmed outcomes; do not treat fluent prose alone
as acceptance. Live channel and calendar work needs an authorized test setup.

## Stage 3 — Unanswered-lead follow-up

Outcome: the agreed cadence provides useful attention and stops correctly.

| Feature | Observable result | Acceptance criteria |
| --- | --- | --- |
| S3.1 Enrollment and due schedule | CRM shows the next eligible step | Genuine WhatsApp property inquiries enroll when the initial reply is unanswered; exclude unrelated messages, opt-outs and human attention; calendar days 1, 5, 7, 14, 18, 22, 26, 28; default later sends at 10:00 Guadalajara time; no duplicate initial reply or managerial confirmation step |
| S3.2 Generated messages and delivery eligibility | Claude composes the wording for a permitted due step | Use verified customer/inventory facts; do not invent properties or promises; backend owns dates and stop rules; provider template and permission requirements still hold; a due date alone does not authorize delivery |
| S3.3 Stop and resume | Replies and CRM ownership change the scheduled work | Reply ends unanswered sequence; opt-out stops outreach; human mode pauses it; no separate future-contact scheduler or alternative contact dates in the pilot |
| S3.4 Sequence completion | Day 28 closes the relevant sequence with a reason | Distinguish no response, undecided and explicit disinterest; retain permitted business records; returning customers can resume attention |

Gate: simulate the dates and state changes without contacting real customers;
then verify authorized delivery and recovery. Step generation instructions remain
to be specified. Managerial confirmation is excluded from the pilot.

## Stage 4 — Conversational website and discovery role

Outcome: anonymous visitors discover, shortlist and enter sales through the same
engine and Inventory Search module.

| Feature | Observable result | Acceptance criteria |
| --- | --- | --- |
| S4.1 Chat-first landing and suggested searches | A suggested search starts a real conversation | Clear chat entry; conventional inventory remains reachable; controls lead to working behavior |
| S4.2 Discovery results and property pages | Chat shows ranked cards and factual detail pages | Same search policy as sales; links and facts originate from result records; description answers are grounded |
| S4.3 Browser shortlist | Visitor keeps up to five selections per need | Persist on same browser; allow replacement at limit; keep browsing; recheck saved availability before action |
| S4.4 Discovery-to-sales role transition | “Consultar este inmueble” or “Consultar mis seleccionados” starts sales | Transfer selected scope, requirements and unanswered questions; remain in website; do not infer outreach intent from a property-fact question |
| S4.5 Optional WhatsApp continuation | Customer explicitly carries the current selection into WhatsApp | Use scoped expiring handoff reference; verify identity before linking an existing relationship; name/phone guesses do not expose records |
| S4.6 Website presentation refinement | Reviewed chat-first layout and scroll transition | Validate desktop/mobile accessibility and real controls; change presentation without duplicating search or sales logic |
| S4.7 Public account and submission form | An account holder requests help selling or renting a property | Normal form without an LLM; submission is private pending review and does not imply verified ownership or enter customer search |
| S4.8 Submission review and assignment | An administrator accepts a submission and assigns its broker | Acceptance and assignment are explicit; submitter identity stays separate; rejection does not publish stock |
| S4.9 Accepted submission publication | The assigned broker maintains and publishes an accepted listing | Reuse the CRM listing and publication rules rather than a second inventory implementation; only published approved facts reach Maia |
| S4.10 Submitter changes and withdrawal | Submitter proposes updates or requests withdrawal | Broker approves proposed factual changes; withdrawal immediately pauses new recommendations and bookings and alerts the broker to resolve existing appointments; retain history |

Gate: the visitor reaches property details, builds a shortlist and books through
sales without repeating requirements; cross-channel linking is explicitly verified.

## Stage 5 — Additional Meta entry channels

Outcome: Instagram/Facebook customer inquiries use the existing sales flow.

| Feature | Observable result | Acceptance criteria |
| --- | --- | --- |
| S5.1 Instagram entry | Authorized text messages reach sales | Correct brokerage routing, delivery status and channel formatting; no accidental identity merge |
| S5.2 Facebook entry | Authorized text messages reach sales | Same product policy and grounded answers; channel-specific permissions/eligibility are verified separately |

These adapters extend the first WhatsApp flow; they do not create independent
sales policy. Cross-channel identity and follow-up eligibility remain explicit.

## Stage 6 — Transaction-assistance role

Outcome: customers receive approved next steps based on broker-confirmed progress.

| Feature | Observable result | Acceptance criteria |
| --- | --- | --- |
| S6.1 Transaction intent and milestones | Broker records the relevant property and purchase/rental progress | Intent, agreement, payment and completion are distinct; customer reports are not automatically confirmed |
| S6.2 Approved procedure guidance | Team maintains purchase/rental guides and applicable steps | Version guidance and responsible approval; missing or exceptional information goes to a human |
| S6.3 Transaction-assistance role | The shared engine explains the current approved next step | Use the confirmed milestone and applicable guide; customer context survives the role change; no invented paperwork or deadlines |
| S6.4 Routine milestone messages | Eligible confirmed changes produce useful guidance | Use approved routine content; exceptions and transaction-specific obligations/payments/deadlines receive human review; no duplicate notification |

Gate: evaluate distinct purchase/rental cases, unverified payment, stale CRM state
and a guide revision using authorized examples. The actual guides are an input,
not information the model can invent to make this stage appear complete.

## Stage 7 — Brokerage pilot validation

Outcome: decide what the product actually improves and what needs revision.

- Review unattended inquiries, grounded-answer quality, confirmed and completed
  visits, broker workload and customer feedback.
- Track latency, calls, operating cost, corrections, recovery and failed delivery
  with appropriately scoped/redacted operational evidence.
- Revise ranking and cadence from observed results; keep evidence and proposals
  separate. There is no accepted numerical improvement target yet.

This is continuous during the earlier stages, not a reason to wait until stage 7
to test the first customer flow.

## Stage 8 — Valuation as an independent investment

Proposed small features: define the intended opinion and limitations; establish
authorized comparable evidence and update responsibility; evaluate a transparent
baseline; assess uncertainty and unsupported inputs; then build its customer
experience. Price opinions need their own evaluation. A plausible generated
number is not proof of a valid valuation methodology.

Data access, comparables, methodology, intended reliance and validation remain
open. This stage follows sales-flow validation and has no selected model or
delivery date.

## Later product expansion

Public property submission belongs to Stage 4 and requests brokerage assistance
rather than independent self-service advertising; no LLM is required.

Serving another brokerage, supplying only the agent through an integration,
broader market intelligence and geographic automation remain later options.
Brokerage isolation applies from the first feature even while onboarding,
commercial SaaS packaging and cross-market analytics are deferred.

## What remains deliberately unresolved

- Detailed deterministic ranking examples and characteristic deviation rules;
  initial comparable suitability means equivalent match before source preference.
- Runtime experiment results with Claude Haiku 5.5 via direct Anthropic API.
- External connector outage detection and recovery thresholds.
- Provider capabilities, credential availability and authorized test environments.
- Detailed public submission form in Stage 4, including broker review
  of proposed changes and immediate pause on a withdrawal request. Website
  property submission requires no LLM.
- Step generation instructions and channel-compatible delivery
  of Claude-generated follow-up wording.
- Approved transaction guidance.
- Pilot workload; it is not established by the USD 100/day API spending ceiling.
- Measured response latency against the provisional 10/20-second targets.

No dependency/library, deployment topology beyond the modular backend shape,
or database rebuild is selected by this feature plan.
