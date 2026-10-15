# Greenfield conversational harness evaluation

Research date: 2026-10-06. Status: research and proposed design, not an accepted ADR. This report evaluates a new design from the agreed customer journey. Existing Maia implementation, its historical runtime integration, and previous deployment choices are intentionally excluded as evidence. No runtime, provider, library, or database design is selected here.

## What we are deciding

A harness is the software surrounding model inference: it assembles context, advertises permitted tools, interprets model events, executes authorized requests, persists progress, stops or resumes work, and controls which outputs reach the customer. A language model provides conversational reasoning; the harness gives that reasoning an execution environment.

Two decisions should be separate:

1. Who implements the conversational loop: our own narrow loop, an agent SDK, or a larger runtime?
2. Who implements durable business execution and conversation ownership: the product must own those contracts, even if infrastructure delegates their mechanics to a library or workflow engine.

The choice is not simply “Hermes versus harness.” Every option contains a harness. The meaningful comparison is which responsibilities we adopt, which we implement, how easily they can be changed, and how we prove correct operation.

Anthropic distinguishes predefined workflows from agents whose models dynamically choose their steps, and recommends introducing complexity in response to measured needs. This is useful conceptual guidance rather than proof that any library fits Maia. [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)

## Required behavior, independent of implementation

The agreed product needs natural-language understanding, clarification, property discovery, typed tool selection, grounded replies, website and Meta conversations, returning-customer continuity, fragmented-message handling, explicit human takeover/resumption, and future brokerage isolation.

The product backend must decide whether an action is legal and authorized in its current business state. The model may request an appointment; it must not directly write a calendar event, assume availability, mark payment as confirmed, or send WhatsApp messages through an unrestricted credential.

This does not prescribe a dialogue tree. A customer can say “we need a bodega near Tonalá, preferably space for a truck, Saturday doesn't work, what about Monday?” The model can reason conversationally, search, clarify, and suggest a next step. Deterministic checks sit at the point where a request changes business state or creates an external effect.

## A production harness is more than a tool loop

| Responsibility | Proposed owner | Why it exists |
|---|---|---|
| Conversational interpretation and reply drafting | Model | Language flexibility and clarification |
| Context assembly and provider protocol | Harness | Reliable inference inputs and continuation |
| Tool registry and dispatch | Harness | Small, typed capability surface |
| Business authorization and validation | Product | Current identity, policy and state |
| Inbox deduplication and ordering | Product/supervisor | Duplicate and concurrent deliveries |
| Turn lifecycle and output fencing | Product/supervisor | Corrections, crashes and takeover |
| Appointments and external reconciliation | Product | Recoverable side effects |
| Conversation ownership | Product | Prevent competing human/automatic replies |
| Short-term execution checkpoint | Harness store | Resume incomplete work |
| Customer requirements and milestones | Domain records | Correctable durable business facts |
| Final delivery and eligibility | Product outbox | Channel rules and observable outcomes |

These are logical responsibilities, not proposed microservices. A modular application with a background worker may implement them initially. Clear boundaries do not require separate processes.

## Provider contracts: abstraction without losing required state

All three examined providers support calling application-defined tools. Their wire protocols are different:

| Provider contract | Harness implication |
|---|---|
| OpenAI Responses returns function-call items and accepts outputs paired by call ID. Reasoning items may need to be preserved across tool continuations. Strict schema mode has supported-schema requirements. | Preserve complete continuation state, validate arguments and pair outputs correctly. |
| Claude emits `tool_use` blocks and expects correlated `tool_result` blocks inside the message structure. Application errors can be represented as tool-result errors. | Preserve block order and protocol requirements; distinguish a tool error from a successful result. |
| Gemini supports sequential and parallel function calls. Some model/API combinations require opaque thought signatures to be returned intact; official SDKs can preserve these when full responses are retained. | Avoid flattening history into text or discarding opaque metadata. |

Sources: [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling), [Claude tool-call handling](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls), [Gemini function calling](https://ai.google.dev/gemini-api/docs/generate-content/function-calling), [Gemini thought signatures](https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures).

Design inference: use a small domain-facing model port plus a provider-specific continuation envelope. A normalized event stream might contain text deltas, tool requests, completion, usage and errors; normalization must preserve the original provider data needed to continue. A portable business conversation is not the same as portable opaque reasoning state. Switching providers mid-tool-cycle needs an explicitly supported conversion or a fresh run reconstructed from completed business facts.

Schema validity is only structural. `book_visit(property_id, date)` can be valid JSON while targeting a different brokerage, an unavailable listing or an outdated customer request. The tool gateway must bind trusted organization and actor outside model-generated arguments, verify allowed references, and validate business preconditions independently.

Do not allow arbitrary SQL, arbitrary HTTP or shell access merely because a runtime exposes them. Maia needs a finite set of business capabilities. Read-only searches can run in parallel when independent; mutations require explicit dependency and concurrency rules.

## Proposed durable conversation supervisor

This is a design proposal, not a sourced claim that an SDK already implements it.

An incoming event is persisted before acknowledging processing success. Deduplicate on the external message identity within the trusted organization/channel context. Assign an internal monotonically increasing sequence to accepted conversation events. Preserve source timestamps, but do not assume arrival time proves the customer's intended order: late events, quoted messages and corrections need explicit treatment.

Processing claims a conversation lease and builds a turn from an input boundary. Persist a turn identifier, input sequence boundary, ownership epoch, context versions, role, prompt/tool versions, model identity and status. A worker renews the lease; expired claims can be recovered. A lease alone is insufficient: a delayed previous worker may still finish after another worker takes over. Every committing request also carries a monotonically advancing fencing token or version checked by the authoritative backend.

Recommended lifecycle vocabulary: pending, running, superseded, waiting-for-human, completed, failed. External operation state is separate: proposed, accepted, in-progress, confirmed, rejected, outcome-unknown. The distinction prevents “turn canceled” from falsely implying “calendar request did not happen.”

One active automatic speaker per conversation is a useful starting rule. Independent conversations can process concurrently. Separate pursuits inside one conversation share the customer-facing speaker but retain distinct business state. Merely choosing the same session identifier in two workers does not guarantee serialized execution.

PostgreSQL provides row-level and advisory locking primitives; that establishes an available coordination mechanism, not a complete supervisor implementation. Avoid holding database locks across slow model/network calls. Claim short-lived transactional ownership, execute outside the lock, and revalidate before commits. [PostgreSQL explicit locking](https://www.postgresql.org/docs/current/explicit-locking.html)

### Fragments and corrections

A bounded debounce window can group rapid fragments before inference. The window is a product latency decision to measure, not a universal fixed number. Never postpone an answer indefinitely because typing continues.

When a new message arrives during a turn, classify its execution impact separately from its semantic meaning. For an MVP, restarting an unfinished read-only reasoning turn from the enlarged input is easier to verify than splicing a message into a partially completed provider stream. If the message changes a pending booking, mark the old proposal stale and revalidate. A backend mutation must check the expected customer-request/confirmation version, not only the conversational epoch.

Example: Maia is preparing Saturday slots; the customer says Sunday. The earlier draft is discarded, searches can be repeated, and Saturday is not booked. If Saturday has already been committed, the next operation is an explicit modification/cancellation flow with reconciliation; killing generation cannot undo it.

### Cancellation and the last possible check

Provider cancellation, worker cancellation and authorization revocation are different. Request cancellation to save latency and cost, but reject obsolete tool requests and draft delivery even if cancellation arrives late or fails.

Recheck ownership and input version at tool acceptance and at final delivery authorization. Persist the result of an already accepted business command even if its originating conversational turn is later superseded. The next turn should see the real result.

A network request already dispatched to Meta or Calendar cannot necessarily be recalled. Define a visible dispatch boundary: after that point the product records the outcome and handles subsequent correction rather than claiming instantaneous revocation. Holding a row lock during the network request would not make an external provider transaction atomic with the database.

Temporal documents graceful cancellation rather than unconditional immediate termination; Python Activity cancellation normally depends on heartbeat participation. This illustrates why choosing a durable engine does not eliminate cooperative-cancellation design. [Temporal cancellation](https://docs.temporal.io/develop/python/workflows/cancellation)

## Tools, retries and unknown external outcomes

Each mutating product operation needs a server-owned identity independent of the model's provider tool-call ID. A regenerated answer may create a fresh provider call for the same intended booking. Use a durable business command/proposal identity, with a request hash and preconditions, so a retry returns the original outcome rather than creating a second event. Distinct appointments must remain distinct; indiscriminately hashing all identical-looking parameters is insufficient.

An operation ledger should distinguish a recorded intention from an observed external success. If Calendar accepts a booking and the response is lost, “timeout” means outcome unknown, not failure. Recover by looking up a stable external reference or supported idempotency identity. If the adapter cannot establish the result, stop blind retries and surface a reconciliation task.

Proposed rule: read retries may use bounded backoff; transient inference failures may restart safely before mutations; mutating retries only happen under the operation's idempotency/reconciliation contract. A model retry is not permission to repeat a side effect.

A durable workflow engine can recover scheduling and execution progress. It cannot create exactly-once effects in an external service that lacks suitable support. Temporal explicitly recommends idempotent Activities because an effect can finish while its completion is lost and the Activity is subsequently retried. [Temporal Activity idempotency](https://docs.temporal.io/activity-definition#idempotency)

Use business-confirmed outputs in customer replies. Before confirmation Maia may say it is checking availability. It must not stream “your visit is confirmed” before the booking operation is confirmed. Tool results should expose statuses, stable references and actionable conflict reasons, not exception stacks or credentials.

## Human takeover is a product ownership protocol

Three concepts must not be conflated:

1. A model-to-model handoff changes which agent reasons next.
2. Approval pauses a proposed action for a human decision.
3. Broker takeover gives a human responsibility for the live customer conversation and pauses automatic speaking.

The OpenAI Agents SDK documents agent handoffs and resumable human approvals. Those mechanisms are useful building blocks; they do not prove an application has brokerage ownership, synchronized outbound delivery or customer-channel continuity. [Agent handoffs](https://openai.github.io/openai-agents-python/handoffs/), [Human-in-the-loop](https://openai.github.io/openai-agents-python/human_in_the_loop/)

Proposed product-owned record: organization, conversation, mode, assigned broker, ownership epoch, reason, actor and timestamp. An authorized takeover transaction increments the epoch, records the human owner and revokes automatic send eligibility. Queued draft messages carry the old epoch and are suppressed before dispatch. In-flight external sends remain observable reconciliation cases.

During human ownership, customer messages are still ingested and broker messages must also be captured through a supported channel path. Automatic replies and customer follow-up stop; internal reminders or draft suggestions may continue if authorized. An agent can request escalation through a typed tool but cannot invent a broker assignment or resume permission.

Resume is explicit. Increment the epoch again and start a fresh conversational turn with known customer messages and authoritative state. Do not blindly resume the model at a tool request generated before takeover. The 2026-10-08 product decision uses personal broker WhatsApp accounts without required conversation synchronization: the CRM controls “Atención del asesor” and “Reactivar Maia” govern ownership, and confirmed CRM updates supply progress. Do not assume access to the broker's personal messages or require complete transcripts for continuity.

Important unresolved dependency: if a broker replies from a channel whose outbound messages the platform cannot observe, complete conversational continuity is impossible. Channel support and the broker's operating workflow must be verified before promising seamless takeover.

LangGraph provides persisted interrupts and resumption; its documentation also notes that interrupted nodes restart and pre-interrupt code can execute again. That is a runtime behavior to account for, not a broker ownership protocol. [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)

## Memory: five different stores of information

| Memory category | Examples | Proposed treatment |
|---|---|---|
| Durable domain state | Pursuit requirements, shortlisted references, confirmed visits, verified milestones | Product records with provenance and correction history |
| Conversation history | Actual customer and broker messages | Access-controlled chronological record |
| Working context | Current user request, recent turns, tool results | Bounded per-run assembly |
| Summary/preference candidates | Earlier discussion, apparent preferences | Derived, versioned and correctable; never stronger than confirmed facts |
| Knowledge/evidence | Listing details, approved procedural guidance | Retrieved under authorization and freshness rules |

Conversation storage alone is not an effective memory policy. Keeping every message in each model request increases context size and may bury relevant details. Summarization may lose qualifiers or convert an uncertain customer report into a seemingly established fact. These failure risks should be measured with returning-customer cases.

Proposed assembly order: trusted role and allowed capability instructions; authenticated scope and ownership; current business-state projection; current request and recent messages; relevant prior summary with source boundaries; retrieved evidence and completed tool results. Give each evidence item an identifier, observation time, source and authority type.

Persist which input versions informed the turn. When the budget or selected property changes, assemble from the latest domain record and invalidate dependent proposals. A stale summary saying a deposit was paid cannot override a broker record stating verification is pending. “Customer reported payment” and “broker confirmed payment” remain distinguishable.

Context engineering is an ongoing selection problem rather than merely writing a longer system prompt. Anthropic discusses compaction, structured notes and context relevance; these techniques suggest options to evaluate rather than authority for our specific retention policy. [Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

LangGraph separates thread checkpointers from cross-thread stores. The Agents SDK also provides session-backed history. These are persistence mechanisms; Maia must still define provenance, cross-channel identity, retention, consent, corrections and organization access. In-memory persistence does not survive restart. [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [Agents SDK sessions](https://openai.github.io/openai-agents-python/sessions/)

## Roles versus separate agents

Discovery, sales and transaction assistance have different objectives and permitted operations, but share language understanding, property facts and customer identity. A first design can use one conversation supervisor and select a role profile containing instructions, tools and evidence scope. Changing the role does not require a new external conversation or separate service.

A separate specialized agent becomes justified if evaluation shows better performance, different access requirements, distinct execution budgets or substantial specialization. That should be an observed advantage, not a naming consequence. Simultaneous agents competing to answer one customer introduce synchronization work without a demonstrated benefit.

An agent-as-tool pattern can keep a main conversational owner while delegating a bounded task. A handoff pattern transfers reasoning control. Both are documented SDK patterns; neither makes independent workers safe to speak concurrently. [Agent orchestration](https://openai.github.io/openai-agents-python/multi_agent/)

## Streaming and channel adaptation

Website streaming can reduce perceived wait time, but partial text is not a committed business message. Stream transient drafting events associated with a turn identifier; the UI discards superseded events and labels the committed response separately. Avoid emitting confidential tool payloads or internal reasoning.

Meta delivery should use the product's completed-message/outbox path rather than mapping each token into a message. Channel-specific reply windows, templates, formatting, attachment handling and delivery statuses are adapter concerns requiring their own verification. A provider stream ending is not equivalent to successful customer delivery.

Graceful degradation matters: if retrieval fails, state the missing information or escalate; if booking is uncertain, say confirmation is pending; if the model is unavailable, preserve the inquiry for a human rather than silently dropping it. Deterministic fallback messages can acknowledge receipt without pretending to answer the property question.

## Narrow custom loop, SDK, graph or durable engine?

| Approach | What it buys | What Maia still owns | Main risk |
|---|---|---|---|
| Provider SDK plus our narrow loop | Transparent dispatch and exact control | Context, lifecycle, persistence, ownership, recovery | Underestimating lifecycle engineering |
| Lightweight agent SDK | Tool schemas, loop, streaming, sessions/traces, handoffs/approval primitives | Business commands, takeover, inbox/outbox, authorized context | Assuming built-in persistence covers concurrency and side effects |
| Graph runtime with durable store | Explicit state transitions and checkpoints | Node design, tenant policy, tool idempotency, channel protocol | Graph/version/replay complexity and abstraction coupling |
| Workflow engine plus conversational loop | Durable timers, worker recovery, recorded progress | Model adapter, authorization, external reconciliation | Infrastructure and operational burden before it is needed |
| Extracted fork of a larger runtime | Reuse selected upstream behavior | Dependency closure, upgrade/security/testing responsibility | “Small copied loop” still depends on large implicit machinery |

The Agents SDK's own overview describes its loop, tools, tracing, sessions and approvals. Those are documented features, not measured Maia suitability. [Agents SDK overview](https://openai.github.io/openai-agents-python/)

A workflow engine is independent of the model vendor and can coexist with a small loop or SDK. We need durable follow-up timers and reliable side effects; this does not mean every token or tool step needs an expensive long-lived workflow. Decide the necessary recovery boundary first: restarting read-only reasoning may be acceptable, while replaying an untracked booking is not.

Do not choose based on source-line count alone. Extracting a loop requires examining imports, configuration, provider-specific response handling, tool-registration conventions, persistence formats, prompt assembly, cancellation assumptions and tests. Removing a UI or built-in tool surface may shrink packaging while leaving the essential dependency closure intact. This report intentionally does not inspect Hermes; its actual closure belongs in the companion source analysis.

Licensing review must inspect the chosen source and transitive dependencies at the exact candidate revision, preserve required notices, and distinguish library code from bundled assets or models. No specific project's license compatibility is asserted here.

## Operational limits, privacy and isolation

Proposed per-turn controls: maximum model steps, tool calls, tokens/cost, elapsed time and repeated error attempts. Track the reason for stopping and provide a supported human fallback. Bound evidence payloads and read fan-out. A limit should prevent runaway work without converting recoverable conversation into a dead end.

Organization scope must come from trusted routing and credentials, never the model. Scope history, domain reads, evidence retrieval, checkpoints, summaries, traces, queues and operation identities. A shared cache key must include scope and authority/version where relevant. Enforce authorization before retrieving data into context: filtering a generated answer after exposure is too late.

Customer text, partner descriptions and retrieved documents are untrusted content. They cannot promote themselves into system instructions, grant broker privileges or select credentials. Role selection is not sufficient authorization; the backend validates every operation.

Retention and deletion cover derived summaries, vectors if introduced, checkpoints and traces as well as primary conversation rows. Collect the minimum needed for the service and measure observability with synthetic or appropriately redacted records. Provider retention, deployment region and data-use terms need a separate review of the chosen provider/service; they are not settled by selecting an open-source harness.

Keep secrets out of model context and serialized run state. An execution checkpoint is trusted server state; a browser-provided checkpoint must not be accepted as an authorized resume instruction. The SDK's approval guide explicitly warns that restoring serialized run state does not authenticate the snapshot or reviewer. [Server-side approval state](https://openai.github.io/openai-agents-python/human_in_the_loop/#long-running-approvals)

## Evidence needed before an architecture decision

Compare candidates with the same synthetic customer cases and product-tool contracts. Separate conversational quality from execution correctness. Model/role changes and harness changes should be measured independently where possible.

Hard correctness cases:

- Duplicate inbound message produces no duplicate business action.
- Customer corrects Saturday to Sunday before booking acceptance; Saturday is not accepted.
- A delayed worker cannot send after human takeover or newer-turn supersession.
- Broker takeover followed by restart still prevents automatic outreach.
- A calendar timeout after external success leads to reconciliation, not a second visit.
- Website handoff carries authorized context without identity guessing.
- Another organization's known property or conversation identifier is refused.
- A returning customer changes budget; old summaries do not override it.
- Customer-reported payment remains unverified until the responsible human confirms it.
- Provider/model switching does not discard required continuation metadata silently.

Quality and operating metrics: grounded answer accuracy, clarification quality, tool-selection accuracy, task completion, first useful response latency, full-response latency, tool round trips, token cost, broker effort, failure recovery time and truthful status communication. Agree thresholds before testing. This report makes no measured performance claims.

## Provisional conclusion

The greenfield baseline worth evaluating is an owned, narrow conversation supervisor and business-operation protocol, with a replaceable inference loop implemented either directly through a provider SDK or through a lightweight agent SDK. Separate role profiles first; separate agents only when evidence justifies them.

This recommendation does not favor existing code or Hermes. It follows from Maia's required consistency, human ownership and channel behavior, which any runtime must satisfy. The unresolved choice is how much inference/context machinery a candidate runtime usefully supplies without imposing unrelated dependencies or preventing the supervisor contract.

A fork is justified only by demonstrated reusable capability whose replacement cost exceeds the maintained dependency closure and upgrade cost. A custom harness is justified only with an honest budget for recovery and evaluation. A framework is justified only after its actual lifecycle semantics are checked against the same cases.

The next research decisions are recovery granularity; broker channel observability; fragmentation latency; takeover dispatch semantics; long-term identity verification; retention requirements; available approved guidance; expected concurrency; and candidate deployment/resource budgets. None requires coding to articulate. The architecture ADR should follow the evidence rather than declaring a winner from API examples.
