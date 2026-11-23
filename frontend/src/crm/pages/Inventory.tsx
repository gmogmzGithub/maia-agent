"use client";
import ErrorNotice from "@/shared/components/ErrorFeedback";
import MoneyInput from "@/shared/components/MoneyInput";
import LocationFields from "@/shared/components/LocationFields";
import type { CaptureData, Catalog, LocationPoint } from "@/shared/lib/capture";

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
import Closings from "@/crm/components/Closings";
import PropertyOutcome from "@/crm/components/PropertyOutcome";
import { labels } from "@/shared/lib/api";
import Advisors from "@/crm/components/Advisors";
import Prospects from "@/crm/components/Prospects";
import Appointments from "@/crm/components/Appointments";
import PropertyInventory from "@/crm/components/PropertyInventory";
import EasyBroker from "@/crm/components/EasyBroker";
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
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [point, setPoint] = useState<LocationPoint | null>(null);
  const [locationPending, setLocationPending] = useState(false);
  const [locationData, setLocationData] = useState<CaptureData>({
    state: value?.state || "",
    municipality: value?.municipality || "",
    neighborhood: value?.neighborhood || "",
    kind: value?.kind || "house",
    private_address: value?.private_data?.private_address || "",
    location_mode: value?.private_data?.location_mode || "address",
    location_reference: value?.private_data?.location_reference || "",
    rural_identification: value?.private_data?.rural_identification || "",
    rural_reference: value?.private_data?.rural_reference || "",
  });
  useEffect(() => {
    void api<Catalog>("/capture/catalog")
      .then(setCatalog)
      .catch(() => setError("No pudimos cargar las opciones de la ficha."));
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
          state: String(locationData.state || ""),
          subtype: String(data.get("subtype") || ""),
          is_presale: data.get("is_presale") === "on",
          operation: data.get("operation") as PropertyInput["operation"],
          kind: data.get("kind") as PropertyInput["kind"],
          municipality: String(locationData.municipality || ""),
          neighborhood: String(locationData.neighborhood || ""),
          price: String(data.get("price")),
          public_address: String(data.get("public_address")),
          bedrooms: optionalNumber("bedrooms"),
          bathrooms: optionalNumber("bathrooms"),
          parking: optionalNumber("parking"),
          area_m2: optionalNumber("area_m2"),
          land_m2: optionalNumber("land_m2"),
          private_m2: optionalNumber("private_m2"),
          private_data: {
            private_address: String(locationData.private_address || ""),
            location_mode: String(locationData.location_mode || "address"),
            location_reference: String(locationData.location_reference || ""),
            rural_identification: String(
              locationData.rural_identification || "",
            ),
            rural_reference: String(locationData.rural_reference || ""),
            zone_type:
              locationData.location_mode === "reference"
                ? "localidad"
                : String(data.get("zone_type") || "colonia"),
            characteristics: {
              age_type: (data.get("age_type") || "") as
                | ""
                | "new"
                | "years"
                | "construction",
              age_years:
                data.get("age_type") === "years"
                  ? optionalNumber("age_years")
                  : null,
              condition: String(data.get("condition") || ""),
              half_bathrooms: optionalNumber("half_bathrooms"),
              amenities:
                data.get("amenities_known") === "on"
                  ? data.getAll("amenities").map(String)
                  : null,
            },
          },
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
          <select
            name="kind"
            defaultValue={value?.kind ?? "house"}
            onChange={(e) =>
              setLocationData((d) => ({ ...d, kind: e.target.value }))
            }
          >
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
        <div className="full">
          <LocationFields
            data={locationData}
            states={catalog?.states || []}
            location={point}
            signedIn
            onLocation={setPoint}
            onChange={setLocationData}
            onPendingChange={setLocationPending}
          />
        </div>
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
          Subtipo
          <select name="subtype" defaultValue={value?.subtype || ""}>
            <option value="">Sin especificar</option>
            {catalog?.kinds[String(locationData.kind)]?.subtypes.map((v) => (
              <option key={v}>{v}</option>
            ))}
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
          Tipo de zona
          <select
            name="zone_type"
            defaultValue={value?.private_data?.zone_type || "colonia"}
          >
            <option value="colonia">Colonia</option>
            <option value="barrio">Barrio</option>
            <option value="localidad">Localidad</option>
          </select>
        </label>
        <label>
          Precio
          <MoneyInput
            currency={currency}
            name="price"
            required
            min="1"
            defaultValue={value?.price ?? undefined}
          />
          <small>Mensual para renta; total para venta.</small>
        </label>
        <label>
          Construcción (m²)
          <input
            name="area_m2"
            type="number"
            min="1"
            step="0.01"
            defaultValue={value?.area_m2 ?? ""}
          />
        </label>
        <label>
          Terreno (m²)
          <input
            type="number"
            name="land_m2"
            min="0.01"
            step="0.01"
            defaultValue={value?.land_m2 ?? ""}
          />
        </label>
        <label>
          Superficie privativa (m², departamentos)
          <input
            type="number"
            name="private_m2"
            min="0.01"
            step="0.01"
            defaultValue={value?.private_m2 ?? ""}
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
          <select
            name="advisor_id"
            required
            defaultValue={value?.advisor_id ?? ""}
          >
            <option value="">Seleccionar asesor responsable</option>
            {advisors.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Antigüedad
          <select
            name="age_type"
            defaultValue={value?.private_data?.characteristics?.age_type || ""}
          >
            <option value="">Desconocida</option>
            <option value="new">Nuevo</option>
            <option value="years">Años conocidos</option>
            <option value="construction">En construcción</option>
          </select>
        </label>
        <label>
          Años de antigüedad
          <input
            name="age_years"
            type="number"
            min="0"
            max="1000"
            defaultValue={value?.private_data?.characteristics?.age_years ?? ""}
          />
        </label>
        <label>
          Medios baños
          <input
            name="half_bathrooms"
            type="number"
            min="0"
            max="100"
            defaultValue={
              value?.private_data?.characteristics?.half_bathrooms ?? ""
            }
          />
        </label>
        <label>
          Conservación
          <select
            name="condition"
            defaultValue={value?.private_data?.characteristics?.condition || ""}
          >
            <option value="">Desconocida</option>
            {catalog?.conditions.map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        </label>
        <div className="full">
          <label className="check">
            <input
              name="amenities_known"
              type="checkbox"
              defaultChecked={
                value?.private_data?.characteristics?.amenities != null
              }
            />
            Amenidades conocidas (ninguna seleccionada significa que no tiene)
          </label>
          {Object.entries(catalog?.amenities || {}).map(([group, items]) => (
            <fieldset key={group}>
              <legend>{group}</legend>
              <div className="closing-checks">
                {items.map((item) => (
                  <label className="check" key={item}>
                    <input
                      name="amenities"
                      type="checkbox"
                      value={item}
                      defaultChecked={
                        value?.private_data?.characteristics?.amenities?.includes(
                          item,
                        ) || false
                      }
                    />
                    {item}
                  </label>
                ))}
              </div>
            </fieldset>
          ))}
        </div>
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
      {error && <ErrorNotice>{error}</ErrorNotice>}
      <div className="form-actions">
        <button type="button" className="button secondary" onClick={onCancel}>
          Cancelar
        </button>
        <button className="button primary" disabled={saving || locationPending}>
          {saving ? "Guardando…" : "Guardar propiedad"}
        </button>
      </div>
    </form>
  );
}

export default function Crm() {
  const [tab, setTab] = useState<
    | "inventory"
    | "prospects"
    | "advisors"
    | "appointments"
    | "captures"
    | "easybroker"
  >("inventory");
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.has("capture")) setTab("captures");
    if (params.has("closing") || params.has("closing_offer"))
      setTab("inventory");
    if (params.has("calendar_advisor") || params.has("calendar_error"))
      setTab("advisors");
    if (new URLSearchParams(window.location.search).has("conversation"))
      setTab("prospects");
  }, []);
  const [user, setUser] = useState<Session | null>(null);
  const [closingOffer, setClosingOffer] = useState<number | null>(null);
  const [outcomeMode, setOutcomeMode] = useState<
    "complete" | "withdraw" | "history"
  >("complete");
  const [legacyOperations, setLegacyOperations] = useState(false);
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("closing_offer");
    if (id && Number.isInteger(Number(id))) setClosingOffer(Number(id));
    const operation = new URLSearchParams(window.location.search).get(
      "closing",
    );
    if (operation)
      void api<{ offer_id: number | null }>(`/crm/closings/${operation}`)
        .then((row) => {
          if (row.offer_id) {
            setClosingOffer(row.offer_id);
            setOutcomeMode("history");
          } else setLegacyOperations(true);
        })
        .catch(() => {});
  }, []);
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
              {error && <ErrorNotice>{error}</ErrorNotice>}
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
                  {tab === "easybroker"
                    ? "EasyBroker"
                    : tab === "inventory"
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
                  ["easybroker", "EasyBroker"],
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
            {error && <ErrorNotice>{error}</ErrorNotice>}
            {tab === "easybroker" ? (
              <EasyBroker onChanged={() => void loadProperties()} />
            ) : tab === "captures" ? (
              <Captures />
            ) : tab === "appointments" ? (
              <Appointments />
            ) : tab === "prospects" ? (
              <Prospects />
            ) : tab === "advisors" ? (
              <Advisors />
            ) : closingOffer !== null ? (
              <PropertyOutcome
                key={closingOffer}
                offerId={closingOffer}
                mode={outcomeMode}
                onDismiss={() => {
                  setClosingOffer(null);
                  window.history.replaceState(null, "", "/crm");
                }}
                onChanged={() => void loadProperties()}
                onEdit={() => {
                  const property = properties.find(
                    (p) => p.id === closingOffer,
                  );
                  setClosingOffer(null);
                  if (property?.capture_id) {
                    window.history.replaceState(
                      null,
                      "",
                      `/crm?capture=${property.capture_id}`,
                    );
                    setTab("captures");
                  } else if (property) setEditing(property);
                }}
              />
            ) : legacyOperations ? (
              <section>
                <button
                  className="link-button"
                  onClick={() => setLegacyOperations(false)}
                >
                  Volver a propiedades
                </button>
                <Closings
                  initialOfferId={null}
                  onInventoryChange={() => void loadProperties()}
                />
              </section>
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
              <>
                <PropertyInventory
                  properties={properties}
                  onOutcome={(property, mode) => {
                    setClosingOffer(property.id);
                    setOutcomeMode(mode);
                    window.history.replaceState(
                      null,
                      "",
                      `/crm?closing_offer=${property.id}`,
                    );
                  }}
                  onEdit={(property) => {
                    if (property.origin === "easybroker") {
                      setTab("easybroker");
                    } else if (property.capture_id) {
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
                <details>
                  <summary>Operaciones anteriores</summary>
                  <p>
                    Carga excepcional de ventas o rentas históricas que todavía
                    no tengan una ficha en el inventario.
                  </p>
                  <button
                    className="link-button"
                    onClick={() => setLegacyOperations(true)}
                  >
                    Consultar o incorporar operaciones anteriores
                  </button>
                </details>
              </>
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
