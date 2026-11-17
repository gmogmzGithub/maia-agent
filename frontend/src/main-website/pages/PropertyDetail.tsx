"use client";
import ErrorNotice from "@/shared/components/ErrorFeedback";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import PropertyExtras from "@/main-website/components/PropertyExtras";
import Header from "@/shared/components/Header";
import { PropertyPhoto } from "@/shared/components/PropertyCard";
import { api, labels, money, type Property } from "@/shared/lib/api";

export default function Detail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [property, setProperty] = useState<Property | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    void api<Property>(`/properties/${id}`)
      .then(setProperty)
      .catch(() =>
        setError(
          "Esta propiedad ya no está disponible o no pudimos consultarla.",
        ),
      );
  }, [id]);
  return (
    <>
      <Header />
      <main className="detail-main">
        <Link className="text-link" href="/#inventario">
          ← Volver a propiedades
        </Link>
        {error ? (
          <ErrorNotice retry={() => window.location.reload()}>
            {error}
          </ErrorNotice>
        ) : !property ? (
          <p>Cargando propiedad…</p>
        ) : (
          <>
            <div className="detail-heading">
              <div>
                <p className="eyebrow">
                  {labels[property.kind]} · {property.reference}
                </p>
                <h1>{property.title}</h1>
                <p>
                  {property.neighborhood}, {property.municipality}
                </p>
              </div>
              <div className="detail-price">
                {money(property.price, property.currency || "MXN")}
                <span>
                  {property.currency || "MXN"}
                  {property.operation === "rent" ? " / mes" : ""} ·{" "}
                  {property.is_presale
                    ? "Preventa"
                    : labels[property.operation]}
                </span>
              </div>
            </div>
            <PropertyPhoto property={property} />
            <div className="detail-columns">
              <section>
                <div className="detail-specs">
                  {[
                    ["Recámaras", property.bedrooms],
                    ["Baños", property.bathrooms],
                    ["Estacionamientos", property.parking],
                    [
                      "Superficie",
                      property.area_m2 ? `${property.area_m2} m²` : null,
                    ],
                  ].map(([label, value]) => (
                    <div key={String(label)}>
                      <span>{label}</span>
                      <strong>{value ?? "Por confirmar"}</strong>
                    </div>
                  ))}
                </div>
                <h2>Sobre este lugar</h2>
                <p className="description-text">
                  {property.description ||
                    "Consulta los detalles de esta propiedad con la inmobiliaria."}
                </p>
                {property.public_address && (
                  <>
                    <h2>Ubicación publicada</h2>
                    <p>{property.public_address}</p>
                  </>
                )}
                <h2>Características</h2>
                <dl className="amenities">
                  {["furnished", "accepts_pets", "near_schools"].map((key) => {
                    const value =
                      property[
                        key as "furnished" | "accepts_pets" | "near_schools"
                      ];
                    return (
                      <div key={key}>
                        <dt>{labels[key]}</dt>
                        <dd>
                          {value == null
                            ? "Por confirmar"
                            : value
                              ? "Sí"
                              : "No"}
                        </dd>
                      </div>
                    );
                  })}
                </dl>
                <PropertyExtras property={property} />
              </section>
              <aside className="detail-contact">
                <span className="eyebrow">Tu búsqueda continúa</span>
                <h2>¿Este lugar se parece a lo que buscas?</h2>
                <p>
                  Cuéntale a Maia qué te interesa o qué te gustaría cambiar.
                </p>
                <a
                  href={`/?propiedad=${property.id}#conversacion`}
                  className="button primary"
                >
                  Me interesa esta propiedad ↗
                </a>
              </aside>
            </div>
            {property.photos.length > 1 && (
              <div className="photo-gallery">
                {property.photos.slice(1).map((src, i) => (
                  <img
                    key={src}
                    src={src}
                    alt={`${property.title}, fotografía ${i + 2}`}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </main>
    </>
  );
}
