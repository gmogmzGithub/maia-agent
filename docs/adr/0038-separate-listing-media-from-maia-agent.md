---
status: accepted
supersedes: 0017-exclude-property-images
---

# Separate Listing Media from Maia Agent

The Platform manages Administrator-approved static Listing Media with known
provenance and publication authority, and the public site presents it. Maia Agent
does not select, inspect, caption, moderate, upload, or otherwise own photographs;
while attending a lead, it may only share the already authorized Listing Gallery
and Listing Technical Sheet URLs.

The MVP accepts JPG, PNG, and WebP photographs. The Administrator selects the
cover and gallery order. Videos, 360-degree tours, interactive renders,
downloadable plans, PDF media, and WhatsApp gallery delivery are deferred. When a
Listing is unpublished its media disappears from public surfaces immediately;
revocation of media authority also requires storage and cache deletion.
ADR-0061 places those bytes in private S3-compatible object storage without
changing Product's authority over publication or revocation.

The public experience separates a shareable, mobile-first Listing Gallery from a
structured Listing Technical Sheet and links them in both directions. The Gallery
combines a full-screen, customer-controlled sequence with progress and an optional
thumbnail grid, groups images by Administrator-assigned space, keeps text overlays
minimal, and provides a persistent `Me interesa esta propiedad` action that can
continue through WhatsApp or the site with Listing context preserved. It must not
auto-advance, require precise gestures, or sacrifice loading performance and
accessibility for visual effect.
