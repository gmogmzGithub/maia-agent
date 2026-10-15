# Learning harness engineering from Hermes

Status: source investigation and teaching material, not an implementation decision.
Inspected on 2026-10-08. No Hermes code was executed, installed or modified.

The local clone `/Users/el-men/Workspace/hermes-agent` points at
`7583a6610ef7226a3dfc1d6721582210d742754a`, with the upstream repository
`https://github.com/NousResearch/hermes-agent`. Links below identify that exact
source snapshot for reproducibility; this is not a deployment pin for Maia.

**Verified** means directly observable in the cited source. **Interpretation**
explains why the pattern matters. **Maia proposal** describes a possible design
to evaluate, rather than existing Maia behavior or a new accepted requirement.
Source inspection does not establish throughput, reliability or model quality.

## What a harness does

A harness is the application machinery around a model. It admits work, builds
context, sends a model request, interprets its response, validates and dispatches
requested tools, records results, decides whether to continue, and closes the
turn with an explicit outcome. The model chooses conversational actions inside
that machinery; it does not make the machinery reliable by itself.

Hermes demonstrates a general-purpose harness, not merely a prompt followed by
an SDK call. Its `AIAgent` composes lifecycle, streaming, persistence,
compression, interruption and turn-management mixins. Its constructor accepts
provider, model, toolsets, callbacks, session state and run budgets.
[Verified: agent composition and constructor](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/run_agent.py#L214-L270)

**Interpretation:** understand the responsibilities before choosing a class
structure. Multiple mixins and many files are Hermes implementation choices;
they are not prerequisites for a good Maia harness.

## Trace one customer turn

Consider a synthetic customer asking: “Busco una casa en La Estancia hasta cuatro
millones, con tres recámaras.” Tool names in this example are illustrative Maia
contracts, not Hermes built-in functions.

| Step | Verified Hermes mechanism | Maia interpretation |
|---|---|---|
| Admit | The public turn façade obtains session admission before entering the loop | Avoid two workers independently answering the same conversation |
| Assemble | Build turn context, prepare an iteration, assemble the request and check preflight gates | Supply role policy, bounded recent context, CRM facts and permitted tools |
| Ask model | The inner request loop builds, sends and checks one model response | Ask Claude to clarify, request a typed operation or answer |
| Validate | Tool names, call IDs and argument JSON receive explicit checks | Do not confuse generated JSON with an authorized business command |
| Record request | The assistant tool-call message is persisted before dispatch | Record the attempted operation before a consequential external effect |
| Dispatch | Scope, hooks and guardrails precede actual execution | Business modules enforce inventory scope and scheduling rules |
| Record result | Execution updates message history; persistence failure halts continuation | Feed the model a verified result or explicit failure, not a guessed success |
| Continue | A tool round returns `continue`, and the outer loop calls the model again | Claude explains the three returned properties or asks a clarification |
| Finish | Finalization closes the turn and assembles the outcome | Keep success, blocked work, uncertainty and failure distinguishable |

The façade calls admission at
[turn_facade.py:79](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/turn_facade.py#L79-L88).
The concrete orchestration is visible at
[conversation_loop.py:1576](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/conversation_loop.py#L1576-L1619)
and
[conversation_loop.py:1636](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/conversation_loop.py#L1636-L1692).
The separate API retry loop is at
[conversation_loop.py:1501](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/conversation_loop.py#L1501-L1530).

**Interpretation:** a single customer message can require several model calls.
“Model requested a search → tool returned properties → model explained results”
is ordinary continuation, not a failed request retry. Conflating these counters
makes limits, traces and costs difficult to interpret.

## Tools are a protocol and an authority boundary

**Verified:** Hermes uniquifies tool-call identifiers, checks names against an
allowed set, can repair names, normalizes arguments and checks JSON. An entirely
invalid-name round is returned to the model for correction, with a three-strike
limit. A mixed batch can execute valid calls while returning errors for invalid
ones. Truncated argument payloads are explicitly refused.
[Tool validation](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/turn_tool_validation.py#L72-L185)

**Interpretation:** syntax validation and business validation are different.
`{"property_id":"...","start":"..."}` may be valid JSON while identifying a
property outside the customer's authorized inventory, an unavailable visit,
or an obsolete selection. The model-facing schema is a useful interface, not
the complete trust boundary.

**Maia proposal:** use exact tool names and explicit schema validation; unknown
tools return a controlled error. Do not initially copy fuzzy name repair for
booking or messaging operations. Let the model correct its request. Resolve
organization, customer identity and permission scope from trusted application
context, not model-generated arguments.

**Verified:** Hermes stages and appends the assistant tool-call message, flushes
it before execution, and stops if persistence explicitly fails. It also stops
before further model continuation if a tool result could not become canonical.
[Persist-before-dispatch](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/turn_tool_round.py#L107-L174)

**Interpretation:** this ordering improves recovery evidence but is not an
exactly-once side-effect guarantee. A persisted request followed by a process
crash still requires knowing whether the external operation happened.

**Maia proposal:** distinguish the conversational record from a business
operation record. Calendar creation needs a stable business operation identity
and an explicit state such as pending, succeeded, failed or unknown. A generated
tool-call ID alone should not be the sole deduplication key across re-generated
model attempts.

**Verified:** actual dispatch passes scope blocking, plugin hooks, checks for
compression artifacts in effect-capable arguments, and tool guardrails before
the real operation.
[Dispatch gate](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/tool_executor.py#L684-L750)

## Sequential execution versus parallel execution

**Verified:** Hermes plans segments of parallel-safe calls separated by
sequential barriers. Its dispatcher selects sequential, concurrent or segmented
execution based on that plan; its documented categories include read-only calls,
non-overlapping file targets and opted-in integrations.
[Batch planning dispatch](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/run_agent.py#L1303-L1330)

**Interpretation:** emitting two tools in one model response does not establish
that they are independent. “Find free slots” and “Create appointment” have a
dependency; the second must consume an authorized, current choice. Independent
property-detail reads can have a different policy.

**Maia proposal:** initially run tools sequentially unless an explicit read-only
batch contract allows safe parallelism. This reduces latency optimization
opportunities but keeps ordering, recovery and audit simpler. Add concurrency
where measured latency justifies it, rather than reproducing Hermes's file and
shell scheduling infrastructure.

## Retries need boundaries

**Verified:** Hermes separates its repeated tool loop from a bounded API retry
loop. Its API handler classifies errors using provider, status, context size and
other evidence; exposes retryability and recovery choices; respects interrupts;
and can rebuild context after provider fallback.
[API loop](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/conversation_loop.py#L1501-L1530),
[classification and recovery](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/turn_api_error.py#L82-L221)

**Interpretation:** retrying a model transport request and retrying Calendar
creation are different decisions. Repeating a search may be harmless; repeating
a booking with an unknown first outcome can duplicate the appointment. Retry
counts also do not substitute for a total elapsed-time bound.

**Maia proposal:** keep a model-call attempt limit, a turn iteration limit and a
turn deadline as separate controls. Account for SDK retries in the same total
deadline so nested retries cannot run unnoticed. Do not import all provider
rotation and fallback branches when the pilot uses one direct provider. An
exhausted conversational request uses the agreed backend-generated notice and
CRM task. An uncertain booking instead reports that its outcome is being checked.

Hermes's constructor defaults `max_iterations` to `sys.maxsize`; Maia should
make a deliberate bounded choice rather than inherit that general-purpose
default.
[Constructor default](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/run_agent.py#L237-L243)

## New messages, interruptions and human takeover

**Verified:** Hermes distinguishes three controls:

- `steer(text)` queues guidance after the current tool batch without interruption.
- `redirect(text)` can cancel an active model request, retain completed context
  and continue with a correction; during tool execution it degrades to steering.
- `interrupt(...)` requests stopping the active loop and signals tracked work.

[Steering and redirect](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/interrupt_control.py#L250-L318),
[interrupt state](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/interrupt_control.py#L115-L165)

**Interpretation:** “No, quise decir tres millones” is a correction; “deja de
responder, yo atiendo al cliente” changes business ownership. They need different
handling even if both result in interrupting some computation.

**Verified:** a sequential tool worker is polled for completion, timeout and
interrupt. On interruption it receives a signal and a short grace period; if it
does not finish, its result is abandoned. Shutdown deliberately does not wait
for an abandoned worker.
[Polling](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/tool_executor.py#L865-L886),
[abandonment](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/tool_executor.py#L936-L985)

**Interpretation:** cancellation is a request to stop processing, not evidence
that an external side effect was undone or never happened. The inspected code
itself permits a non-cooperative worker to remain in flight.

**Maia proposal:** human takeover changes durable CRM ownership and increments
a conversation revision. Check that revision before accepting new consequential
operations and before admitting customer delivery. In-flight outcomes still
need reconciliation. A reply composed before takeover must not later be sent
merely because the model finished. These are application responsibilities;
calling `interrupt()` is only one supporting mechanism.

## Memory and compression are separate decisions

**Verified:** Hermes compression prunes older tool results, chooses a middle
window, preserves protected head/tail regions, generates a summary or controlled
fallback, and assembles the resulting context. Finalization sanitizes tool pairs
and reintroduces an in-flight user task when needed. It contains stale-attempt
checks before shared mutations.
[Compression phases](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/context_compressor.py#L5649-L5735),
[protocol cleanup](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/context_compressor.py#L5571-L5582)

**Interpretation:** summary text is lossy conversational context. It is not
authoritative proof of budget, booked visits or payments. A seven-day retention
policy also does not guarantee that seven days of messages fit a model request:
time retention and token budgeting are separate dimensions.

**Maia proposal:** build bounded active context from recent exchanges and verified
business facts. Limit property result sizes and refresh referenced property
details through tools. If summarization later proves necessary, preserve complete
tool-call/result groups and validate continuity through correction and reference
cases. Do not recreate Hermes's extensive long-running, multimodal compression
machinery before observing the need.

## Admission, deadlines and finalization

**Verified:** Hermes has a durable cross-process session lease with refresh,
release and loss handling. Its source explicitly distinguishes renewal from
actual progress: a stalled turn could otherwise renew forever. It also guards
finalization steps independently so a cleanup failure cannot discard the whole
response.
[Lease lifecycle](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/turn_facade_lease.py#L1-L113),
[cleanup isolation](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/turn_finalizer.py#L104-L121)

**Interpretation:** the difficult state is often outside the happy-path model
loop. Two incoming messages, a worker restart, a late tool completion and a broker
takeover can race. A lock in one process alone does not prevent a second worker
from acting after deployment scales to multiple processes.

**Maia proposal:** begin with an explicit admission/ownership contract, not a
specific lease implementation. Review crash recovery and obsolete-worker
behavior before claiming a design is safe. Preserve distinct terminal outcomes
and correlate inbound event, turn, model request, tool request, business
operation and outbound delivery. Do not make a successful model completion
synonymous with successful customer delivery.

## Observability is a harness responsibility

**Verified:** Hermes stamps a model request identifier from the turn and API
iteration, and passes task, turn, session and request IDs into its API error
hook alongside duration, status, attempt count, retryability and classification.
It also provides normalized usage summaries.
[Request identity](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/conversation_loop.py#L1650-L1654),
[error hook payload](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/api_request_hooks.py#L163-L198),
[usage summary](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/api_request_hooks.py#L35-L49)

**Verified:** tool-call references retain task, pairing ID and middleware trace;
terminal hooks expose status, error category and duration. Result commit observes
tool outcome, logs error previews, and can log full result text when verbose
logging is enabled.
[Tool identity and terminal hooks](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/tool_executor.py#L270-L301),
[result logging](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/tool_executor.py#L1054-L1101)

**Verified:** the shared harness-metrics module describes structural categories
such as error recovery, loop guards and bad model replies. Its recording is
opt-in and exceptions do not propagate into the caller. This is a different
surface from detailed lifecycle hooks, which can include request and response
bodies. Hook sanitization redacts recognized secret-key names and caps payload
size; it does not establish general customer-data removal.
[Metrics behavior](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/hermes_cli/observability/shared_metrics_harness.py#L1-L46),
[hook sanitization](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/api_request_hooks.py#L15-L160)

**Interpretation:** available hooks do not establish an installed collector,
working dashboards, delivered telemetry or production measurements. A completed
model request, completed tool dispatch, confirmed Calendar operation and
delivered WhatsApp answer are four different outcomes.

**Maia proposal:** instrument the harness from its first experiment. A trace
should connect inbound message → admitted turn → model attempts → tool attempts
→ business operation → outbound delivery. Record timing, model/role, bounded
usage, retry classification, tool result status, conversation revision and
terminal reason. Keep business success explicit: `visit_confirmed` requires
verified scheduling evidence, not merely a tool response without an exception.

Default operational telemetry need not retain conversation text. Store IDs,
categories, durations and counts; keep approved business facts in the CRM under
its retention policy. Any temporary diagnostic body capture requires explicit
scope, redaction and expiry. Errors and uncertainty should be visible without
copying customer messages into permanent logs. Observability collector failures
should be distinguishable from mandatory business audit/persistence failures;
the former should not silently masquerade as the latter.

## What to borrow, what to defer

| Borrow as an engineering responsibility | Do not copy without a demonstrated need |
|---|---|
| Explicit request → tool → result → continuation loop | Broad shell, filesystem and computer tools |
| Complete protocol records and controlled failure results | Provider-specific repairs and every fallback route |
| Separate retry, iteration and elapsed-time limits | Unlimited iteration defaults |
| Admission, interruption and obsolete-work checks | Desktop/terminal scheduling machinery |
| Context budgets and complete tool-pair preservation | Extensive multimodal compression pathways |
| Persistence before consequential dispatch | Autonomous profile memory and skill learning |
| Traced terminal outcomes and isolated cleanup | General-purpose delegation and task-board machinery |

The right lesson is not “copy a small number of Hermes files.” Its core class
delegates into helpers that themselves depend on other runtime services, hooks
and state. The inspected façade, dispatch and finalizer imports demonstrate this
coupling. A lightweight fork needs dependency analysis, not deletion by directory
name. An owned harness can implement the smaller responsibility set while using
Hermes source as a catalogue of failure modes to test.

## Teaching exercises before implementation

1. Draw the exact state changes for search → results → answer, naming every
   model call and every persisted business fact.
2. Repeat for appointment creation when Calendar accepts the request but the
   response times out. Identify what is known and what is uncertain.
3. Insert a budget correction while search is running. Explain which completed
   work can be reused and which answer is now obsolete.
4. Insert human takeover immediately before outbound delivery. Explain the
   authoritative check that prevents a late automated answer.
5. Remove old context while the customer refers to “la segunda.” Explain how
   the shortlist's stable identifiers survive without a permanent transcript.

These exercises establish the design's invariants. Only then should a bounded
experiment compare the owned harness and Hermes with equivalent authorized
tools and the same selected model where supported. This source snapshot does
not establish support for a subsequently released model or guarantee equivalent
provider protocol behavior; verify that in the experiment.
