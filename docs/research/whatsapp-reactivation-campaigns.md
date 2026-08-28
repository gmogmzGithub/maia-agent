# Meta WhatsApp requirements for reactivation and campaigns

Status: implementation research, not legal advice or an architecture decision
Verified: 2026-08-28
Method: public, unauthenticated review of first-party Meta and WhatsApp policy,
product, API, SDK, and 2026 marketing-guidance sources. No WhatsApp Business
Account, phone number, template, credential, or real Contact was accessed.

## Conclusion

A Maia reactivation message about a newly matching Listing and a Campaign
announcement for a Development are **marketing**, not customer service. Meta
describes marketing messages as awareness, sales, retargeting, offers, and
related product suggestions. A user message instead opens a 24-hour customer
service window for replies; it does not turn a later campaign into service or
prove marketing consent. [WhatsApp Business Platform
pricing](https://whatsappbusiness.com/products/platform-pricing/), [WhatsApp
Business Messaging Policy, sections 1-2](https://whatsappbusiness.com/policy/)

The defensible Stage 7 boundary is therefore:

> Product may plan and preview fake-backed reactivation and Development
> campaigns, but a real recipient is eligible only when Product can prove the
> recipient's applicable marketing opt-in, absence of suppression, current
> audience reason, exact approved Meta marketing template and language, current
> provider/account health, and Larevia's own conservative timing and frequency
> limits. Any unknown or changed fact denies the send.

Meta approval is live provider state, not a local Administrator assertion. Meta
may review, approve, pause, or reject a template at any time, and only an
approved template can initiate a conversation. [WhatsApp Business Messaging
Policy, section 2](https://whatsappbusiness.com/policy/)

At this research checkpoint Maia has not authenticated to a real Meta account,
so it has **zero verified real templates**, **zero verified account messaging
capacity**, and **zero provider-confirmed quality state**. The repository also
records that the pre-Stage-7 approved-template registry is empty and marketing
consent capture has not been activated. [ADR-0045](../adr/0045-gate-every-outbound-message-on-product-eligibility.md)

## Confirmed Meta and WhatsApp facts

### Permission and opt-in

WhatsApp permits a business to contact a person only when the person provided
their mobile number and gave opt-in permission to receive subsequent messages or
calls. The business, not WhatsApp, is responsible for choosing the opt-in method,
providing the required notices, and complying with applicable law. [WhatsApp
Business Messaging Policy, section 1](https://whatsappbusiness.com/policy/)

The current first-party marketing guide adds three requirements for an expected
message: obtain opt-in in advance, clearly say that the person is opting in to
messages, and clearly identify the business whose messages they will receive. It
also says the opt-in should reflect the kinds of messages intended, promotional
consent should not be bundled with transactional communications, and the flow
should be clear and intuitive. [WhatsApp, *Best Practices for Marketing Messages*,
pp. 19-21](https://whatsappbusiness.com/wp-content/uploads/2026/04/Best-Practices-for-Marketing-Messages-on-WhatsApp-.pdf)

The same 2026 guide says a separate "WhatsApp-specific" consent is no longer
required and lists possible collection settings such as a website, in person,
during a transaction, a service call, a click-to-WhatsApp ad, a QR code, or a
WhatsApp thread. That change does **not** eliminate advance opt-in, identification
of the business, clarity about message type, or local-law compliance. [WhatsApp,
*Best Practices for Marketing Messages*, pp. 19-22](https://whatsappbusiness.com/wp-content/uploads/2026/04/Best-Practices-for-Marketing-Messages-on-WhatsApp-.pdf)

Consequences for Maia:

- A phone number, an inbound property inquiry, an appointment, an old
  Opportunity, a confirmed Property Need, or silence after earlier contact is
  not by itself evidence of marketing opt-in. This is the fail-closed inference
  from Meta's separate number-plus-opt-in requirement.
- A real consent record needs evidence of the collection event and the text the
  Contact saw. Fields such as business identity, message scope, channel, source,
  timestamp, notice version, evidence locator, and revocation time are proposed
  Maia audit fields; Meta does not prescribe this database schema.
- Until the approved Larevia collection path and its evidence are configured,
  `MarketingConsentMissing` remains the correct outcome.

### Opt-out and suppression

The business must honor every request, made on or off WhatsApp, to block,
discontinue, or opt out of WhatsApp communications, including removal from its
contact list. Meta also says communications must not confuse, deceive, mislead,
spam, or surprise people. [WhatsApp Business Messaging Policy, section
1](https://whatsappbusiness.com/policy/)

Meta's opt-in best practices recommend clear instructions for opting out of
specific categories and clear, intuitive opt-in and opt-out flows. The official
Cloud API template example includes a `Stop promotions` quick reply and matching
footer, demonstrating one platform-native implementation but not making that
exact English phrase mandatory. [WhatsApp Business Messaging Policy, “Best
Practices for Opt-In”](https://whatsappbusiness.com/policy/), [Meta official
Postman collection, template list example](https://www.postman.com/meta/whatsapp-business-platform/request/hl0hxc0/get-all-templates-default-fields)

Consequences for Maia:

- A campaign-time opt-out or suppression must prevent every not-yet-requested
  send and must also be rechecked immediately before provider delivery.
- A broad request such as “do not contact me” must not be narrowed silently to
  one campaign. A clearly category-specific request may be represented as a
  category suppression only if the approved Product policy preserves the
  person's expressed scope.
- A reply stops the generic sequence. Product may continue only as a response to
  the new message or after a new, separately eligible decision; it must not let
  the campaign race ahead of the inbound event.

### Approved templates, category, and language

Business-initiated conversations may start only with an approved Message
Template, used for its designated purpose. Outside the customer-service window,
only approved templates may be sent. Meta reserves the right to review, approve,
pause, and reject templates at any time. [WhatsApp Business Messaging Policy,
section 2](https://whatsappbusiness.com/policy/)

The Business Management API exposes the WABA's templates through
`GET /{WABA-ID}/message_templates`. Meta's official example returns each
template's provider ID, name, components, language, status, and category; its
marketing example is explicitly `APPROVED` and `MARKETING`. [Meta official
Postman collection, `GET message_templates`](https://www.postman.com/meta/whatsapp-business-platform/request/hl0hxc0/get-all-templates-default-fields),
[Meta official Postman workspace](https://www.postman.com/meta/whatsapp-business-platform/documentation/wl)

Meta's current generated Business SDK enumerates template statuses including
`APPROVED`, `ARCHIVED`, `DELETED`, `DISABLED`, `IN_APPEAL`, `LIMIT_EXCEEDED`,
`PAUSED`, `PENDING`, `PENDING_DELETION`, and `REJECTED`; it also exposes quality
filters `GREEN`, `YELLOW`, `RED`, and `UNKNOWN`. [Meta Business SDK source,
commit `788f363`](https://github.com/facebook/facebook-python-business-sdk/blob/788f363d15b1269ab5efb7cd00fb5e3b133cd99b/facebook_business/adobjects/whatsappbusinessaccount.py#L913-L963)

The send operation identifies a template by name and an explicit language code.
Meta's Cloud API SDK documents deterministic language selection as the supported
policy, and Meta's marketing guide instructs API users to submit the same
template name separately for each intended language. [Meta official Postman
Cloud API documentation](https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api?entity=request-13382743-f2eb9575-f109-4767-ab47-4cf74c14444f),
[Meta-hosted WhatsApp Node.js SDK language object](https://whatsapp.github.io/WhatsApp-Nodejs-SDK/api-reference/types/language_object/),
[WhatsApp, *Best Practices for Marketing Messages*, p. 34](https://whatsappbusiness.com/wp-content/uploads/2026/04/Best-Practices-for-Marketing-Messages-on-WhatsApp-.pdf)

Consequences for Maia:

- The registry key must preserve the WABA, Meta template ID, name, language,
  category, components or checksum, status, quality signal, API version, and
  observed time. These are proposed Product fields derived from provider facts.
- Only current `APPROVED` + `MARKETING` + exact intended language is usable for
  Stage 7. `PENDING`, `PAUSED`, `DISABLED`, `REJECTED`, deleted/archived states,
  unknown values, missing fields, stale evidence, and provider read failures all
  deny.
- Maia must not translate an approved template locally, substitute a generic
  Spanish template for an unapproved conversation language, or infer approval
  from a template name. If no approved template exists in the intended language,
  no proactive message is sent.
- A provider status webhook can invalidate the cache. Meta's official webhook
  schema includes `message_template_status_update`; activation and each delivery
  batch should still refresh provider truth so a missed or reordered notification
  cannot make a local approval authoritative. [Meta official Postman webhook
  schema](https://www.postman.com/meta/whatsapp-business-platform/request/j09tht8/components)

### The 24-hour customer-service window

WhatsApp allows a business to reply without a template within 24 hours of the
last user message. The pricing documentation says each new user message resets
this customer-service window. Outside it, the Business Messaging Policy permits
only approved templates. [WhatsApp Business Messaging Policy, section
2](https://whatsappbusiness.com/policy/), [WhatsApp Business Platform
pricing](https://whatsappbusiness.com/products/platform-pricing/)

This window is a permission to **respond**; it is not a waiver for an unrelated
Development campaign. Stage 7 should always classify reactivation and campaign
content as Marketing and use its approved Marketing template, even when a
customer-service window happens to be open. That is a conservative Maia policy
derived from the message's purpose.

If automation responds during the 24-hour window, Meta requires prompt, clear,
and direct escalation paths such as in-chat human transfer, phone, email, web
support, an in-person location, or a support form. [WhatsApp Business Messaging
Policy, section 2](https://whatsappbusiness.com/policy/)

### Frequency, quality, and delivery limits

WhatsApp does not publish one universal safe campaign frequency or quiet-hours
schedule in the reviewed material. Its first-party guidance instead says messages
should be expected, timely, and relevant; businesses should decide when and how
often their own customers want contact and consider times when people may be
offline. [WhatsApp, *Best Practices for Marketing Messages*, pp. 18 and
22-23](https://whatsappbusiness.com/wp-content/uploads/2026/04/Best-Practices-for-Marketing-Messages-on-WhatsApp-.pdf)

The platform applies its own quality and integrity controls. Meta says user
blocks and reports contribute to quality, sustained low quality can limit the
amount a business may send, and unauthorized messaging at scale can lead to
limited or removed access. [WhatsApp Business Messaging Policy, section
7](https://whatsappbusiness.com/policy/)

The 2026 marketing guide is explicit that a marketing template message may not
be delivered because of user blocks, spam filters, template pausing after high
negative feedback, or per-user marketing-template limits. It does not publish
the numeric per-user threshold. [WhatsApp, *Best Practices for Marketing
Messages*, pp. 45-46](https://whatsappbusiness.com/wp-content/uploads/2026/04/Best-Practices-for-Marketing-Messages-on-WhatsApp-.pdf)

WhatsApp Manager exposes phone-number status, quality rating, messaging limit,
and a 30-day quality history. Template surfaces expose template status and
quality, delivered/read metrics, and top block reason. The guide recommends
gradual volume ramp-up and monitoring warnings over 7-10 days. [WhatsApp, *Best
Practices for Marketing Messages*, pp. 37-41](https://whatsappbusiness.com/wp-content/uploads/2026/04/Best-Practices-for-Marketing-Messages-on-WhatsApp-.pdf)

Consequences for Maia:

- Provider limits are an additional refusal/throttling layer, not Larevia's
  frequency policy. Stage 7 still needs versioned Product caps per Contact,
  channel, and campaign plus conservative quiet hours chosen by the business and
  legal reviewers.
- A plan cannot promise delivery merely because a template is approved. Unknown
  account health, low/unknown quality, a provider warning, exhausted account
  capacity, or a template transition must pause new requests and appear in Admin.
- `Sent` is not `Delivered`. Meta's official webhook reference provides sent,
  delivered, and read updates and warns that notification arrival order may not
  match event timing; results should preserve provider timestamps and never
  manufacture delivery/read outcomes. [Meta official Postman message-status
  webhook](https://www.postman.com/meta/whatsapp-business-platform/request/rgtfq23/message-status-update-notifications)

### Data, identity, and audience restrictions

Meta makes the business responsible for the notices, permissions, and consents
needed to collect, use, and share personal information, including a published
privacy policy and compliance with applicable law. Data obtained from Meta about
a person may be used only as reasonably necessary to support messaging with that
person, and information from one customer chat may not be shared with another
customer. [WhatsApp Business Messaging Policy, section
3](https://whatsappbusiness.com/policy/)

The business profile and support details must be accurate. A business may not
impersonate another entity, misrepresent its affiliation, or speak in another
business's voice without permission. [WhatsApp Business Messaging Policy,
section 1](https://whatsappbusiness.com/policy/)

WhatsApp also prohibits wrongful discrimination or preference based on protected
personal characteristics including race, ethnicity, national origin,
citizenship, religion, age, sex, sexual orientation, gender identity, family or
marital status, disability, and medical or genetic condition. [WhatsApp Business
Messaging Policy, section 4](https://whatsappbusiness.com/policy/)

Consequences for Maia:

- A Stage 7 audience may use confirmed real-estate needs and explicit consent;
  it must not segment or exclude by protected characteristics or proxies chosen
  for discriminatory treatment.
- Audience preview/export, logs, and metrics should use Product IDs and aggregate
  counts, not phone numbers or chat content. This minimization is Maia policy
  supporting the platform data restrictions, not a Meta-defined export schema.
- Larevia must prove its authority to promote each Development and its affiliation
  to the represented business. A Listing or Development record alone cannot
  supply that authorization.
- Meta may change the Business Messaging Policy without notice where law permits,
  so the policy review date and account/template observations must be operational
  evidence, not a one-time migration constant. [WhatsApp Business Messaging
  Policy, section 7](https://whatsappbusiness.com/policy/)

## Recommended fail-closed provider contract

This is a Maia design derived from the verified facts above, not a Meta-prescribed
interface.

```text
MetaTemplateCatalog.refresh(waba_id, at)
  -> TemplateEvidence[] | Unavailable

TemplateEvidence
  provider_template_id
  waba_id
  name
  category
  language
  status
  quality
  component_checksum
  provider_api_version
  observed_at

MarketingEligibility.evaluate(contact, purpose, template, at)
  -> Eligible | Denied(reason, evidence)
```

The registry should ingest provider reads and webhook invalidations, but it must
never expose a local “approve” operation. `Campaigns.activate` should re-resolve
the audience and provider state; each `OutboundMessaging.request(intent)` should
validate the exact template evidence; and the delivery worker should repeat the
suppression, reply, consent, template, service-window, account-health, and
campaign-state checks under the existing Product lock. A campaign must not write
Outbox directly.

Fixtures may represent every lifecycle state for deterministic tests. They must
be labelled `Fake` or `Fixture`; they are not evidence that Larevia owns an
approved production template.

## Current activation gates

### Provider facts not verified in this research

- The real WABA ID, sender phone-number ID, business verification state, billing
  readiness, account restrictions, current messaging capacity, and phone quality.
- Any real approved Marketing template, its exact Meta ID/name/components,
  Spanish or other language variant, current quality, or continued approval.
- Live `message_template_status_update` subscription and delivery-status webhook
  behavior for Larevia's actual account.
- The current account's access to any optional marketing optimization product.

All remain `Denied`/inactive until an authenticated, secret-safe provider check is
performed with a test recipient expressly authorized for that rehearsal.

### Business and legal gates not resolved by Meta policy

- Mexican counsel must approve the controller identity, privacy notice,
  marketing-consent language and collection path, retention/evidence rules,
  revocation handling, consumer-advertising exclusions, and any required checks.
- Larevia must choose a conservative numeric frequency budget, quiet hours and
  timezone behavior, quality stop thresholds, pilot size, and review owner. Meta
  does not supply these business decisions.
- The operation must approve the exact purposes covered by consent: new matching
  properties, reactivation, Development announcements, or a narrower subset.
- The operation must establish authority and current factual support for every
  advertised Development, Listing, price, availability, attribution, and
  appointment invitation.
- The team must decide how quickly a Meta warning, quality decline, webhook gap,
  template change, or provider-read failure pauses an active campaign. The safe
  default is immediate pause before any new outbound request.
- Protected-characteristic and proxy review is required for every audience-rule
  version; explainability alone does not make a discriminatory rule permissible.

Until these gates are closed, Stage 7 can truthfully demonstrate candidate
matching, Admin decisions, audience preview, dry-run, cancellation, transactional
outbound requests, and fake delivery results. It cannot truthfully claim real
marketing consent, real Meta approval, or production campaign readiness.

## First-party sources reviewed

- [WhatsApp Business Messaging Policy](https://whatsappbusiness.com/policy/)
- [WhatsApp Business Platform pricing and message-category overview](https://whatsappbusiness.com/products/platform-pricing/)
- [WhatsApp, *Best Practices for Marketing Messages on WhatsApp*, 2026](https://whatsappbusiness.com/wp-content/uploads/2026/04/Best-Practices-for-Marketing-Messages-on-WhatsApp-.pdf)
- [Meta official WhatsApp Business Platform Postman workspace](https://www.postman.com/meta/whatsapp-business-platform/documentation/wl)
- [Meta official `GET message_templates` example](https://www.postman.com/meta/whatsapp-business-platform/request/hl0hxc0/get-all-templates-default-fields)
- [Meta official Cloud API template-send example](https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api?entity=request-13382743-f2eb9575-f109-4767-ab47-4cf74c14444f)
- [Meta official template-status webhook schema](https://www.postman.com/meta/whatsapp-business-platform/request/j09tht8/components)
- [Meta official message-status webhook example](https://www.postman.com/meta/whatsapp-business-platform/request/rgtfq23/message-status-update-notifications)
- [Meta Business SDK template status and quality enums, pinned commit](https://github.com/facebook/facebook-python-business-sdk/blob/788f363d15b1269ab5efb7cd00fb5e3b133cd99b/facebook_business/adobjects/whatsappbusinessaccount.py#L913-L963)
- [Meta-hosted WhatsApp Node.js SDK language object](https://whatsapp.github.io/WhatsApp-Nodejs-SDK/api-reference/types/language_object/)
