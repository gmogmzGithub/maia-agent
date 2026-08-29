# Runbook: onboarding a Brokerage Organization

Accompanied onboarding. There is no self-service signup, and nothing in this
runbook is safe to skip because "the customer is in a hurry" — every step exists
because the alternative fails silently.

**Before you start you need**, in writing from the customer:

- the brokerage's legal and working name, and the public hostname they will use;
- the municipalities they operate in;
- their bookable hours and visit length;
- the founding team: who administers, who advises, and who is the default Advisor;
- whether they bring their own WhatsApp number and Meta app, or use ours;
- which add-ons they bought (collaborator inventory, reactivation, development
  campaigns, sponsored placement);
- a named contact for the data-processing conversation.

If any of those is missing, stop. Provisioning with a guess produces a
configuration document that says something nobody agreed to, and the document is
the record.

## 1. Put the credentials in the secret store first

For each provider the Organization will use, store the value under a name you can
say out loud — `LAREVIA_META_ACCESS_TOKEN`, `ACME_EASYBROKER_API_KEY`. Product will
store the **name**, never the value.

Verify each name resolves before you provision. Provisioning reports whether a
reference resolves; it cannot tell you whether the provider accepts it.

## 2. Provision

```
POST /platform/organizations
Authorization: Bearer $PLATFORM_OPERATOR_TOKEN
X-Platform-Operator: <your login>
```

```json
{
  "slug": "acme",
  "display_name": "Acme Inmobiliaria",
  "configuration": {
    "brand": {"working_name": "Acme", "public_origin": "https://acme.mx"},
    "service_area": {"municipalities": ["Guadalajara", "Zapopan"]},
    "scheduling": {"time_zone": "America/Mexico_City", "visit_minutes": 90,
                   "weekly_schedule": "mon=09:00-17:00;tue=09:00-17:00;wed=09:00-17:00;thu=09:00-17:00;fri=09:00-17:00;sat=nada;sun=nada"},
    "team": {"default_advisor": "ana@acme.mx"},
    "channels": {"whatsapp_phone_number_id": "…"},
    "integrations": {"expected": ["MetaWhatsApp", "GoogleCalendar"]},
    "limits": {"campaign_recipients": 50}
  },
  "administrators": ["dir@acme.mx"],
  "advisors": ["ana@acme.mx", "luis@acme.mx"],
  "default_advisor": "ana@acme.mx",
  "channels": [
    {"kind": "WhatsAppPhoneNumberId", "external_id": "…"},
    {"kind": "PublicSiteHost", "external_id": "acme.mx"}
  ],
  "credentials": [
    {"provider": "MetaWhatsApp", "reference": "ACME_META_ACCESS_TOKEN"}
  ],
  "add_ons": ["ExternalInventory"],
  "reason": "Alta acompañada de Acme Inmobiliaria, contrato firmado el 3 de marzo.",
  "command_key": "provision-acme-2026-03-03"
}
```

Read the `steps` array in the response. Every step must be `Completed`.

**If a step failed**, the Organization is `Provisioning` and cannot answer a
customer. Two options and no third:

- fix the cause and re-POST with the **same** `command_key` — completed steps are
  skipped and the run continues;
- `POST /platform/runs/{run_id}/rollback` with a reason, and start over.

Do not "just activate it manually". A partially provisioned Organization with no
default Advisor sends every Opportunity to the Assignment Queue and nobody
notices for a week.

## 3. Confirm the credentials actually work

Provisioning proved the reference resolves. Now prove the provider accepts it:

- send one WhatsApp message to a number you control and confirm delivery;
- read one Advisor's calendar availability through the CRM's visit Calendar;
- if EasyBroker is an add-on, run one search and confirm the source health panel
  is green.

A credential that resolves and is rejected looks exactly like a credential that
works until the first real customer writes.

## 4. Import their inventory — dry run first, always

```
POST /platform/organizations/{id}/import/dry-run
POST /platform/organizations/{id}/import/apply
```

Send the dry run's findings to the customer and get an answer on every
`Invalid` and `Duplicate` before you apply. The apply requires a dry run over the
identical source checksum, so re-reading the file with one cell changed correctly
refuses.

Imported Properties are `Pending` facts review. They cannot be published,
recommended or scheduled until their Administrator reviews them — say this to the
customer, or they will report the site as broken.

If the apply is wrong: `POST /platform/import-runs/{run_id}/rollback`. Properties
another record already references are left in place and reported.

## 5. Hand over

- point the customer's Administrator at `/crm/plataforma` and walk them through
  it: their configuration version, what their plan includes, where their
  credentials come from, and the support-access list;
- tell them explicitly that Maia's team cannot read their records without a
  temporary grant that appears on that page;
- record the data-processing conversation outcome as a configuration `notes`
  section, or as a retention hold if one was agreed.

## 6. Verify the isolation, once, out loud

With the customer's Administrator watching:

- log in as their Administrator and confirm the Property list shows only their
  inventory;
- confirm the Assignment Queue, Contacts and Inbox are empty or theirs alone;
- send one message to their WhatsApp number and confirm it appears in *their*
  Inbox and nowhere else.

This is five minutes and it is the only demonstration that means anything to the
person signing.
