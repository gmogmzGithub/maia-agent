"use client";

import { useEffect, useRef, useState } from "react";
import {
  api,
  labels,
  type Advisor,
  type Prospect,
} from "@/shared/lib/api";
import type { CaptureData, Catalog, LocationPoint } from "@/shared/lib/capture";
import ErrorNotice from "@/shared/components/ErrorFeedback";
import LocationFields from "@/shared/components/LocationFields";
import MoneyInput from "@/shared/components/MoneyInput";
import {
  closingLabels as text,
  emptyClosing,
  type Closing,
  type ClosingData,
  type ClosingList,
  type ClosingPreview,
} from "@/crm/lib/closings";
import "@/crm/styles/closings.css";

type Intent = {
  id: string;
  started_at: string;
  criteria: Record<string, unknown>;
  resolved_at: string | null;
};

function closingMoney(value: string, currency: string) {
  return new Intl.NumberFormat("es-MX", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(Number(value));
}

function Facts({
  data,
  advisors,
  prospects,
}: {
  data: ClosingData;
  advisors: Advisor[];
  prospects: Prospect[];
}) {
  return (
    <dl className="closing-facts">
      <dt>Operación</dt>
      <dd>{labels[data.operation] || "Pendiente"}</dd>
      <dt>Precio final</dt>
      <dd>
        {data.price
          ? closingMoney(data.price, data.currency || "MXN")
          : "Desconocido"}{" "}
        {data.currency}
        {data.operation === "rent" ? " / mes" : ""}
      </dd>
      <dt>Fecha real</dt>
      <dd>
        {[data.day, data.month, data.year].map((v) => v ?? "?").join("/")}
      </dd>
      <dt>Tipo</dt>
      <dd>
        {labels[data.kind] || "Pendiente"}
        {data.subtype ? ` · ${data.subtype}` : ""}
      </dd>
      <dt>Zona</dt>
      <dd>
        {[data.zone, data.municipality, data.state]
          .filter(Boolean)
          .join(", ") || "Pendiente"}
      </dd>
      <dt>Dirección privada</dt>
      <dd>
        {data.address_mode === "rural"
          ? [data.rural_identification, data.rural_reference]
              .filter(Boolean)
              .join(" · ")
          : data.address_text || [
              data.street,
              data.exterior_number,
              data.interior_number && `Int. ${data.interior_number}`,
            ]
              .filter(Boolean)
              .join(" ") || "Pendiente"}
      </dd>
      {(["land_m2", "construction_m2", "private_m2"] as const).map((key) => (
        <span className="closing-fact" key={key}>
          <dt>{text[key]}</dt>
          <dd>{data[key] ?? "Desconocida"}</dd>
        </span>
      ))}
      <dt>Cargos</dt>
      <dd>
        {data.charges_status === "unknown" ? (
          "Desglose desconocido"
        ) : data.charges_status === "none" ? (
          "Sin cargos adicionales"
        ) : (
          <ul>
            {data.charges.map((row, i) => (
              <li key={i}>
                {row.concept}: {closingMoney(row.amount || "0", row.currency)}{" "}
                {row.currency}
              </li>
            ))}
          </ul>
        )}
      </dd>
      {(["bedrooms", "bathrooms", "half_bathrooms", "parking"] as const).map(
        (key) => (
          <span className="closing-fact" key={key}>
            <dt>{text[`characteristics.${key}`]}</dt>
            <dd>
              {data.characteristics.not_applicable.includes(key)
                ? "No aplica"
                : (data.characteristics[key] ?? "Desconocido")}
            </dd>
          </span>
        ),
      )}
      <dt>Antigüedad al cierre</dt>
      <dd>
        {data.characteristics.age_type === "years"
          ? `${data.characteristics.age_years ?? "?"} años`
          : data.characteristics.age_type === "new"
            ? "Nuevo"
            : data.characteristics.age_type === "construction"
              ? "En construcción"
              : "Desconocida"}
      </dd>
      <dt>Conservación</dt>
      <dd>{data.characteristics.condition || "Desconocida"}</dd>
      <dt>Amenidades</dt>
      <dd>
        {data.characteristics.amenities === null
          ? "Desconocidas"
          : data.characteristics.amenities.join(", ") || "Ninguna"}
      </dd>
      <dt>Asesor responsable</dt>
      <dd>
        {advisors.find((a) => a.id === data.responsible_id)?.name ||
          (data.responsible_id ? `Asesor ${data.responsible_id}` : "Pendiente")}
      </dd>
      <dt>Comprador o arrendatario</dt>
      <dd>
        {prospects.find((p) => p.id === data.buyer_id)?.name ||
          prospects.find((p) => p.id === data.buyer_id)?.phone ||
          (data.buyer_id ? `Contacto ${data.buyer_id}` : "Sin vincular")}
      </dd>
      <dt>Referencia o notas</dt>
      <dd>{data.notes || "Sin notas"}</dd>
    </dl>
  );
}

export default function Closings({
  initialOfferId,
  onInventoryChange,
}: {
  initialOfferId: number | null;
  onInventoryChange: () => void;
}) {
  const [list, setList] = useState<ClosingList | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [advisors, setAdvisors] = useState<Advisor[]>([]);
  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [selected, setSelected] = useState<Closing | null>(null);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(false);
  const [data, setData] = useState<ClosingData>(structuredClone(emptyClosing));
  const [origin, setOrigin] = useState("historical");
  const [offerId, setOfferId] = useState<number | null>(null);
  const [identity, setIdentity] = useState("");
  const [identityQuery, setIdentityQuery] = useState("");
  const [identities, setIdentities] = useState<{ id: string; label: string }[]>(
    [],
  );
  const [location, setLocation] = useState<LocationPoint | null>(null);
  const [locationData, setLocationData] = useState<CaptureData>({});
  const [locationPending, setLocationPending] = useState(false);
  const [preview, setPreview] = useState<ClosingPreview | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [reason, setReason] = useState("");
  const [reverseDate, setReverseDate] = useState("");
  const [intents, setIntents] = useState<Intent[]>([]);
  const [intentId, setIntentId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [filters, setFilters] = useState({
    status: "",
    operation: "",
    kind: "",
    state: "",
    municipality: "",
    zone: "",
    year: "",
    is_test: "",
  });
  const [offset, setOffset] = useState(0);
  const sequence = useRef(0);
  const priorWrite = useRef<{ payload: string; key: string } | null>(null);
  const startedOffer = useRef<number | null>(null);
  function rememberSelection(id: string | null) {
    const url = new URL(window.location.href);
    url.searchParams.delete("closing_offer");
    if (id) url.searchParams.set("closing", id);
    else url.searchParams.delete("closing");
    window.history.replaceState(null, "", url);
  }

  function fail(e: unknown) {
    setError(
      e instanceof Error ? e.message : "No pudimos completar la operación.",
    );
  }
  async function reload() {
    const query = new URLSearchParams({ ...filters, offset: String(offset) });
    setList(await api<ClosingList>(`/crm/closings?${query}`));
  }
  async function write<T>(
    path: string,
    payload: Record<string, unknown>,
  ): Promise<T> {
    const signature = JSON.stringify({ path, payload });
    if (priorWrite.current?.payload !== signature)
      priorWrite.current = { payload: signature, key: crypto.randomUUID() };
    const result = await api<T>(path, {
      method: "POST",
      body: JSON.stringify({ ...payload, request_id: priorWrite.current.key }),
    });
    priorWrite.current = null;
    return result;
  }
  useEffect(() => {
    let active = true;
    Promise.all([
      api<Catalog>("/capture/catalog"),
      api<Advisor[]>("/crm/advisors"),
      api<Prospect[]>("/crm/prospects"),
    ])
      .then(([c, a, p]) => {
        if (active) {
          setCatalog(c);
          setAdvisors(a);
          setProspects(p);
        }
      })
      .catch(fail);
    return () => {
      active = false;
      sequence.current++;
    };
  }, []);
  useEffect(() => {
    let active = true;
    const query = new URLSearchParams({ ...filters, offset: String(offset) });
    api<ClosingList>(`/crm/closings?${query}`)
      .then((row) => {
        if (active) setList(row);
      })
      .catch(fail);
    return () => {
      active = false;
    };
  }, [filters, offset]);
  useEffect(() => {
    let active = true;
    const timer = setTimeout(() => {
      api<{ items: { id: string; label: string }[] }>(
        `/crm/closings/identities?q=${encodeURIComponent(identityQuery)}`,
      )
        .then((row) => {
          if (active) setIdentities(row.items);
        })
        .catch(fail);
    }, 250);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [identityQuery, creating, selected?.id]);
  useEffect(() => {
    let active = true;
    setIntentId("");
    setIntents([]);
    if (
      selected?.data.buyer_id &&
      selected.status === "confirmed" &&
      selected.origin === "current"
    ) {
      api<{ items: Intent[] }>(
        `/crm/closings/searches?prospect_id=${selected.data.buyer_id}`,
      )
        .then((row) => {
          if (active) setIntents(row.items);
        })
        .catch(fail);
    }
    return () => {
      active = false;
    };
  }, [selected?.id, selected?.revision]);

  function begin() {
    rememberSelection(null);
    sequence.current++;
    setSelected(null);
    setCreating(true);
    setEditing(false);
    setPreview(null);
    setData(structuredClone(emptyClosing));
    setOrigin("historical");
    setOfferId(null);
    setIdentity("");
    setLocation(null);
    setLocationData({});
    setError("");
    setNotice("");
    setReason("");
  }
  async function fromOffer(id: number) {
    begin();
    const ticket = sequence.current;
    setBusy(true);
    try {
      const value = await api<{
        data: ClosingData;
        address_to_review: string;
        physical_property_id: string | null;
      }>(`/crm/closings/offers/${id}/proposal`);
      if (sequence.current !== ticket) return;
      setOrigin("current");
      setOfferId(id);
      setIdentity(value.physical_property_id || "");
      setData(value.data);
      setLocationData({ private_address: value.address_to_review });
      if (value.address_to_review)
        setNotice(
          `Dirección de la ficha para revisar: ${value.address_to_review}. Confirma calle y números por separado.`,
        );
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (initialOfferId && initialOfferId !== startedOffer.current) {
      startedOffer.current = initialOfferId;
      void fromOffer(initialOfferId);
    }
    return () => {
      startedOffer.current = null;
    };
  }, [initialOfferId]);
  async function open(id: string) {
    const ticket = ++sequence.current;
    setBusy(true);
    setError("");
    setPreview(null);
    setCreating(false);
    setEditing(false);
    setReason("");
    try {
      const row = await api<Closing>(`/crm/closings/${id}`);
      if (sequence.current === ticket) {
        setSelected(row);
        rememberSelection(row.id);
        setIdentity("");
        setData(structuredClone(row.data));
        setLocationData({});
        setLocation(null);
      }
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("closing");
    if (id) void open(id);
  }, []);
  async function save() {
    setBusy(true);
    setError("");
    try {
      const row = creating
        ? await write<Closing>("/crm/closings", {
            data,
            origin,
            offer_id: offerId,
            physical_property_id: identity || null,
          })
        : await api<Closing>(`/crm/closings/${selected!.id}`, {
            method: "PUT",
            body: JSON.stringify({ revision: selected!.revision, data }),
          });
      setSelected(row);
      rememberSelection(row.id);
      setData(structuredClone(row.data));
      setCreating(false);
      setEditing(false);
      setPreview(null);
      setNotice("Borrador guardado.");
      await reload();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function act(action: string) {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      const row = await write<Closing>(`/crm/closings/${selected.id}/actions`, {
        action,
        revision: selected.revision,
        ...(action === "confirm"
          ? {
              preview_token: preview?.preview_token,
              reviewed_duplicates: preview?.duplicates,
            }
          : { reason }),
        ...(action === "correct" ? { data } : {}),
        ...(action === "reverse" ? { reversal_date: reverseDate } : {}),
      });
      setSelected(row);
      rememberSelection(row.id);
      setData(structuredClone(row.data));
      setEditing(false);
      setPreview(null);
      setReason("");
      setNotice(`${text[action]} registrada.`);
      await reload();
      onInventoryChange();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  function set<K extends keyof ClosingData>(key: K, value: ClosingData[K]) {
    setData((prev) => ({ ...prev, [key]: value }));
    setPreview(null);
  }
  const editable = creating || editing;
  const mayEdit =
    !!selected &&
    (selected.status === "draft"
      ? selected.author_id === list?.user_id || list?.admin
      : list?.can_confirm && selected.status === "confirmed");
  const mapData: CaptureData = {
    ...locationData,
    state: data.state,
    municipality: data.municipality,
    neighborhood: data.zone,
    kind: data.kind,
    location_mode: data.address_mode === "rural" ? "reference" : "address",
    location_reference: data.access_notes,
  };

  return (
    <section className="closings" aria-label="Registro de cierres">
      {error && <ErrorNotice>{error}</ErrorNotice>}
      {notice && (
        <p role="status" className="notice">
          {notice}
        </p>
      )}
      <div className="crm-actions">
        <button className="button primary" disabled={busy} onClick={begin}>
          + Operación histórica
        </button>
      </div>
      <div className="closing-layout" data-detail={!!selected || creating}>
        <aside>
          <h2>Cierres registrados</h2>
          <div className="closing-filters">
            <label>
              Estado
              <select
                value={filters.status}
                onChange={(e) => {
                  setOffset(0);
                  setFilters({ ...filters, status: e.target.value });
                }}
              >
                <option value="">Todos</option>
                {["draft", "confirmed", "annulled", "reversed"].map((v) => (
                  <option key={v} value={v}>
                    {text[v]}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Operación
              <select
                value={filters.operation}
                onChange={(e) => {
                  setOffset(0);
                  setFilters({ ...filters, operation: e.target.value });
                }}
              >
                <option value="">Todas</option>
                <option value="sale">Venta</option>
                <option value="rent">Renta</option>
              </select>
            </label>
            <label>
              Tipo
              <select
                value={filters.kind}
                onChange={(e) => {
                  setOffset(0);
                  setFilters({ ...filters, kind: e.target.value });
                }}
              >
                <option value="">Todos</option>
                {Object.entries(catalog?.kinds || {}).map(([key, value]) => (
                  <option key={key} value={key}>
                    {value.label}
                  </option>
                ))}
              </select>
            </label>
            {(["state", "municipality", "zone", "year"] as const).map((key) => (
              <label key={key}>
                {text[key]}
                <input
                  value={filters[key]}
                  type={key === "year" ? "number" : "search"}
                  onChange={(e) => {
                    setOffset(0);
                    setFilters({ ...filters, [key]: e.target.value });
                  }}
                />
              </label>
            ))}
            <label>
              Registros de prueba
              <select
                value={filters.is_test}
                onChange={(e) => {
                  setOffset(0);
                  setFilters({ ...filters, is_test: e.target.value });
                }}
              >
                <option value="">Todos</option>
                <option value="false">Operaciones reales</option>
                <option value="true">Solo pruebas</option>
              </select>
            </label>
          </div>
          <p>{list?.count ?? 0} registros</p>
          {list?.items.map((row) => (
            <button
              className={`closing-item ${selected?.id === row.id ? "active" : ""}`}
              disabled={busy}
              key={row.id}
              onClick={() => void open(row.id)}
            >
              <strong>
                {row.data.zone || "Sin zona"} ·{" "}
                {labels[row.data.kind] || "Sin tipo"}
              </strong>
              <span>
                {text[row.status]} ·{" "}
                {labels[row.data.operation] || "Sin operación"}
                {row.data.is_test ? " · PRUEBA" : ""}
              </span>
              <span>
                {row.data.price
                  ? closingMoney(row.data.price, row.data.currency || "MXN")
                  : "Precio pendiente"}{" "}
                · {row.data.year || "Sin fecha"}
              </span>
            </button>
          ))}
          {!list?.items.length && <p>No hay cierres con estos filtros.</p>}
          <div className="crm-actions">
            <button
              disabled={offset === 0 || busy}
              onClick={() => setOffset(Math.max(0, offset - 50))}
            >
              Anterior
            </button>
            <button
              disabled={!list || offset + 50 >= list.count || busy}
              onClick={() => setOffset(offset + 50)}
            >
              Siguiente
            </button>
          </div>
        </aside>
        <div className="closing-detail">
          {editable ? (
            <form
              noValidate
              onSubmit={(e) => {
                e.preventDefault();
                if (selected?.status === "confirmed") void act("correct");
                else void save();
              }}
              className="editor"
            >
              <h2>
                {creating
                  ? origin === "current"
                    ? "Cierre de oferta actual"
                    : "Operación histórica"
                  : selected?.status === "confirmed"
                    ? "Corregir cierre"
                    : "Editar borrador"}
              </h2>
              <p>
                El vendedor confirma los datos. Guarda un borrador si todavía
                falta información.
              </p>
              <fieldset disabled={busy}>
                <div className="form-grid">
                  {creating && !offerId && (
                    <div className="full">
                      <label>
                        Buscar inmueble existente
                        <input
                          value={identityQuery}
                          onChange={(e) => setIdentityQuery(e.target.value)}
                          placeholder="Colonia, calle o referencia"
                        />
                      </label>
                      <label>
                        Identidad del inmueble
                        <select
                          value={identity}
                          onChange={(e) => setIdentity(e.target.value)}
                        >
                          <option value="">Crear inmueble nuevo</option>
                          {identities.map((v) => (
                            <option key={v.id} value={v.id}>
                              {v.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <small>
                        Revisa las coincidencias antes de crear otra identidad.
                      </small>
                    </div>
                  )}
                  <label>
                    Operación
                    <select
                      value={data.operation}
                      onChange={(e) => set("operation", e.target.value)}
                    >
                      <option value="">Pendiente</option>
                      <option value="sale">Venta</option>
                      <option value="rent">Renta</option>
                    </select>
                  </label>
                  <label>
                    Tipo
                    <select
                      value={data.kind}
                      onChange={(e) => {
                        set("kind", e.target.value);
                        set("subtype", "");
                      }}
                    >
                      <option value="">Pendiente</option>
                      {Object.entries(catalog?.kinds || {}).map(
                        ([key, value]) => (
                          <option key={key} value={key}>
                            {value.label}
                          </option>
                        ),
                      )}
                    </select>
                  </label>
                  <label>
                    Subtipo
                    <select
                      value={data.subtype}
                      onChange={(e) => set("subtype", e.target.value)}
                    >
                      <option value="">Sin especificar</option>
                      {catalog?.kinds[data.kind]?.subtypes.map((v) => (
                        <option key={v}>{v}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Asesor responsable
                    <select
                      value={data.responsible_id || ""}
                      onChange={(e) =>
                        set(
                          "responsible_id",
                          e.target.value ? Number(e.target.value) : null,
                        )
                      }
                    >
                      <option value="">Pendiente</option>
                      {advisors.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Moneda
                    <select
                      value={data.currency}
                      onChange={(e) => set("currency", e.target.value)}
                    >
                      <option value="">Pendiente</option>
                      <option>MXN</option>
                      <option>USD</option>
                    </select>
                  </label>
                  <label>
                    {data.operation === "rent"
                      ? "Mensualidad base final"
                      : "Precio final de venta"}
                    <MoneyInput
                      currency={data.currency || "MXN"}
                      value={data.price || ""}
                      min="0.01"
                      onValueChange={(v) => set("price", v || null)}
                    />
                  </label>
                  {(["year", "month", "day"] as const).map((key) => (
                    <label key={key}>
                      {text[key]} de{" "}
                      {data.operation === "rent"
                        ? "firma del contrato"
                        : "firma de escritura"}
                      <input
                        type="number"
                        min="1"
                        max={key === "year" ? 9999 : key === "month" ? 12 : 31}
                        value={data[key] ?? ""}
                        onChange={(e) =>
                          set(
                            key,
                            e.target.value === ""
                              ? null
                              : Number(e.target.value),
                          )
                        }
                      />
                    </label>
                  ))}
                  <label>
                    Tipo de zona
                    <select
                      value={data.zone_type}
                      onChange={(e) => set("zone_type", e.target.value)}
                    >
                      <option value="">Pendiente</option>
                      <option value="colonia">Colonia</option>
                      <option value="barrio">Barrio</option>
                      <option value="localidad">Localidad</option>
                    </select>
                  </label>
                  <div className="full">
                    <LocationFields
                      data={mapData}
                      states={catalog?.states || []}
                      location={location}
                      signedIn
                      onLocation={setLocation}
                      onPendingChange={setLocationPending}
                      onChange={(v) => {
                        setLocationData(v);
                        setData((prev) => ({
                          ...prev,
                          state: String(v.state || ""),
                          municipality: String(v.municipality || ""),
                          zone: String(v.neighborhood || ""),
                          address_mode:
                            v.location_mode === "reference" ? "rural" : "urban",
                          access_notes: String(v.location_reference || ""),
                        }));
                      }}
                    />
                  </div>
                  <label>
                    Identificación
                    <select
                      value={data.address_mode}
                      onChange={(e) => set("address_mode", e.target.value)}
                    >
                      <option value="urban">Dirección urbana</option>
                      <option value="rural">Identificación rural</option>
                    </select>
                  </label>
                  {data.address_mode === "urban" ? (
                    <>
                      <label>
                        Calle
                        <input
                          value={data.street}
                          maxLength={240}
                          onChange={(e) => set("street", e.target.value)}
                        />
                      </label>
                      <label>
                        Número exterior
                        <input
                          value={data.exterior_number}
                          maxLength={40}
                          onChange={(e) =>
                            set("exterior_number", e.target.value)
                          }
                        />
                      </label>
                      <label>
                        ¿Tiene interior?
                        <select
                          value={
                            data.interior_applicable == null
                              ? ""
                              : String(data.interior_applicable)
                          }
                          onChange={(e) => {
                            set(
                              "interior_applicable",
                              e.target.value === ""
                                ? null
                                : e.target.value === "true",
                            );
                            if (e.target.value !== "true")
                              set("interior_number", "");
                          }}
                        >
                          <option value="">Pendiente de confirmar</option>
                          <option value="false">No aplica</option>
                          <option value="true">Sí</option>
                        </select>
                      </label>
                      {data.interior_applicable && (
                        <label>
                          Número interior
                          <input
                            value={data.interior_number}
                            maxLength={40}
                            onChange={(e) =>
                              set("interior_number", e.target.value)
                            }
                          />
                        </label>
                      )}
                    </>
                  ) : (
                    <>
                      {(
                        [
                          "rural_identification",
                          "rural_reference",
                          "access_notes",
                        ] as const
                      ).map((key) => (
                        <label key={key}>
                          {key === "access_notes"
                            ? "Acceso (opcional)"
                            : text[key]}
                          <textarea
                            maxLength={500}
                            value={data[key]}
                            onChange={(e) => set(key, e.target.value)}
                          />
                        </label>
                      ))}
                    </>
                  )}
                  {(["land_m2", "construction_m2", "private_m2"] as const).map(
                    (key) => (
                      <label key={key}>
                        {text[key]}
                        <input
                          type="number"
                          min="0.01"
                          step="0.01"
                          value={data[key] ?? ""}
                          onChange={(e) => set(key, e.target.value || null)}
                        />
                        <small>Vacío significa desconocido.</small>
                      </label>
                    ),
                  )}
                  {(
                    [
                      "bedrooms",
                      "bathrooms",
                      "half_bathrooms",
                      "parking",
                    ] as const
                  ).map((key) => (
                    <label key={key}>
                      {text[`characteristics.${key}`]}
                      <input
                        type="number"
                        min="0"
                        step={key === "bathrooms" ? "0.5" : "1"}
                        disabled={data.characteristics.not_applicable.includes(
                          key,
                        )}
                        value={data.characteristics[key] ?? ""}
                        onChange={(e) =>
                          set("characteristics", {
                            ...data.characteristics,
                            [key]:
                              e.target.value === ""
                                ? null
                                : key === "bathrooms"
                                  ? e.target.value
                                  : Number(e.target.value),
                          })
                        }
                      />
                      <span>
                        <input
                          type="checkbox"
                          checked={data.characteristics.not_applicable.includes(
                            key,
                          )}
                          onChange={(e) =>
                            set("characteristics", {
                              ...data.characteristics,
                              [key]: null,
                              not_applicable: e.target.checked
                                ? [...data.characteristics.not_applicable, key]
                                : data.characteristics.not_applicable.filter(
                                    (v) => v !== key,
                                  ),
                            })
                          }
                        />{" "}
                        No aplica
                      </span>
                    </label>
                  ))}
                  <label>
                    Antigüedad
                    <select
                      value={data.characteristics.age_type}
                      onChange={(e) =>
                        set("characteristics", {
                          ...data.characteristics,
                          age_type: e.target.value,
                          age_years: null,
                        })
                      }
                    >
                      <option value="">Desconocida</option>
                      <option value="new">Nuevo</option>
                      <option value="years">Años conocidos</option>
                      <option value="construction">En construcción</option>
                    </select>
                  </label>
                  {data.characteristics.age_type === "years" && (
                    <label>
                      Años al cierre
                      <input
                        type="number"
                        min="0"
                        max="1000"
                        value={data.characteristics.age_years ?? ""}
                        onChange={(e) =>
                          set("characteristics", {
                            ...data.characteristics,
                            age_years:
                              e.target.value === ""
                                ? null
                                : Number(e.target.value),
                          })
                        }
                      />
                    </label>
                  )}
                  <label>
                    Conservación
                    <select
                      value={data.characteristics.condition}
                      onChange={(e) =>
                        set("characteristics", {
                          ...data.characteristics,
                          condition: e.target.value,
                        })
                      }
                    >
                      <option value="">Desconocida</option>
                      {catalog?.conditions.map((v) => (
                        <option key={v}>{v}</option>
                      ))}
                    </select>
                  </label>
                  <div className="full">
                    <h3>Amenidades al cierre</h3>
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={data.characteristics.amenities !== null}
                        onChange={(e) =>
                          set("characteristics", {
                            ...data.characteristics,
                            amenities: e.target.checked ? [] : null,
                          })
                        }
                      />{" "}
                      Conozco las amenidades (ninguna marcada significa que no
                      tenía)
                    </label>
                    {data.characteristics.amenities !== null &&
                      Object.entries(catalog?.amenities || {}).map(
                        ([group, values]) => (
                          <fieldset key={group}>
                            <legend>{group}</legend>
                            <div className="closing-checks">
                              {values.map((v) => (
                                <label className="check" key={v}>
                                  <input
                                    type="checkbox"
                                    checked={
                                      data.characteristics.amenities?.includes(
                                        v,
                                      ) || false
                                    }
                                    onChange={(e) =>
                                      set("characteristics", {
                                        ...data.characteristics,
                                        amenities: e.target.checked
                                          ? [
                                              ...(data.characteristics
                                                .amenities || []),
                                              v,
                                            ]
                                          : (
                                              data.characteristics.amenities ||
                                              []
                                            ).filter((a) => a !== v),
                                      })
                                    }
                                  />
                                  {v}
                                </label>
                              ))}
                            </div>
                          </fieldset>
                        ),
                      )}
                  </div>
                  <label>
                    Cargos adicionales
                    <select
                      value={data.charges_status}
                      onChange={(e) =>
                        setData((prev) => ({
                          ...prev,
                          charges_status: e.target.value,
                          charges:
                            e.target.value === "itemized"
                              ? [
                                  {
                                    concept: "",
                                    amount: "",
                                    currency: data.currency || "MXN",
                                  },
                                ]
                              : [],
                        }))
                      }
                    >
                      <option value="unknown">Desglose desconocido</option>
                      <option value="none">Sin cargos adicionales</option>
                      <option value="itemized">Registrar desglose</option>
                    </select>
                  </label>
                  {data.charges_status === "itemized" && (
                    <div className="full">
                      {data.charges.map((c, i) => (
                        <div className="closing-charge" key={i}>
                          <label>
                            Concepto
                            <input
                              value={c.concept}
                              maxLength={120}
                              onChange={(e) =>
                                set(
                                  "charges",
                                  data.charges.map((v, j) =>
                                    j === i
                                      ? { ...v, concept: e.target.value }
                                      : v,
                                  ),
                                )
                              }
                            />
                          </label>
                          <label>
                            Importe
                            <MoneyInput
                              currency={c.currency}
                              value={c.amount}
                              onValueChange={(v) =>
                                set(
                                  "charges",
                                  data.charges.map((row, j) =>
                                    j === i ? { ...row, amount: v } : row,
                                  ),
                                )
                              }
                            />
                          </label>
                          <label>
                            Moneda
                            <select
                              value={c.currency}
                              onChange={(e) =>
                                set(
                                  "charges",
                                  data.charges.map((v, j) =>
                                    j === i
                                      ? { ...v, currency: e.target.value }
                                      : v,
                                  ),
                                )
                              }
                            >
                              <option>MXN</option>
                              <option>USD</option>
                            </select>
                          </label>
                          <button
                            type="button"
                            onClick={() =>
                              set(
                                "charges",
                                data.charges.filter((_, j) => j !== i),
                              )
                            }
                          >
                            Quitar
                          </button>
                        </div>
                      ))}
                      <button
                        type="button"
                        onClick={() =>
                          set("charges", [
                            ...data.charges,
                            {
                              concept: "",
                              amount: "",
                              currency: data.currency || "MXN",
                            },
                          ])
                        }
                      >
                        + Agregar cargo
                      </button>
                    </div>
                  )}
                  <label>
                    Comprador o arrendatario (opcional)
                    <select
                      value={data.buyer_id || ""}
                      onChange={(e) =>
                        set(
                          "buyer_id",
                          e.target.value ? Number(e.target.value) : null,
                        )
                      }
                    >
                      <option value="">Sin vincular</option>
                      {prospects.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name || p.phone}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={data.is_test}
                      onChange={(e) => set("is_test", e.target.checked)}
                    />{" "}
                    Registro de prueba (las acciones siguen siendo reales)
                  </label>
                  <label className="full">
                    Referencia o notas (opcional)
                    <textarea
                      maxLength={2000}
                      value={data.notes}
                      onChange={(e) => set("notes", e.target.value)}
                    />
                  </label>
                  {selected?.status === "confirmed" && (
                    <label className="full">
                      Motivo de la corrección
                      <textarea
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                        maxLength={1000}
                      />
                    </label>
                  )}
                </div>
              </fieldset>
              <div className="form-actions">
                <button
                  disabled={busy || locationPending}
                  className="button primary"
                >
                  {busy
                    ? "Guardando…"
                    : selected?.status === "confirmed"
                      ? "Guardar corrección con historial"
                      : "Guardar borrador"}
                </button>
                <button
                  type="button"
                  className="button secondary"
                  disabled={busy}
                  onClick={() => {
                    setEditing(false);
                    setCreating(false);
                    if (selected) setData(structuredClone(selected.data));
                  }}
                >
                  Cancelar
                </button>
              </div>
            </form>
          ) : selected ? (
            <article className="editor">
              <h2>
                {text[selected.status]}
                {selected.data.is_test ? " · Registro de prueba" : ""}
              </h2>
              <p>
                {selected.origin === "historical"
                  ? "Carga histórica"
                  : `Oferta ${selected.offer_id}`}{" "}
                · Revisión {selected.revision}
              </p>
              <Facts
                data={selected.data}
                advisors={advisors}
                prospects={prospects}
              />
              {selected.missing_characteristics.length > 0 && (
                <p className="notice">
                  Características pendientes:{" "}
                  {selected.missing_characteristics
                    .map((k) => text[k] || k)
                    .join(", ")}
                </p>
              )}
              {selected.data.notes && (
                <p>Referencia o notas: {selected.data.notes}</p>
              )}
              <div className="crm-actions">
                {mayEdit && (
                  <button
                    disabled={busy}
                    className="button secondary"
                    onClick={() => {
                      setData(structuredClone(selected.data));
                      setEditing(true);
                    }}
                  >
                    {" "}
                    {selected.status === "draft"
                      ? "Editar borrador"
                      : "Corregir con historial"}
                  </button>
                )}
                {selected.status === "draft" && list?.can_confirm && (
                  <button
                    disabled={busy}
                    className="button primary"
                    onClick={async () => {
                      setBusy(true);
                      try {
                        setPreview(
                          await api<ClosingPreview>(
                            `/crm/closings/${selected.id}/preview`,
                          ),
                        );
                        setReviewed(false);
                      } catch (e) {
                        fail(e);
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    Revisar para confirmar
                  </button>
                )}
                {selected.status === "draft" && mayEdit && (
                  <button
                    disabled={busy}
                    onClick={async () => {
                      if (
                        !window.confirm(
                          "¿Borrar este borrador nunca confirmado?",
                        )
                      )
                        return;
                      setBusy(true);
                      try {
                        await api(`/crm/closings/${selected.id}`, {
                          method: "DELETE",
                          body: JSON.stringify({ revision: selected.revision }),
                        });
                        setSelected(null);
                        await reload();
                      } catch (e) {
                        fail(e);
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    Borrar borrador
                  </button>
                )}
              </div>
              {preview && (
                <section className="closing-preview">
                  <h3>Resumen de confirmación</h3>
                  <Facts
                    data={preview.data}
                    advisors={advisors}
                    prospects={prospects}
                  />
                  <p>
                    {preview.effects.ends_offer
                      ? `Se despublicará únicamente la oferta ${preview.effects.ends_offer} y terminará su comercialización y exclusividad vigente.`
                      : "Carga histórica: no modifica ofertas ni seguimientos actuales."}
                  </p>
                  {preview.missing_required.length > 0 && (
                    <p role="alert">
                      Faltan datos obligatorios:{" "}
                      {preview.missing_required
                        .map((k) => text[k] || k)
                        .join(", ")}
                    </p>
                  )}
                  {preview.duplicates.length > 0 && (
                    <div className="notice">
                      <strong>
                        Posibles duplicados. Revisa cada registro:
                      </strong>
                      {preview.duplicates.map((id) => (
                        <p key={id}>
                          <a
                            target="_blank"
                            rel="noopener noreferrer"
                            href={`/crm?closing=${id}`}
                          >
                            Abrir cierre {id.slice(0, 8)}
                          </a>
                        </p>
                      ))}
                    </div>
                  )}
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={reviewed}
                      onChange={(e) => setReviewed(e.target.checked)}
                    />{" "}
                    Revisé los datos, los faltantes y las posibles
                    coincidencias. Confirmo que la operación ocurrió.
                  </label>
                  <button
                    disabled={
                      busy || !reviewed || !!preview.missing_required.length
                    }
                    className="button primary"
                    onClick={() => void act("confirm")}
                  >
                    Confirmar cierre
                  </button>
                </section>
              )}
              {list?.can_confirm &&
                ["confirmed", "annulled"].includes(selected.status) && (
                  <section>
                    <h3>
                      {selected.status === "confirmed"
                        ? "Cambios del cierre"
                        : "Reapertura por error"}
                    </h3>
                    <label>
                      Motivo
                      <textarea
                        maxLength={1000}
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                      />
                    </label>
                    {selected.status === "confirmed" ? (
                      <>
                        <p>
                          Anular: la operación nunca ocurrió. Revertir: sí
                          ocurrió y después se deshizo.
                        </p>
                        <div className="crm-actions">
                          <button
                            disabled={busy || !reason.trim()}
                            onClick={() => void act("annul")}
                          >
                            Anular registro erróneo
                          </button>
                          <label>
                            Fecha de reversión
                            <input
                              type="date"
                              value={reverseDate}
                              onChange={(e) => setReverseDate(e.target.value)}
                            />
                          </label>
                          <button
                            disabled={busy || !reason.trim() || !reverseDate}
                            onClick={() => void act("reverse")}
                          >
                            Registrar reversión
                          </button>
                        </div>
                      </>
                    ) : (
                      selected.origin === "current" && (
                        <>
                          <p>
                            La oferta seguirá despublicada hasta completar las
                            condiciones de publicación y exclusividad.
                          </p>
                          <button
                            disabled={
                              busy ||
                              !reason.trim() ||
                              selected.offer_periods?.some(
                                (p) => !!p.reopened_at,
                              )
                            }
                            onClick={() => void act("reopen")}
                          >
                            Reabrir oferta expresamente
                          </button>
                        </>
                      )
                    )}
                  </section>
                )}
              {list?.can_confirm &&
                selected.status === "confirmed" &&
                selected.origin === "current" &&
                selected.data.buyer_id && (
                  <section>
                    <h3>Búsqueda del comprador o arrendatario</h3>
                    <p>
                      Selecciona únicamente la búsqueda que quedó atendida. El
                      permiso general de contacto se conserva.
                    </p>
                    <label>
                      Búsqueda
                      <select
                        value={intentId}
                        onChange={(e) => setIntentId(e.target.value)}
                      >
                        <option value="">Seleccionar</option>
                        {intents.map((i) => (
                          <option
                            key={i.id}
                            value={i.id}
                            disabled={!!i.resolved_at}
                          >
                            {new Date(i.started_at).toLocaleDateString("es-MX")}{" "}
                            ·{" "}
                            {Object.values(i.criteria)
                              .filter((v) => typeof v === "string")
                              .join(" · ")}
                            {i.resolved_at ? " · Atendida" : ""}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button
                      disabled={busy || !intentId}
                      onClick={async () => {
                        setBusy(true);
                        try {
                          await write(`/crm/closings/${selected.id}/actions`, {
                            action: "resolve_search",
                            intent_id: intentId,
                          });
                          setIntents((prev) =>
                            prev.map((v) =>
                              v.id === intentId
                                ? {
                                    ...v,
                                    resolved_at: new Date().toISOString(),
                                  }
                                : v,
                            ),
                          );
                          setIntentId("");
                          setNotice(
                            "Búsqueda atendida; permiso de contacto conservado.",
                          );
                        } catch (e) {
                          fail(e);
                        } finally {
                          setBusy(false);
                        }
                      }}
                    >
                      Dar por atendida esta búsqueda
                    </button>
                  </section>
                )}
              {list?.can_confirm && (
                <details>
                  <summary>
                    Vincular con otro registro del mismo inmueble
                  </summary>
                  <p>
                    Confirma que se trata del mismo inmueble físico. Se
                    relacionará el historial de ambos registros y se conservarán
                    sus datos originales.
                  </p>
                  <label>
                    Buscar inmueble
                    <input
                      value={identityQuery}
                      onChange={(e) => setIdentityQuery(e.target.value)}
                    />
                  </label>
                  <label>
                    Registro del mismo inmueble
                    <select
                      value={identity}
                      onChange={(e) => setIdentity(e.target.value)}
                    >
                      <option value="">Seleccionar</option>
                      {identities
                        .filter(
                          (v) =>
                            v.id !== selected.canonical_physical_property_id,
                        )
                        .map((v) => (
                          <option key={v.id} value={v.id}>
                            {v.label}
                          </option>
                        ))}
                    </select>
                  </label>
                  <label>
                    Motivo de la vinculación
                    <textarea
                      value={reason}
                      maxLength={1000}
                      onChange={(e) => setReason(e.target.value)}
                    />
                  </label>
                  <button
                    disabled={busy || !identity || !reason.trim()}
                    onClick={async () => {
                      setBusy(true);
                      try {
                        await write("/crm/closings/identities", {
                          source_id: selected.physical_property_id,
                          target_id: identity,
                          reason,
                        });
                        await open(selected.id);
                        await reload();
                        setNotice(
                          "Identidades vinculadas con historial conservado.",
                        );
                      } catch (e) {
                        fail(e);
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    Confirmar que es el mismo inmueble
                  </button>
                </details>
              )}
              <details>
                <summary>Historial completo</summary>
                {selected.identity_links?.map((link) => (
                  <p key={link.source_id}>
                    Identidades vinculadas el{" "}
                    {new Date(link.at).toLocaleString("es-MX")} por{" "}
                    {link.actor_email || `Usuario ${link.actor_id}`}: {link.reason}. Se conservaron las
                    referencias originales.
                  </p>
                ))}
                {selected.history?.map((h) => (
                  <section className="closing-history" key={h.number}>
                    <h3>
                      {h.number}. {text[h.action] || h.action} ·{" "}
                      {new Date(h.at).toLocaleString("es-MX")}
                    </h3>
                    <p>
                      {h.actor_email || `Usuario ${h.actor_id}`}
                      {h.reason ? ` · ${h.reason}` : ""}
                    </p>
                    <Facts
                      data={h.data}
                      advisors={advisors}
                      prospects={prospects}
                    />
                    {h.reversal_date && <p>Reversión: {h.reversal_date}</p>}
                  </section>
                ))}
                {selected.offer_periods?.map((p) => (
                  <p key={p.period}>
                    Periodo {p.period}: cerrado{" "}
                    {new Date(p.closed_at).toLocaleString("es-MX")}
                    {p.reopened_at
                      ? `; reabierto ${new Date(p.reopened_at).toLocaleString("es-MX")} por ${p.reopened_by_id}: ${p.reason}`
                      : ""}
                  </p>
                ))}
              </details>
            </article>
          ) : (
            <div className="empty-state">
              <h2>Conserva las operaciones realizadas.</h2>
              <p>
                Selecciona un cierre, registra una operación histórica o parte
                de una oferta actual.
              </p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
