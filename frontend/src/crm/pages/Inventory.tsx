"use client";
import ErrorNotice from "@/shared/components/ErrorFeedback";
import MoneyInput from "@/shared/components/MoneyInput";

import { useEffect, useState } from "react";
import Header from "@/shared/components/Header";
import {
  api,
  session,
  type Advisor,
  type ManagedProperty,
  type PropertyInput,
  type Session,
} from "@/shared/lib/api";
import Captures from "@/crm/components/Captures";
import { labels } from "@/shared/lib/api";
import Advisors from "@/crm/components/Advisors";
import Prospects from "@/crm/components/Prospects";
import Appointments from "@/crm/components/Appointments";
import PropertyInventory from "@/crm/components/PropertyInventory";
import "@/crm/styles/prospects.css";

function Editor({
  value,
  onSave,
  onCancel,
}: {
  value: ManagedProperty | null;
  onSave: () => void;
  onCancel: () => void;
}) {
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [currency, setCurrency] = useState(value?.currency || "MXN");
  const [advisors, setAdvisors] = useState<Advisor[]>([]);
  useEffect(() => {
    void api<Advisor[]>("/crm/advisors")
      .then(setAdvisors)
      .catch(() => setError("No pudimos cargar los asesores."));
  }, []);
  const triValue = (v: boolean | null | undefined) =>
    v == null ? "" : String(v);
  return (
    <form
      className="editor"
      onSubmit={async (e) => {
        e.preventDefault();
        setSaving(true);
        setError("");
        const data = new FormData(e.currentTarget);
        const optionalNumber = (k: string) =>
          data.get(k) === "" ? null : Number(data.get(k));
        const tri = (k: string) =>
          data.get(k) === "" ? null : data.get(k) === "true";
        const payload: PropertyInput = {
          title: String(data.get("title")),
          currency: (data.get("currency") ||
            value?.currency ||
            "MXN") as PropertyInput["currency"],
          state: String(data.get("state") || value?.state || ""),
          subtype: value?.subtype || "",
          is_presale: data.get("is_presale") === "on",
          operation: data.get("operation") as PropertyInput["operation"],
          kind: data.get("kind") as PropertyInput["kind"],
          municipality: data.get(
            "municipality",
          ) as PropertyInput["municipality"],
          neighborhood: String(data.get("neighborhood")),
          price: String(data.get("price")),
          public_address: String(data.get("public_address")),
          bedrooms: optionalNumber("bedrooms"),
          bathrooms: optionalNumber("bathrooms"),
          parking: optionalNumber("parking"),
          area_m2: optionalNumber("area_m2"),
          furnished: tri("furnished"),
          accepts_pets: tri("accepts_pets"),
          near_schools: tri("near_schools"),
          description: String(data.get("description")),
          internal_notes: String(data.get("internal_notes")),
          photos: String(data.get("photos"))
            .split("\n")
            .map((x) => x.trim())
            .filter(Boolean),
          published: data.get("published") === "on",
          advisor_id: data.get("advisor_id")
            ? Number(data.get("advisor_id"))
            : null,
        };
        try {
          await api(value ? `/crm/properties/${value.id}` : "/crm/properties", {
            method: value ? "PUT" : "POST",
            body: JSON.stringify(payload),
          });
          onSave();
        } catch (e) {
          setError(
            e instanceof Error ? e.message : "No pudimos guardar la propiedad.",
          );
        } finally {
          setSaving(false);
        }
      }}
    >
      <div className="editor-heading">
        <h2>{value ? "Editar propiedad" : "Nueva propiedad"}</h2>
        <button type="button" className="link-button" onClick={onCancel}>
          Cerrar ✕
        </button>
      </div>
      <div className="form-grid">
        <label className="full">
          Título
          <input
            name="title"
            required
            minLength={3}
            maxLength={180}
            defaultValue={value?.title}
            placeholder="Casa con jardín en La Estancia"
          />
        </label>
        <label>
          Operación
          <select name="operation" defaultValue={value?.operation ?? "rent"}>
            <option value="rent">Renta</option>
            <option value="sale">Venta</option>
          </select>
        </label>
        <label>
          Tipo
          <select name="kind" defaultValue={value?.kind ?? "house"}>
            {Object.entries(labels)
              .filter(
                ([key]) =>
                  ![
                    "rent",
                    "sale",
                    "bedrooms",
                    "bathrooms",
                    "parking",
                    "furnished",
                    "accepts_pets",
                    "near_schools",
                  ].includes(key),
              )
              .map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
          </select>
        </label>
        <label>
          Estado
          <input
            name="state"
            defaultValue={value?.state || ""}
            maxLength={80}
          />
        </label>
        <label>
          Municipio
          <input
            name="municipality"
            required
            defaultValue={value?.municipality || ""}
            maxLength={100}
          />
        </label>
        <label>
          Moneda
          <select
            name="currency"
            value={currency}
            onChange={(event) =>
              setCurrency(event.target.value as "MXN" | "USD")
            }
          >
            <option>MXN</option>
            <option>USD</option>
          </select>
        </label>
        <label>
          <input
            name="is_presale"
            type="checkbox"
            defaultChecked={value?.is_presale}
          />
          Preventa (solo venta)
        </label>
        <label>
          Colonia
          <input
            name="neighborhood"
            required
            maxLength={100}
            defaultValue={value?.neighborhood}
          />
        </label>
        <label>
          Precio
          <MoneyInput
            currency={currency}
            name="price"
            required
            min="1"
            defaultValue={value?.price}
          />
          <small>Mensual para renta; total para venta.</small>
        </label>
        <label>
          Superficie en m²
          <input
            name="area_m2"
            type="number"
            min="1"
            step="0.01"
            defaultValue={value?.area_m2 ?? ""}
          />
        </label>
        <label>
          Recámaras
          <input
            name="bedrooms"
            type="number"
            min="0"
            max="100"
            defaultValue={value?.bedrooms ?? ""}
          />
        </label>
        <label>
          Baños
          <input
            name="bathrooms"
            type="number"
            min="0"
            max="100"
            step="0.5"
            defaultValue={value?.bathrooms ?? ""}
          />
        </label>
        <label>
          Estacionamientos
          <input
            name="parking"
            type="number"
            min="0"
            max="100"
            defaultValue={value?.parking ?? ""}
          />
        </label>
        {(
          [
            ["furnished", "Amueblada"],
            ["accepts_pets", "Acepta mascotas"],
            ["near_schools", "Escuelas cercanas confirmadas"],
          ] as const
        ).map(([key, label]) => (
          <label key={key}>
            {label}
            <select name={key} defaultValue={triValue(value?.[key])}>
              <option value="">Sin información</option>
              <option value="true">Sí</option>
              <option value="false">No</option>
            </select>
          </label>
        ))}
        <label className="full">
          Asesor responsable
          <select name="advisor_id" defaultValue={value?.advisor_id ?? ""}>
            <option value="">Usar el asesor predeterminado</option>
            {advisors.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label className="full">
          Dirección pública
          <input
            name="public_address"
            maxLength={240}
            defaultValue={value?.public_address}
          />
        </label>
        <label className="full">
          Descripción pública
          <textarea
            name="description"
            rows={4}
            maxLength={5000}
            defaultValue={value?.description}
          />
        </label>
        <label className="full">
          Fotografías: una URL por línea
          <textarea
            name="photos"
            rows={3}
            defaultValue={value?.photos.join("\n")}
            placeholder="https://…"
          />
        </label>
        <label className="full">
          Notas internas
          <textarea
            name="internal_notes"
            rows={2}
            maxLength={5000}
            defaultValue={value?.internal_notes}
          />
          <small>
            Solo visibles para el equipo; no se entregan al agente ni al website
            público.
          </small>
        </label>
        <label className="check full">
          <input
            type="checkbox"
            name="published"
            defaultChecked={value?.published ?? false}
          />
          Publicar en el inventario
        </label>
      </div>
      {error && (
        <ErrorNotice>
          {error}
        </ErrorNotice>
      )}
      <div className="form-actions">
        <button type="button" className="button secondary" onClick={onCancel}>
          Cancelar
        </button>
        <button className="button primary" disabled={saving}>
          {saving ? "Guardando…" : "Guardar propiedad"}
        </button>
      </div>
    </form>
  );
}

export default function Crm() {
  const [tab, setTab] = useState<
    "inventory" | "prospects" | "advisors" | "appointments" | "captures"
  >("inventory");
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.has("capture")) setTab("captures");
    if (params.has("calendar_advisor") || params.has("calendar_error"))
      setTab("advisors");
    if (new URLSearchParams(window.location.search).has("conversation"))
      setTab("prospects");
  }, []);
  const [user, setUser] = useState<Session | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [properties, setProperties] = useState<ManagedProperty[]>([]);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<ManagedProperty | null | undefined>(
    undefined,
  );
  const [loggingIn, setLoggingIn] = useState(false);
  const loadProperties = async () => {
    try {
      setProperties(await api<ManagedProperty[]>("/crm/properties"));
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "No pudimos cargar las propiedades.",
      );
    }
  };
  useEffect(() => {
    void session()
      .then((s) => {
        setUser(s);
        if (s.staff) void loadProperties();
      })
      .catch(() => setError("No pudimos conectar con el CRM."))
      .finally(() => setLoaded(true));
  }, []);
  return (
    <>
      <Header crm className="crm-site-header" />
      <main
        className={`crm-main${tab === "captures" ? " crm-main-captures" : ""}`}
      >
        {!loaded ? (
          <p>Cargando…</p>
        ) : !user?.staff ? (
          <section className="login-panel">
            <p className="eyebrow">Acceso al equipo</p>
            <h1>Bienvenido de vuelta.</h1>
            <p>Administra el inventario de tu inmobiliaria.</p>
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                setLoggingIn(true);
                setError("");
                const values = new FormData(e.currentTarget);
                try {
                  await api("/auth/login", {
                    method: "POST",
                    body: JSON.stringify({
                      email: values.get("email"),
                      password: values.get("password"),
                    }),
                  });
                  const s = await session();
                  setUser(s);
                  await loadProperties();
                } catch (e) {
                  setError(
                    e instanceof Error
                      ? e.message
                      : "No pudimos iniciar sesión.",
                  );
                } finally {
                  setLoggingIn(false);
                }
              }}
            >
              <label>
                Email
                <input
                  name="email"
                  type="email"
                  autoComplete="username"
                  required
                />
              </label>
              <label>
                Contraseña
                <input
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  required
                />
              </label>
              {error && (
                <ErrorNotice>
                  {error}
                </ErrorNotice>
              )}
              <button className="button primary" disabled={loggingIn}>
                {loggingIn ? "Entrando…" : "Entrar al CRM ↗"}
              </button>
            </form>
          </section>
        ) : (
          <>
            <div className="crm-heading">
              <div>
                <p className="eyebrow">Tu inmobiliaria</p>
                <h1>
                  {tab === "inventory"
                    ? "Inventario de propiedades"
                    : tab === "prospects"
                      ? "Atención a prospectos"
                      : tab === "appointments"
                        ? "Citas y disponibilidad"
                        : tab === "captures"
                          ? "Captación"
                          : "Equipo y notificaciones"}
                </h1>
                {tab === "inventory" && (
                  <p>
                    {properties.length} propiedades ·{" "}
                    {properties.filter((p) => p.published).length} publicadas
                  </p>
                )}
              </div>
              <div className="crm-actions">
                <button
                  className="button secondary"
                  onClick={async () => {
                    await api("/auth/logout", { method: "POST" });
                    setUser(null);
                  }}
                >
                  Salir
                </button>
                {tab === "inventory" && (
                  <button
                    className="button primary"
                    onClick={() => setEditing(null)}
                  >
                    + Nueva propiedad
                  </button>
                )}
              </div>
            </div>
            <nav className="crm-tabs" aria-label="Secciones del CRM">
              {(
                [
                  ["inventory", "Propiedades"],
                  ["prospects", "Prospectos"],
                  ["advisors", "Asesores"],
                  ["appointments", "Citas"],
                  ["captures", "Captación"],
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  className={tab === id ? "active" : ""}
                  aria-current={tab === id ? "page" : undefined}
                  onClick={() => setTab(id)}
                >
                  {label}
                </button>
              ))}
            </nav>
            {user.ai_configured === false && (
              <div className="notice">
                La búsqueda con filtros funciona. Para activar la conversación,
                configura ANTHROPIC_API_KEY en el entorno del backend y del
                worker.
              </div>
            )}
            {error && (
              <ErrorNotice>
                {error}
              </ErrorNotice>
            )}
            {tab === "captures" ? (
              <Captures />
            ) : tab === "appointments" ? (
              <Appointments />
            ) : tab === "prospects" ? (
              <Prospects />
            ) : tab === "advisors" ? (
              <Advisors />
            ) : editing !== undefined ? (
              <Editor
                key={editing?.id ?? "new"}
                value={editing}
                onCancel={() => setEditing(undefined)}
                onSave={() => {
                  setEditing(undefined);
                  void loadProperties();
                }}
              />
            ) : properties.length ? (
              <PropertyInventory
                properties={properties}
                onEdit={(property) => {
                  if (property.capture_id) {
                    window.history.replaceState(
                      null,
                      "",
                      `/crm?capture=${property.capture_id}`,
                    );
                    setTab("captures");
                  } else setEditing(property);
                }}
                onChange={(saved) =>
                  setProperties((current) =>
                    current.map((p) => (p.id === saved.id ? saved : p)),
                  )
                }
              />
            ) : (
              <div className="empty-state">
                <h2>El inventario comienza aquí.</h2>
                <p>
                  Agrega tu primera propiedad y publícala cuando la información
                  esté lista.
                </p>
                <button
                  className="button primary"
                  onClick={() => setEditing(null)}
                >
                  Crear propiedad
                </button>
              </div>
            )}
          </>
        )}
      </main>
    </>
  );
}
