# First harness slice: one grounded inventory search

Status: agreed first design exercise with accepted context, search, lifecycle
and observability contracts. Executable schemas and evaluation settings remain
implementation work. Agreement to this slice does not authorize coding.
Prepared October 9, 2026. No code, provider calls or runtime tests are included.
Read with the [learning guide](harness-engineering-learning-guide.md) and
[tool contracts](tool-contracts.md).
The concrete context, search result, lifecycle and worked correction trace are
specified in the accepted [first-turn engineering contract](first-turn-engineering-contract.md).

## Outcome and scope

A customer asks for a house, receives a necessary clarification, then gets
options derived from a typed inventory tool. A developer can follow the complete
execution through a metadata trace and explain every returned property fact.

The first exercise uses synthetic stock and the sales role, not live WhatsApp,
EasyBroker or Calendar. Existing product policy determines inventory matching;
the harness controls model continuation. Booking, automatic CRM fact writes and
follow-up are later slices. This is a vertical behavior slice, not permission
to scaffold all proposed modules.

## Customer scenario

1. Customer: "Busco una casa en venta en La Estancia, Zapopan, de tres recámaras,
   dos baños y dos estacionamientos."
2. Expected Maia behavior: preserve these preferences and ask for the missing
   budget, without inventing a price range or collecting every optional field.
3. Customer: "Hasta tres millones de pesos mexicanos."
4. Expected Maia behavior: search with MXN 3,000,000 as a hard ceiling. The
   requested room/bathroom/parking counts remain desired targets, not minimums.

For the happy-path exercise use only DEMO-A, DEMO-B and DEMO-C from the
[synthetic evaluation stock](initial-engine-evaluation-cases.md). Specify
complete source coverage for this fixture. Both directly registered and
EasyBroker-sourced listings belong to the same brokerage; Santiago is the
responsible broker by default. These rows are fictional, not market claims.

Expected pairwise ordering: A precedes C when their fit is equivalent and no
preferred price was stated; C precedes B because it better matches three rooms.
Showing B as an alternative requires explicitly saying it has two rooms.
An indicative reply can show A and C and optionally B within the three-option
limit. Exact prose is not an acceptance condition.

## First tool contract

Illustrative tool name: `search_inventory`. This is not an implemented API.

Model-controlled criteria:

- Sale/rental operation and property type.
- Municipality and neighborhood names for validated resolution.
- Currency, price range or maximum, and preferred price only if stated.
- Desired bedroom, bathroom and parking counts.
- Explicit hard requirements, distinct from preferences.

Trusted execution context, supplied outside those arguments: brokerage scope,
actor, conversation, current role and request/ownership revisions. The model
cannot grant itself a different brokerage or permission level.

Authoritative result:

- Outcome and source coverage: matches, authoritative empty or incomplete source.
- A bounded ordered set of listing references and approved links when supplied.
- Verified price/currency, location and characteristic values.
- Match differences and ranking-policy version.
- Source identity/freshness, with unknown facts remaining unknown.

Search owns normalization, eligibility and deterministic ranking. The harness
checks the allowed tool and argument structure, calls the business operation,
and returns its result. Claude explains the result; it does not sort independently
or fill in missing facts from general knowledge.

## Walk the event sequence before implementation

1. Accept and identify the first inbound customer event under trusted scope.
2. Assemble bounded relevant context and the permitted search tool definition.
3. Claude asks for the missing budget; record the completed clarification turn.
4. Accept the budget reply as a new event and reconstruct relevant context.
5. Claude requests search; validate criteria and current execution permission.
6. Execute the synthetic inventory operation and record its typed outcome.
7. Return the correctly paired tool result with preserved provider blocks.
8. Claude composes the property reply from that evidence.
9. Check current request/ownership before committing the reply.
10. Record the reply outcome at the test boundary, without claiming live delivery.

The budget clarification and search reply are two customer-facing turns. The
search turn ordinarily needs a model round requesting the tool and another
round composing the answer. These are continuations, not retries.

## Small acceptance frontier

| Case | Required observable result |
| --- | --- |
| Missing budget | Clarification rather than invented budget |
| Happy-path search | Returned references/facts explain the answer and agreed ordering |
| No suitable stock | Concise no-match reply without pressure to relax requirements |
| Source outage | Incomplete access remains distinguishable from authoritative zero matches |
| Malformed or unknown tool | No unauthorized dispatch; bounded correction or failure |
| Model failure | Deterministic failure notice; later product integration creates the agreed CRM task |
| Correction before reply commitment | Obsolete answer is suppressed and latest criteria govern work |
| Explicit human request during work | Suppress pending automatic answers; the handoff transition permits one acknowledgement and creates Santiago's task; CRM resumption is explicit |

Failure, correction and human-request cases establish subsequent recovery/control slices; the first
exercise traces expected outcomes on paper rather than pretending they run.

## Observability from the first slice

Correlate inbound events, turns, logical model rounds and tool calls. Record
role/model, prompt and schema versions, duration, reported usage when available,
stop reason, sanitized error class, source coverage and reference counts.
Record separate outcomes for clarification, grounded answer, no matches,
incomplete source, failed and superseded work.

No customer phone/name, raw prompts, message bodies, thinking signatures or
raw tool payloads go to default exported telemetry. Synthetic test artifacts
can separately retain complete fixtures and expected evidence. A trace does
not replace business records or prove semantic quality.

## How this becomes an implementation sequence later

The contract and paper traces are accepted. The proposed
[implementation sequence](first-harness-implementation-sequence.md) turns them
into observable small features for later authorized coding. Context size,
model-round/retry limits and concrete telemetry storage remain design/evaluation
choices; no values or libraries are silently selected.
