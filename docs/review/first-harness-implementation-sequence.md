# First harness slice: proposed implementation sequence

Prepared October 9, 2026. Status: delivery proposal derived from the
[accepted first-turn contracts](first-turn-engineering-contract.md). No coding,
provider access or runtime activation is authorized by this document. No feature
below is implemented or verified. The existing no-coding instruction remains.

## Starting scope

Use the sales role, synthetic inventory and an inspectable test surface. A
scripted model adapter exercises protocol/control behavior first; actual Haiku
runs later evaluate conversational interpretation and wording. Synthetic
inventory still passes through the search interface and accepted ranking rules.
Test adapters do not bypass trusted scope, revisions or result pairing.

Each completed feature should produce a customer-visible example and correlated
metadata trace. Trace correlation starts with H1, rather than being postponed
until all the features are complete. Existing runtime and customer data are not
reset as a prerequisite. Eventual implementation uses the repository's supported
runtime; this proposal does not add another startup/deployment path.

## Small features and gates

| Feature | Observable result | Focused completion evidence |
| --- | --- | --- |
| H1 One grounded search | A fully specified synthetic inquiry produces ranked property options through one tool continuation | A/C/B ordering and actual facts; paired tool request/result; hard budget held; context/model/tool/draft trace; synthetic output is not labelled live delivery |
| H2 Budget clarification and continuity | The customer supplies a missing budget and receives options without repeating the house request | Two turns preserve relevant context; criteria distinguish targets from hard limits; no invented budget or redundant summary confirmation |
| H3 Empty and incomplete inventory | No match and source outage produce different truthful answers | Complete empty search gives concise no-match reply; partial coverage cannot make a global no-match claim; unverified external candidates stay excluded |
| H4 Correction during work | A newer budget changes the search and prevents obsolete queued output | New event advances revision; duplicate event does not; old tool may finish without old reply dispatch; post-dispatch correction is subsequent work |
| H5 Bounded failure recovery | A request that cannot complete produces the deterministic notice and an attention request | Fallback works without the model; retries/rounds respect configured bounds; synthetic task outcome is recorded without claiming a live CRM action; generic failure does not switch ownership |
| H6 Explicit human request | Asking for Santiago pauses automatic attention with one acknowledgement | Ownership transition blocks old replies/follow-up; only transition acknowledgement is eligible; internal reminders remain; explicit CRM resumption restores automation; no assumed personal-message synchronization |
| H7 Actual model evaluation | The same fixtures are answered through the selected direct Haiku API | Authorized later environment; criteria fidelity, grounded wording, continuation behavior, useful latency and usage; deterministic adapter results are not represented as model-quality proof |
| H8 Equivalent Hermes comparison | Candidate runtimes are assessed on the same product tasks and tools | Same model where supported; equivalent scope/facts; documented protocol differences, correction/takeover behavior, failure diagnosis and recovery; no full fork required |

H1-H6 are harness behavior gates. Their scripted cases control when corrections
and failures arrive so the tests prove the specific contract rather than relying
on lucky timing. H7 includes actual model variability. H8 informs the final
runtime choice before a larger implementation commitment. Hermes is still a
comparison candidate, not a dependency implied by the sequence.

## Integration boundaries after this slice

The test surface records drafts and attention requests through synthetic
adapters. It does not imply real customer delivery, CRM task creation, Calendar
events or a live EasyBroker connection. Those effects arrive through the staged
inventory/CRM and sales flow in the [product delivery plan](../product/delivery-plan.md).
Durable CRM storage of customer-stated criteria also belongs to that integration.
Keeping criteria in the current synthetic conversation demonstrates continuity,
not persistence across product restarts unless such storage is explicitly added.

Before live integration, replace test adapters at the established seams and
verify authorization, durable state and channel evidence. Passing H1-H8 does not
by itself prove deployment readiness, appointment idempotency or complete provider
eligibility for the follow-up cadence.

## Engineering settings and review

Executable schemas, context bounds, model-round/retry/deadline values, fragment
grouping, state storage and telemetry export require concrete choices during
implementation design. Treat initial limits as named experiment settings and
adjust from measured cases; do not bury them in arbitrary defaults.

For each feature, Guillermo can inspect input, expected output, actual output,
trace and focused contract checks. Stop at a failed gate, diagnose the cause,
and repair that feature before adding the next behavior. Do not implement all
eight and leave validation until the end. No benchmark outcome or target
achievement is claimed by this plan.
