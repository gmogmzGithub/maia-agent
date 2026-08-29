"""The words paid and unpaid prominence are allowed to use.

Two labels, and they are not interchangeable. ``Destacada`` is unpaid editorial
selection; ``Patrocinada`` is bought visibility. ADR-0043 keeps them apart
because a property owner who was told their listing is *featured* and later
discovers the word means somebody paid has been misled, and because a buyer who
paid deserves the audience to know it.

They live in their own module so the site, the buyer report, the PDF and the
operator surfaces all render the same string. A label that appears in four
places with three spellings is a label an accessibility test can only check in
one of them.
"""

from __future__ import annotations

#: Bought visibility. Required on every paid exposure, in every medium.
SPONSORED_LABEL = "Patrocinada"

#: Unpaid editorial selection. Never used for a Sponsorship Campaign.
EDITORIAL_LABEL = "Destacada"

#: The accessible description a screen reader announces for a sponsored slot.
#: Longer than the visible chip on purpose: "Patrocinada" alone is a word out of
#: context when it is read without the card around it.
SPONSORED_ARIA_LABEL = "Publicación patrocinada, visibilidad pagada"

#: What a Sponsored Placement does and does not buy. Shown next to the label on
#: the buyer-facing surfaces, because "more visibility" is the honest promise
#: and "more sales" is not one Product can make (ADR-0043).
SPONSORED_DISCLOSURE = (
    "Una publicación patrocinada compra visibilidad adicional claramente "
    "etiquetada. No cambia el nivel de presentación, no influye en las "
    "recomendaciones de Maia y no garantiza contactos, citas ni ventas."
)

#: The sentence every report carries. Attribution reports what happened after an
#: exposure inside a declared window; it does not claim the exposure caused it.
NON_CAUSAL_DISCLAIMER = (
    "Las cifras describen lo que ocurrió después de una exposición dentro de la "
    "ventana declarada. No miden causalidad ni comparan contra un grupo de "
    "control, y no deben leerse como incremento atribuible a la campaña."
)

#: What a report says when the comparable cohort is too small to describe.
INSUFFICIENT_HISTORY = "Estimación inicial sin historial suficiente"
