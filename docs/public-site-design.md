# Public Site Design System

This document defines the approved visual system for Larevia's complete public
experience. It combines Resider's photographic discipline and low-noise layout
with Tuhabi's cognitive simplicity, while remaining an original Mexican-Spanish
experience for Guadalajara, Zapopan, and Tlaquepaque.

The redesign is a local design exercise. It does not authorize production use,
real customer data, real property claims, deployment, or a change to Product's
business authority.

## Experience principles

1. **Property first.** Photography and authorized facts lead. Maia is a
   contextual alternative, never an AI spectacle or an unsolicited popup.
2. **Quiet premium for every Listing.** The base Larevia tier is excellent and
   complete. Premium and Super Premium change editorial scale and sequencing,
   never service quality, factual truth, accessibility, or customer treatment.
3. **One next action.** Each screen makes its primary action obvious and moves
   complexity into progressive disclosure.
4. **Local and truthful.** Public Location may orient a customer; Visit Address
   stays private. Copy never invents neighborhood expertise, statistics,
   availability, reviews, or brokerage credentials.
5. **Accountless continuity.** Saving is immediate and anonymous. Verified
   WhatsApp protects continuity and is required before a visit is confirmed.
6. **Original, not copied.** Resider informs hierarchy, spacing, and restraint;
   Tuhabi informs flow and language. Components, identity, copy, and composition
   remain Larevia's own.

## Visual tokens

| Token | Value | Role |
| --- | --- | --- |
| Marfil | `#f7f5ef` | Principal background |
| Tinta | `#17211d` | Body text and deepest surfaces |
| Agave | `#315c4c` | Links, focus-adjacent emphasis, primary action |
| Arcilla | `#a85f45` | Rare editorial warmth |
| Maíz | `#d3a446` | Restrained highlight with Tinta text |
| Piedra | `#d9d6cd` | Quiet surfaces and non-essential separators |
| Blanco | `#ffffff` | Cards and action text |

Normal text uses Tinta on Marfil, Agave on Marfil, white on Agave, white on
Arcilla, or Tinta on Maíz. Piedra never acts as the sole control boundary or
focus indication. Error and focus tokens must independently meet WCAG 2.2 AA.

Spacing uses a four-pixel base with `8`, `12`, `16`, `24`, `32`, `48`, `64`,
and `96` pixel steps. Cards use an eight-pixel radius, panels use twelve pixels,
and only chips are fully rounded. Shadows indicate real overlay elevation, not
decoration.

## Typography

Self-host variable **Inter** for navigation, controls, prices, dense facts, and
body copy. Self-host variable **Newsreader** for property titles and selected
editorial statements. Retain both OFL license files with the font assets.

| Role | Intended size |
| --- | --- |
| Metadata | 13-14px |
| Body and controls | 16px |
| Editorial introduction | 18-20px |
| Card title or price | 22-28px |
| Section heading | fluid 32-48px |
| Hero heading | fluid 44-72px |

Mexican-Spanish copy is direct, calm, warm, and outcome-led. Avoid AI hype,
translated portal jargon, exaggerated luxury language, and unsupported claims.

## Global composition

The sticky header is thin and contains the typographic Larevia wordmark,
`Propiedades`, `Zonas`, `Cómo funciona`, `Guardadas`, and a restrained Maia
action. There is no account control. Mobile navigation becomes a compact,
keyboard-operable menu without hiding essential destinations.

The homepage uses a full-bleed photographic hero with a controlled dark overlay,
the headline `Encuentra tu lugar.`, service-area orientation, and one unified
search dock. Operation, zone, and property type are authoritative explicit
criteria; `Cuéntaselo a Maia` is the conversational alternative in the same
composition. The supporting sequence is deliberately short: coverage proof,
six to eight selected Listings, three municipality cards, the Larevia and Maia
process, a secondary seller path, specialists, and one final discovery action.

Catalog results use three generous columns on ordinary desktop viewports, four
only on very wide screens, two on tablets, and one on mobile. Cards use roughly
3:2 photography and show operation/type, visible price or consultation copy,
Public Location, three or four relevant characteristics, and Save. Tier names
are not customer-facing card badges. A sponsored card keeps the same footprint
and carries one unambiguous `Patrocinada` label.

Essential filters stay visible. Advanced filters use a right drawer on desktop
and a full-screen sheet on mobile. Results use `Mostrar más`, never infinite
scroll. An optional map is secondary to the grid and may use only approximate
Public Location; it stays unavailable until the implementation is truthful.

## Presentation Tiers

All tiers share navigation, facts, actions, privacy, performance, and
accessibility. Search, zone, saved, and shared-selection layouts remain stable.
The Technical Sheet and Gallery carry the meaningful difference.

- **Larevia** is bright, calm, complete, and deliberately designed: generous
  photography, warm-white surfaces, crisp facts, and balanced spacing.
- **Premium** increases photographic scale, editorial whitespace, serif
  hierarchy, full-width moments, image sequencing, and tonal depth.
- **Super Premium** uses an immersive opening image, paced editorial sections,
  refined dark-and-ivory moments, and more dramatic scale without gold,
  ornamental scripts, autoplay, or reduced usability.

Premium is felt rather than announced. Presentation Tier remains separate from
Sponsored Placement and never derives from customer identity or behavior.

## Listing, Gallery, and Maia

The Technical Sheet leads with an editorial image mosaic and uses a compact
in-page navigation. Desktop places facts in a wide content column and the price
and action in a restrained rail. Mobile stacks the same content and exposes one
compact sticky action. `Me interesa esta propiedad` opens Maia with Listing
context; Save and Share remain secondary. A visit is not confirmed on the site.

The separate Gallery contains one dominant image, optional thumbnails,
Administrator-assigned space groups, progress, keyboard and button controls,
and a persistent interest action. It never autoplays or obscures media with
decorative text.

Maia appears as a contextual side panel on desktop, a full-screen sheet on
mobile, and the dedicated `/maia` route. It never opens automatically. The
conversation displays its Listing or search context, short suggestion prompts,
the anonymous privacy boundary, and explicit transitions to the official
WhatsApp or a human. It uses no robot avatar or typing theatre.

## Human-visible route and state matrix

| Family | Required states |
| --- | --- |
| Homepage | Inventory, empty catalog, sponsored section, catalog failure |
| Catalog | Default, filtered, zero results, sponsored, more results |
| Zone | Guadalajara, Zapopan, Tlaquepaque, unknown or empty |
| Technical Sheet | Larevia, Premium, Super Premium, hidden price, withdrawn, unknown |
| Gallery | Three tiers, grouped media, withdrawn, unknown |
| Guardadas | Empty, available, withdrawn item, protect, share, delete, mutation failure |
| Shared selection | Read-only available, withdrawn item, empty, expired or revoked |
| Maia | Empty, contextual, conversation, error, WhatsApp continuation |
| Handoff | WhatsApp redirect, reference fallback, refusal |
| Sponsorship report | Structured report, fallback report, expired or revoked, aligned PDF |
| Global | 404, validation, service failure, keyboard focus, reduced motion |

Machine-only media, measurement, crawler, and sitemap responses do not receive a
visual layer.

## Responsive and accessible behavior

Verify at `320`, `390`, `768`, `1024`, `1440`, and `1920` pixel widths. Mobile
recomposes the complete experience; it does not hide material facts. Controls
have at least a 44-pixel target, focus is visible, headings remain semantic,
errors preserve submitted values and explain recovery, and reduced-motion users
receive no smooth scrolling or decorative transition.

The essential server-backed flows continue without JavaScript. JavaScript may
enhance navigation, drawers, optimistic Save feedback, Gallery controls, and the
Maia panel, but it never becomes business authority.

## Photography and fictional design media

Authorized Listing Media remains Product truth. Design-only property media is
never imported as authorized inventory merely to make a preview work.

Local review uses all thirteen photographs Guillermo downloaded from Unsplash.
Optimized derivatives are committed with source attribution and the license
review in `src/realestate/site/assets/demo/ASSET-PROVENANCE.md`. Two restrained
ImageGen interior fixtures are reused across the fictional galleries; no other
generated photography is needed for this review.
Tracked demo media must be original or clearly licensed, optimized for the web,
and described in that provenance manifest.
Fictional Listings use invented names and broad Public Locations, never real
street addresses or real-development claims. Synthetic Property Experts are not
created; local review uses an initials placeholder labelled `Especialista de
demostración`.

Every local preview that contains fictional inventory displays the
environment-only notice `Demostración local · propiedades e imágenes ficticias`.
That notice is not part of the intended production identity.

`SITE_DESIGN_DEMO=true` activates the labelled local projection. It supplies
nine invented Guadalajara-area Listings across the three presentation tiers.
The fixtures exist only in the separate Site process and never enter Product.
The setting defaults to false in application configuration; canonical local
Compose enables it for design review. Product's approved Listing Media and
business records remain untouched.

## Visual acceptance

Completion requires more than passing tests. Review desktop and mobile evidence
for every route family, all three tiers, exceptional states, keyboard operation,
reduced motion, contrast, overflow, and truthful withdrawn-media behavior. Keep
review screenshots and temporary fixtures outside Git. Compare the result with
the pre-redesign interface and check that the final composition follows this
document rather than copying either reference site.
