"""Public property summaries built only from inventory data."""

import re
from decimal import Decimal

LABELS = {
    "bedrooms": "recámaras",
    "bathrooms": "baños",
    "parking": "estacionamientos",
    "furnished": "Amueblado",
    "accepts_pets": "Acepta mascotas",
    "near_schools": "Escuelas cercanas",
}


def split_closing_question(text):
    match = re.search(r"((?:Por cierto,\s*)?¿[^¿?]+\?)\s*$", text, re.IGNORECASE)
    return (text[: match.start()].strip(), match[1]) if match else (text, "")


def repeats_card_details(text, cards):
    if re.search(
        r"\$|\bMXN\b|https?://|\*\*|\bID\s*\d|\d+\s+(?:recámaras?|baños?|caj[oó]n|estacionamientos?)",
        text,
        re.IGNORECASE,
    ):
        return True
    folded = text.casefold()
    if "oferta comercial" in folded or "propiedad de prueba" in folded:
        return True
    return any(
        str(card.get(key, "")).casefold() in folded
        for card in cards
        for key in ("title", "reference")
        if card.get(key)
    )


def property_highlights(prop, criteria):
    preferred = [
        key for key in LABELS if criteria.get("min_" + key) is not None or criteria.get(key) is True
    ]
    fields = list(dict.fromkeys(preferred + ["bedrooms", "bathrooms", "parking"]))
    result = []
    for field in fields:
        value = prop.get(field)
        if value is None or value is False:
            continue
        if value is True:
            result.append(LABELS[field])
        else:
            number = Decimal(str(value))
            label = (
                {"bedrooms": "recámara", "bathrooms": "baño", "parking": "estacionamiento"}[field]
                if number == 1
                else LABELS[field]
            )
            result.append(f"{number.normalize():f} {label}")
    return result[:3]


def property_text(prop, criteria, base_url):
    price = (f"${Decimal(prop['price']):,.0f} {prop.get('currency', 'MXN')}"
             if prop.get("price") is not None and prop.get("price_visible", True)
             else "Precio por consultar")
    if prop.get("is_presale"):
        price += " · Preventa"
    if prop["operation"] == "rent" and prop.get("price") is not None:
        price += " al mes"
    lines = [
        prop["title"],
        price,
        " · ".join(filter(None, [prop.get("neighborhood"), prop.get("municipality")])),
        " · ".join(property_highlights(prop, criteria)),
    ]
    if prop.get("reference", "").upper().startswith("PRUEBA"):
        lines.append("Propiedad de prueba, no es una oferta comercial.")
    if prop.get("unconfirmed"):
        lines.append("Por confirmar: " + ", ".join(LABELS.get(k, k) for k in prop["unconfirmed"]))
    lines.append(f"Ver propiedad: {base_url}/propiedades/{prop['id']}")
    return "\n".join(line for line in lines if line)
