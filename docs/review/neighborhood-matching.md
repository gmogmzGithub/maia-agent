# Neighborhood matching: initial decision and future options

Status: the broker-reviewed nearby-neighborhood list is accepted for the first
version. Geographic automation, external datasets and infrastructure remain
future options; their selection is explicitly deferred.

The product needs to distinguish proximity from similarity. The agent asks a
product tool for related neighborhoods and evidence; it must not invent those
relationships from pretrained knowledge or text similarity.

## Accepted initial approach

Keep canonical neighborhood names, municipality and aliases, with a small
broker-reviewed list of nearby neighborhoods for areas represented in authorized
inventory. Start with that explicit list rather than requiring city-wide mapping.
If no relationship is recorded, do not assert that another neighborhood is near.

Keep these relationships in product data rather than embedding them in agent
instructions. The future design must permit expanding or replacing that data
source without changing the meaning of nearby versus similar. No generalized
geographic engine or integration is required for the first version.

Treat similar housing options separately: compare available authorized stock by
transaction type, price range, property type and characteristics. A neighborhood
with comparable stock is not automatically geographically nearby, and those
stock observations are not a claim about the entire neighborhood or market.

## Possible geographic extension

Verified coordinates or neighborhood geometries could support spatial distance
queries later. PostGIS provides distance filtering in meters for geography
values. A property point, representative neighborhood point and neighborhood
polygon answer different distance questions; straight-line distance does not
establish road distance or travel time.

Source: [PostGIS ST_DWithin](https://postgis.net/docs/manual-3.5/en/ST_DWithin.html).

The postal settlement catalog can help normalize names, municipality and postal
identity. It should not be treated as proof of geographic proximity or real-estate
similarity. Source selection, permitted use and geometry coverage need review
before ingestion; no dataset is selected here.

Source: [Correos de México field definitions](https://www.correosdemexico.gob.mx/SSLServicios/ConsultaCP/imagenes/Descrip.pdf).

## Customer explanation

Say that an option is in a broker-approved nearby area or has comparable available
property characteristics, as supported by the relevant data. State the actual
neighborhood and any differences. Do not assert unsupported safety, lifestyle,
price appreciation or exact travel-time equivalence.
