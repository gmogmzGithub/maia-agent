# Conversation runtime: evidence and open decision

Status: a small Maia-owned harness using a standard model-provider SDK is the
accepted primary design candidate. Hermes remains a comparison candidate; final
implementation selection depends on later evaluation. A fork is deferred unless
a concrete reusable capability justifies extraction and maintenance.
No code changes are authorized in this review.
The October 8 engineering investigation is organized in the
[harness learning guide](harness-engineering-learning-guide.md), with fresh
Hermes source, Claude protocol and observability reports. Observability is an
explicit requirement; instrumentation and runtime selections remain proposals.
Evaluate from agreed product needs, independently of Maia's existing integration,
previous deployment constraints, and previous pinned Hermes version.

## Evaluation basis

The candidate source checkout is `~/Workspace/hermes-agent`. Inspect it to
understand available capabilities and boundaries, not to inherit its defaults
as product requirements. Source observations describe inspected code and do not
select a deployment version.

Begin with the conversation, tool-use, retrieval, isolation, and recovery behavior
the product needs. Existing Maia code is excluded as justification for choosing
Hermes or a retrieval approach.

## Options to evaluate

1. Use upstream Hermes behind a product-owned conversational interface.
2. Use a smaller model/tool runtime that meets agreed behavior requirements.
3. Maintain a fork, accepting responsibility for upstream integration and fixes.

The existence of unused upstream features does not by itself justify a fork.
No specific fork-only requirement has been established. Hermes remains a
comparison candidate, not an accepted permanent architecture requirement.
The comparison should evaluate a product-owned
conversational interface rather than importing runtime-specific concepts into
business policy.

## Retrieval evaluation

Evaluate structured inventory questions, exact property-information questions,
and questions about approved guidance separately. Define representative queries,
permitted sources, freshness, and expected answers before selecting text search,
semantic retrieval, or a combination. No vector infrastructure decision has been
accepted. Runtime choice and retrieval choice are separate decisions.

## Evidence still needed

The initial baseline uses one provider and one capable tool-calling model across
all three role configurations. Use the same model for the harness comparison
where supported. Claude Haiku 5.5 through a hosted API is the selected model
baseline. The Claude API identifier is `claude-haiku-5-5`, verified against the
[official migration guide](https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide)
on October 8, 2026. Direct Anthropic API access is selected. Hermes compatibility and measured results
remain open; documentation availability does not establish account access or
successful integration.

- Runtime defaults for compaction and persistent memory, including isolation.
- Representative conversation quality, latency, cost, and recovery measurements.
- Actual approved guidance corpus and examples that exact or text search cannot
  answer adequately before proposing semantic retrieval infrastructure.

## Accepted conversational behavior

The initial architecture uses one modular backend and one conversational engine
with three role configurations: discovery, sales and transaction assistance.
Discovery and sales use the same Inventory Search business module. These
decisions define responsibilities. The primary engine design candidate is a small
owned harness using a standard provider SDK; final implementation selection and
runtime activation remain deferred.

Automatic input interpretation initially supports text only. Other incoming
formats go to broker attention; transcription is a possible later feature.
Use Mexican Spanish by default, with English when requested or used by the
customer, preserving explicit units, dates and currency.

- Reconcile message fragments and corrections; consequential operations check
  the latest customer confirmation.
- Explicit human takeover pauses automated replies and follow-ups in that
  conversation while backend reminders remain active.
- Persist requirements, shortlist, visits, and open pursuits as editable product
  records. Conversation summaries provide context, not business authority.

## Simplification recorded on 2026-10-08

Human brokers use personal WhatsApp accounts; their conversations do not require
product synchronization or transcript storage. CRM updates remain the source
for operational progress. The CRM controls “Atención del asesor” and “Reactivar
Maia” explicitly pause and resume automatic replies and customer follow-up;
internal reminders remain active.
Complete agent transcripts are not an initial requirement; durable business
records and bounded active conversational context are distinct needs.

Initial property discovery targets typed inventory filters and concise factual
answers. This narrows retrieval evaluation without selecting embedding
infrastructure or model training. Search own and authorized
EasyBroker inventory together, rank customer fit first, prefer own listings
when suitability is comparable, and deduplicate confirmed identities. This
supersedes the earlier external-fallback-only requirement.
