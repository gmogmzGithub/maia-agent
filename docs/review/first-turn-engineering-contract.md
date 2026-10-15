# First search turn: engineering contracts and worked traces

Date: October 9, 2026. Status: accepted engineering contracts for the
[agreed first slice](first-harness-slice.md). Examples are synthetic, names are
illustrative, and no interface or trace below has been implemented or executed.
Product behavior comes from the accepted inventory and customer-journey rules.
No library, deployment topology or database schema is selected here.
Acceptance covers context/authority separation, search criteria/results, turn
lifecycle, revision checks and diagnostic events. Payload names remain
illustrative; exact executable schemas and measured settings listed at the end
are implementation/evaluation work. This acceptance does not authorize coding.

## 1. A small module interface

Accepted external interface: run a bounded turn from accepted customer input
and trusted product context; return an outcome and, when eligible, a reply draft.
The caller does not manage individual model rounds or tool/result pairing.

The harness implementation can use internal seams for the Claude adapter,
inventory search and turn supervision. These are logical modules/adapters, not
an instruction to create a separate class, package or network hop for each row.
The synthetic inventory adapter and later real inventory adapter provide an
actual reason for a search seam.

| Module | Interface hides |
| --- | --- |
| Conversational engine | Context assembly, model rounds, allowed-tool dispatch and provider continuation |
| Inventory Search | Location resolution, publication/availability policy, confirmed duplicates, source coverage and deterministic ranking |
| Conversation supervision | Current input/ownership revisions and whether a draft or operation is still eligible |
| Delivery | Draft commitment, channel formatting, dispatch and observed outcomes |

An engine result cannot authorize its own delivery. The product checks current
conversation state at the delivery interface. Diagnostic events describe what
happened; they do not grant permission.

## 2. Turn input and context

| Group | Proposed fields | Supplier and trust |
| --- | --- | --- |
| Identity | Brokerage, actor, conversation and optional pursuit references | Resolved by product routing/identity, never selected by the model |
| Work | Inbound event references, turn reference, input revision, ownership revision | Product supervision; revisions identify the snapshot being processed |
| Behavior | Role, permitted tool set, prompt/tool contract versions | Product configuration; first exercise uses sales and search only |
| Customer input | Current text plus relevant recent exchanges | Customer content; evidence of requests, not privileged instructions |
| Business context | Current customer-stated requirements, selected references/display order and relevant confirmed CRM facts | Product records with source/revision/status |
| Execution context | Active provider protocol segment and remaining execution limits | Harness-owned mechanics, not customer or business authority |

The model sees only the context needed to interpret and answer; internal
authorization/fencing data need not be copied into the prompt. Customer and
property text cannot change roles, permitted tools or trusted scope. Context
does not contain credentials or the full inventory.

At the budget reply, relevant context includes the earlier house request,
Maia's budget question and "Hasta tres millones de pesos mexicanos." Current
stored customer-stated criteria take precedence over a stale derived summary. Within an active
provider segment, append the correction rather than rewriting old messages.
Starting a fresh segment reconstructs relevant context without transplanting
incompatible opaque thinking blocks. Exact context/token bounds remain to be
measured.

## 3. Search tool input

Illustrative model-visible name: `search_inventory`. The first payload contract
focuses on the agreed house-search exercise; later property characteristics
extend it when real use cases require them. This is a payload sketch, not a
complete executable JSON Schema or an installed API.

```json
{
  "operation": "sale",
  "property_type": "house",
  "location": {
    "municipality": "Zapopan",
    "neighborhood": "La Estancia",
    "exact_neighborhood_required": false
  },
  "price": {
    "currency": "MXN",
    "period": "total",
    "minimum_amount": null,
    "maximum_amount": "3000000.00",
    "preferred_amount": null
  },
  "characteristics": {
    "bedrooms": {"target": 3, "minimum": null, "exact": null},
    "bathrooms": {"target": 2, "minimum": null, "exact": null},
    "parking": {"target": 2, "minimum": null, "exact": null}
  }
}
```

Accepted representation: exact decimal strings for money; nonnegative integers
for room counts; explicit null for unknown/unstated values. Zero and null differ.
An explicit maximum is hard. Targets are preferences; minimum/exact constraints
exist only when the customer makes them indispensable. No preferred price is
inferred from a ceiling. Contradictory constraints require clarification.

Location strings resolve through product location data. An ambiguous name can
produce a clarification rather than a guessed municipality. Nearby alternatives
come only from the approved neighborhood relationships. Role, organization,
actor, arbitrary result limits and ranking weights are not model arguments.
The product controls the initial three-option presentation limit.

Validation order: permitted tool and argument structure; trusted product
authority; coherent criteria; catalog/location resolution; business search.
Validation does not prove that every criterion was faithfully extracted from
the customer's language. Interpretation quality needs the evaluation cases.

## 4. Search tool result

Keep execution and source coverage independent:

| Field | Meaning |
| --- | --- |
| `execution` | Completed, needs clarification or failed |
| `coverage` | Complete, partial or none for the requested authorized inventory scope |
| `items` | Bounded ordered verified matches/alternatives |
| `resolved_criteria` | Canonical criteria actually applied |
| `sources` | Source identities, current coverage/status and freshness |
| `ranking_version` | Policy/implementation version used to rank |
| `clarification` | Structured reason/options when criteria cannot be resolved |
| `error_code` | Sanitized technical failure category, when applicable |

Every item has a stable scoped reference, approved link when available,
listing revision/observation metadata, verified price/location/characteristics,
and structured differences from the request. Unknown characteristics stay null.
Source is directly registered or EasyBroker-imported brokerage inventory; it
does not determine a different commercial owner. Santiago is responsible by
default in this pilot.

The synthetic three-row exercise produces:

| Order | Reference | Verified facts | Match difference |
| --- | --- | --- | --- |
| 1 | DEMO-A | La Estancia; MXN 3,000,000; 3 rooms, 2 bathrooms, 2 parking | None for stated characteristics |
| 2 | DEMO-C | La Estancia; MXN 2,950,000; 3 rooms, 2 bathrooms, 2 parking | None for stated characteristics |
| 3 | DEMO-B | La Estancia; MXN 2,700,000; 2 rooms, 2 bathrooms, 2 parking | One fewer bedroom than desired |

A precedes C because fit is equivalent under the stated criteria and directly
published stock wins the source tie. No preferred price was stated. C precedes
B because fit beats source preference. This only specifies the three-row
fixture, not a complete scoring formula for every possible property.

| Combination | Allowed interpretation |
| --- | --- |
| Completed + complete coverage + nonempty items | Present the returned options and labelled differences |
| Completed + complete coverage + empty items | Authoritative no-match answer, without insistence |
| Completed + partial coverage + items | Present eligible verified own results and explain missing external access |
| Completed + partial coverage + empty items | No verified own match; external access unavailable, not a global no-match claim |
| Needs clarification | Ask the specific unresolved question, within the turn limits |
| Failed / no usable coverage | Report technical inability according to recovery policy |

No-match and clarification are normal business outcomes, not transport errors.
Unverified external candidates are excluded during an outage under the accepted
policy. If availability changes after a result, revalidation is required before
booking; this search result is not a booking guarantee.

## 5. Provider continuation and reply output

The adapter passes complete assistant content back with matching tool results
in the next user message; result blocks precede ordinary text. Preserve opaque
provider blocks in the required order. Parse a complete request before dispatch,
not partial streaming JSON. These protocol requirements are confirmed by
[Claude tool handling](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls)
and the current
[Haiku migration guide](https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide),
checked October 9, 2026. General indexed API examples can describe older models;
model-specific constraints govern this chosen baseline.

The model can explain verified evidence, ask clarification or provide the
no-match response. The harness returns an illustrative `TurnResult` with:

- Lifecycle result: completed, failed, superseded or blocked by ownership.
- Customer outcome: clarification, property answer, no match or partial sources.
- Reply draft when applicable, its ordered listing references and evidence links.
- Input/ownership revisions and observed model/tool usage metadata.

Keep listing order/reference association from search in the product's reply
projection. Prices, links and property-card fields can be rendered directly
from verified records; narrative wording receives separate grounding evaluation.
Reference membership and ordering can be checked deterministically. A schema
check alone cannot prove the truth of arbitrary natural-language prose. Do not
claim semantic grounding is solved merely by making the draft structured.

The first synthetic delivery adapter records an eligible reply; it does not
claim WhatsApp sent or delivered it. Provider completion, draft commitment,
dispatch and delivery remain distinct observations.

## 6. Turn lifecycle and commitment

Use a small lifecycle, with detailed activities represented as trace events:

| State | Meaning |
| --- | --- |
| Queued | Accepted input awaiting processing |
| Running | A worker processes a particular input/ownership revision |
| Completed | A result/draft was recorded for that revision; delivery is separate |
| Failed | Bounded processing could not produce a usable result |
| Superseded | New input makes this work obsolete |
| Blocked | Current ownership prevents automatic processing/output |

Context assembly, model calls, tool execution and draft preparation are phases,
not extra persistent lifecycle states unless recovery demonstrates a need.

Accepted first-slice rule: a newly accepted customer event advances the input
revision and invalidates unfinished automatic work from the prior revision.
Duplicate delivery of the same inbound event does not advance the revision.
Interpret its meaning in the new turn. This avoids needing an instant separate
intent classifier merely to know that the old work is stale. It may repeat
read work for short message fragments; grouping windows and limits are later
evaluation settings, not an unbounded wait for the customer to stop typing.

Check current authority before starting work, before tool admission and when
recording an eligible reply. A queued reply must also pass the check at dispatch.
Product state update and reply eligibility/commitment need transactional
coordination; a check followed by an unrelated write leaves a race.

New input can invalidate a queued reply even if its generating turn completed.
Record delivery suppression separately rather than rewriting history to claim
the earlier turn never produced a draft. A message already dispatched cannot
be recalled by this check. For that case retain the observed result and handle
the new customer input as subsequent work. No lock should span a slow remote
model or channel request in an attempt to make it magically atomic.

Human ownership changes use a separate ownership revision. An explicit request
for a human pauses automation with one permitted transition acknowledgement
and a Santiago task. That exception cannot authorize unrelated old replies.
A generic failure task alone does not change ownership. Resume remains the
explicit CRM action. The first read-only search slice does not specify durable
booking reconciliation; the later booking slice must preserve admitted effects.

## 7. Successful worked trace

Illustrative identifiers and events, not actual telemetry:

```text
E1 accepted: house request; input revision 1
T1 running: revision 1, automatic ownership revision 1
  context assembled
  model round M1 -> completed budget clarification
T1 completed: clarification draft committed
synthetic output observed: budget question

E2 accepted: budget reply; input revision 2
T2 running: revision 2, automatic ownership revision 1
  context assembled: house request + clarification + budget
  model round M2 -> search request C1
  C1 admitted under current revision
  inventory search -> completed, coverage complete, ordered A/C/B
  model round M3 with paired result -> grounded property explanation
  eligibility check -> current
T2 completed: draft and ordered reference projection committed
synthetic output observed: verified options and B's bedroom difference
```

Model rounds M2/M3 are continuation, not failure retries. Clarification T1 and
answer T2 are separate turns. Neither search creates a booking or starts an
independent pursuit for each result.

## 8. Correction during search

Starting during T2 above:

```text
M2 has requested search C1 at input revision 2
E3 accepted: "Mejor hasta dos millones de pesos mexicanos"
current input revision becomes 3
T2 is obsolete; cancellation requested as an optimization
C1 may still finish -> record result, do not authorize old output
T2 -> superseded; no old reply committed/dispatched

T3 processes revision 3 with the corrected budget
  latest criteria use maximum MXN 2,000,000
  new search -> completed, complete coverage, empty in this fixture
  reply -> "Por ahora no tengo inmuebles en mi inventario
            que se ajusten a lo que buscas."
T3 -> completed; current reply eligible at synthetic output
```

The event acceptance/revision advancement is deterministic. Claude interprets
the correction; later requirements recording stores it as a customer-stated
fact without another confirmation. The first exercise carries it in current
context rather than claiming a CRM write was implemented.

If E3 arrives after T2's draft was queued, suppress that old queued output at
dispatch. If T2's reply was already dispatched, do not claim to undo delivery;
the next turn acknowledges the correction and uses the new budget. This is the
precise limit of cancellation and output fencing.

## 9. Minimum trace/event contract

Accepted event meanings use illustrative application names, not official telemetry names:

| Event | Necessary metadata |
| --- | --- |
| Input accepted | Opaque event/conversation references, input revision, received time |
| Turn started | Turn/trace references, input and ownership revisions, role/version |
| Context assembled | Context version/count/size and relevant fact/evidence revisions |
| Model round ended | Round/attempt references, observed provider request ID, model, duration, stop reason, reported usage |
| Tool finished | Tool/call references, duration, typed execution result, source coverage, result count, ranking version |
| Turn finished | Lifecycle result, customer outcome, draft/evidence references when present |
| Reply eligibility decided | Draft reference, expected/current revisions, allowed or suppression reason |
| Output observed | Test adapter observation here; real channel status only when later integration supplies it |

Trace records use opaque scoped references, not names or phone numbers. Routine
exported telemetry excludes raw prompts, customer text, signatures and raw tool
payloads. Detailed synthetic fixtures can be kept separately for teaching and
evaluation. Unknown provider usage is unknown, not zero.

A superseded turn is expected control behavior. It is useful to measure repeated
work and latency, but it should not automatically trigger an infrastructure
failure alert. A failed model round, failed tool and incomplete source have
different error/outcome categories. Preserve durable business state independently
of sampled traces.

## 10. Review and later verification

Review these two traces first. Then use focused cases to verify criteria fidelity,
typed outcomes, current-revision checks and correlated events through the module
interfaces. A synthetic model adapter can supply fixed provider responses for
protocol/control checks; later actual Haiku runs evaluate linguistic behavior.
Passing deterministic fixtures does not prove model quality or live delivery.

Open engineering settings: exact executable schema details, context size,
iteration/retry/deadline values, fragment grouping, store/locking mechanism and
telemetry exporter. Those settings will be selected with measurements, not
inferred from the illustrative IDs or this paper trace. None require reopening
the already accepted brokerage journey to start this slice.
