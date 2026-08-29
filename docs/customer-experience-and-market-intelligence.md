# Customer Experience and Market Intelligence

This document defines the Customer Experience and Market Intelligence capability
implemented locally after Stage 9. The Product code, migration 0028, CRM
workspace, read-only Hermes operation, shared projection, analyst dashboard and
credential-free acceptance tests exist. This is not a claim that the capability
has been activated or accepted in a live brokerage: Santiago must review and
approve the first purchase-journey template before it is used with customers.

## Implementation status

The implementation preserves the operating gates in this design:

- an Organization Administrator creates and approves a versioned buyer template;
- starting a Journey freezes that version and does not mark the Opportunity Won;
- only a human Organization Member can confirm milestone, Profile and sale facts;
- a completed sale cannot become Won without the minimum facts in ADR-0058;
- PostgreSQL triggers version direct SQL corrections and enqueue a durable,
  idempotent re-projection;
- the `market_intelligence` schema contains only selected shared analytical
  facts, reached through a separate analyst authority and credential surface;
- Hermes can read human-confirmed Journey state but cannot advance it or receive
  recorded evidence prose; and
- individual comparables are available immediately, while aggregates remain
  withheld below five applicable completed sales.

Operational activation remains gated on Santiago's template approval and on
explicit configuration of the analyst credentials. No historical or external
dataset was introduced.

## Product outcome

Customer Experience is the operating priority. Maia will accompany a buyer from
an explicitly started purchase process through completion and aftercare, while
Product remains authoritative for every milestone and a human confirms every
material fact. The same work will create a proprietary market-history asset from
new facts the participating brokerages record manually.

The first data product is an internal Comparable Sales Report. It answers which
known Properties sold around a subject Property, for how much, when, and with
which comparable characteristics. It informs a human; it is not an automated
valuation.

## Accepted boundaries

- Begin with the buyer journey. Rental, seller and landlord journeys follow
  later rather than sharing one generic workflow.
- Start collecting data from zero. Do not backfill historical transactions.
- Accept only facts entered by participating real-estate operators. Do not
  ingest INEGI, registries, cadastral systems, public portals, MLS feeds or other
  external datasets in this version.
- Keep Product and PostgreSQL as one modular authority. Market Intelligence is a
  separate context and schema, not a separate service or warehouse yet.
- Keep every Brokerage Organization's CRM, identities, documents and
  conversations isolated. Project selected analytical facts into a distinct
  Platform-wide dataset instead of reading across Organizations.
- Build geographic selection later with SQL. Capture the available location
  facts now without committing to one permanent definition of a zone.
- Correct current Profile and sale facts directly in PostgreSQL, not through a
  correction UI. Database triggers preserve and republish corrections.

## Transaction Journey

An authorized Organization Member starts a Transaction Journey from an
Opportunity with `Iniciar trámite de compra`. Starting it does not mark the
Opportunity Won. Product freezes the Organization's currently approved template
version into the new Journey, so later template changes do not rewrite active or
historic work.

The draft buyer template is:

1. operation agreed;
2. payment path established;
3. applicable preparatory agreement recorded;
4. buyer file assembled;
5. Property file assembled;
6. legal review recorded by the responsible human;
7. appraisal and applicable technical review;
8. financing approval and conditions;
9. notarial preparation;
10. signature scheduled;
11. deed signature and settlement;
12. possession and handover;
13. registration and documentary delivery; and
14. aftercare.

Santiago may change the names, ordering, dependencies, responsibilities,
required evidence and messages before approval. Cash, financed, new-build and
used-home paths may skip or reorder milestones under explicit template rules.

The Journey state is `Active`, `Completed` or `Cancelled`. A milestone is
`Pending`, `InProgress`, `Blocked`, `Completed`, `Skipped` or `Cancelled`.
Blocked, Skipped and Cancelled milestones require a reason. The responsible
Advisor advances milestones for owned work; an Organization Administrator may
correct, cancel or complete any Journey.

Maia communicates only confirmed Product state. It may announce Journey start,
explain the current step, request approved missing information, report a human-
confirmed change, remind before a due item or appointment, report a recorded
delay, and provide a bounded no-change update. It does not negotiate, interpret
documents legally, approve financing, infer completion or declare the sale Won.
Every proactive message continues through Product's outbound eligibility gate.

## Purchase Profile

One Opportunity has one dated Purchase Profile. It is not a permanent Contact
classification. The responsible Advisor records and updates it in the CRM;
Maia may request a missing fact but never invent or infer one.

The v1 fields are:

- birth year;
- individual monthly income and currency;
- adults in the household;
- number of children;
- financial dependants;
- number of co-buyers;
- first, second, third or later home purchase;
- cash, credit or combined payment;
- financing institution or modality;
- available down payment;
- target monthly payment;
- preapproval state;
- recorded time; and
- recording Advisor.

The profile does not include children's age bands, occupation, income stability
or household monthly income. Each optional answer distinguishes `NotCaptured`
from `NotProvided`. Operational storage retains exact contributed values;
reports may derive bands without destroying the source precision.

## Market Sale Record

Starting a Transaction Journey opens one Market Sale Record in preparation. The
Advisor fills it as facts become known. The last asking price before the parties
agreed the deal is `Published Price`; the appraisal used for the deal, when
known, is `Appraisal Value`; and the final completed amount is `Paid Price`.
Amounts always carry their own currency and v1 reports do not compare unlike
currencies.

The sale-time Property snapshot may contain:

- Property reference, type, municipality, colonia and available address;
- land and construction square metres;
- bedrooms, bathrooms and parking spaces;
- known construction year;
- new, excellent, good or needs-improvement condition;
- publication and completion dates;
- Published Price;
- Appraisal Value; and
- Paid Price.

Only an Organization Administrator marks the Opportunity Won and the Market Sale
Record Completed. Completion requires the Property, property type, municipality,
completion date, Paid Price and currency. The remaining comparison facts are
optional and distinguish `NotProvided` from `NotCaptured`. A Won operation cannot
bypass this minimum; if Paid Price is not yet known, the deal remains in process.

A cancelled Journey retains its known sale, Property and Profile facts plus its
outcome. It may inform negotiation and loss analysis but is never a completed or
Comparable Sale.

## Logical ownership and flow

The first implementation should preserve these logical stores; exact physical
table names may be chosen with the migration.

| Logical record | Ownership | Purpose |
| --- | --- | --- |
| Purchase Profile | Organization | Current buyer facts for one Opportunity |
| Transaction Journey | Organization | Frozen template, state and responsibility |
| Transaction Milestone | Organization | Evidence-bearing progress step |
| Market Sale Record | Organization | Current sale and Property comparison facts |
| Market record revision | Organization | Prior and replacement values from SQL corrections |
| Market contribution outbox | Organization | Durable idempotent request to republish analytical facts |
| Shared market record | Platform | Central analytical copy without Contact identity |
| Shared buyer profile | Platform | Exact contributed buyer facts linked analytically to a deal |
| Market sale resolution | Platform | Human decision that several contributions describe one sale |

The write flow is:

```text
CRM or authorized SQL
        |
        v
Organization Purchase Profile / Market Sale Record
        |
        | PostgreSQL trigger, same transaction
        +--> append old/new revision when applicable
        +--> enqueue idempotent Market Contribution
                         |
                         v
                  central projector
                         |
                         v
                Shared Market Dataset
```

The Shared Market Dataset includes the accepted Property, sale and Purchase
Profile analytical values but no Contact identifier, phone number, channel
identity, document or conversation. The contribution retains enough platform
provenance for correction and duplicate resolution without granting a brokerage
access to another brokerage's operational record.

Brokerage members see their own detailed records and shared derived statistics.
A Market Intelligence Analyst may inspect the complete shared analytical dataset
but receives no Organization CRM authority. This is not a superadmin role.

## SQL corrections and revisions

There is no correction screen. An authorized operator updates the Organization's
current row directly in SQL. PostgreSQL triggers must:

1. capture the prior and replacement values, database role and time;
2. append the revision rather than erase the prior value;
3. enqueue a new contribution atomically; and
4. let an idempotent projector replace the current shared analytical version.

Operators never edit the Organization and shared copies separately. Reports use
the current accepted version while the revision history explains earlier values.

## Duplicate sales

Two brokerages may contribute the same co-brokered deal. Product preserves both
contributions and may flag a candidate from matching Property, completion date
and Paid Price. It does not merge automatically. A Market Intelligence Analyst
may resolve the contributions as one shared sale; aggregate reports then count it
once while retaining both provenances.

## Reports

An individual completed sale may appear as a comparable from the first record.
Aggregate medians, ranges and buyer-profile distributions require at least five
applicable completed records and always disclose sample size. Unfinished and
cancelled deals never appear as sold comparables.

The first internal dashboard contains:

- completed sales;
- total and median Paid Price;
- Paid Price per square metre when the applicable area exists;
- Published-to-Paid Price difference;
- publication-to-completion days;
- distribution by Property type and municipality;
- cash versus financed purchases;
- first, second or later home purchase;
- buyer distributions by age, income, children and dependants; and
- record completeness.

The first Comparable Sales Report shows the subject Property and selected sales
with date, location, comparable characteristics, Paid Price, price per square
metre and the known Published Price and Appraisal Value. Geographic selection,
distance and zone definitions remain report-time SQL concerns for a later design.

## CRM experience

The Opportunity page receives one Mexican-Spanish workspace titled `Trámite y
datos de venta`. It combines the Journey, milestones, Purchase Profile and Market
Sale Record and reuses known Contact, Opportunity, Listing and Property facts.
The design must not make an Advisor enter the same fact twice.

## Implemented composition

1. Add the Organization-scoped Journey, milestone, Profile and Market Sale
   records and their invariants.
2. Add the CRM workspace and the explicit `Iniciar trámite de compra` action.
3. Require the minimum Market Sale Record when an Administrator records Won.
4. Expose bounded Product operations for Maia to read the Journey, request
   approved information and communicate confirmed milestones.
5. Add revision and Market Contribution triggers plus the durable projector.
6. Add the Platform-wide shared schema and Market Intelligence Analyst boundary.
7. Add candidate duplicate detection and human resolution.
8. Add the Comparable Sales Report and internal dashboard.
9. Verify Organization isolation, correction propagation, outbound eligibility,
   duplicate counting and sample thresholds in canonical Docker Compose.

## Explicit non-goals

- historical backfill;
- external government, registry, cadastral, demographic, portal or MLS feeds;
- automatic valuation or price recommendation;
- automatic duplicate merging;
- a separate warehouse or microservice;
- a correction UI;
- cross-Organization CRM access;
- public exposure of individual buyer profiles; and
- rental, seller or landlord Journey/Profile variants in v1.

## Acceptance properties

- Starting a Journey does not mark an Opportunity Won.
- Maia cannot advance a milestone or invent its evidence.
- Won is refused without the minimum completed sale facts.
- Every direct SQL correction produces a revision and refreshed shared version.
- A second Organization can contribute without reading the first one's CRM.
- Shared analytical rows contain no Contact, channel, document or conversation
  identity.
- A co-brokered deal resolved from two contributions counts once.
- Cancelled and unfinished deals never appear as sold comparables.
- Aggregate results with fewer than five applicable sales are withheld and the
  sample size is always visible.
