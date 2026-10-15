# Inventory policy: agreed requirements

These requirements describe intended business behavior agreed during the fresh
product review. They do not assert complete implementation or provider readiness.

## Structured discovery and grounded answers

The initial discovery target is straightforward natural-language filtering by
property type, municipality, neighborhood, bedrooms, bathrooms and parking,
plus any other explicitly stated criteria. Agents answer from authorized stock
information only; unsupported characteristics remain unknown. Reply wording
should be concise and easy to understand.

Requested bedroom, bathroom and parking quantities describe desired values,
not automatic minimum filters. Discovery should find the closest available
matches and clearly explain differences from the request. This clarification
supersedes the earlier proposed minimum-count interpretation on 2026-10-08.

Ask the customer for their price range when it is missing and needed for
discovery ranking, including transaction type, currency and price period where
ambiguous. Respect an explicit maximum budget. Within the budget, rank location
fit before characteristic fit; price proximity is useful when the customer
states a preferred price, without assuming they want to spend the maximum.

Both fewer and more rooms may be presented as explained alternatives to desired
quantities. Prefer exact characteristic matches among otherwise comparable
options, with missing requested rooms penalized more than extra rooms. An
explicit minimum or exact requirement overrides approximate matching.

An in-budget property in the requested neighborhood can precede a nearby
property with closer room counts under the default location-before-characteristics
policy. Explicit customer priorities override that default. The initial ranking
uses explicit deterministic ordered rules rather than a weighted numerical
score. Filter hard requirements and budget ceilings first; then apply customer
priorities or default location-before-characteristics ordering, comparing desired
quantities with shortages penalized more than extras. Price closeness applies
when a preferred price is stated. Initially, comparable suitability means
equivalent match under those preceding rules; only then prefer own inventory.
Claude does not calculate or override ranking. Detailed ordering examples and
characteristic deviation rules remain engineering specification work; scoring
can be reconsidered if reviewed cases demonstrate a need.
For the first version, nearby neighborhoods come from
broker-reviewed lists stored in product data; comparable housing options are
based on authorized stock. Geographic automation and scaling are deferred.

When an authoritative search finds no suitable stock, say concisely:
"Por ahora no tengo inmuebles en mi inventario que se ajusten a lo que buscas."
Do not insist on changing requirements or invent an offer. This does not
remove the agreed ability to present genuine approximate matches to preferences
with their differences explained. Source failure is not an empty search.

## Combined inventory search

For this pilot, authorized EasyBroker listings are the brokerage's inventory,
not an outside brokerage's stock requiring a new assignment workflow. Santiago
is the default responsible broker for directly registered and EasyBroker
listings. Humans can change responsibility through the CRM. "Own" versus
"external" below distinguishes directly published records from connector-sourced
records, not separate commercial ownership or responsibility.

Search authorized own inventory and EasyBroker inventory together using the
customer's explicit criteria. Rank customer fit first and prefer own listings
when suitability is comparable; source preference must not promote a materially
worse match. Remove confirmed duplicates. This replaces the previously agreed external-fallback-only policy
as of 2026-10-08. Other authorized connectors can follow the same policy.

For a listing available on the brokerage website, the brokerage's published
listing information takes precedence over external information for its
characteristics. External sources are secondary. If a local listing lacks a
fact, Maia reports that confirmation is needed and asks its responsible broker.
External facts may help the broker update the listing, but must not silently
fill customer-facing gaps. Handling conflicting updates and the definition of
a usable approximate match remain engineering specification work.

A connector failure is not evidence of zero external matches. Duplicate identity
must be established without merging distinct properties based only on similar
descriptions. Initially, a brokerage administrator or responsible broker
explicitly confirms the link between an own listing and its external identifier.
Similar addresses or descriptions cannot automatically merge properties.
Connector synchronization mechanics remain design work.

## External inventory freshness and outages

Discovery and ranking search a synchronized local copy of authorized external
inventory alongside own stock. The accepted provisional pilot target is a
configurable refresh every 30 minutes, subject to verifying provider limits and
inventory size. This target does not establish provider readiness.

Recheck an EasyBroker listing before offering bookable options. The local search
projection does not establish current source availability. Use Santiago's
configured calendar by default, or the broker explicitly assigned in the CRM.
Own published authority for duplicates continues to apply.

If EasyBroker is unavailable, continue showing verified own inventory and state
that external options could not be checked. Do not describe the outage as no
matches or confirm availability that requires external verification. Retain
external records internally, but exclude unverified external listings from new
customer recommendations during an outage. For a previously shown external
listing, explain that current availability needs confirmation. An own published
listing stays governed by its own authority even if an external duplicate cannot
be rechecked. Outage detection and recovery thresholds remain implementation work.

## Explicit customer requirements

Distinguish desired values from explicit hard requirements. Preserve explicit
hard limits; disclose differences when presenting approximate matches to
preferences. Neighborhood alternatives use the approved lists, with any explicit
customer location restriction preserved. Unsupported characteristics remain
unknown rather than being assumed to match.

Show actual quantities in every result and explain deviations from the desired
values. An explicitly mandatory quantity must be treated as a hard requirement;
unknown facts cannot be assumed to satisfy it.

## Property responsibility

### Property registration and access

Three access paths are accepted:

- A brokerage administrator can view, add, edit and remove inventory within
  their brokerage. This is an organization-scoped role, not a platform-wide
  administrator. Administrators and brokers use one authenticated CRM management
  area, reachable through a login link from the main website.
- A registered broker can add and remove their own properties without being
  an administrator. A broker may separately be granted administrator access.
  "Their own" means properties currently assigned to them, not necessarily
  properties they originally submitted. Administrators can reassign responsibility.
  Brokers can publish and update assigned brokerage-created listings and
  already accepted public submissions without administrator approval for every
  change. An administrator first accepts a public submission and assigns its broker.
- Any account holder can submit a property through the website using a normal
  form, without an LLM, in a simpler submission area. The initial business flow
  is a request for brokerage assistance selling or renting: submission,
  brokerage review, responsible broker assignment, then publication. Public
  submission does not automatically enter Maia's customer-facing stock.
  The user's detailed form flow remains to be captured. After publication,
  submitter changes to price, description or availability are proposed for the
  responsible broker to approve, rather than directly changing approved stock.
  A submitter withdrawal request immediately pauses new recommendations and
  bookings and alerts the broker to resolve existing appointments.

Keep submitter identity separate from responsible broker assignment. A broker
can also hold administrator access. These paths do not grant access to another
brokerage's inventory or customer records.

Broker reassignment and changes to existing appointments are human-managed CRM
operations. Authorized humans decide the changes; no LLM is involved in deciding
or performing reassignment. A property reassignment does not independently
instruct Maia to transfer existing appointments. The CRM uses ordinary product
authorization and scheduling operations for the human-requested changes.

Ordinary removal means withdrawal from customer search and new bookings,
preserving business history. Existing appointments need explicit resolution;
withdrawal does not silently cancel them. Permanent deletion is a separate
action whose conditions remain open. Public submission arrives in Stage 4
alongside the website, after the first WhatsApp pilot uses brokerage-entered
and authorized external stock.

### Inventory facts and visit responsibility

The team maintains own inventory through a simple CRM property form with
structured fields for price, transaction type, location, characteristics,
availability, responsible broker and visit schedule, plus an approved free-text
description. Structured fields support ranking and scheduling; the approved
description supports grounded explanations. The detailed form remains to be
designed under the accepted publication permissions above.

Every property has an assigned responsible broker. Each property has an editable
visit time window in the CRM. A brokerage-wide default recurring weekly schedule
is copied to each property and may be edited there, using Guadalajara local
time. Appointments use 60-minute slots; the entire appointment must fit inside
the property window and the responsible broker's calendar availability.

EasyBroker listings use Santiago as the default responsible broker in the pilot.
There is no separate unassigned-external-property queue or mandatory human
assignment step before continuing a customer request. Calendar configuration and
the property visit window are still required for booking. Future reassignment
is a human CRM operation, not an LLM decision.
