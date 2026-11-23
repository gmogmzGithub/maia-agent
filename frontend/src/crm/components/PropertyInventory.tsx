"use client";
import ErrorNotice from "@/shared/components/ErrorFeedback";

import { useState } from "react";
import { api, labels, money, type ManagedProperty } from "@/shared/lib/api";
import "@/crm/styles/inventory.css";

const emptyFilters = {
  query: "",
  publication: "",
  operation: "",
  kind: "",
  municipality: "",
};
const normalize = (value: string) =>
  value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();

export default function PropertyInventory({
  properties,
  onEdit,
  onOutcome,
  onChange,
}: {
  properties: ManagedProperty[];
  onEdit: (property: ManagedProperty) => void;
  onOutcome?: (
    property: ManagedProperty,
    mode: "complete" | "withdraw" | "history",
  ) => void;
  onChange: (property: ManagedProperty) => void;
}) {
  const [filters, setFilters] = useState(emptyFilters);
  const [pending, setPending] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [result, setResult] = useState("");
  const words = normalize(filters.query).trim().split(/\s+/).filter(Boolean);
  const visible = properties.filter((p) => {
    const text = normalize(
      [
        p.title,
        p.reference,
        p.neighborhood,
        p.municipality,
        p.public_address,
      ].join(" "),
    );
    return (
      words.every((word) => text.includes(word)) &&
      (!filters.publication ||
        p.published === (filters.publication === "published")) &&
      (!filters.operation || p.operation === filters.operation) &&
      (!filters.kind || p.kind === filters.kind) &&
      (!filters.municipality || p.municipality === filters.municipality)
    );
  });
  const activeFilters = Object.values(filters).some(Boolean);

  async function publish(property: ManagedProperty) {
    setPending(property.id);
    setError("");
    setResult("");
    try {
      const saved = await api<ManagedProperty>(
        `/crm/properties/${property.id}/publication`,
        {
          method: "PATCH",
          body: JSON.stringify({ published: !property.published }),
        },
      );
      onChange(saved);
      setResult(
        `${saved.title}: ${saved.published ? "publicada" : "despublicada"}.`,
      );
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "No pudimos cambiar la publicación.",
      );
    } finally {
      setPending(null);
    }
  }

  return (
    <section aria-label="Inventario de propiedades">
      <div className="inventory-filters">
        <label className="inventory-query">
          Buscar propiedad
          <input
            type="search"
            value={filters.query}
            placeholder="Nombre, referencia, colonia o dirección"
            onChange={(e) => setFilters({ ...filters, query: e.target.value })}
          />
        </label>
        {(
          [
            [
              "publication",
              "Publicación",
              [
                ["published", "Publicadas"],
                ["unpublished", "No publicadas"],
              ],
            ],
            [
              "operation",
              "Operación",
              [
                ["rent", "Renta"],
                ["sale", "Venta"],
              ],
            ],
            [
              "kind",
              "Tipo",
              [...new Set(properties.map((p) => p.kind))].map((key) => [
                key,
                labels[key] || key,
              ]),
            ],
            [
              "municipality",
              "Municipio",
              [...new Set(properties.map((p) => p.municipality))]
                .sort()
                .map((name) => [name, name]),
            ],
          ] as const
        ).map(([field, label, options]) => (
          <label key={field}>
            {label}
            <select
              value={filters[field]}
              onChange={(e) =>
                setFilters({ ...filters, [field]: e.target.value })
              }
            >
              <option value="">Todas las opciones</option>
              {options.map(([value, text]) => (
                <option key={value} value={value}>
                  {text}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      <div className="inventory-filter-summary">
        <p role="status">
          {visible.length} de {properties.length} propiedades
        </p>
        {activeFilters && (
          <button
            className="link-button"
            onClick={() => setFilters(emptyFilters)}
          >
            Limpiar filtros
          </button>
        )}
      </div>
      {error && <ErrorNotice>{error}</ErrorNotice>}
      {result && (
        <p className="inventory-action-result" role="status">
          {result}
        </p>
      )}
      {visible.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Propiedad</th>
                <th>Operación</th>
                <th>Precio</th>
                <th>Publicación</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((p) => (
                <tr key={p.id}>
                  <td>
                    <strong>{p.title}</strong>
                    <small>
                      {p.reference} · {p.neighborhood}, {p.municipality}
                      {p.origin === "easybroker" && " · EasyBroker, última oferta aplicada"}
                    </small>
                  </td>
                  <td>{labels[p.operation]}</td>
                  <td>
                    {money(p.price, p.currency || "MXN") +
                      " " +
                      (p.currency || "MXN")}
                    {p.operation === "rent" && <small>por mes</small>}
                  </td>
                  <td>
                    <span
                      className={`status-pill ${p.published ? "published" : "draft"}`}
                    >
                      {p.published ? "Publicada" : "No publicada"}
                    </span>
                    {p.commercial_status !== "available" && (
                      <small>
                        {(
                          {
                            sold: "Vendida",
                            rented: "Rentada",
                            withdrawn: "Retirada",
                          } as Record<string, string>
                        )[p.commercial_status] || "Conservada en historial"}
                      </small>
                    )}
                  </td>
                  <td>
                    <div className="inventory-row-actions">
                      <button
                        className="button secondary"
                        disabled={
                          pending !== null ||
                          p.commercial_status !== "available"
                        }
                        aria-label={`${p.published ? "Despublicar" : "Publicar"} ${p.title}`}
                        onClick={() => void publish(p)}
                      >
                        {pending === p.id
                          ? "Guardando…"
                          : p.published
                            ? "Despublicar"
                            : "Publicar"}
                      </button>
                      <button
                        className="link-button"
                        disabled={pending === p.id}
                        onClick={() => onEdit(p)}
                      >
                        Editar ↗
                      </button>
                      {onOutcome && (
                        <button
                          className="link-button"
                          onClick={() =>
                            onOutcome(
                              p,
                              p.commercial_status === "available"
                                ? "complete"
                                : "history",
                            )
                          }
                        >
                          {p.commercial_status === "available"
                            ? `Marcar ${p.operation === "sale" ? "vendida" : "rentada"}`
                            : "Ver resultado e historial"}
                        </button>
                      )}
                      {onOutcome && p.commercial_status === "available" && (
                        <button
                          className="link-button"
                          onClick={() => onOutcome(p, "withdraw")}
                        >
                          Retirar
                        </button>
                      )}
                      {onOutcome && p.commercial_status === "available" && (
                        <button
                          className="link-button"
                          onClick={() => onOutcome(p, "history")}
                        >
                          Historial
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty-state">
          <h2>No hay coincidencias.</h2>
          <p>Cambia o limpia los filtros para ver otras propiedades.</p>
        </div>
      )}
    </section>
  );
}
