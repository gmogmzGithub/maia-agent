---
status: accepted
---

# Exclude property images from Maia

Maia deliberately handles property information as approved text and structured facts
without images. The administrative form, Property Document schema, Property Catalog,
runtime artifacts, PostgreSQL records, Hermes tools, and WhatsApp delivery must not
add image uploads, image URLs, galleries, or media messages. This keeps the product
focused on grounded property answers and operations without introducing media
storage, moderation, lifecycle, or delivery responsibilities; adding images later
would require explicitly superseding this decision.
