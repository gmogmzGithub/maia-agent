"use client";
import ErrorNotice from "@/shared/components/ErrorFeedback";
import MoneyInput from "@/shared/components/MoneyInput";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { api, ApiError, money, type Advisor } from "@/shared/lib/api";
import {
  type Capture,
  type CaptureData,
  type Catalog,
} from "@/shared/lib/capture";
import CapturePhotos from "@/crm/components/CapturePhotos";
import CaptureStatus from "@/crm/components/CaptureStatus";
import {
  captureState,
  captureTabs,
  captureTabForStatus,
  capturesInTab,
  captureTitle,
  type CaptureTab,
} from "@/crm/lib/capture-status";
import LocationFields from "@/shared/components/LocationFields";
import type { LocationPoint } from "@/shared/lib/capture";
import LocationMap from "@/shared/components/LocationMap";
import { CaptureReviewSession } from "@/crm/lib/capture-review-session";
import "@/shared/styles/capture.css";
import "@/crm/styles/captures.css";

const deliveryLabels: Record<string, string> = {
  pending: "Pendiente de envío",
  sending: "Enviando",
  sent: "Aceptado por el proveedor",
  delivered: "Entregado al servidor del destinatario",
  delayed: "Entrega demorada; el proveedor sigue intentando",
  bounced: "Rebotó; revisar el correo del propietario",
  complained: "El destinatario lo marcó como spam",
  suppressed: "El proveedor bloqueó la entrega",
  stored: "Guardado en correo local; no entregado al cliente",
  failed: "Falló el envío",
  blocked: "Falta destinatario o proveedor",
  uncertain: "Envío sin confirmación; revisar antes de reenviar",
  superseded: "Omitido porque la solicitud cambió",
};

export default function Captures() {
  const review = useMemo(
    () =>
      new CaptureReviewSession({
        request: api,
        now: () => new Date().toLocaleTimeString("es-MX"),
      }),
    [],
  );
  const {
    rows,
    selected,
    loaded,
    busy,
    error: failure,
    notice,
    lastCheck,
  } = useSyncExternalStore(review.subscribe, review.snapshot, review.snapshot);
  const error =
    failure instanceof Error
      ? failure.message
      : failure
        ? "No pudimos completar la acción."
        : "";
  const errorIssues = failure instanceof ApiError ? failure.issues : [];
  const outsideError = errorIssues.some(
    (issue) => issue.field === "outside_area_approved",
  );
  const [tab, setTab] = useState<CaptureTab>("review");
  const [detailOpen, setDetailOpen] = useState(false);
  const listScroll = useRef(0);
  const detailHeading = useRef<HTMLHeadingElement>(null);
  const cardRefs = useRef(new Map<string, HTMLButtonElement>());
  const deepLinkOpened = useRef("");
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [advisors, setAdvisors] = useState<Advisor[]>([]);
  const [editing, setEditing] = useState<CaptureData | null>(null);
  const [locationPending, setLocationPending] = useState(false);
  const [editingLocation, setEditingLocation] = useState<LocationPoint | null>(
    null,
  );
  const acceptanceMail = selected?.deliveries?.find(
    (x) => x.channel === "email",
  );
  const approvalResult = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (selected?.status === "approved")
      approvalResult.current?.focus({ preventScroll: true });
  }, [selected?.id, selected?.status]);
  const load = review.load;
  const openCapture = (row: Capture) => {
    listScroll.current = window.scrollY;
    review.select(row);
    setEditing(null);
    setDetailOpen(true);
    if (window.matchMedia("(max-width: 760px)").matches)
      requestAnimationFrame(() => {
        detailHeading.current
          ?.closest("article")
          ?.scrollIntoView({ block: "start", behavior: "instant" });
        detailHeading.current?.focus({ preventScroll: true });
      });
  };
  const backToList = () => {
    setDetailOpen(false);
    requestAnimationFrame(() => {
      window.scrollTo({ top: listScroll.current, behavior: "instant" });
      if (selected)
        cardRefs.current.get(selected.id)?.focus({ preventScroll: true });
    });
  };
  const visibleRows = capturesInTab(rows, tab);
  const refresh = review.refresh;
  useEffect(() => {
    review.resume();
    void Promise.all([
      load(),
      api<Catalog>("/capture/catalog").then(setCatalog),
      api<Advisor[]>("/crm/advisors").then(setAdvisors),
    ]).catch(review.fail);
    return () => review.stop();
  }, [review]);
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("capture");
    if (id && id !== deepLinkOpened.current) {
      const row = rows.find((candidate) => candidate.id === id);
      if (row) {
        deepLinkOpened.current = id;
        setTab(captureTabForStatus(row.status));
        openCapture(row);
      }
    }
  }, [rows]);
  const act = async (action: string, extra: Record<string, unknown> = {}) => {
    const saved = await review.act(action, extra);
    if (saved) setEditing(null);
  };
  const editField = (key: string, label: string, type = "text") => (
    <label key={key}>
      {label}
      {["price", "maintenance"].includes(key) ? (
        <MoneyInput
          name={key}
          currency={String(editing?.currency || "MXN")}
          value={String(editing?.[key] ?? "")}
          onValueChange={(raw) =>
            setEditing(
              (data) =>
                data && {
                  ...data,
                  [key]: raw === "" || raw === "." ? null : Number(raw),
                },
            )
          }
        />
      ) : (
        <input
          name={key}
          type={type}
          value={String(editing?.[key] ?? "")}
          onChange={(e) =>
            setEditing(
              (d) =>
                d && {
                  ...d,
                  [key]:
                    type === "number"
                      ? e.target.value === ""
                        ? null
                        : Number(e.target.value)
                      : e.target.value,
                },
            )
          }
        />
      )}
    </label>
  );
  return (
    <section className={`capture-crm${detailOpen ? " has-detail" : ""}`}>
      <div className="capture-dashboard-heading">
        <div>
          <h2>Solicitudes</h2>
          <p className="capture-summary">
            {loaded
              ? `${rows.length} solicitudes de captación`
              : "Cargando solicitudes…"}
          </p>
        </div>
        <button
          className="button secondary"
          disabled={busy}
          onClick={() => void refresh()}
        >
          Actualizar
        </button>
      </div>
      <div
        className="capture-status-tabs"
        role="tablist"
        aria-label="Estado de las solicitudes"
      >
        {captureTabs.map((item) => (
          <button
            type="button"
            role="tab"
            disabled={busy}
            id={`capture-tab-${item.id}`}
            key={item.id}
            aria-selected={tab === item.id}
            aria-controls="capture-results"
            tabIndex={tab === item.id ? 0 : -1}
            onKeyDown={(event) => {
              const index = captureTabs.findIndex(
                (candidate) => candidate.id === item.id,
              );
              let next = index;
              if (event.key === "ArrowRight")
                next = (index + 1) % captureTabs.length;
              else if (event.key === "ArrowLeft")
                next = (index + captureTabs.length - 1) % captureTabs.length;
              else if (event.key === "Home") next = 0;
              else if (event.key === "End") next = captureTabs.length - 1;
              else return;
              event.preventDefault();
              setTab(captureTabs[next].id);
              review.select(null);
              setDetailOpen(false);
              setEditing(null);
              review.clearFeedback();
              document
                .getElementById(`capture-tab-${captureTabs[next].id}`)
                ?.focus();
            }}
            onClick={() => {
              setTab(item.id);
              review.select(null);
              setDetailOpen(false);
              setEditing(null);
              review.clearFeedback();
            }}
          >
            <span>{item.label}</span>
            <span className="capture-tab-count">
              {capturesInTab(rows, item.id).length}
            </span>
          </button>
        ))}
      </div>
      {error && (
        <ErrorNotice
          issues={errorIssues}
          fields={{
            outside_area_approved: 'input[name="outside"]',
            representation_verified: 'input[name="representation"]',
          }}
        >
          {error}
        </ErrorNotice>
      )}
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      {busy && <p role="status">Procesando…</p>}
      <div className="capture-crm-layout">
        <aside
          id="capture-results"
          role="tabpanel"
          aria-labelledby={`capture-tab-${tab}`}
        >
          {visibleRows.map((row) => (
            <button
              className={`capture-list-item ${row.id === selected?.id ? "selected" : ""}`}
              key={row.id}
              ref={(node) => {
                if (node) cardRefs.current.set(row.id, node);
                else cardRefs.current.delete(row.id);
              }}
              aria-pressed={selected?.id === row.id}
              disabled={busy}
              onClick={() => openCapture(row)}
            >
              <strong>{captureTitle(row)}</strong>
              <CaptureStatus status={row.status} />
              <span className="capture-card-next">
                {captureState(row.status).next}
              </span>
              <small>
                {row.owner?.email}
                {row.pending_request.kind && " · Solicitud pendiente"}
              </small>
            </button>
          ))}
          {loaded && !visibleRows.length && (
            <div className="capture-empty" role="status">
              {tab === "review"
                ? "No hay solicitudes por revisar."
                : tab === "process"
                  ? "No hay solicitudes en proceso."
                  : tab === "published"
                    ? "No hay solicitudes publicadas."
                    : "Aún no hay solicitudes enviadas."}
            </div>
          )}
        </aside>
        {selected && catalog ? (
          <article className="capture-review" key={selected.id}>
            <div className="capture-detail-heading">
              <button
                type="button"
                className="capture-back button secondary"
                disabled={busy}
                onClick={backToList}
              >
                ← Volver a solicitudes
              </button>
              <h2 ref={detailHeading} tabIndex={-1}>
                {captureTitle(selected)}
              </h2>
              <CaptureStatus status={selected.status} />
              {selected.property_id && <a className="button secondary" href={`/crm?closing_offer=${selected.property_id}`}>{selected.status === "closed" ? "Ver resultado e historial" : `Marcar ${selected.data.operation === "rent" ? "rentada" : "vendida"}`}</a>}
              <p className="capture-detail-next">
                {captureState(selected.status).next}
              </p>
            </div>
            <details className="capture-reference">
              <summary>Referencia de solicitud</summary>
              <code>{selected.id}</code>
            </details>
            {selected.status === "approved" && (
              <div className="notice" role="status">
                <h3>Revisión aprobada. Sigue la aceptación del propietario.</h3>
                <ol>
                  <li>
                    El propietario debe entrar a su cuenta en{" "}
                    <a
                      href="/propietarios"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      el portal de propietarios
                    </a>
                    , seleccionar la solicitud en «Mis propiedades», leer el
                    acuerdo de seis meses y pulsar «Aceptar exclusividad».
                  </li>
                  <li>
                    Después, pulsa «Actualizar» en este CRM. Se habilitará
                    «Publicar inmueble» para que el equipo lo publique.
                  </li>
                </ol>
                <p>La aprobación todavía no publica el inmueble.</p>
                <p>
                  Al aprobar se prepara un correo con el contrato PDF y la liga
                  directa a esta solicitud. Consulta su estado en «Actividad y
                  avisos».
                </p>
                {selected.mail_configuration &&
                  !selected.mail_configuration.ready && (
                    <p className="capture-hint">
                      {selected.mail_configuration.local
                        ? "Envío real pendiente de activar. La solicitud está aprobada, pero el cliente aún necesita recibir su aviso."
                        : selected.mail_configuration.issues.join(" ")}
                    </p>
                  )}
                {selected.deliveries
                  ?.filter(
                    (x) =>
                      x.channel === "email" &&
                      x.status === "stored" &&
                      x.can_retry,
                  )
                  .slice(0, 1)
                  .map((x) => (
                    <button
                      key={x.id}
                      type="button"
                      className="button primary"
                      disabled={busy}
                      onClick={() =>
                        void act("retry_delivery", { delivery_id: x.id })
                      }
                    >
                      Enviar correo con el proveedor configurado
                    </button>
                  ))}
              </div>
            )}
            {selected.status === "accepted" && (
              <p className="notice" role="status">
                El propietario ya aceptó la exclusividad. El equipo puede
                continuar con «Publicar inmueble».
              </p>
            )}
            <p>
              {catalog.kinds[String(selected.data.kind)]?.label}
              {selected.data.subtype
                ? ` · ${selected.data.subtype}`
                : ""} ·{" "}
              {selected.data.is_presale
                ? "Preventa"
                : selected.data.operation === "sale"
                  ? "Venta"
                  : "Renta"}
            </p>
            <p>
              <strong>
                {money(
                  String(selected.data.price),
                  String(selected.data.currency),
                )}{" "}
                {String(selected.data.currency)}
              </strong>
            </p>
            <section className="capture-private">
              <h3>Información privada</h3>
              <p>
                {String(selected.data.name)} ·{" "}
                {selected.data.relationship === "owner"
                  ? "Propietario"
                  : "Representante autorizado"}
              </p>
              <p>
                {selected.owner?.email} · {selected.owner?.phone} · Email{" "}
                {selected.owner?.verified ? "verificado" : "sin verificar"}
              </p>
              <p>
                {String(
                  selected.data.private_address ||
                    selected.data.location_reference ||
                    "",
                )}
                , {String(selected.data.neighborhood)},{" "}
                {String(selected.data.municipality)},{" "}
                {String(selected.data.state)}
              </p>
              <p>{String(selected.data.description || "Sin descripción")}</p>
            </section>
            {(selected.location?.latitude != null ||
              selected.data.latitude != null) && (
              <LocationMap
                key={`${selected.id}-map`}
                latitude={
                  selected.location?.latitude ?? Number(selected.data.latitude)
                }
                longitude={
                  selected.location?.longitude ??
                  Number(selected.data.longitude)
                }
              />
            )}
            <details>
              <summary>Características completas</summary>
              <dl className="capture-data-list">
                {Object.entries(selected.data)
                  .filter(
                    ([key]) =>
                      ![
                        "private_address",
                        "name",
                        "relationship",
                        "location_ref",
                        "location_confirmed",
                      ].includes(key),
                  )
                  .map(([key, value]) => (
                    <div key={key}>
                      <dt>
                        {(
                          {
                            title: "Título",
                            operation: "Operación",
                            kind: "Tipo",
                            subtype: "Subtipo",
                            state: "Estado",
                            municipality: "Municipio",
                            neighborhood: "Colonia",
                            currency: "Moneda",
                            price: "Precio",
                            is_presale: "Preventa",
                            bedrooms: "Recámaras",
                            bathrooms: "Baños",
                            half_bathrooms: "Medios baños",
                            parking: "Estacionamientos",
                            area_m2: "Construcción m²",
                            land_m2: "Terreno m²",
                            age_type: "Antigüedad",
                            age_years: "Años",
                            condition: "Conservación",
                            amenities: "Comodidades",
                            maintenance: "Mantenimiento",
                            no_maintenance: "Sin mantenimiento",
                            valuation_requested: "Opinión de valor solicitada",
                            phone_confirmed: "Teléfono confirmado",
                            latitude: "Latitud",
                            longitude: "Longitud",
                            videos: "Videos",
                            tours: "Recorridos 360",
                            floors: "Niveles",
                            elevators: "Elevadores",
                            storage_rooms: "Bodegas",
                            description: "Descripción",
                            subdivision: "Subdivisión",
                            location_reference: "Referencia de ubicación",
                            location_mode: "Tipo de dirección",
                          } as Record<string, string>
                        )[key] || key}
                      </dt>
                      <dd>
                        {Array.isArray(value)
                          ? value.join(", ")
                          : value === true
                            ? "Sí"
                            : value === false
                              ? "No"
                              : String(value ?? "Por confirmar")}
                      </dd>
                    </div>
                  ))}
              </dl>
            </details>
            <CapturePhotos key={selected.id} assets={selected.assets} />
            {selected.pending_request.kind && (
              <div className="notice">
                <h3>Solicitud del propietario</h3>
                <p>
                  {selected.pending_request.kind === "withdraw"
                    ? "Retirada"
                    : selected.pending_request.kind === "renew"
                      ? "Renovación"
                      : "Cambio"}
                  : {selected.pending_request.message}
                </p>
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() => void act("resolve_request")}
                >
                  Marcar como atendida
                </button>
              </div>
            )}
            {editing ? (
              <form
                className="capture-correction"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (locationPending) return;
                  void act("update", { data: editing });
                }}
              >
                <h3>Corregir información</h3>
                <p className="notice">
                  Guardar retira la publicación e invalida la aceptación
                  anterior. Será necesario revisar y aceptar de nuevo.
                </p>
                <div className="capture-grid">
                  {editField("name", "Nombre")}
                  {editField("title", "Título")}
                  <label>
                    Operación
                    <select
                      value={String(editing.operation)}
                      onChange={(e) =>
                        setEditing(
                          (d) =>
                            d && {
                              ...d,
                              operation: e.target.value,
                              is_presale: false,
                            },
                        )
                      }
                    >
                      <option value="sale">Venta</option>
                      <option value="rent">Renta</option>
                    </select>
                  </label>
                  <label>
                    Tipo
                    <select
                      value={String(editing.kind)}
                      onChange={(e) =>
                        setEditing(
                          (d) =>
                            d && { ...d, kind: e.target.value, subtype: "" },
                        )
                      }
                    >
                      {Object.entries(catalog.kinds).map(([key, x]) => (
                        <option key={key} value={key}>
                          {x.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  {catalog.kinds[String(editing.kind)]?.subtypes.length > 0 && (
                    <label>
                      Subtipo
                      <select
                        value={String(editing.subtype || "")}
                        onChange={(e) =>
                          setEditing(
                            (d) => d && { ...d, subtype: e.target.value },
                          )
                        }
                      >
                        <option value="">Sin especificar</option>
                        {catalog.kinds[String(editing.kind)].subtypes.map(
                          (x) => (
                            <option key={x}>{x}</option>
                          ),
                        )}
                      </select>
                    </label>
                  )}
                  <div className="full">
                    <LocationFields
                      key={selected.id}
                      data={editing}
                      states={catalog.states}
                      location={editingLocation}
                      onChange={(value) =>
                        setEditing({ ...value, location_confirmed: true })
                      }
                      onLocation={setEditingLocation}
                      onPendingChange={setLocationPending}
                      signedIn
                      captureId={selected.id}
                    />
                  </div>
                  {editField("price", "Precio", "number")}
                  <label>
                    Moneda
                    <select
                      value={String(editing.currency)}
                      onChange={(e) =>
                        setEditing(
                          (d) => d && { ...d, currency: e.target.value },
                        )
                      }
                    >
                      <option>MXN</option>
                      <option>USD</option>
                    </select>
                  </label>
                  {[
                    ["bedrooms", "Recámaras"],
                    ["bathrooms", "Baños"],
                    ["parking", "Estacionamientos"],
                    ["area_m2", "Construcción m²"],
                    ["land_m2", "Terreno m²"],
                    ["private_m2", "Superficie privativa m²"],
                    ["half_bathrooms", "Medios baños"],
                    ["age_years", "Años de antigüedad"],
                    ["maintenance", "Mantenimiento"],
                    ["floors", "Niveles"],
                    ["storage_rooms", "Bodegas"],
                    ["elevators", "Elevadores"],
                  ].map(([k, l]) => editField(k, l, "number"))}
                  <label>
                    Conservación
                    <select
                      value={String(editing.condition || "")}
                      onChange={(e) =>
                        setEditing(
                          (d) => d && { ...d, condition: e.target.value },
                        )
                      }
                    >
                      <option value="">Por confirmar</option>
                      {catalog.conditions.map((x) => (
                        <option key={x}>{x}</option>
                      ))}
                    </select>
                  </label>
                </div>
                <label className="capture-check">
                  <input
                    type="checkbox"
                    checked={editing.is_presale === true}
                    disabled={editing.operation !== "sale"}
                    onChange={(e) =>
                      setEditing(
                        (d) => d && { ...d, is_presale: e.target.checked },
                      )
                    }
                  />
                  Preventa
                </label>
                <label>
                  Descripción
                  <textarea
                    value={String(editing.description || "")}
                    onChange={(e) =>
                      setEditing(
                        (d) => d && { ...d, description: e.target.value },
                      )
                    }
                  />
                </label>
                <button
                  className="button primary"
                  disabled={busy || locationPending || selected.status === "closed"}
                >
                  Guardar corrección
                </button>
                <button
                  type="button"
                  className="link-button"
                  onClick={() => setEditing(null)}
                >
                  Cancelar
                </button>
              </form>
            ) : (
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => {
                  setEditingLocation(selected.location || null);
                  setEditing({ ...selected.data });
                }}
              >
                Corregir información
              </button>
            )}
            {selected.status === "approved" ? (
              <div
                className="notice"
                ref={approvalResult}
                tabIndex={-1}
                role="status"
              >
                <h3>Revisión completada</h3>
                <p>
                  El siguiente paso le corresponde al propietario: debe abrir su
                  solicitud en «Mis propiedades» y aceptar el acuerdo de
                  exclusividad. Después podrás publicar el inmueble.
                </p>
                <p>
                  Correo con el contrato:{" "}
                  {acceptanceMail
                    ? deliveryLabels[acceptanceMail.status] ||
                      acceptanceMail.status
                    : "Todavía no hay un aviso registrado."}
                </p>
                {acceptanceMail?.status === "stored" && (
                  <p>
                    {selected.mail_configuration?.ready
                      ? "El proveedor está configurado. Ya puedes enviar este aviso al propietario."
                      : "Falta activar el envío real para que el cliente reciba su correo."}
                  </p>
                )}
                {acceptanceMail?.status === "stored" &&
                  acceptanceMail.can_retry && (
                    <button
                      type="button"
                      className="button primary"
                      disabled={busy}
                      onClick={() =>
                        void act("retry_delivery", {
                          delivery_id: acceptanceMail.id,
                        })
                      }
                    >
                      Enviar correo con el proveedor configurado
                    </button>
                  )}
                <button
                  type="button"
                  className="button secondary"
                  disabled={busy}
                  onClick={() => void refresh()}
                >
                  {busy
                    ? "Consultando…"
                    : "Comprobar aceptación del propietario"}
                </button>
                <p className="capture-hint">
                  No necesitas volver a aprobar ni completar las casillas de
                  revisión.
                </p>
                {lastCheck?.id === selected.id && (
                  <p role="status">
                    Consultado a las {lastCheck.at}: seguimos esperando la
                    aceptación del propietario.
                  </p>
                )}
              </div>
            ) : (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  const form = new FormData(e.currentTarget);
                  void act("approve", {
                    representation_verified:
                      form.get("representation") === "on",
                    outside_area_approved: form.get("outside") === "on",
                    exact_location_approved: form.get("exact") === "on",
                    advisor_id: Number(form.get("advisor")),
                    review_notes: form.get("notes"),
                  });
                }}
              >
                <h3>Revisión del equipo</h3>
                <label>
                  Responsable
                  <select
                    name="advisor"
                    defaultValue={selected.advisor_id || ""}
                    required
                  >
                    <option value="">Selecciona asesor</option>
                    {advisors.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Notas privadas
                  <textarea
                    name="notes"
                    defaultValue={selected.review_notes}
                    maxLength={5000}
                  />
                </label>
                <label className="capture-check">
                  <input name="representation" type="checkbox" required />
                  Verifiqué al propietario o representante y el inmueble
                </label>
                <p className="capture-hint">
                  Obligatorio para aprobar. Confirma que el equipo revisó quién
                  ofrece el inmueble y su relación con él. Esta casilla registra
                  una revisión humana; no verifica documentos ni identidad
                  automáticamente.
                </p>
                <label className="capture-check">
                  <input
                    name="outside"
                    onChange={(event) => {
                      if (event.target.checked && outsideError)
                        review.clearFeedback();
                    }}
                    type="checkbox"
                    defaultChecked={selected.outside_area_approved}
                  />
                  Apruebo la captación fuera de la zona base
                </label>
                <p className="capture-hint">
                  Solo es necesaria si el inmueble está fuera de Guadalajara y
                  su zona metropolitana. Registra que el equipo acepta atender
                  esa ubicación.
                </p>
                <label className="capture-check">
                  <input
                    name="exact"
                    type="checkbox"
                    defaultChecked={selected.exact_location_approved}
                  />
                  Autorizo publicar la ubicación exacta
                </label>
                <p className="capture-hint">
                  Opcional. Al marcarla, la ficha pública podrá mostrar la
                  dirección y el punto exactos. Sin marcar, se oculta la
                  dirección exacta y se muestra ubicación aproximada cuando hay
                  coordenadas.
                </p>
                <button
                  className="button primary"
                  disabled={
                    busy ||
                    !["submitted", "rejected", "expired", "withdrawn"].includes(
                      selected.status,
                    )
                  }
                >
                  {selected.status === "approved"
                    ? "Revisión aprobada"
                    : "Aprobar y solicitar aceptación"}
                </button>
              </form>
            )}
            {selected.agreement && (
              <div className="notice">
                <h3>Exclusividad vigente</h3>
                <p>
                  Desde{" "}
                  {new Date(selected.agreement.accepted_at).toLocaleDateString(
                    "es-MX",
                  )}{" "}
                  hasta{" "}
                  {new Date(selected.agreement.expires_at).toLocaleDateString(
                    "es-MX",
                  )}
                  .
                </p>
                <details>
                  <summary>Texto aceptado</summary>
                  <p>{selected.agreement.text}</p>
                </details>
              </div>
            )}
            <div className="capture-form-actions">
              {selected.status !== "approved" && (
                <button
                  className="button primary"
                  disabled={busy || selected.status !== "accepted"}
                  onClick={() => void act("publish")}
                >
                  Publicar inmueble
                </button>
              )}
              {selected.status !== "approved" && (
                <button
                  className="button secondary"
                  disabled={
                    busy ||
                    !["accepted", "published", "expired"].includes(
                      selected.status,
                    )
                  }
                  onClick={() => void act("renew")}
                >
                  Preparar renovación
                </button>
              )}
              <button
                className="button secondary"
                disabled={busy || ["withdrawn", "closed"].includes(selected.status)}
                onClick={() => void act("withdraw")}
              >
                Retirar y cancelar exclusividad
              </button>
              <button
                className="link-button"
                disabled={busy || ["rejected", "closed"].includes(selected.status)}
                onClick={() => void act("reject")}
              >
                Descartar solicitud
              </button>
            </div>
            {selected.data.valuation_requested && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  const form = new FormData(e.currentTarget);
                  void act("valuation", {
                    valuation: form.get("value"),
                    valuation_notes: form.get("notes"),
                    communicated: form.get("communicated") === "on",
                  });
                }}
              >
                <h3>Opinión de valor · {String(selected.data.currency)}</h3>
                <label>
                  Importe
                  <MoneyInput
                    currency={String(selected.data.currency || "MXN")}
                    name="value"
                    min="1"
                    required
                    defaultValue={selected.valuation}
                  />
                </label>
                <label>
                  Comentarios
                  <textarea
                    name="notes"
                    maxLength={5000}
                    defaultValue={selected.valuation_notes}
                  />
                </label>
                <label className="capture-check">
                  <input name="communicated" type="checkbox" />
                  Ya la comuniqué al propietario; puede verla desde su cuenta
                </label>
                <button className="button secondary" disabled={busy}>
                  Registrar opinión
                </button>
              </form>
            )}
            <details>
              <summary>Actividad y avisos</summary>
              {selected.events?.map((x, i) => (
                <p key={i}>
                  {new Date(x.created_at).toLocaleString("es-MX")} ·{" "}
                  {(
                    {
                      submitted: "Solicitud recibida",
                      approve: "Revisión aprobada",
                      accepted: "Exclusividad aceptada",
                      publish: "Propiedad publicada",
                      withdraw: "Retirada",
                      expired: "Exclusividad vencida",
                      renew: "Renovación preparada",
                      update: "Información corregida",
                      valuation: "Opinión de valor",
                      reject: "Descartada",
                      change: "Cambio solicitado",
                      resolve_request: "Solicitud atendida",
                      closed: "Comercialización terminada por cierre",
                      closing_reopened: "Oferta reabierta tras anulación",
                    } as Record<string, string>
                  )[x.action] || "Solicitud registrada"}{" "}
                  {x.summary}
                </p>
              ))}
              {selected.deliveries?.map((x) => (
                <p key={x.id}>
                  {x.channel === "email" ? "Correo" : "Aviso Telegram"}:{" "}
                  {deliveryLabels[x.status] || x.status}
                  {x.can_retry && (
                    <button
                      className="link-button"
                      disabled={busy}
                      onClick={() =>
                        void act("retry_delivery", { delivery_id: x.id })
                      }
                    >
                      {x.status === "stored"
                        ? "Enviar correo local con el proveedor configurado"
                        : "Reintentar aviso"}
                    </button>
                  )}
                </p>
              ))}
            </details>
          </article>
        ) : selected ? (
          <div className="capture-detail-loading" role="status">
            <button
              className="capture-back button secondary"
              type="button"
              onClick={backToList}
            >
              ← Volver a solicitudes
            </button>
            <p>Cargando ficha…</p>
          </div>
        ) : (
          <p className="capture-select-hint">
            Selecciona una solicitud para revisarla.
          </p>
        )}
      </div>
    </section>
  );
}
