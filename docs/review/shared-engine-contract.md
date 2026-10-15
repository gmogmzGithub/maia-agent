# Shared conversational engine: proposed contract

Status: design proposal. The small owned harness is the primary candidate;
implementation and comparative experiments remain deferred. Claude Haiku 5.5
through the direct Anthropic API is the selected model baseline.

## Inputs

- Trusted brokerage and conversation identity, resolved by the product.
- Current role: discovery, sales or transaction assistance.
- Current customer text and bounded active conversational context.
- Relevant confirmed CRM facts and customer requirements.
- Typed permitted tools backed by product modules.

The product supplies role and authority. The customer's words, retrieved
descriptions and model arguments cannot grant a different scope or role.

## Behavior

The engine assembles role-specific instructions and relevant evidence, invokes
the model, validates tool request structure, and routes requests through the
product's authorized operations. It repeats only while needed and within bounded
execution limits, then composes a grounded reply or clarification.

The same loop serves all three roles. Inventory matching and appointment policy
remain in business modules. Human takeover suppresses obsolete automated work
through product supervision, independently of model cancellation.

Inventory evidence is retrieved through typed product tools, not by inserting
the full catalog into the prompt. Search returns a bounded ranked set with
verified facts and match differences; property detail supplies approved facts
and descriptions on demand. This does not require vector retrieval.

An authoritative empty search receives a concise no-match answer, without
insisting that the customer relax requirements. It remains distinct from a
technical failure or incomplete source access.

For conversational-engine outages, the accepted tone is brief Mexican Spanish,
lightly humorous and professional. Example copy for review: "Maia se tomó una
pausa para comer. No pude completar tu consulta; intenta de nuevo más tarde."
Show a notice on the website and a short message on WhatsApp only when the
current request cannot be completed. The backend supplies the fallback without
depending on a successful model call; actual delivery still depends on channel
availability. Exact copy remains open, without a promised recovery time.
After bounded recovery attempts fail, create a CRM broker-attention task with
the known customer request and failure. Task creation does not itself change
conversation ownership or imply that a broker has responded. Uncertain appointment
outcomes require factual pending-status wording rather than this generic copy.

## Outputs

Observability must correlate model/tool execution with product outcomes and
delivery, without requiring full permanent transcripts. See the proposed
[observability contract](harness-observability-research.md). Runtime traces do not
replace durable business records or prove answer quality.

- Customer-facing reply or clarification.
- Structured listing or appointment references from authorized tool results.
- Turn outcome: answered, needs clarification, needs broker attention, failed,
  or superseded.
- Necessary operational trace and usage, without requiring complete permanent
  conversation transcripts.

Channel presentation is outside conversational reasoning: the website can show
property cards and controls, while WhatsApp can show concise text and links from
the same result records. An appointment reference is confirmed only if the
business operation returns a confirmed outcome.

## Review cases

1. Discovery extracts desired criteria, asks for a missing price range, and
   explains ranked authorized inventory without inventing characteristics.
2. Sales requests valid slots and books only after the current customer
   confirmation; an inconclusive outcome is not reported as success.
3. Transaction assistance reads a broker-confirmed milestone and retrieves the
   approved next-step guidance without confirming a customer-reported payment.
4. A correction or human takeover makes an old pending reply obsolete; an
   external action already admitted is reconciled rather than presumed undone.

These are proposed acceptance cases, not implemented or executed tests.
