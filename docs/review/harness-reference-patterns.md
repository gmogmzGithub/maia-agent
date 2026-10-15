# Harness reference patterns for Maia

Research date: 2026-10-08. Status: learning material and design proposals, not an
implementation decision. No runtime was executed or benchmarked. This review
uses primary sources outside Hermes and does not infer requirements from the
existing Maia implementation.

## What we mean by a harness

A useful working definition is the runtime around a model: it assembles context,
calls the provider, handles requested tools, supplies their results, controls
continuation, and records enough execution state to diagnose or recover work.
The model proposes a next step; the runtime performs the protocol and admission
checks. The product's business modules decide whether an operation is allowed.

These are related but separate engineering problems:

| Responsibility | Example in Maia | Owner proposed here |
| --- | --- | --- |
| Conversational loop | Ask budget, search, explain three options | Small shared engine |
| Context selection | Include selected property references and recent corrections | Context builder |
| Business operation | Check a property window and the responsible broker's calendar | Scheduling module |
| Durable workflow | Day 18 contact survives a worker restart | Product scheduler and delivery state |
| Human ownership | Broker takes attention through CRM | Product conversation policy |

This table is a Maia proposal. It is not a claim that every reference implements
these boundaries or that these components need separate services.

## Reference 1: simple model/tool loops and explicit workflows

Verified evidence: Anthropic distinguishes predefined workflows from systems
where the model dynamically chooses tools and next steps. Its foundational
article recommends starting with direct APIs and introducing additional
orchestration only when measured benefits justify it. Frameworks simplify
protocol plumbing but may hide prompts and responses. Feedback from actual tool
execution, stopping conditions, and clear tool interfaces are important parts
of the loop. The article now explicitly warns that its 2024 tooling overview is
dated and points readers to newer Managed Agents material. [Building effective
agents](https://www.anthropic.com/engineering/building-effective-agents)

Maia inference: flexible conversation does not require making every business
process autonomous. A model-selected search and a fixed follow-up schedule can
coexist. The schedule remains fixed even though Claude generates the message.
We do not need a planner agent to decide whether Day 18 has arrived.

Tradeoff: a custom loop makes behavior easier to inspect and teach, but its owner
must implement protocol handling, cancellation, limits, and event tracing. A
library removes some mechanical work; it does not remove the need to understand
those mechanics. Start small enough that a developer can trace one request from
arrival to final delivery without navigating a generic orchestration platform.

## Reference 2: context is assembled, not simply accumulated

Verified evidence: Anthropic recommends focused context, small clear toolsets,
and loading relevant information at runtime through lightweight references.
Runtime retrieval adds latency and requires good navigation tools. Compaction,
structured notes, and specialized contexts address longer tasks, each with
tradeoffs; more tokens do not automatically provide better behavior. [Effective
context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

Maia proposal: assemble each request from the role instructions, permitted tool
definitions, authoritative CRM facts, bounded recent exchanges, and relevant
property references. Fetch detailed listing data through a tool when required.
Do not send the whole inventory or treat a model-written summary as inventory
truth.

Example: after showing three listings, preserve their stable references and
display order so “la segunda” is resolvable. Preserve a customer's correction
“mejor hasta cuatro millones” separately from the previous budget. A recent
conversation summary can help continuity, but the booking operation still checks
current stock and calendar state.

Tradeoff: raw recent exchanges preserve wording; structured facts are cheaper to
use consistently; summaries lose detail and can introduce errors. An initial
bounded recent window plus confirmed business facts is simpler than an autonomous
memory-writing subsystem. Seven-day retention is an agreed product setting, not
proof that seven days of messages should fit inside every model request.

## Reference 3: long-running work needs explicit continuity

Verified evidence: Anthropic's long-running coding experiment used an initializer
and subsequent incremental workers sharing structured progress artifacts.
Compaction alone did not reliably preserve progress, and end-to-end verification
was needed before treating features as complete. The authors describe this as
one solution for software-development tasks, not a universally proven agent
architecture. [Effective harnesses for long-running
agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)

Maia inference: copy the principle of explicit progress, not the coding agent's
filesystem or initializer/planner arrangement. An unresolved inquiry, confirmed
visit, broker takeover, and completed follow-up step are structured product
facts. A later request should reconstruct the current situation from these
records without a model guessing what an earlier worker accomplished.

The 28-day follow-up program is long-lived business work made of short runs. It
does not require one Claude invocation, process, or in-memory conversation to
stay alive for 28 days. Each eligible scheduled step loads current state, obtains
a message, and requests delivery. No customer response means no need for a
continuously reasoning agent between scheduled steps.

## Reference 4: separate execution state from current model context

Verified evidence: Anthropic's 2026 Managed Agents engineering describes separate
session, harness, and execution-environment interfaces. A durable session lives
outside a failing harness; the context sent to Claude is a selected or transformed
view of session information. Its design also separates credential handling from
untrusted execution. The authors note that model improvements can make older
harness scaffolding unnecessary. [Managed Agents
engineering](https://www.anthropic.com/engineering/managed-agents)

Maia proposal: distinguish durable business records, bounded conversational
context, and diagnostic operation events. We need not adopt that hosted service,
its append-only transcript model, code sandbox, or distributed topology. The
lesson is to define interfaces so replacing or restarting the engine does not
erase an appointment or expose delivery credentials to the model.

An API timeout illustrates why this matters. Claude may fail while a Calendar
request has already succeeded. Replaying the conversation is not sufficient
evidence that repeating the booking is safe. Product operations need their own
stable identity, observed outcome, and recovery procedure. A humorous general
failure notice must not claim that an uncertain appointment failed or succeeded.

## Reference 5: LangGraph persistence and interrupts

Verified evidence: LangGraph separates thread-state checkpoints from stores for
application-defined information across threads. A checkpointer supports
conversation continuity, paused work, and recovery; a store serves different
longer-term data needs. The distinction is useful even without adopting its data
model. [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)

Verified evidence: an interrupt requires a checkpointer, thread identifier, and
serializable payload; a production pause needs durable persistence. Resume runs
the interrupted node again from its beginning rather than restoring a Python
stack at the interrupt line. Consequently, preceding side effects must tolerate
re-execution or be separated. [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)

Maia inference: graph checkpoints are not a guarantee of exactly-once Calendar
events or WhatsApp sends. A framework can recover execution, while product
idempotency and provider reconciliation handle effects.

Also distinguish two uses of “human in the loop.” Approval asks a person to allow
one operation and then resumes that operation. Broker takeover changes who owns
customer attention: replies and follow-ups must stay paused across future
messages until the CRM explicitly reactivates Maia. A graph interrupt can be a
mechanism inside an implementation; it does not itself define this durable
product policy.

Tradeoff: LangGraph is valuable when explicit branching, checkpointed work, and
resumable review become significant requirements. Adopting it adds graph-state,
node/replay, persistence and migration semantics to learn. A small tool loop with
existing product workflow state may need fewer moving pieces. This is a proposal
for evaluation, not a benchmark that custom code is faster or more reliable.

## Reference 6: pi as readable small-loop source

Verified source evidence: the pi agent loop exposes streamed events and an abort
signal, processes requested tools, checks queued steering/follow-up messages,
and permits preparation hooks around further turns. Its documentation separately
describes transforming application messages into model-facing context. Sources
were inspected at current `main` on the research date; these mutable URLs are
reading references, not a reviewed dependency version. [Loop
source](https://github.com/badlogic/pi-mono/blob/main/packages/agent/src/agent-loop.ts),
[agent package documentation](https://github.com/badlogic/pi-mono/blob/main/packages/agent/README.md)

Maia inference: this is useful to learn the mechanics at a smaller scope than a
whole assistant application. It also demonstrates that a “simple loop” still has
message ordering, tool results, cancellation, and lifecycle events to engineer.
Borrowing ideas does not require adopting its TypeScript runtime or copying its
provider abstraction. Tool execution cancellation is not reversal of an external
effect; newer customer corrections still require product admission checks before
consequential operations and delivery.

## Observability: a loop trace is not the whole business trace

Maia proposal: connect the conversational run to its inbound message, requested
tools, product operations, and outbound delivery using correlation identifiers.
Record model duration/outcome, tool duration/outcome, recovery attempts, state
version, and the reason an operation or response was suppressed. Keep sensitive
message bodies out of ordinary logs; raw recent context and production diagnostics
need different access and retention policies.

A framework checkpoint answers “which execution state can we resume?” A model
trace can answer “which tools were requested?” The product still needs to answer
“was the visit actually booked, was the confirmation delivered, and did broker
takeover suppress a stale reply?” For example, a successful model response with
a failed WhatsApp delivery is not a successfully attended customer.

Inspection is a requirement whether the loop is custom, borrowed, or framework
based. Instrumentation must remain useful when Claude is unavailable: provider
error, recovery outcome, CRM attention task, and fallback delivery should be
observable without asking a model to explain itself. Detailed instrumentation
standards and schemas belong to the separate observability research.

## What to learn before choosing a dependency

Trace one complete request, then examine failures around each boundary:

1. What information enters the model context, and what remains outside it?
2. How does a tool request become an authorized business operation?
3. What is persisted before and after the effect?
4. How are malformed arguments and unavailable tools returned to the model?
5. What makes another model/tool round necessary, and what ends it?
6. What happens if the customer corrects the request while work runs?
7. What happens if a broker takes over just before a reply is delivered?
8. What survives a process crash, and what must be reconciled externally?

Compare our small loop and Hermes using the same authorized tools and realistic
Maia cases. Inspect traces and maintenance effort as well as final wording. Add a
framework, evaluator loop, memory subsystem, or further agent only when a
specific observed failure or engineering requirement justifies it. None of the
sources proves that one library or architecture will perform best for Maia.
