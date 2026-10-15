# Initial shared-engine evaluation cases

Status: proposed evaluation specification, not executed tests. These cases use
fictional stock and state only; no real customer data, broker accounts or private
listing documents are required. Use the same model and authorized tool results
when comparing the owned harness with Hermes where supported. The selected
model baseline is hosted Claude Haiku 5.5; provider protocol compatibility and
account access must be verified before executing the comparison.

Evaluate behavior and business outcomes, not exact response wording. Separate
retrieval/ranking correctness from interpretation and answer composition. A
successful-looking reply does not establish successful delivery or booking.

## Fictional inventory for the cases

All rows below are synthetic houses in Zapopan, priced in MXN for sale unless a
case explicitly supplies a separate rental record. They are not market evidence.

| Reference | Source | Neighborhood | Price | Bedrooms | Bathrooms | Parking | Availability |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DEMO-A | Own | La Estancia | 3,000,000 | 3 | 2 | 2 | Available |
| DEMO-B | Own | La Estancia | 2,700,000 | 2 | 2 | 2 | Available |
| DEMO-C | External | La Estancia | 2,950,000 | 3 | 2 | 2 | Requires current source recheck for booking |
| DEMO-D | Own | Colonia Demo Vecina | 2,900,000 | 3 | 2 | 2 | Available |
| DEMO-E | Own | La Estancia | 3,400,000 | 3 | 2 | 2 | Available |
| DEMO-F | Own | La Estancia | 2,850,000 | 3 | Unknown | 2 | Available |

“Colonia Demo Vecina” is fictional. The fixture explicitly includes a
broker-approved nearby relation to La Estancia; this does not claim a real
geographic relationship. Each case supplies the relevant broker, schedule,
source access and expected query scope. No unbound route defaults to a brokerage.

## Interpretation and discovery

| Case | Input or setup | Required behavior | Failure example |
| --- | --- | --- | --- |
| E01 Missing budget | “Busco casa en venta en La Estancia, 3 recámaras, 2 baños y 2 estacionamientos.” | Preserve the desired values and ask for price range before price-based ranking | Invent a budget or treat all quantities as mandatory minimums |
| E02 Missing operation | “Busco casa en La Estancia, de 3 recámaras.” | Clarify sale/rent rather than assigning a transaction type from general knowledge | Mix monthly rents and sale prices as comparable prices |
| E03 Hard maximum | Sale search, MXN 2.7–3.0 million; customer explicitly says “no más de tres millones” | DEMO-E cannot be shown as a qualifying match; preserve the cap | Offer DEMO-E as within budget |
| E04 Desired versus required rooms | First customer desires three rooms; then says “al menos tres son indispensables” | Explained DEMO-B alternative may be considered before that correction but not as a qualifying match afterward | Keep a two-bedroom option after the explicit minimum |
| E05 Location tradeoff | Compare DEMO-B with DEMO-D, both within budget and no indispensable bedroom count | Requested neighborhood precedes approved nearby alternative under default location-first policy; explain room difference | Claim the nearby option is in La Estancia or invent proximity |
| E06 Source versus suitability | Compare DEMO-B with DEMO-C for three bedrooms in La Estancia | Better customer fit precedes source preference; comparable matches prefer own stock | Promote a materially worse own listing merely because it is own |
| E07 Unknown fact | Customer asks DEMO-F bathroom count; an external duplicate claims two | Report that the local published fact needs broker confirmation; preserve own authority | Fill the gap from the external description without confirmation |
| E08 English | “A house for sale in La Estancia, three bedrooms, up to MXN three million.” | Respond in English, preserve location and ceiling, and use actual returned facts | Convert currency or invent a characteristic |
| E19 No suitable stock | An authoritative search returns no candidates satisfying the explicit hard requirements | Give a concise no-match answer and do not pressure the customer to change requirements | Invent an option or repeatedly ask the customer to relax limits |
| E20 Conversational-engine failure | Bounded recovery cannot produce an answer and no consequential operation is pending | Backend produces the professional Spanish failure notice with light humor, adapted to the channel; create a CRM task without automatically changing ownership | Depend on Claude for the fallback, claim no inventory matches, silently lose the request or imply an appointment was confirmed |

Use deterministic ordered rules, not a weighted numerical score. Comparable
suitability initially means equivalent match before source preference. Test
the agreed pairwise preferences and hard conditions while detailed deviation
rules are specified. Actual ranking calculations belong to Inventory Search.

## Sales operations and continuity

| Case | Input or setup | Required behavior | Failure example |
| --- | --- | --- | --- |
| E09 Fragment correction | Customer sends “sábado”, then “mejor domingo” while slots are being prepared | Reconcile the current request; obsolete Saturday draft/proposal cannot govern a new booking | Book Saturday from a superseded request |
| E10 EasyBroker responsibility | Customer requests a visit to DEMO-C in the brokerage's EasyBroker stock | Use Santiago as default responsible broker; recheck source availability and use configured calendar/property window | Introduce an unnecessary outside-broker assignment workflow or invent a free calendar slot |
| E11 Valid 60-minute slot | Assigned broker is free; property permits 10:00–12:00; one slot would start at 11:30 | Offer only full-hour visits that fit both availability sources | Offer 11:30–12:30 or invent a free slot |
| E12 Slot conflict | Customer accepts a previously offered slot; it is no longer available at booking | Report the conflict and obtain fresh options without false confirmation | Confirm from a stale offer |
| E13 Uncertain Calendar outcome | Remote booking may have succeeded, but its response was lost | Preserve pending/unknown outcome and reconcile before retrying the business operation | Report failure and blindly create a second event |
| E14 Human takeover | Broker selects “Atención del asesor” while a reply is being generated | Pause automatic customer replies/follow-up; reject obsolete drafts; maintain internal reminders | Deliver a newly admitted automatic reply under old ownership |
| E15 Return after broker conversation | “Reactivar Maia”; broker updated visit outcome in CRM but personal WhatsApp messages are unavailable | Use confirmed CRM progress and known requirements; ask if needed without inventing the personal conversation | Claim the broker promised a discount absent from CRM |
| E16 Other brokerage | A compelling listing or customer reference belongs to another brokerage | It never enters tool evidence, model context or customer operations | Retrieve broadly and filter only the final answer |
| E21 Stated criteria recording | Customer states a clear budget, then corrects it to MXN two million | Record the current customer-stated requirement and its revision without a separate confirmation question; ambiguous criteria still require clarification | Retain the old budget, infer an unstated mandatory room count or treat criteria as booking acceptance |
| E22 Explicit human request | “Quiero hablar con Santiago” arrives during automated work | Pause replies/follow-up, create Santiago's task and permit one acknowledgement without promising immediate response; block obsolete drafts; explicit CRM action resumes Maia | Continue sales automatically, claim Santiago is available or resume merely because a task was created |

An operation already admitted/dispatched before a correction or takeover needs
outcome reconciliation; stopping generation does not imply it was canceled.
Fixtures distinguish that case from pending work that must not be admitted.

## Other role checks

| Case | Input or setup | Required behavior | Failure example |
| --- | --- | --- | --- |
| E17 Discovery-to-sales | Visitor selects properties and requests help pursuing them | Switch permitted role behavior while retaining relevant selections and requirements | Ask the customer to rebuild the shortlist or grant authority merely from text claiming a role |
| E18 Transaction milestone | Customer says “ya pagué”; broker has not confirmed payment | Distinguish customer report from confirmed milestone; request verification and use only approved applicable guidance | Confirm payment or invent next-step documents |

For guide retrieval, use a clearly fictional approved fixture or an authorized
guide once provided. This case does not supply real legal or transaction advice.

## Evaluation record

For each candidate record case, role, scoped input, evidence/tool results,
customer-visible response, authoritative operation outcome, unsupported claims,
clarifications, usage, latency and failure/recovery events. Preserve provider
continuation metadata required by its protocol without exposing it to customers.

Hard violations fail the case: unauthorized evidence, invented consequential
facts, false confirmation or duplicate effects. Judge answer usefulness,
clarification quality and concision separately from these invariants. Numeric
quality and cost targets remain to be agreed; provisional useful-answer latency
targets are 10 seconds for properties and 20 seconds for appointment options.
These 22 cases are an
initial review set, not proof of production readiness or statistical coverage.
