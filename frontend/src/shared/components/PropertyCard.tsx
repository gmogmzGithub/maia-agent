"use client";

import Link from "next/link";
import { useState } from "react";
import { labels, money, type Criteria, type Property } from "@/shared/lib/api";

export function PropertyPhoto({ property }: { property: Property }) {
  const [failed, setFailed] = useState(false);
  return (
    <div className={`property-photo photo-${property.kind}`}>
      {property.photos[0] && !failed ? (
        <img
          src={property.photos[0]}
          alt={property.title}
          onError={() => setFailed(true)}
        />
      ) : (
        <div className="photo-placeholder">
          <svg
            width="90"
            height="80"
            viewBox="0 0 90 80"
            fill="none"
            aria-hidden="true"
          >
            <path
              d="M12 68V33L45 9l33 24v35H12Z M34 68V44h22v24 M5 35L45 5l40 30"
              stroke="currentColor"
              strokeWidth="1.2"
            />
            <path d="M21 38h10v13H21zM60 38h10v13H60z" stroke="currentColor" />
          </svg>
          <span>Fotografía por agregar</span>
        </div>
      )}
      <span className="photo-badge">
        {property.is_presale ? "Preventa" : labels[property.operation]}
      </span>
    </div>
  );
}

export default function PropertyCard({
  property,
  compact = false,
  criteria = { verified_only: false },
  onInterest,
  interestDisabled = false,
}: {
  property: Property;
  compact?: boolean;
  criteria?: Criteria;
  onInterest?: (property: Property) => void;
  interestDisabled?: boolean;
}) {
  const names = {
    bedrooms: "recámaras",
    bathrooms: "baños",
    parking: "estacionamientos",
    furnished: "Amueblado",
    accepts_pets: "Acepta mascotas",
    near_schools: "Escuelas cercanas",
  };
  type Feature = keyof typeof names;
  const fields = Object.keys(names) as Feature[];
  const preferred = fields.filter((key) => {
    const criterion = ["bedrooms", "bathrooms", "parking"].includes(key)
      ? `min_${key}`
      : key;
    const value = criteria[criterion as keyof Criteria];
    return value != null && value !== false;
  });
  const ordered: Feature[] = compact
    ? ["bedrooms", "bathrooms", "parking"]
    : [...preferred, "bedrooms", "bathrooms", "parking"];
  const highlights = [...new Set(ordered)]
    .flatMap((key) => {
      const value = property[key];
      if (value == null || value === false) return [];
      if (value === true) return [names[key]];
      const singular: Partial<Record<Feature, string>> = {
        bedrooms: "recámara",
        bathrooms: "baño",
        parking: "estacionamiento",
      };
      const label =
        Number(value) === 1 ? (singular[key] ?? names[key]) : names[key];
      return [`${Number(value)} ${label}`];
    })
    .slice(0, 3);
  return (
    <article
      className={`property-card${compact ? " property-card-compact" : ""}`}
    >
      <Link
        href={`/propiedades/${property.id}`}
        className="photo-link"
        aria-label={`Ver ${property.title}`}
      >
        <PropertyPhoto property={property} />
      </Link>
      <div className="property-body">
        <p className="eyebrow">
          {labels[property.kind]} · {property.municipality}
        </p>
        <h3>
          <Link href={`/propiedades/${property.id}`}>{property.title}</Link>
        </h3>
        <p className="property-zone">{property.neighborhood}</p>
        <div className="property-price">
          {money(property.price, property.currency || "MXN")}{" "}
          <span>
            {property.currency || "MXN"}
            {property.operation === "rent" ? " / mes" : ""}
          </span>
        </div>
        {compact ? (
          <div className="property-specs">
            {highlights.map((value) => (
              <span key={value}>{value}</span>
            ))}
          </div>
        ) : (
          <div className="property-specs">
            {property.bedrooms !== null && (
              <span>{property.bedrooms} rec.</span>
            )}
            {property.bathrooms !== null && (
              <span>{property.bathrooms} baños</span>
            )}
            {property.parking !== null && (
              <span>{property.parking} estac.</span>
            )}
            {property.area_m2 !== null && (
              <span>{Number(property.area_m2)} m²</span>
            )}
          </div>
        )}
        {property.reference.toUpperCase().startsWith("PRUEBA") && (
          <p className="unconfirmed">
            Propiedad de prueba, no es una oferta comercial.
          </p>
        )}
        {!!property.unconfirmed?.length && (
          <p className="unconfirmed">
            Por confirmar:{" "}
            {property.unconfirmed.map((k) => labels[k] ?? k).join(", ")}
          </p>
        )}
        <Link href={`/propiedades/${property.id}`} className="text-link">
          Ver propiedad <span aria-hidden="true">↗</span>
        </Link>
        {onInterest ? (
          <button
            type="button"
            className="button secondary property-interest"
            disabled={interestDisabled}
            onClick={() => onInterest(property)}
          >
            Me interesa
          </button>
        ) : (
          <a
            href={`/?propiedad=${property.id}#conversacion`}
            className="button secondary property-interest"
          >
            Me interesa
          </a>
        )}
      </div>
    </article>
  );
}
