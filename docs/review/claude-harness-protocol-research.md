# Claude protocol research for Maia's conversational harness

Research date: 2026-10-08. Status: design research, not an implementation or a
benchmark. Sources are Anthropic's current documentation. No credentials, model
requests, customer data or production operations were used. Conceptual traces
below are illustrative and have not been executed.

The chosen baseline is the direct Anthropic API and `claude-haiku-5-5`.
The model identifier is fixed, without a dated suffix or a separate alias.
Haiku 5.5 enables adaptive thinking by default; content can begin with a thinking
block, and its thinking consumes the output token allowance. Its protocol adapter
must select blocks by type. Older fixed-thinking-budget configurations and
assistant prefills cannot be copied unchanged. Omit legacy sampling parameters.
[Haiku migration guide](https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide)

## What a harness owns

A useful Maia harness is an application supervisor around the model. It prepares
authorized context, sends requests, classifies responses, admits tool operations,
records outcomes, continues the conversation, and produces a deliverable reply
or a recoverable failure. A provider SDK simplifies transport and serialization;
it does not establish which brokerage or customer an operation belongs to.

Proposed responsibility split:

| Component | Responsibility |
| --- | --- |
| Claude adapter | Messages, content blocks, tool/result pairing, stream accumulation, provider errors |
| Conversation supervisor | Current turn/version, role, loop limits, cancellation, allowed operations, response readiness |
| Business operations | Inventory authority, assignment, booking policy, follow-up eligibility, CRM facts |
| Delivery and operation records | Send eligibility, external outcomes, deduplication, reconciliation |

This is a logical division within the proposed modular backend. It does not
require separate services or a class for every row. The protocol adapter should
hide provider mechanics without pretending that every provider has identical
history or thinking rules.

## The smallest useful tool loop

Client tools execute in the application. Claude proposes a tool name, argument
object and call identifier. The application returns results in a **user** message,
paired with the original call through `tool_use_id`; there is no separate `tool`
message role. Preserve the complete assistant content containing the calls.
The results must immediately follow their corresponding assistant tool turn,
and appear before any ordinary text in the result message. Errors can be returned
with `is_error: true` rather than fabricated successful output.
[Handle tool calls](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls)

Conceptual search trace:

```text
Customer: casa en La Estancia, compra, hasta cuatro millones

Application -> Claude:
  role instructions + trusted context + available inventory tools + customer text

Claude -> Application:
  assistant content:
    thinking/signature blocks if supplied
    tool_use(id=search_1, name=search_inventory, input=structured criteria)
  stop_reason=tool_use

Application:
  validate arguments, scope the search, execute deterministic matching

Application -> Claude:
  unchanged preceding history
  assistant: exact returned content
  user: tool_result(tool_use_id=search_1, content=verified ranked results)

Claude -> Application:
  text explanation + stop_reason=end_turn

Application:
  check current ownership/turn, then permit delivery
```

Maia's tool names and internal result shapes in this example are proposals, not
Anthropic API fields. Search results should include real quantities and match
differences, so Claude explains what engineering already calculated. Unknown
property facts should remain unknown. A valid model request is neither a
publication decision nor booking authorization.

## Parallel calls are proposed work, not an execution policy

Claude can return several calls in one assistant response. The application may
execute independent reads concurrently or execute calls sequentially. Return all
results together in the next user message, one for every call. If a call is
skipped, return an error result for that identifier rather than leaving it
unanswered. The API does not dictate execution order.
[Parallel tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use)

Proposed Maia policy: allow parallel independent property detail reads; serialize
operations that affect the same pursuit or appointment. A calendar availability
read and a booking write are dependent even if the model proposes them together.
The supervisor should reject or defer the write if its preconditions are absent.
Do not infer safety from the order of blocks or from a reassuring model sentence.

## Typed tools improve syntax; business checks establish authority

Anthropic's strict tool mode uses constrained sampling to produce arguments that
match the supported JSON Schema subset. That is valuable for bounded enums,
required fields and numeric types.
[Strict tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use)

Proposed Maia baseline: strict schemas plus local validation and business
authorization. Schema-valid `property_id` is not proof that the property exists,
belongs to the current brokerage, is published or is available. The actor and
organization should come from trusted request context, not model-controlled
arguments. Tool descriptions tell Claude how to use an operation; they do not
replace checks inside it.

## Stop reasons are control flow

The successful HTTP response includes a reason generation stopped. Relevant
values include `end_turn`, `tool_use`, `max_tokens`, `stop_sequence`, `refusal`
and `model_context_window_exceeded`. `pause_turn` concerns an API-run server-tool
loop and has a different continuation procedure. An empty `end_turn` is possible;
it does not guarantee a useful answer. An incomplete tool call caused by
`max_tokens` needs recovery rather than execution.
[Stop reasons](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons)

Proposed behavior:

| Outcome | Maia behavior |
| --- | --- |
| Complete text, end turn | Check reply/turn eligibility; deliver |
| Complete tool requests | Validate and admit operations; return recorded results |
| Truncation or context exhaustion | Do not publish an incomplete confirmation; bounded recovery |
| Empty customer reply | Detect explicitly; bounded recovery or deterministic fallback |
| Refusal | Handle separately from transport outage; no automatic model switch is selected |
| Unexpected block or stop value | Preserve diagnostic metadata; stop safely until supported |

Maia initially needs its own inventory, calendar and CRM operations. Adding
provider web search or code execution would enlarge both the protocol and the
information authority surface without satisfying a current requirement.

## Streaming is a presentation optimization

Streaming has message and block lifecycle events, deltas and a final stop reason.
Text, tool input and thinking are distinct event types. Assemble by content index,
not by treating every fragment as customer-visible text. SDK accumulation helpers
can construct the final message.
[Streaming messages](https://platform.claude.com/docs/en/build-with-claude/streaming)

Fine-grained tool streaming starts with a placeholder empty input object and then
sends JSON string fragments. The finished input may be invalid or cut off.
Anthropic documents accumulating fragments, parsing after the block closes and
reporting invalid input through an error result. The current option is per-tool
`eager_input_streaming`.
[Fine-grained tool streaming](https://platform.claude.com/docs/en/agents-and-tools/tool-use/fine-grained-tool-streaming)

Proposed baseline: complete responses for the WhatsApp pilot. Later, stream text
to the website when useful, while buffering authoritative appointment outcomes.
Do not execute a booking from partial JSON. Even a complete block is insufficient
if ownership or confirmation changed while it streamed. Waiting for a completed
message makes the first implementation easier to reason about, at the cost of
later first-visible-text delivery.

## Thinking blocks make history a protocol artifact

On Haiku 5.5, retained thinking binds to the preceding conversation. Changing
earlier messages, tools or the top-level system instructions can invalidate that
thinking. The provider documents account-specific behavior and a compatibility
exception for older accounts; design against the strict contract rather than
depending on an account exemption. Append new context instead of silently
rewriting old turns.
[Preserved thinking](https://platform.claude.com/docs/en/build-with-claude/preserved-thinking)

The migration guide additionally says thinking normally arrives with an empty
thinking string and an opaque signature. Pass returned thinking blocks back
unchanged with tool results. Summarized display is optional; it is not a business
audit record or durable customer memory.
[Haiku migration guide](https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide)

Design consequence: two representations are needed conceptually. The active
provider history preserves original block structure; durable CRM facts retain
confirmed requirements, shortlist references and appointments. A plain text
transcript cannot reconstruct opaque provider state. Nor should changing a CRM
budget mutate yesterday's user message: append the correction and update the
current business fact separately. Storage of bounded active context does not
require permanent storage of all conversations.

## Role changes and context reduction must be deliberate

Current Haiku 5.5 supports appended system messages without a beta header.
They have placement restrictions: do not insert one between a tool request and
its result. Mid-conversation tool additions/removals are currently beta. Editing
the original top-level prompt or tools can invalidate cached prefixes and later
thinking. Retrieved third-party content belongs in tool results, not elevated
system messages.
[Mid-conversation instructions and tools](https://platform.claude.com/docs/en/build-with-claude/mid-conversation-system-messages)

Two proposed designs deserve comparison:

1. Continue one append-only protocol segment, append a trusted role change after
   completing tool/result pairs, and use supported tool-change semantics.
2. Start a fresh protocol segment at the role boundary with current verified
   facts and bounded customer context. Do not transplant incompatible thinking.

The first preserves richer continuity but adds provider-feature dependencies.
The second is simpler to inspect but needs explicit reference continuity: “la
segunda” must still map to the second property previously shown. Neither permits
a discovery role to make a booking just because an old tool was visible. Current
backend permission checks remain decisive.

Anthropic distinguishes on-demand signed compaction, threshold compaction and
application-generated summaries. They have different history/thinking contracts.
An ordinary summary cannot preserve the original thinking binding.
[Compaction overview](https://platform.claude.com/docs/en/build-with-claude/compaction)

On-demand compaction currently supports Haiku 5.5 through a beta API. It returns
a signed block that must be replayed unchanged; unfinished tool/result pairs
cannot be compacted. Instructions summarized inside the replaced range cease
applying and may need reestablishment.
[Compaction on demand](https://platform.claude.com/docs/en/build-with-claude/compaction-on-demand)

Retaining recent turns with thinking across signed compaction has additional
binding constraints; use that documented mechanism rather than arbitrarily
splicing a summary before signed blocks.
[Compaction and thinking](https://platform.claude.com/docs/en/build-with-claude/compaction-thinking-blocks)

Proposed minimal baseline: bounded protocol segments and reconstruction from
verified CRM facts at explicit boundaries. Defer automatic compaction until
conversation measurements show a need. Seven-day retention does not imply seven
days of content must fit into every prompt; choose an additional token bound.
Refresh mutable property facts through tools instead of trusting an old summary.

## Provider retries are different from business-operation retries

Anthropic documents HTTP error categories, including rate limits and overload,
and possible streaming errors after HTTP 200. The official SDK retries transient
failures twice by default with backoff and exposes `max_retries`; it honors
`retry-after` when present.
[API errors](https://platform.claude.com/docs/en/api/errors)

Proposed Maia behavior: combine SDK and application retry limits under one turn
deadline. Do not multiply three SDK attempts by several uncounted outer retries.
Use request IDs and sanitized outcomes for diagnostics, not full customer text by
default. Authentication/schema failures need correction, not endless retry.

Conceptual ambiguous booking trace:

```text
Customer confirms a previously offered 60-minute visit.
Claude requests booking.
Maia records an admitted operation with a stable operation key.
Calendar receives creation request; connection drops before the response.
Outcome is unknown, not failed and not confirmed.
Maia reconciles that operation using the adapter's supported lookup/recovery.
Only a verified outcome permits a confirmation or a new attempt.
```

These are proposed product semantics, not a promise that Anthropic's tool-call
identifier provides calendar idempotency. Preserve the admitted business
operation across regenerated tool calls. Read operations can often be retried;
an unknown write requires reconciliation. A customer's newer cancellation cannot
erase an event that might already have been created.

## Observability is part of the protocol contract

Anthropic supplies a `request-id` response header and `request_id` in error
bodies. Python and TypeScript expose `_request_id` on top-level response objects.
Capture available IDs rather than inventing provider identifiers for requests
that never received a response.
[API errors and request IDs](https://platform.claude.com/docs/en/api/errors)

With caching, `usage.input_tokens` is only the uncached input portion. Keep
`cache_read_input_tokens` and `cache_creation_input_tokens` separately; total
processed input is their sum with `input_tokens`. Cache creation can also report
separate five-minute and one-hour token amounts. A cache hit does not mean no
input was processed.
[Prompt caching usage](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)

Thinking contributes to output usage even when thinking display is omitted.
Where returned, `usage.output_tokens_details.thinking_tokens` provides a
reasoning-token breakdown. Do not estimate thinking from the empty displayed
string or add the breakdown to total output a second time.
[Thinking accounting](https://platform.claude.com/docs/en/build-with-claude/extended-thinking)

Streaming `message_delta` usage is cumulative. Store the latest observation,
not the sum of repeated cumulative events. A terminated stream may leave only
partial observed usage; record that accounting is incomplete rather than zero.
Final message completion and HTTP success are separate observations.
[Streaming lifecycle and usage](https://platform.claude.com/docs/en/build-with-claude/streaming)

Proposed observability contract:

- Correlate channel receipt, conversation/turn version, logical model call,
  observed HTTP attempt, tool request, business operation and delivery attempt.
- Record model, role, prompt/tool-schema version, effort, stop reason, timings,
  sanitized error category, provider request ID and reported usage.
- Measure queue time, model time, tool time and delivery time separately. First
  streamed text is not a completed answer or confirmed appointment.
- Distinguish model/tool success from business outcome and customer delivery.
  HTTP 200 can contain a tool request, refusal, empty answer or truncated output.
- Record retries the chosen SDK exposes. If default internal retries are hidden,
  instrument its supported transport hooks or disable internal retries and own
  the bounded policy; do not claim every physical attempt was traced otherwise.
- Avoid prompts, customer text, phone numbers, credentials, signatures and raw
  tool payloads in routine metrics or logs. Authorized short-lived debugging is
  a separate access-controlled mechanism, not an observability prerequisite.
- Keep customer/organization identifiers out of high-cardinality metric labels;
  correlation records can hold scoped opaque IDs with appropriate access.

An opaque thinking signature belongs to resumable active protocol state, not a
dashboard. These proposed fields support failure diagnosis and evaluation without
requiring permanent customer transcripts. No tracing vendor is selected here.

## SDK runner or Maia-controlled loop?

Anthropic's beta Tool Runner automates calls, result wrapping and conversation
state, with an iteration limit and hooks to alter history. The documentation
recommends a manual loop for human approval, custom logging or conditional
execution. Taking over runner history means the application must restore valid
tool/result structure itself.
[Tool Runner](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-runner)

Proposed starting point: official SDK transport and streaming helpers, with a
small Maia-owned supervisor. Evaluate the runner only if its hooks enforce our
admission and outcome contracts without hiding important transitions. Convenience
must not relocate business authority into a callable Python function's decorator.

Human takeover means CRM ownership changes. Before starting a model request,
before a consequential tool operation and before delivery, check the current
ownership/version. An old response must not send after the broker activates
human attention. A canceled network request is an optimization; checking current
authority is the actual safeguard. No provider SDK reconstructs the broker's
personal WhatsApp conversation or knows that the broker took over unless Maia
records and enforces it.

## Small research-to-design exercises

Before implementation, walk through synthetic cases and identify which component
owns each decision:

1. Two parallel detail calls, one fails: produce a complete paired result batch.
2. Search returns no suitable stock: distinguish a successful empty search from
   a provider/tool failure.
3. Truncated booking arguments: execute nothing and recover within the deadline.
4. Broker takeover between tool response and final text: block delivery.
5. Same operation proposed with a new tool ID after an API retry: recover the
   original business outcome rather than creating a second appointment.
6. Discovery-to-sales handoff: preserve shortlist references while preventing
   incompatible prompt/history edits.
7. Expired context: rebuild from permitted facts, ask when an old reference cannot
   be resolved, and refresh property availability.

These exercises are acceptance candidates. They have not passed a runtime test.
Effort, token limits, role-boundary strategy and compaction choice remain design
proposals to measure, not settled requirements. A correct wire loop is necessary;
it is insufficient to prove Maia's conversational quality or operational recovery.
