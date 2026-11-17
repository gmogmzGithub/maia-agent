"use client";
import ErrorNotice from "@/shared/components/ErrorFeedback";
import MoneyInput from "@/shared/components/MoneyInput";

import { useCallback, useEffect, useState } from "react";
import { api, type SearchResult } from "@/shared/lib/api";
import type { Catalog } from "@/shared/lib/capture";
import PropertyCard from "@/shared/components/PropertyCard";

export default function Inventory() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [currency, setCurrency] = useState("MXN");
  const [page, setPage] = useState(0);
  const load = useCallback(
    async (filters: string, offset = 0, append = false) => {
      setError("");
      setLoading(true);
      try {
        const data = await api<SearchResult>(
          `/properties?${filters}${filters ? "&" : ""}offset=${offset}`,
        );
        setResult((prev) =>
          append && prev
            ? { ...data, results: [...prev.results, ...data.results] }
            : data,
        );
        setPage(offset);
      } catch (e) {
        setError(
          e instanceof Error
            ? e.message
            : "No pudimos consultar el inventario.",
        );
      } finally {
        setLoading(false);
      }
    },
    [],
  );
  useEffect(() => {
    void load("");
    void api<Catalog>("/capture/catalog")
      .then(setCatalog)
      .catch(() => {});
  }, [load]);

  return (
    <section id="inventario" className="inventory-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Lugares para tu siguiente etapa</p>
          <h2>Explora el inventario</h2>
        </div>
        <p>
          Propiedades de nuestra inmobiliaria.
          <br />
          Información clara, a tu ritmo.
        </p>
      </div>
      <form
        className="filter-bar"
        onSubmit={(e) => {
          e.preventDefault();
          const values = new FormData(e.currentTarget);
          const params = new URLSearchParams();
          values.forEach((v, k) => {
            if (String(v).trim()) params.set(k, String(v));
          });
          if (params.get("operation") === "presale") {
            params.set("operation", "sale");
            params.set("is_presale", "true");
          }
          const q = params.toString();
          setQuery(q);
          void load(q);
        }}
      >
        <label>
          Operación
          <select name="operation">
            <option value="">Venta y renta</option>
            <option value="rent">Renta</option>
            <option value="sale">Venta</option>
            <option value="presale">Preventa</option>
          </select>
        </label>
        <label>
          Tipo
          <select name="kind">
            <option value="">Todos los inmuebles</option>
            {Object.entries(
              catalog?.kinds || {
                house: { label: "Casa" },
                apartment: { label: "Departamento" },
                land: { label: "Terreno" },
              },
            ).map(([key, value]) => (
              <option key={key} value={key}>
                {value.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Municipio
          <input
            name="municipality"
            placeholder="Todo México"
            list="municipalities"
          />
          <datalist id="municipalities">
            {["Guadalajara", "Zapopan", "Tlaquepaque", "Tonalá"].map((x) => (
              <option key={x}>{x}</option>
            ))}
          </datalist>
        </label>
        <label>
          Moneda
          <select
            name="currency"
            value={currency}
            onChange={(event) => setCurrency(event.target.value)}
          >
            <option>MXN</option>
            <option>USD</option>
          </select>
        </label>
        <label>
          Presupuesto máximo
          <MoneyInput name="max_price" currency={currency} min="0" />
        </label>
        <button className="button primary" type="submit" disabled={loading}>
          Buscar <span aria-hidden="true">↗</span>
        </button>
      </form>
      {error && (
        <ErrorNotice retry={() => void load(query, page)}>
          {error}{" "}
          <button
            className="link-button"
            onClick={() => void load(query, page)}
          >
            Reintentar
          </button>
        </ErrorNotice>
      )}
      {result && !error && (
        <p className="result-count" aria-live="polite">
          {result.total}{" "}
          {result.total === 1
            ? "propiedad encontrada"
            : "propiedades encontradas"}
        </p>
      )}
      {loading && !result && (
        <div className="empty-state">Consultando propiedades…</div>
      )}
      {result && !result.total && !error && (
        <div className="empty-state">
          <h3>Aún no hay propiedades con estos filtros.</h3>
          <p>Prueba otra búsqueda o cuéntale a Maia qué necesitas.</p>
        </div>
      )}
      {!error && (
        <div className="property-grid">
          {result?.results.map((p) => (
            <PropertyCard key={p.id} property={p} />
          ))}
        </div>
      )}
      {result?.next_offset != null && !error && (
        <div className="load-more">
          <button
            className="button secondary"
            disabled={loading}
            onClick={() => void load(query, result.next_offset!, true)}
          >
            {loading ? "Buscando…" : "Ver más propiedades"}
          </button>
        </div>
      )}
    </section>
  );
}
