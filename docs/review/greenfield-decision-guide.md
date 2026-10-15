# Greenfield decisions: conversational runtime and information retrieval

Status: research and proposed design, not accepted architecture. Existing Maia
implementation and the previous pinned runtime are excluded as decision evidence.
Agreed product behavior is the basis of this review. No implementation work is
authorized by these notes.

## Read the evidence

- [Hermes candidate evaluation](hermes-greenfield-evaluation.md): inspected
  candidate code, extension paths, memory and control semantics, and fork cost.
- [Custom harness evaluation](custom-harness-greenfield-evaluation.md): model
  loop, durable execution, human ownership, recovery, and provider integration.
- [Retrieval evaluation](retrieval-greenfield-evaluation.md): structured, exact,
  lexical, semantic, and hybrid retrieval with Spanish brokerage scenarios.

## Separate the two decisions

A conversational runtime handles model interaction, tool calls, context, and
turn lifecycle. A retriever selects information. Either can vary independently:
Hermes could call typed catalog tools without a vector index; a custom harness
could use semantic retrieval. Maintaining a fork does not settle retrieval.

Also separate model quality from runtime quality. A capable model can still
receive stale context, execute a disallowed operation, or lose a corrected
requirement through a poor harness. A reliable harness cannot supply an absent
property fact or make an unreliable model understand every request.

## Proposed responsibility split

This is a greenfield proposal inferred from the agreed product behavior.

| Module | Responsibility | Information or action it supplies |
| --- | --- | --- |
| Conversation supervision | Trusted conversation identity, incoming message order, ownership, turn acceptance, durable progress | Whether an agent turn may run and whether its result is still current |
| Conversational runtime | Model interaction, clarification, bounded tool use, context management, composition | Proposed tool calls and grounded responses |
| Catalog and guidance retrieval | Select authorized sources and return current evidence | Listing facts, candidates, unknown facts, approved guide passages and provenance |
| Commercial operations | Validate and persist customer requirements, inquiries, visits, transaction milestones | Authoritative outcomes and business records |
| External delivery | Calendar and messaging dispatch, durable attempt state, retries and reconciliation | Confirmed, rejected, pending or inconclusive external outcomes |

These modules do not imply separate processes, containers, agents, or class
hierarchies. Their interfaces should hide substantial implementation behavior.
Only introduce an additional abstraction where it supports real variation or
concentrates complexity needed by multiple callers.

An incoming message should reach the model with trusted scope and selected
context. Model-requested operations return through product validation. A final
response must pass current ownership and turn checks before publication. Scope
is supplied by trusted routing, never by accepting a model-selected brokerage ID.

## Agent roles versus independent engines

Website discovery, sales, and transaction assistance have distinct purposes but
share customer questions and facts. They can be role-specific instructions and
tool permissions inside one conversational runtime, or independent runtimes if
evaluation establishes a benefit. Neither approach requires agents to negotiate
with one another to answer a property question.

The user-visible continuity belongs to the product conversation. A role change
must preserve the relevant requirements and selections without copying every
historical tool result into a new prompt. A CRM-confirmed milestone can enable
transaction guidance without a model guessing that a payment happened.

## Memory is several contracts

| Kind | Examples | Proposed authority |
| --- | --- | --- |
| Working context | Recent messages, tool results, active question | Ephemeral turn context |
| Conversation history | Customer-visible customer, agent and broker messages | Durable ordered conversation record |
| Conversation summary | Earlier preferences and unresolved questions | Derived context, with provenance; not business authority |
| Customer and pursuit records | Budget, shortlist, visits, intended transaction | Editable product records with source and confirmation status |
| Brokerage knowledge | Approved process guides and property information | Versioned authorized sources |
| Model parameters | General language and reasoning capability | Never the authoritative inventory or customer record |

Product simplification on 2026-10-08: complete transcripts are not an initial
requirement. Retain necessary business records and bounded active context;
history persistence mechanisms in candidate runtimes are capabilities to assess,
not a mandate to archive every message. Personal broker messages are not assumed
available to the product.

Summarizing context does not update a listing price. Remembering an utterance
does not confirm a payment. Personal-agent profile memory is not automatically
an appropriate customer- or brokerage-isolated memory model.

## Human takeover: proposed concurrency contract

The agreed product requirement is to pause automatic replies and customer
follow-ups while a broker controls the conversation, with internal reminders
remaining available. A prompt saying that a human has taken over is insufficient
to enforce this during concurrent work.

Proposed behavior:

1. Persist the new owner and advance a conversation ownership generation.
2. Stop admitting automated customer actions under the previous generation.
3. Request runtime cancellation or interruption to avoid wasted work.
4. Reject stale turn outputs and pending automated dispatch before admission.
5. Identify external operations already admitted or in flight and reconcile
   their outcome; do not imply they were undone by stopping generation.
6. The broker records operational progress in the CRM; personal WhatsApp replies
   do not require synchronization into the product.
7. On “Reactivar Maia”, assemble known context, current owner and confirmed CRM
   state. “Atención del asesor” is the explicit takeover control. Do not invent
   the contents of the broker's personal conversation.

The generation is a concurrency guard, not a substitute for authorization or
operation idempotency. Checks must accompany the execution/dispatch path, rather
than being a one-time check before a slow model call. No database transaction
can atomically roll back a remote Calendar or WhatsApp request already accepted.
The exact dispatch admission and draining policy requires a later design decision.

PostgreSQL offers concurrency primitives that could support this product-owned
protocol; using a durable workflow engine is an alternative to investigate,
not a prerequisite. [PostgreSQL concurrency documentation](https://www.postgresql.org/docs/current/explicit-locking.html).

## Retrieval design by question

Proposed baseline:

1. Extract candidate criteria through typed tools; clarify ambiguous units,
   operations, locations, or hard requirements rather than silently inferring.
2. Apply current brokerage authorization and hard constraints to structured
   catalog data. Compute counts and ranges from actual queries, not nearest
   text chunks or a model's remembered examples.
3. Search eligible own and authorized external stock together, rank customer fit
   first, prefer own listings when suitability is comparable, and deduplicate
   confirmed identities. This updates the original
   fallback-only research premise as of 2026-10-08. If ranking is added, a failed
   query or empty approximate vector result must not be presented as proof that
   no eligible listings exist.
4. For a known listing, retrieve its current authorized facts and approved
   description directly. Missing facts stay unknown under the agreed policy.
5. Retrieve procedure guidance by transaction type and confirmed stage. Start
   with exact guide lookup and a lexical baseline where the corpus warrants it.
6. Evaluate semantic or hybrid retrieval for questions not adequately served by
   that baseline. Adding an embedding index is conditional on measured benefit.
7. Render property cards and links from structured result records. Generate
   conversational explanations from the same evidence and recheck critical
   facts before booking or dispatching time-sensitive claims.

Example: "Tres recámaras, menos de cuatro millones, en Zapopan" calls for
structured constraints. "Un espacio que pueda adaptar como estudio" may require
clarification, explicit amenity tags, text search, semantic retrieval, or a
combination. Similar wording does not establish that the property actually has
the desired feature. A retrieved price description is not a current-price
authority when the source has been superseded.

The original RAG paper combines learned retrieval with generation; that
particular method is narrower than every application that fetches evidence
before generating a response. Define which meaning is intended before comparing
"RAG" with alternatives. [Original RAG paper](https://arxiv.org/abs/2005.11401).

## Proposed evaluation before implementation selection

The following are experimental specifications, not tests that were executed.
Use public-safe synthetic records and conversations. Do not populate this public
repository with real customer data or private property documents.

### Runtime comparison

Compare upstream Hermes and a minimal harness using the same model where the
provider permits equivalent requests, the same tools, the same knowledge, and
the same conversation cases. Document unavoidable prompt/provider differences.
The fork option first needs an extraction feasibility assessment; do not
implement a third full runtime merely to make a three-column benchmark.

| Case | Evidence required |
| --- | --- |
| Customer sends a request in several fragments | Requirements are assembled without duplicate replies or lost messages |
| Correction arrives before an operation | The latest confirmed request governs admission |
| Correction arrives after an external operation | Its actual outcome is explained and an explicit change is proposed |
| Human takeover during generation | Stale output is not newly admitted for automated delivery |
| Human takeover during remote booking | Outcome is reconciled; no false cancellation or duplicate booking |
| Worker or runtime restarts mid-turn | Durable progress supports recovery without duplicated effects |
| Provider timeout after remote success | Inconclusive outcome is resolved rather than blindly repeated |
| Customer returns after a broker conversation | Confirmed CRM progress is included; unobserved broker messages are not invented |
| Role changes from discovery to sales | Selections and requirements survive; permissions remain enforced |
| Another brokerage has similar names and listings | No cross-brokerage evidence, memory, or operations reach the turn |

Measure correct outcomes, intervention rate, context loss, duplicate/rejected
operations, first-useful-response latency, end-to-end p50/p95 latency, model and
tool calls, total tokens, cost per completed journey, and recovery behavior.
Include maintenance surface and integration clarity in the engineering review.
Set numeric performance/cost targets only after a workload and budget are agreed.

### Retrieval comparison

Use queries labeled with eligible results, hard constraints, source scope and
expected answer evidence. Include synonyms in Mexican Spanish, accents and
misspellings, sale/rent ambiguity, exact addresses or references, unsupported
amenities, conflicting old descriptions, and unavailable listings.

Compare structured/exact lookup, lexical search, semantic ranking, and hybrid
retrieval using the same authorized corpus. Measure eligible recall, ranking
quality, hard-constraint violations, current-fact accuracy, correct abstention,
provenance, leakage, update/delete lag, latency, cost and operating complexity.
For final selection, use held-out cases rather than repeatedly tuning to the
same evaluation questions.

Hard invariants are pass/fail requirements. A better relevance score cannot
compensate for unauthorized disclosure, wrong prices, or duplicate appointments.
Retrieval quality and answer quality must be evaluated separately: a relevant
source can still be misquoted or contradicted by generation.

## Open product inputs

- Approximate active listings, source churn and concurrent conversations.
- Initial approved guidance corpus, including length and update responsibility.
- Conversational quality, latency and per-journey cost targets.
- How to handle automated operations already in flight during takeover.
- How to establish duplicate identity and report partial connector failures.
- Whether the independent runtime interface pays for itself with two candidates.

No existing code or prior deployment obligation resolves these choices.
