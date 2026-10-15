# Conversational tools: proposed initial contracts

Status: design proposal derived from accepted product workflows. Names and
payloads are illustrative, not implemented APIs. No coding or runtime activation
is authorized. Review this alongside [the shared engine contract](shared-engine-contract.md).

## Responsibilities

The harness runs a bounded conversational turn: assemble relevant context, call
Claude, validate requested tools, dispatch allowed operations, return their
results to Claude and produce a reply. Inventory, CRM and scheduling modules
own their business rules. Channel adapters present replies and structured
references; they do not duplicate business policy.

The product supplies trusted brokerage, conversation, role and actor context.
Tool arguments cannot choose a different brokerage or elevate permissions.
Each operation checks its own authorization even when exposed through a tool.
Credentials and arbitrary SQL are not conversational capabilities.

## Sales tools

| Proposed capability | Input from the model | Authoritative result |
| --- | --- | --- |
| Search inventory | Operation, property type, location, price range, desired characteristics and explicit hard requirements | Bounded ranked listing references, verified facts, differences and source coverage; distinguish authoritative empty results from incomplete source access |
| Read property details | A permitted listing reference | Approved structured facts, description, publication/availability state and customer-facing link; unknown facts stay unknown |
| Record customer requirements | Customer-stated criteria or corrections for the relevant pursuit | Validated stored criteria with source and revision; this is not confirmation of payments or transaction milestones |
| Record property interest | Permitted property references and the customer's expressed interest | Updated pursuit interests/shortlist under the applicable product limits; merely showing a result does not establish selection |
| Offer visit slots | Property reference and requested dates | Actual 60-minute options intersecting the property window and responsible broker calendar; Santiago is responsible by default in the pilot |
| Book confirmed visit | A current offered option and collected customer contact details | Confirmed appointment reference, conflict, refused or pending/unknown outcome; the product verifies the current customer's acceptance |
| Request broker attention | Known request and reason | A CRM task, without claiming human response or changing ownership unless the applicable workflow explicitly requires it |

Explicit customer acceptance is evidence supplied by trusted conversation
processing, not authority created by a model argument such as `confirmed=true`.
Operation identifiers and duplicate prevention belong to the product. Offered
slots are proposals and must be rechecked when booking. Unknown remote outcomes
are reconciled before a consequential operation is retried.

Discovery uses the same inventory and interest operations with its permitted
role behavior. Transaction assistance later adds reads of broker-confirmed
progress and applicable approved guidance. The customer model cannot confirm
transaction milestones, reassign brokers, edit stock or publish submissions.

## Memory

Keep three kinds of information separate:

- Bounded recent conversational context, provisionally retained for seven days
  after the last interaction. Include references needed to interpret phrases
  such as "la segunda"; their availability must be rechecked before action.
- Structured CRM business facts: customer-stated criteria, expressed interests,
  appointments and broker-recorded progress. Model-extracted customer statements
  must remain distinct from broker-confirmed milestones and tool-confirmed effects.
- Necessary execution state for pending operations, revisions and recovery.
  Expiry of recent messages does not resolve an uncertain calendar operation.

Automatically record clearly stated customer criteria and corrections without
another summary-confirmation question. Preserve their source as customer-stated
requirements, distinguish preferences from hard requirements, and clarify
ambiguous interpretation. This does not confirm a booking or transaction fact.

An explicit customer request for Santiago or a human pauses automated replies
and follow-up for that conversation and creates a CRM task for Santiago in the
pilot. Permit one acknowledgement as part of the transition, without promising
immediate availability or claiming that a human has responded. Internal reminders
continue. Humans conduct their conversation through personal WhatsApp and use
"Reactivar Maia" to resume. A failure-attention task alone still does not change
ownership; the explicit customer request is a separate transition reason.

## Recovery and acceptance

Business outcomes such as no matches and slot conflict are normal typed results,
not generic model outages. On unrecoverable conversational failure, the backend
supplies the agreed channel-specific Spanish notice and creates a CRM task.
Uncertain booking uses factual pending-status wording. Human takeover and new
corrections invalidate obsolete work; previously dispatched effects still need
reconciliation.

Later implementation should prove: no unauthorized references reach evidence;
hard requirements cannot be silently relaxed; corrections supersede old criteria;
no visit is confirmed before a confirmed operation outcome; duplicate processing
does not duplicate appointments; fallback does not require a working model.

Exact schemas, context bounds, provider continuation metadata, retry limits and
tool-call limits remain implementation specification and evaluation work.
