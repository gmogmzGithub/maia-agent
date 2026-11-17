"use client";
import { useEffect, useState } from "react";
import { api } from "@/shared/lib/api";
import type { Property } from "@/shared/lib/api";
import LocationMap from "@/shared/components/LocationMap";
import "@/shared/styles/capture.css";

export default function PropertyExtras({ property }: { property: Property }) {
  const details = property.details || {};
  const [resolved, setResolved] = useState<{
    latitude?: number;
    longitude?: number;
    approximate?: boolean;
  } | null>(null);
  const published = property.public_location || {};
  useEffect(() => {
    let cancelled = false;
    setResolved(null);
    if (published.lookup)
      void api<{ location: typeof resolved }>(
        `/location/properties/${property.id}`,
      )
        .then((value) => {
          if (!cancelled) setResolved(value.location);
        })
        .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [property.id, published.lookup]);
  const location = published.lookup ? resolved || {} : published;
  const list = (key: string) =>
    Array.isArray(details[key])
      ? (details[key] as unknown[]).filter(
          (x): x is string => typeof x === "string",
        )
      : [];
  const links = (key: string) =>
    list(key).filter(
      (x) => x.startsWith("https://") || x.startsWith("/api/capture/assets/"),
    );
  return (
    <>
      {property.subtype && <p>Subtipo: {property.subtype}</p>}
      <dl className="amenities">
        {[
          ["land_m2", "Superficie total (m²)"],
          ["half_bathrooms", "Medios baños"],
          ["condition", "Conservación"],
          ["age_years", "Años de antigüedad"],
          ["maintenance", `Mantenimiento (${property.currency || "MXN"})`],
          ["storage_rooms", "Bodegas"],
          ["elevators", "Elevadores"],
          ["floors", "Niveles construidos"],
        ]
          .filter(([key]) => details[key] != null && details[key] !== "")
          .map(([key, label]) => (
            <div key={key}>
              <dt>{label}</dt>
              <dd>{String(details[key])}</dd>
            </div>
          ))}
      </dl>
      {!!list("amenities").length && (
        <>
          <h2>Comodidades</h2>
          <div className="capture-amenities">
            {list("amenities").map((x) => (
              <span key={x}>✓ {x}</span>
            ))}
          </div>
        </>
      )}
      {typeof location.latitude === "number" &&
        typeof location.longitude === "number" && (
          <>
            <h2>
              {location.approximate ? "Ubicación aproximada" : "Ubicación"}
            </h2>
            <LocationMap
              latitude={location.latitude}
              longitude={location.longitude}
              approximate={!!location.approximate}
            />
          </>
        )}
      {[
        ["plans", "Planos"],
        ["videos", "Videos"],
        ["tours", "Recorridos 360°"],
      ].map(
        ([key, label]) =>
          links(key).length > 0 && (
            <section key={key}>
              <h2>{label}</h2>
              {links(key).map((url, i) => (
                <p key={url}>
                  <a
                    className="text-link"
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {label} {i + 1} ↗
                  </a>
                </p>
              ))}
            </section>
          ),
      )}
    </>
  );
}
