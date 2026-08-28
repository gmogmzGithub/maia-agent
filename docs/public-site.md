# Stage 5 Public Site

Stage 5 adds a complete local public experience for the working Brokerage Brand
**Larevia** and its assistant **Maia**. Larevia remains a working name pending
formal trademark clearance. The implementation is a separate server-rendered
process; it is not a second catalog or a CMS.

## Authority and process boundary

The browser reaches only Product on port 8080. Product proxies an allowlist of
public paths to Site over loopback. Site calls Product through
`/internal/public-site/*` with `SITE_PRODUCT_API_TOKEN`; that credential never
crosses into browser traffic. Site has no database, storage, Hermes, Meta, or
Calendar credentials.

Product remains authoritative for:

- publication eligibility, physical-identity deduplication, price visibility,
  presentation tier, media access, and withdrawal;
- saved-collection state, expiry, merging, sharing, and protection;
- anonymous Website Conversation state and the PII boundary;
- opaque channel handoff creation, verification, expiry, replay protection, and
  binding to verified WhatsApp identity;
- public analytics validation and durable audit facts.

Site owns HTML composition, navigation, responsive-image derivatives, public
cookies, and progressive enhancement. The browser never sends Product's internal
credential and never receives database identifiers as an identity claim.

## Product contracts

The stable module seams are:

- `PublicCatalog.search(query)` — explicit filters, pagination, deterministic
  ordering, eligibility, and evidence-backed physical deduplication;
- `PublicListing.read(slug)` / `media(media_id)` — current publication or honest
  withdrawal with immediate media revocation;
- `SavedCollections.record(command)` — idempotent Add, Remove, Empty, Delete,
  Share, anonymous continuity, and later verified protection;
- `WebsiteConversation.handle(command)` — anonymous context, 90-day content
  expiry, PII rejection, and Hermes response through the Sales role;
- `ChannelHandoff.create(command)` / `resolve(token)` — opaque `LAR-*`
  references, 30-minute normal expiry, 24-hour collection-protection expiry,
  single use, and verified identity binding;
- `DiscoveryPublication.project(listing_id)` — visible-fact metadata and
  structured data derived from the same authorized Listing;
- `PublicAnalytics.record(command)` — allowlisted funnel events and properties,
  without free text or behavioral profiles.

The internal HTTP adapter exposes those seams only to Site. It does not expand
the browser's authority.

## Public routes and states

| Route | Purpose | Important states |
| --- | --- | --- |
| `/` | Brand landing and current selection | Catalog outage renders an honest empty selection |
| `/propiedades` | Shareable explicit search | Filters stay in the URL; filtered pages are `noindex,follow`; zero results preserve criteria |
| `/zonas/{zona}` | Curated local discovery | Guadalajara, Zapopan, and Tlaquepaque only; unavailable inventory returns 404 |
| `/propiedades/{slug}` | Technical Sheet | 200 current, 410 withdrawn, 404 unknown; canonical and visible-fact schema |
| `/propiedades/{slug}/galeria` | Separate keyboard-operable gallery | Same 410/404 publication truth; no autoplay |
| `/media/{id}?w=480\|960\|1440` | Responsive authorized media | WebP derivative, bounded width, cache validator, 404 after withdrawal |
| `/guardadas` | Server-backed private collection | HttpOnly secure opaque cookie; empty, available, withdrawn, share, delete, and protect states |
| `/selecciones/{token}` | Fixed shared selection | 410 when unknown, expired, or revoked |
| `/maia` | Anonymous Website Conversation | No identity request; verified-channel action is explicit |
| `/handoffs` | Continue in WhatsApp or request a visit | Only an opaque reference crosses channels; a visit remains unconfirmed |
| `/robots.txt` / `/sitemap.xml` | Discovery policy and current URLs | Private surfaces excluded; image URLs included |

The official WhatsApp redirect contains only the public channel number, neutral
continuity copy, and an opaque handoff reference. Product resolves it only after
Meta intake establishes a verified Contact and Conversation. A request never
creates an Appointment on the website.

## Saved collections and privacy

Anonymous collections live for up to 365 days of activity and use a random
opaque HttpOnly cookie. No browser fingerprint is created. A user may explicitly
protect the collection through the verified WhatsApp handoff. Collections from
multiple devices then merge under the verified Contact, preserving unique items.
Shared selections are immutable snapshots that expire after 30 days.

Website Conversation rejects phone numbers and email addresses before calling
Hermes. Product supplies only eligible Listing context, stores conversation
content with its existing 90-day expiry policy, and replaces a model reply that
requests PII with the same verified-channel safety response.

Public measurement accepts only the funnel events needed for inventory,
gallery, saves, Maia, handoff, and appointment-request diagnostics. It records no
keystrokes, mouse movement, session replay, advertising identifier, or free-form
message content.

## Discovery and crawler policy

Current Listing pages are server rendered with one canonical URL, visible-fact
structured data, authorized image discovery, and sitemap entries. Withdrawn
Listings return an honest 410 page and disappear from catalog, discovery, media,
and sitemap surfaces.

`robots.txt` allows `OAI-SearchBot`, `ChatGPT-User`, normal search crawlers, and
other user-requested retrieval. It blocks training-only `GPTBot` and
`Google-Extended`, and blocks Saved, Maia, and shared-selection paths for general
crawlers. This matches the current distinctions documented by the
[OpenAI crawler FAQ](https://help.openai.com/en/articles/12627856-publishers-and-developers-faq)
and [Google crawler documentation](https://developers.google.com/crawling/docs/crawlers-fetchers/google-common-crawlers).
Provider identities and policies must be reverified before any production launch.
Robots directives are access preferences, not a privacy or authorization control.

## Visual direction

The final Stage 5 direction is warm, editorial, and recognizably Mexican without
using decorative clichés: cream paper surfaces, deep forest text, agave accents,
clay calls to action, and restrained maize highlights. A display serif carries
property and service hierarchy while a neutral sans-serif handles controls and
dense facts. Spacious cards, asymmetric editorial sections, visible source
attribution, and tactile 44-pixel-or-larger controls make the experience feel
like a capable brokerage operator rather than an AI novelty.

Larevia, Premium, and Super Premium share the same navigation, interaction, and
accessibility model. Tier differences are restrained to surface treatment and
marks; no customer profiling selects a tier. Motion is minimal and disabled by
the user's reduced-motion preference. The gallery is horizontal and responds to
buttons plus left/right keyboard input without shifting the document.

## Verification

Automated coverage includes Product contracts, migrations, eligible publication,
withdrawal, explicit search, hidden prices, deduplication, responsive media,
saved lifecycle and device merging, conversation privacy, handoff expiry/replay
and identity binding, discovery metadata, crawler output, security headers,
frontend byte budgets, and error states. The relevant suites are:

- `tests/test_public_site_domain.py`
- `tests/test_public_site_boundary.py`
- `tests/test_public_site_pages.py`
- `tests/test_public_site_adapters.py`
- `tests/test_public_site_migration.py`

Run the canonical verification from the repository root:

```bash
docker compose up -d --build
docker compose exec product pytest
```

Manual acceptance should exercise `/`, a filtered `/propiedades` URL, a
Technical Sheet, gallery keyboard navigation, save/reload/delete, anonymous Maia
PII rejection, and a WhatsApp handoff. Check 320-pixel mobile and desktop
viewports, confirm that only port 8080 is published, and verify `/robots.txt` and
`/sitemap.xml`. This proves the local Stage 5 behavior; it does not claim a
production deployment, legal readiness for real customer data, ranking, or
assistant citation.
