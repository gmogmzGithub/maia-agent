# Hermes evaluation for a greenfield real-estate product

Date: 2026-10-06. Source: the current local Hermes checkout, commit `7583a6610ef7226a3dfc1d6721582210d742754a`.

## Scope and evidence limits

This evaluates Hermes against the intended product, independently of existing Maia implementation or earlier runtime versions. The product needs conversational discovery and sales, grounded answers, appointment operations, customer continuity, fragmented-message correction, streaming, explicit human takeover, and eventual brokerage isolation. Durable business records must remain separate from conversational memory.

The investigation read source, package metadata, license and upstream documentation. It did not run Hermes, install dependencies, access credentials or customer conversations, benchmark providers, or change runtime configuration. “Inspected” means visible source behavior; “documented” means upstream describes an interface; neither proves successful production operation.

Product clarification on 2026-10-08: complete transcripts are not an initial
requirement, and personal broker WhatsApp messages need not be synchronized.
CRM controls explicitly pause/resume automation, with confirmed CRM progress
supplying continuity. Hermes persistence remains an available capability, not
an accepted requirement to retain all conversations.

## 1. What Hermes contributes

Hermes has a reusable agent core, `AIAgent`. Its constructor exposes model/provider routing, enabled and disabled toolsets, streaming and tool callbacks, session identifiers, a supplied session database, memory controls, iteration budgets and execution-time budgets. Its simple `chat()` returns text; `run_conversation()` accepts supplied history and returns a structured result. The loop repeatedly invokes provider handling and routes responses either into tool execution or final-response handling. This is useful machinery for clarification, choosing typed operations and composing a grounded response; it does not guarantee the model chooses correctly.

Inspected: [constructor](/Users/el-men/Workspace/hermes-agent/run_agent.py:236), [turn entry](/Users/el-men/Workspace/hermes-agent/agent/turn_facade.py:22), [loop](/Users/el-men/Workspace/hermes-agent/agent/conversation_loop.py:1636). [Official source at the reviewed commit](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/conversation_loop.py#L1636).

Upstream documents provider selection, interruptible model calls, sequential or concurrent tool execution, retries, fallback and compression. These are implementation capabilities to evaluate, not a service-level guarantee. Application-side command authorization, inventory eligibility, scheduling policy, idempotency and delivery reconciliation remain product responsibilities. A model retry must not accidentally repeat a successful booking or outbound message.

Documented: [agent responsibilities](/Users/el-men/Workspace/hermes-agent/website/docs/developer-guide/agent-loop.md:13). [Official agent guide](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/website/docs/developer-guide/agent-loop.md#L13).

## 2. Supported integration boundaries

**Embedding is explicitly documented.** The FAQ says Hermes can be used in a Python project and demonstrates importing `AIAgent` and calling `chat()`. Therefore this is more than an incidental import possibility. However, its link labeled as a Python library guide leads to the code-execution feature page. The inspected material does not establish a dedicated, versioned SDK compatibility promise or a production multi-tenant embedding recipe. Constructor breadth, global tool registries, profile scopes and lifecycle hooks remain integration concerns.

Documented: [programmatic use](/Users/el-men/Workspace/hermes-agent/website/docs/reference/faq.md:109). [Official FAQ](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/website/docs/reference/faq.md#L109).

**A separate backend is also documented.** `hermes serve` exposes a headless JSON-RPC/WebSocket backend for remote clients. This gives an independently supervised process and wire boundary, but introduces authentication, lifecycle, transport failure, reconnection and protocol-version management. It is a broad backend used by other Hermes surfaces; a business product would need an adapter with an explicitly limited contract.

Documented: [server command](/Users/el-men/Workspace/hermes-agent/website/docs/reference/cli-commands.md:1858). [Official server reference](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/website/docs/reference/cli-commands.md#L1858).

Embedding avoids a network protocol but places synchronous execution, threading, teardown and profile binding inside the application process. A service isolates process failure but needs reliable transport semantics. Neither arrangement is automatically cleaner. Both should be assessed using the same customer scenarios and authority boundary.

### Smallest documented interface versus an extracted engine

The smallest documented caller interface is `AIAgent(...).chat(message)`; the more useful integration interface is `run_conversation(...)` plus explicit tools, callbacks, session storage and lifecycle cleanup. This is an interface to the installed Hermes distribution, not a separately declared minimal engine package. Packaging includes `agent`, `tools`, configuration, gateways, scheduler, plugins and providers; root modules such as `run_agent` are added by the wheel build. The declared project version is `0.0.0`. No independent kernel artifact or versioned library compatibility commitment was found in the inspected guides and metadata. This is a bounded finding, not proof that no other upstream document makes such a commitment.

Inspected: [package discovery](/Users/el-men/Workspace/hermes-agent/pyproject.toml:782), [root-module packaging](/Users/el-men/Workspace/hermes-agent/setup.py:76), [close lifecycle](/Users/el-men/Workspace/hermes-agent/run_agent.py:942). [Official packaging source](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/pyproject.toml#L782).

Static import inspection shows material host coupling even before constructing an agent: `run_agent` imports bootstrap/upgrade recovery, resolves the profile home, loads environment files, imports tool orchestration and imports terminal/browser cleanup. Its loop imports prompt construction, compression, metrics, logging, skill-provenance tracking and multiple provider/response phases. Initialization reads shared configuration, resolves the home and calls back through the facade. Passing a `session_db` and disabling memory therefore do not by themselves make the runtime a pure, stateless library.

Inspected: [bootstrap/recovery imports](/Users/el-men/Workspace/hermes-agent/run_agent.py:9), [home/environment/tool imports](/Users/el-men/Workspace/hermes-agent/run_agent.py:91), [loop dependencies](/Users/el-men/Workspace/hermes-agent/agent/conversation_loop.py:20), [initialization dependencies](/Users/el-men/Workspace/hermes-agent/agent/agent_init.py:40). [Official facade imports](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/run_agent.py#L91).

Three choices must remain distinct: configuring a small tool surface in the full runtime; deleting facilities in a maintained fork; and extracting an independently packaged engine with its own configuration, interfaces and regression suite. Only the first uses the existing documented configuration surface directly. The other two take ownership of compatibility and dependency closure. This review inspected representative import edges, not a complete transitive closure, and does not claim all included facilities execute or load on every request.

## 3. Extensions and restricted capabilities

The general plugin interface registers typed tool schemas, handlers and hooks. Registration is associated with a plugin/profile scope; overriding a built-in requires an operator setting. Memory providers have an ABC with initialization, retrieval, turn synchronization and session-end hooks. These are practical extension seams for product operations and, if needed later, explicitly scoped customer recall.

Inspected: [tool registration](/Users/el-men/Workspace/hermes-agent/hermes_cli/plugins.py:456), [memory provider contract](/Users/el-men/Workspace/hermes-agent/agent/memory_provider.py:84). [Official plugin interface](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/hermes_cli/plugins.py#L456).

The constructor accepts per-agent enabled and disabled toolsets, but schemas alone are not authorization. Every operation must validate trusted brokerage and conversation context at execution time. A customer must never acquire broader permissions by mentioning a role, another property identifier or a tool name. A plugin should supply product capabilities without importing privileged credentials or database writes into the model's authority.

Hermes includes general-purpose shell, browser, skills, scheduling, delegation and messaging capabilities. These are optional product behaviors, but disabling tools does not prove their dependencies disappear from the installed package. The appropriate initial surface is a small explicit set of product operations; generic personal-agent powers need a demonstrated requirement before inclusion.

Documented extension policy: [plugin guide instructions](/Users/el-men/Workspace/hermes-agent/plugins/AGENTS.md:5). [Official extension policy](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/plugins/AGENTS.md#L5).

## 4. Three different kinds of memory

**Session continuity:** Hermes persists transcripts through a SQLite-oriented persistence layer with deduplication and filtering. Default storage is profile-aware `state.db`; service sessions may open a dedicated handle for a selected profile. This preserves conversation context and enables resume. It is not a transaction ledger or a substitute for product truth.

Inspected: [persistence layer](/Users/el-men/Workspace/hermes-agent/agent/session_persistence.py:1), [default database](/Users/el-men/Workspace/hermes-agent/hermes_state.py:177), [profile database handle](/Users/el-men/Workspace/hermes-agent/tui_gateway/methods_session.py:87). [Official persistence source](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/session_persistence.py#L1).

**Curated cross-session memory:** Built-in memory and user-profile flags default to enabled. Storage resolves to the profile home's `memories` directory, with `MEMORY.md` and `USER.md`. The system-prompt snapshot freezes at load time. This is profile-scoped memory, not inherently customer-scoped or brokerage-scoped. Sharing one role profile across customers must not be assumed safe for personalized recall. The existence of defaults does not prove that any deployment has written customer information; write exposure and review triggers require separate verification.

Inspected: [default flags](/Users/el-men/Workspace/hermes-agent/hermes_cli/config_defaults.py:1313), [resolved flags](/Users/el-men/Workspace/hermes-agent/tools/memory_tool.py:297), [profile directory](/Users/el-men/Workspace/hermes-agent/tools/memory_tool.py:38), [memory snapshot](/Users/el-men/Workspace/hermes-agent/tools/memory_tool_store.py:187). [Official memory implementation](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/tools/memory_tool.py#L297).

**Business memory:** Budget, confirmed requirements, appointment status, consent, assigned adviser, takeover state and customer identity need typed product records with provenance. Conversational summaries can reference these records, but cannot authoritatively replace them. These are requirements for the new product rather than capabilities supplied by generic file-backed memory.

A sensible candidate configuration explicitly disables shared personal memory and background self-improvement until a customer/brokerage recall contract exists, while retaining conversation continuity. This is a proposal to assess, not an accepted decision or a runtime change.

## 5. Compaction and long conversations

Automatic context management is enabled by default. The base compression threshold is 50%, with model-specific handling; in-place compaction defaults to enabled. Compression prunes or summarizes history to fit model limits. This reduces the need to implement a context manager from scratch, but does not guarantee that a summary preserves every budget correction, consent change or previously offered appointment.

Inspected: [compression threshold](/Users/el-men/Workspace/hermes-agent/agent/agent_init.py:1493), [enablement](/Users/el-men/Workspace/hermes-agent/agent/agent_init.py:1574), [in-place setting](/Users/el-men/Workspace/hermes-agent/agent/agent_init.py:1606). [Official initialization](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/agent_init.py#L1574).

Product facts should be reloaded through authorized tools after compaction. Assessment must include correction retention, resumed sessions, removed availability, and a human takeover occurring while a summary is being generated. Compression calls may use additional provider requests; no cost or latency has been measured here.

## 6. Fragments, corrections, streaming and human takeover

Native `steer()` queues correction text after the current tool batch. `redirect()` can cancel an active model request, preserve completed context and retry with the correction; during tool execution it falls back to steering. `interrupt()` requests stopping the active loop and supports hard cancellation. Streaming and tool callbacks are constructor arguments.

Inspected: [interrupt](/Users/el-men/Workspace/hermes-agent/agent/interrupt_control.py:115), [steer and redirect](/Users/el-men/Workspace/hermes-agent/agent/interrupt_control.py:250), [stream callbacks](/Users/el-men/Workspace/hermes-agent/run_agent.py:251). [Official control implementation](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/interrupt_control.py#L250).

These mechanisms fit fragmented customer messages, but durable fragment ingestion, ordering, deduplication and acknowledgment remain application work. A queued correction is not proof the customer received an updated answer. Streaming speculative prose to a customer before tool-grounding or takeover checks requires a clear release policy.

Human takeover requires a durable product state transition: pause automatic replies and follow-ups, stop or suppress an in-flight response, preserve authorized backend reminders, and define when automation resumes. An agent interrupt cannot undo a delivered message or an already accepted Calendar event. A product must fence operations and reply delivery against the current takeover state, and resolve ambiguous external outcomes independently of the model loop.

## 7. Brokerage isolation

Hermes has profile-aware homes, databases, tool registration and scoped credential access. `get_secret()` documents fail-closed behavior when multiplex scope is required and absent; outside that mode it can fall through to the process environment. These are useful mechanisms, not an organization authorization contract. Profile names, conversation IDs and arbitrary model arguments must not become trusted tenant identity.

Inspected: [credential scope](/Users/el-men/Workspace/hermes-agent/agent/secret_scope.py:219), [profile session storage](/Users/el-men/Workspace/hermes-agent/tui_gateway/methods_session.py:87). [Official scope implementation](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/agent/secret_scope.py#L219).

Future verification must cover concurrent brokerages, customer recall, background work, restart, provider routing and plugin execution. Profile-level separation may be part of a solution, but neither one profile per role nor one profile per brokerage is accepted by this report.

## 8. Footprint, extraction and license

Static counts at the reviewed checkout: 45 base dependency requirement entries and 56 optional dependency groups; 266 top-level Python files under `agent/`; `run_agent.py` has 1,559 lines, initialization 2,526, the conversation loop 1,835, tool orchestration 992 and toolsets 498. These are source/package measures, not loaded-module counts, transitive dependency counts or runtime resource use. The package metadata accepts Python 3.11–3.14, but adjacent comments state active support is 3.14 and older versions exist for upgrade compatibility. Base requirements include browser and server infrastructure as well as model clients.

Inspected: [package metadata and requirements](/Users/el-men/Workspace/hermes-agent/pyproject.toml:5). [Official package definition](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/pyproject.toml#L5).

Extracting “only the loop” would require identifying its imports, provider/error/retry machinery, tool registry, context management, persistence and scope/lifecycle dependencies. The facade-plus-mixins organization helps navigation, but is not proof of an independently distributable minimal kernel. A fork inherits compatibility, security and regression maintenance for retained code; line-count reductions alone cannot establish lower complexity. No extraction closure or effort estimate has been measured.

The repository is MIT-licensed and permits modification and redistribution with preservation of its copyright/license notice; the software carries no warranty. This makes reuse and a fork possible. It does not determine the maintenance choice, and third-party dependencies require their own inventory before redistribution.

Inspected: [license](/Users/el-men/Workspace/hermes-agent/LICENSE:1). [Official license](https://github.com/NousResearch/hermes-agent/blob/7583a6610ef7226a3dfc1d6721582210d742754a/LICENSE).

## 9. Proposal and unresolved evidence

Evaluate unmodified Hermes behind a small conversation contract before considering extraction or a fork. Compare its documented library and service boundaries using the same synthetic tasks. Keep tool authorization, business records, external side effects and takeover enforcement in the product. Explicitly restrict tools and shared memory rather than relying on personal-agent defaults.

The assessment needs: grounded answer quality; clarification correctness; fragment ordering and correction adoption; stop/takeover races; duplicate and ambiguous side-effect recovery; restart and compaction continuity; brokerage/customer isolation; actual streaming behavior; request counts, latency, memory use and cost; dependency/import closure; and the stability of the chosen integration interface. Run these as bounded experiments in a later implementation stage. No benchmark results, runtime activation or architectural decision are claimed here.
