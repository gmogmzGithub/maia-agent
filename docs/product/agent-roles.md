# Agent roles and shared conversational engine

Status: accepted product and architectural shape; implementation design remains
deferred. Claude Haiku 5.5 through a hosted API is the selected initial model;
runtime implementation and model training remain deferred.

The initial product has one conversational engine with three role configurations:

| Role | Primary responsibility |
| --- | --- |
| Website discovery | Present and compare inventory and maintain the relevant shortlist |
| Sales | Answer grounded property questions and help the customer arrange visits |
| Transaction assistance | Explain approved next steps for broker-confirmed transaction progress |

Each role receives appropriate instructions, relevant customer and business
context, and permitted tools. Both discovery and sales answer property questions.
All three roles initially use one provider and one capable tool-calling model.
Role-specific model choices require measured quality, latency or cost benefit.
Compare the owned harness and Hermes with the same model where supported;
record any unavoidable provider/protocol differences. The selected baseline is
Claude Haiku 5.5 through a hosted API for all three roles. The Claude API model
identifier is `claude-haiku-5-5`, verified against the
[official migration guide](https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide)
on October 8, 2026. Direct Anthropic API access is selected for the pilot.
Account access and measured fitness for Maia remain to be established.
Roles do not require separate runtimes or agents negotiating a handoff. Product
state and trusted routing determine available capabilities; role instructions do
not independently grant business authority.

The customer relationship and business records preserve continuity when the role
changes. Full conversation transcripts are not an initial requirement. The
engine's context assembly and short-term persistence remain implementation work.
The accepted provisional pilot policy retains bounded recent conversation
messages for seven days after the last interaction. Confirmed requirements,
selections, appointments and next steps remain separate CRM business records.
After recent context expires, continue from known facts and clarify references
that can no longer be resolved. This is not a retention rule for all CRM data.

Search once operation, property type, location and budget are sufficiently clear.
Initially present up to three useful options, then ask one useful narrowing
question. Clarify material ambiguity before searching rather than requiring
every optional characteristic up front.

## Shared inventory search

Inventory Search is a business module used by discovery and sales. It accepts
customer criteria and returns ranked authorized properties, verified facts and
explanations of differences from the request. It owns the agreed source,
deduplication, price, neighborhood and ranking policies, independently of reply
composition. The model interprets the request and explains the resulting evidence.

Search uses synchronized authorized external stock for discovery, with external
revalidation before bookable options. Connector outages must remain distinct
from zero search matches; verified own inventory stays available.

## Initial inputs and languages

The first version automatically interprets text. Voice notes, images and
documents remain available for broker attention without a promise of automatic
interpretation. Voice-note transcription can be evaluated as a separate later
feature based on pilot demand.

Maia responds in Mexican Spanish by default and in English when the customer
uses or requests it. Currency, measurements, dates and local terminology must
remain explicit in either language.

Typed operation details, runtime lifecycle, and the choice between Hermes and a
smaller harness remain open. Supporting future modalities does not select an
initial media-processing pipeline.

## Delivery priorities

The first complete flow is WhatsApp inquiry, requirement clarification,
inventory search, grounded options, and a confirmed visit with the responsible
broker. Minimum CRM and inventory features arrive alongside it. Follow-up
automation and the conversational website extend the same foundation.

Valuation is a separate later stage, after the initial sales-and-visit flow is
validated. It needs its own data, methodology and evaluation. The primary
conversational design candidate is a small Maia-owned harness with a standard
provider SDK; Hermes remains a comparison candidate until evaluation settles
implementation selection.
