# WhatsApp lead follow-up: supplied framework

Source: a supplied image titled “PROCESO DE 28 DIAS-LEADS FACEBOOK”. The product
review explicitly selects only its WhatsApp column; calls and email are excluded.
The source transcription below is supplemented by the agreed interpretation.
Claude-generated follow-up wording is selected; delivery eligibility is not yet
fully specified.
This is a product requirement, not an implementation claim.

| Day | WhatsApp annotation |
| --- | --- |
| 1 | SI |
| 3 | X |
| 5 | SI |
| 7 | SI (2) |
| 10 | X |
| 14 | SI |
| 18 | SI |
| 22 | SI; the day label also contains “(2 A)” |
| 26 | SI |
| 28 | SI |

The image also states “ARCHIVAR”, “SOFT APPOINTMENTS: +72 HORAS”,
“SOLID APPOINTMENTS: -72 HORAS”, and “CONFIRMACION GERENCIAL: DIA DE LA CITA”.
The soft/solid appointment annotations and managerial confirmation are explicitly
excluded from Maia's intended process. They add no approval gate or extra
scheduled action.

## Agreed interpretation

- Day 1 starts with the very first incoming customer message.
- Count local calendar days, with the inquiry date as day 1. Answer the initial
  inquiry promptly; day 1 does not create a duplicate scheduled message.
- Later scheduled messages default to 10:00 Guadalajara local time, including
  weekends. The sending hour is configurable.
- The intended WhatsApp contact days are 1, 5, 7, 14, 18, 22, 26, and 28.
  The clarified cadence does not specify a second send on day 7 or day 22.
- Enroll genuine WhatsApp property sales/rental inquiries when Maia's initial
  answer goes unanswered. Unrelated messages do not enroll. Opt-outs and human
  attention prevent automated outreach; anonymous website browsing does not
  enroll a customer.
- A reply ends the unanswered-inquiry sequence; subsequent attention follows
  the customer's actual next step. Requests to stop end outreach.
- Keep only the settled contact-day sequence for the pilot. Do not implement a
  separate customer-requested future-contact schedule or automatically create
  alternative contact dates. This supersedes the proposed deferral feature.
- Claude generates follow-up wording rather than using a fixed collection of
  Santiago-approved step messages. The backend selects due steps and enforces
  sequence state, ownership, opt-outs and channel eligibility; Claude cannot
  select extra contact dates or invent inventory facts, promises or milestones.
  Give the model relevant verified customer and inventory context, including
  known changes to the original property's availability. Fixed approved wording
  can be reconsidered later. Provider-required template compatibility remains a
  separate integration question; free generation alone does not permit delivery.
- At the end of day 28, end this sequence for prospects who have not responded,
  are not interested, or remain undecided. Retain permitted business history and
  resume attention if the customer returns.
- Mark the sequence Completed, distinguishing No response, Undecided, and
  Explicitly not interested as outcome reasons. Apply the outcome to the
  relevant property pursuit rather than to the whole customer identity.
- Applying this framework to other lead sources should depend on customer
  behavior and stated interest rather than automatic blanket enrollment.

## Unresolved questions

- What useful purpose and generation instructions apply to each scheduled step?

Delivery eligibility and WhatsApp messaging requirements remain separate from
the cadence. The existence of a scheduled step does not itself authorize sending.
