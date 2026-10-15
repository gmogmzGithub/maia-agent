# Harness observability: evidence and proposed Maia contract

Research date: October 8, 2026. Status: research and design proposal, not an
implemented telemetry stack. Observability is an explicit product engineering
requirement. No exporter, dashboard vendor, retention duration or library is
selected here. No customer data, credentials or runtime were accessed.

## What observability must explain

For Maia, a useful investigation is: a customer asked for a house, the engine
searched, a correction arrived, the earlier work became obsolete, a new search
completed and a reply was delivered. We need evidence for each boundary. A log
saying "agent succeeded" cannot establish which customer request was answered,
whether the answer used valid inventory or whether WhatsApp received it.

Recommended distinction:

- Traces show the timing and relationships of execution steps.
- Metrics describe rates, distributions, queues and trends.
- Structured events explain discrete transitions and failure classes.
- Durable business records establish appointments, ownership, command outcomes
  and delivery state. Telemetry is a view of these records, not their authority.
- Evaluation assesses interpretation and answer quality. A successful network
  request and attractive trace do not prove a good answer.

These are proposed application responsibilities, not claims about a vendor.

## Primary-source findings

OpenTelemetry publishes conventions for model operations and agent/tool spans.
The current agent specification is marked Development. Keep instrumentation
mapping isolated and record the convention version; do not treat evolving
attribute names as permanent domain interfaces.
[Agent conventions](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md).

The model/tool conventions support operation, provider/model, tool identity,
usage and related context. They explicitly recommend not collecting instructions,
inputs or outputs by default because they can be large and sensitive. An
application can observe execution without exporting whole conversations.
[Model and tool conventions](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md).

Anthropic supplies request identifiers and typed API failures. The official SDK
has automatic transient retries; a stream can fail after HTTP 200. Instrumenting
only HTTP status or only our outer retry count therefore misses important
behavior. Record the observable SDK/provider attempts where supported, final
stop reason, usage availability and actual application outcome separately.
[Claude API errors](https://platform.claude.com/docs/en/api/errors).

OpenTelemetry describes head sampling as a decision before the complete trace
is available and tail sampling as a decision using completed trace information.
Tail sampling can preserve slow/error traces but adds state and operating cost.
Discarded head-sampled events cannot subsequently be recovered by a tail sampler.
[Sampling](https://opentelemetry.io/docs/concepts/sampling/).

OpenTelemetry recommends minimizing sensitive collection and documents
attribute removal, filtering, redaction and transformation. Hashing predictable
identifiers does not itself guarantee anonymity. Prefer opaque internal
references over phone numbers or customer names.
[Sensitive data handling](https://opentelemetry.io/docs/security/handling-sensitive-data/).

## Proposed execution trace

The following is an illustrative hierarchy, not standard-required span names
or executed output:

```text
process customer inquiry [turn T42]
  claim conversation work
  assemble context [role/prompt/tools/context versions]
  call Claude [attempt/request ID/stop reason/usage]
  execute search inventory [coverage/count/ranking version]
  call Claude [tool continuation]
  validate reply eligibility [current input/ownership version]
  enqueue reply [outbox reference]

dispatch reply [linked to T42]
  send through channel [accepted/failed/unknown]

observe delivery status [linked to delivery reference and T42]
```

Use one trace per bounded processing attempt, with correlation across queued
work. A conversation can span many turns and traces. A 28-day follow-up sequence
is a durable business workflow, not one open tracing span for 28 days. Its due
steps, worker retries and later provider callbacks produce linked traces/events.
An uncertain booking later reconciled by another worker is similarly linked to
the same durable command, not represented as a new unrelated booking.

## Proposed metadata contract

Record fields only when they exist and have a diagnostic purpose:

| Scope | Useful fields | Why |
| --- | --- | --- |
| Work | Opaque conversation, pursuit, inbound event, turn and trace references | Connect relevant work without exporting customer identity |
| Authority | Brokerage scope, actor type, role, ownership/request revision | Explain access and obsolete-work decisions; restrict telemetry access too |
| Reproducibility | Harness build, prompt/tool schema/ranking versions, requested and returned model | Distinguish regressions from changed configuration |
| Context | Message count, context size, evidence references/versions, summary version | Explain omissions and stale evidence without raw content capture |
| Model | Provider request ID, stop reason, elapsed time, attempts, reported usage | Separate provider failures from application failures |
| Tool | Tool name, call reference, duration, structured outcome, source coverage | Explain empty results, conflicts and failures |
| Effect | Durable command/proposal reference, accepted/confirmed/unknown state | Correlate retries with the actual business operation |
| Delivery | Outbox reference, channel, attempt and observed status | Distinguish drafting, provider acceptance and customer delivery |

A provider tool-call ID identifies a model request; it is not the product's
durable command identity. A trace ID is not a conversation ID. Missing usage
means unknown usage, not zero. Do not reconstruct or expose private model
reasoning merely to create an explanation of decisions.

Keep high-cardinality identifiers in access-controlled traces/events. Metrics
use bounded dimensions such as role, tool, source, outcome and model; do not
create a time series per customer, appointment or trace.

## Proposed useful metrics

Measure useful-answer latency from accepted inbound work to the committed
useful answer, then separately measure queue delay and channel dispatch/delivery.
Report distributions and the proportion meeting the provisional 10-second
property and 20-second slot targets. A typing indicator or failure notice is
not a useful property answer. Customer acceptance-to-booking outcome is another
measurement, independent of slot-offering latency.

Suggested initial groups:

- Throughput/backlog: accepted inquiries, pending work age, outbox backlog and
  follow-up due-step delay.
- Engine: completed, failed and superseded turns; model rounds, tool calls,
  bounded-loop exhaustion, retry attempts and reported tokens.
- Inventory: authoritative no matches, incomplete source coverage, external
  outage/refresh age and approved-evidence references.
- Scheduling: offered slots, confirmed visits, conflicts and unknown-outcome
  count/age; reconciliation resolution.
- Control: takeover/resumption events and obsolete output blocked. Blocking a
  stale reply is successful enforcement, not necessarily a system failure.
- Channel: accepted, failed, pending and observed delivered messages. Delivery
  states depend on provider evidence, not a model's wording.
- Quality: reviewed unsupported claims, incorrect criteria, wrong references
  and unnecessary clarifications, with an explicit denominator and review source.

Automated checks can prove reference membership or detect a hard-budget
violation. Semantic fidelity and helpfulness require reviewed cases or a
validated evaluator. An LLM evaluator is evidence to calibrate, not business
truth or a replacement for deterministic invariant checks.

## Failure taxonomy and alerting

Use distinguishable outcomes: no matching stock, missing customer information,
source unavailable, invalid tool arguments, authorization refusal, slot conflict,
provider transient error, protocol error, exhausted execution budget, superseded
turn, unknown remote outcome and delivery failure. Normal clarification or a
legitimate no-match answer should not inflate infrastructure failure rates.

Pilot alert candidates: sustained inability to process inquiries, aging pending
bookings, channel delivery failures, stalled follow-up work and any isolation or
false-confirmation violation. Exact thresholds and alert destination are open.
Do not alert a human on every harmless retry. Do not claim an alert was delivered
until an alert channel and its delivery evidence exist.

## Privacy, recovery and storage tradeoffs

Default proposal: metadata and structured outcomes only in exported telemetry;
no secrets, phone numbers, names, raw customer messages, full prompts, raw tool
payloads or thinking blocks. Synthetic evaluation fixtures can retain complete
protocol artifacts in a separate test environment. Any live diagnostic content
capture needs explicit scope, access and expiry and is not silently enabled by
an instrumentation library.

Maia's seven-day recent-context setting does not automatically define telemetry
or audit retention. Sampling traces must never remove the durable record needed
to reconcile an appointment. Conversely, keeping an audit entry does not justify
retaining the whole conversation forever.

Start with correlated structured events and model/tool/business spans. Full
metadata trace capture may be reasonable at pilot volume if measured overhead
allows it; volume is not established yet. Introduce sampling when necessary,
with explicit failure visibility and aggregate counters. A telemetry exporter
failure should not break an otherwise valid customer operation. Losing a
mandatory durable business/audit write is a different failure and must not be
silently treated as harmless logging loss.

## Proposed small acceptance features

1. One synthetic inquiry produces a correlated trace through search and reply.
2. A model failure produces a fallback and CRM task with an identifiable cause.
3. A correction or takeover explains why obsolete output was blocked.
4. An uncertain booking can be followed from original command to reconciliation.
5. A follow-up due step links to its sequence, generated message and delivery.
6. A fixture containing secret-like strings and personal data proves those
   values are absent from default exported telemetry.

No implementation or live measurements have been performed. Vendor selection
comes after this contract, rather than defining the contract through a dashboard.
