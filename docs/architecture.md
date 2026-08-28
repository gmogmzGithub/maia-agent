# Maia Architecture

Maia is built around a strict split between conversational intelligence and
business authority.

## Runtime Split

Hermes is the conversational runtime. It receives the lead-facing context,
maintains sessions, interprets fragmented WhatsApp messages, and decides which
tool to call.

The Maia backend is the product authority. It receives webhooks, persists state,
checks policy, owns idempotency, calls external systems, and records audit
events.

```mermaid
sequenceDiagram
    participant Lead as WhatsApp Lead
    participant Meta as Meta Cloud API
    participant Backend as Maia Backend
    participant DB as PostgreSQL
    participant Hermes as Hermes Runtime
    participant Plugin as Maia Plugin
    participant Calendar as Google Calendar
    participant Telegram as Broker on Telegram

    Lead->>Meta: Message
    Meta->>Backend: Signed webhook
    Backend->>DB: Store inbox event
    Backend->>Hermes: Continue durable sales session
    Hermes->>Plugin: Request typed operation
    Plugin->>Backend: Authenticated product API call
    Backend->>DB: Validate and record outcome
    Backend->>Calendar: Read or write appointment state
    Backend->>Meta: Enqueue/send reply
    Backend->>Telegram: Send appointment notice when owed
```

The customer channel is WhatsApp. Telegram is not the customer entry point: it
is the private Broker/Administrator channel. Its inbound administrative role is
an additional operator surface, while its outbound notices are Product-owned
effects caused by appointment state (immediate booking or review notice,
morning digest, and pre-visit reminder). Hermes composes the natural customer
conversation; Maia decides when a Telegram notice is owed and performs the
send.

## Why the Model Is Not the Authority

The model can be good at conversation and still be the wrong place for business
truth. Maia keeps the risky operations below the model:

- the backend chooses whether a property exists and is active;
- the backend decides whether a slot can be booked;
- the backend records every accepted operation;
- the backend handles duplicate webhooks and retries;
- the backend classifies uncertain delivery or Calendar outcomes for review.

This allows natural conversation without giving the model unchecked access to
database credentials, Calendar credentials, or WhatsApp delivery state.

One consequence is a freshness rule. A property document or status can change
while a durable session stays open, so a turn that repeats a property fact must
re-read it through `get_property_information` rather than reuse a fact retrieved
earlier in the same conversation. Product restates that contract on every Sales
turn, because an instruction given only once loses salience behind facts the
model already has. This reverses an earlier position that revalidating before
every ordinary reply was unnecessary; the cost is one extra tool call on turns
that discuss a property.

## The Commercial System of Record

Product owns the commercial truth beneath the conversation: who the person is,
what they want, who is responsible, what is owed, and how it ended. Those live in
`domain/commercial/` as deep modules — a small interface over the transactions,
invariants, idempotency and audit the capability actually needs — and the
routers, workers and templates above them hold none of those rules.

| Seam | The only way to |
|---|---|
| `CommercialIdentity.resolve` | turn a channel identity into a Contact |
| `PropertyNeeds` | record what the Contact wants, and how confirmed it is |
| `OpportunityManagement.record` | open an Opportunity or change its stage |
| `Assignment.assign` | decide who is responsible, or make the absence visible |
| `NextActions.schedule` / `.complete` | owe and discharge the next action |
| `CommercialInbox.query` | read anything an operator surface shows |
| `CommercialIntake.record_inbound` | cross from the WhatsApp Inbox into commercial work |
| `ConversationRetention` / `CommercialMaintenance` | apply the rules that are about time |
| `OrganizationDirectory` | resolve the Organization and who belongs to it |

Four separations are structural rather than conventional, each enforced by the
schema:

- an **Organization** owns commercial data, so nothing is implicitly global;
- a **Contact** is a person across time, distinct from the channel identity Meta
  authenticates and from the Conversation they happen to be having;
- a **commercial stage** says where the pursuit stands and nothing else —
  assignment, appointments, consent and Do Not Contact are their own state;
- an **inferred criterion** is Pending until the Contact confirms it.

The races that matter are guarded by partial unique indexes, not by service-layer
checks: one open assignment per Opportunity, one Pending Next Action, one open
queue entry, one current value per named criterion, one open exception, one
default Advisor per Organization. Terminal outcomes are guarded by CHECK
constraints, so a conversational inference cannot satisfy them by accident.

Intake runs inside the transaction that persists the inbound message. A Contact
or an Opportunity that outlived the message which produced it would be a record
of something that never durably happened.

The time-driven rules are paced rather than polled. `CommercialMaintenance` knows
what they are; `CommercialUpkeepWorker` is the object that lives long enough to
remember when they last ran, and it holds them to a 15-minute interval. The
background loop ticks once a second and these rules have 28- and 90-day horizons,
so without the guard the pass would scan roughly 86,400 times a day to discover
there was nothing to do — the same reason the Broker notifier owns its own
cadence.

## Operator Surfaces

`/crm` is server-rendered, Mexican Spanish, and needs no JavaScript: every action
is a form submission, so the surfaces stay usable on a slow phone and testable
without a browser. Authentication is the existing HTTP Basic credential;
authorization resolves it to an Organization member row (ADR-0046). Property
administration and document upload go through the same resolution and require the
Administrator role — before this cut they accepted any configured credential
without looking at a role at all.

Every mutating form carries a hidden idempotency key minted when the page was
rendered, so a double click, an impatient refresh or a retried request replays
the command the domain already recorded instead of repeating it. The shell,
including the table renderer that carries the caption and header scopes, is
shared with the Property surfaces so one screen cannot quietly lose the
accessibility guarantees the others are tested for.

The panel reports Follow-up Coverage with its gaps attached. The Inbox,
Opportunities, Contacts and Assignment Queue read exclusively through
`CommercialInbox`, which is also where Organization scoping, role visibility,
expired message bodies and communication restrictions are applied once.

Denied outbound decisions and an active Do Not Contact are shown to the operator
with the reason. Showing them is the point — an operator who cannot see why a
message did not go out concludes the system is broken — and none of these
surfaces can send anything: the Stage 1 eligibility gate has no entry point in
the CRM router.

## Tool Boundary

The standalone Hermes plugin is deliberately thin. It exposes typed tools to
Hermes and calls Maia's product API with a local shared token. It does not
import the database layer and does not implement business rules.

That keeps the agent interface clear:

- Hermes sees stable tool contracts.
- Maia keeps deterministic policy.
- Tests can cover the product behavior without mocking the model.

## Current Local Topology

Docker Compose runs the topology as three containers:

- `db`: PostgreSQL and the durable Product state;
- `product`: FastAPI and the in-process background workers;
- `hermes`: the pinned Hermes runtime with the standalone Maia plugin.

Product and Hermes share a private network namespace so their authenticated
JSON-RPC WebSocket remains loopback-only. They are still separate processes and
containers. Product reaches PostgreSQL through the private Compose network.
Only Product port 8080 is published to the host.

Runtime configuration lives in one ignored `.env`. Docker volumes retain
PostgreSQL data, Hermes profile state, and accepted Property Documents. No
local Python virtual environment or sibling Hermes checkout is part of the
operator workflow.

Optional integrations require their normal provider credentials:

- optional Meta, Telegram, Google Calendar, and model-provider credentials.

This is enough to prove product behavior and recovery paths before adding cloud
deployment, managed secrets, production WhatsApp assets, and real lead data.
