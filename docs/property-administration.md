# Manual Property Administration

This document records the accepted Stage 0 behavior for manually creating,
updating, and controlling Maia's Property inventory.

## Scope

- Property information is entered manually. Maia does not crawl or synchronize
  with EasyBroker.
- Maia contains no property images, image URLs, galleries, uploads, or WhatsApp
  media.
- The administrative UI is protected by the existing HTTP Basic credential.
- Telegram administration remains restricted to the configured allowlisted users.

## Property Documents and runtime truth

- `src/properties` is the local, public-safe Property Catalog.
- The local Compose runtime bind-mounts the catalog so an accepted submission can
  write `src/properties/{property_id}.md`.
- PostgreSQL and accepted immutable artifacts remain runtime truth. Hermes reads
  through typed Product tools and never reads the catalog directly.
- A first accepted submission creates document version 1 and activates the
  Property. A fact edit creates another immutable version and preserves the current
  availability.
- Invalid submissions change neither the catalog nor runtime truth.

## Identity

- `property_id` is generated from the Property name, uses lowercase hyphenated
  text, and is immutable after creation.
- Editing one Property reuses its `property_id`; a different Property requires a
  distinct name and identifier.
- The create path rejects collisions. Updates begin from the existing Property's
  Edit action rather than silently treating a duplicate create as an update.

## Availability

- Availability is `Active` or `Inactive`.
- An Inactive Property has one reason: `Sold`, `Rented`, `Reserved`,
  `TemporarilyUnavailable`, `Withdrawn`, or `Unspecified`.
- Only Active Properties may be disclosed to customers or considered for new
  bookings.
- Existing confirmed visits are never cancelled by a Property status change. They
  become Inactive Appointment Reviews for an Administrator.
- Authorized Telegram instructions execute immediately when both the Property and
  requested change are explicit. Ambiguous instructions require clarification.

## Location privacy

- The Property Document requires a customer-safe state, municipality or city, and
  neighborhood, coto, or development name.
- Optional Public Location notes may mention approved nearby avenues, parks, schools,
  or landmarks.
- The Property Document excludes street, exterior or interior number, exact
  coordinates, and access instructions.
- An optional exact Visit Address is private PostgreSQL data, omitted from the
  public catalog, and disclosed only after booking confirmation.

## Administrative pages

- `/admin/properties` shows Active, Inactive, and All views. Active is the default.
- Each row shows identity, type, operation, price, availability, inactive reason,
  document version, last update, and future confirmed visits.
- Each row provides View, Edit facts, Deactivate, and Reactivate actions.
- `/admin/properties/new` presents a structured Spanish form and a generated
  Markdown preview before the explicit `Create and activate property` action.
- Editing facts preserves availability.

## Property facts

Supported Property types are exactly:

- `House`, shown as `Casa`;
- `Apartment`, shown as `Departamento`;
- `Land`, shown as `Terreno`.

Coto, fraccionamiento, or development membership is a separate fact rather than a
Property type.

Supported operations are exactly `Sale` (`En venta`) and `Rental` (`En renta`). One
Property has one operation in Stage 0.

Supported monetary currencies are exactly `MXN` and `USD`. Every price carries its
currency explicitly, and Maia never converts or infers currency.

Always required:

- name;
- Property type;
- sale or rental operation;
- price and currency;
- city and neighborhood or development;
- customer-facing description;
- half-bathroom count, where zero is valid;
- parking-space count, where zero is valid;
- explicit Maintenance Terms.

Conditionally required:

- land area for land;
- bedrooms and full bathrooms for a house or apartment;
- maintenance amount, currency, and description when a maintenance charge exists;
- an explanation when maintenance is absent or unknown.

Other numeric facts are optional when applicable: construction area, floors, year
built, and related dimensions.

## Generated narrative

The form requires two plain-text narrative fields:

- `Descripción general`;
- `Distribución y espacios`.

The generated Markdown body uses this order:

1. level-one heading matching the Property name;
2. general description;
3. `Distribución y espacios`;
4. `Características de la propiedad`, when selected;
5. `Amenidades del coto`, when applicable and selected;
6. `Mantenimiento`;
7. `Ubicación`, containing only the Public Location.

Generated sections with no applicable content are omitted.

## Property characteristics

Private Property Characteristics are optional checkboxes:

- Jardín — generated and disclosed as a private garden;
- Bodega;
- Cisterna;
- Paneles solares;
- Estacionamiento techado;
- Alberca privada;
- Otra característica, with a short plain-text value.

The form separately asks whether the Property belongs to a coto, fraccionamiento,
or development with amenities. When it does, these optional checkboxes generate the
`Amenidades del coto` section:

- Jardines comunes;
- Alberca;
- Gimnasio;
- Jacuzzi;
- Área de juegos infantiles;
- Salón de usos múltiples;
- Casa club;
- Terraza;
- Seguridad 24 horas;
- Estacionamiento de visitas;
- Centro de negocios;
- Otra amenidad, with a short plain-text value.

When the Property does not belong to such a development, the shared-amenities group
and generated Markdown section are omitted.
