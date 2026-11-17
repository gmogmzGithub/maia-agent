"use client";
import ErrorNotice from "@/shared/components/ErrorFeedback";

import { useEffect, useRef, useState } from "react";
import { api, type ManagedProperty, type Prospect } from "@/shared/lib/api";
import {
  type Visit,
  type VisitRules,
  visitLabels,
  visitTime,
} from "@/shared/lib/booking";

const days = [
  "Lunes",
  "Martes",
  "Miércoles",
  "Jueves",
  "Viernes",
  "Sábado",
  "Domingo",
];
type Policy = { notice_hours: number; horizon_days: number };
type ConversationRef = { id: string; phone: string; created_at: string };

function Rules({ propertyId }: { propertyId: number }) {
  const [rules, setRules] = useState<VisitRules | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    void api<VisitRules>(`/crm/properties/${propertyId}/visits`)
      .then((v) => {
        if (live) setRules(v);
      })
      .catch(() => {
        if (live) setMessage("No pudimos cargar horarios.");
      });
    return () => {
      live = false;
    };
  }, [propertyId]);
  if (!rules) return <p>{message || "Cargando horarios…"}</p>;
  return (
    <form
      className="editor"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setMessage("");
        try {
          setRules(
            await api<VisitRules>(`/crm/properties/${propertyId}/visits`, {
              method: "PUT",
              body: JSON.stringify(rules),
            }),
          );
          setMessage(
            "Horarios guardados. Las citas existentes conservan sus datos.",
          );
        } catch (e) {
          setMessage(
            e instanceof Error ? e.message : "No pudimos guardar horarios.",
          );
        } finally {
          setBusy(false);
        }
      }}
    >
      <h3>Horarios de visita de la propiedad</h3>
      <p>Hora de Guadalajara. Cada cita debe caber completa en una ventana.</p>
      <label>
        Duración de la cita, minutos
        <input
          type="number"
          min={15}
          max={480}
          required
          value={rules.duration}
          onChange={(e) =>
            setRules({ ...rules, duration: Number(e.target.value) })
          }
        />
      </label>
      {rules.windows.map((w, i) => (
        <div className="visit-window" key={i}>
          <label>
            Día
            <select
              value={w.day}
              onChange={(e) =>
                setRules({
                  ...rules,
                  windows: rules.windows.map((x, j) =>
                    j === i ? { ...x, day: Number(e.target.value) } : x,
                  ),
                })
              }
            >
              {days.map((d, n) => (
                <option key={d} value={n}>
                  {d}
                </option>
              ))}
            </select>
          </label>
          <label>
            Desde
            <input
              type="time"
              required
              value={w.start}
              onChange={(e) =>
                setRules({
                  ...rules,
                  windows: rules.windows.map((x, j) =>
                    j === i ? { ...x, start: e.target.value } : x,
                  ),
                })
              }
            />
          </label>
          <label>
            Hasta
            <input
              type="time"
              required
              value={w.end}
              onChange={(e) =>
                setRules({
                  ...rules,
                  windows: rules.windows.map((x, j) =>
                    j === i ? { ...x, end: e.target.value } : x,
                  ),
                })
              }
            />
          </label>
          <button
            type="button"
            className="link-button"
            onClick={() =>
              setRules({
                ...rules,
                windows: rules.windows.filter((_, j) => j !== i),
              })
            }
          >
            Quitar
          </button>
        </div>
      ))}
      <div className="form-actions">
        <button
          type="button"
          className="button secondary"
          disabled={rules.windows.length >= 28}
          onClick={() =>
            setRules({
              ...rules,
              windows: [
                ...rules.windows,
                { day: 0, start: "10:00", end: "14:00" },
              ],
            })
          }
        >
          Agregar ventana
        </button>
        <button className="button primary" disabled={busy}>
          Guardar horarios
        </button>
      </div>
      {!rules.windows.length && (
        <p>Sin ventanas, no se ofrecen nuevas visitas.</p>
      )}
      {message && (
        <p role="status" className="notice">
          {message}
        </p>
      )}
    </form>
  );
}

function VisitActions({
  visit,
  onChange,
}: {
  visit: Visit;
  onChange: () => Promise<void>;
}) {
  const [action, setAction] = useState(
    visit.status === "review" ? "accept" : "move",
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const key = useRef(crypto.randomUUID());
  if (
    !["review", "confirmed"].includes(visit.status) ||
    ["queued", "running", "verifying"].includes(visit.operation_status)
  )
    return null;
  return (
    <form
      className="visit-action"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError("");
        const data = new FormData(e.currentTarget);
        try {
          await api(`/crm/appointments/${visit.id}/change`, {
            method: "POST",
            body: JSON.stringify({
              action,
              start: data.get("start") || null,
              request_id: key.current,
              confirmed: data.get("confirmed") === "on",
            }),
          });
          key.current = crypto.randomUUID();
          await onChange();
        } catch (e) {
          setError(
            e instanceof Error ? e.message : "No pudimos aplicar el cambio.",
          );
        } finally {
          setBusy(false);
        }
      }}
    >
      <label>
        Acción
        <select
          value={action}
          onChange={(e) => {
            setAction(e.target.value);
            key.current = crypto.randomUUID();
          }}
        >
          {(visit.status === "review"
            ? ["accept", "restore"]
            : ["move", "cancel", "done", "no_show"]
          ).map((x) => (
            <option key={x} value={x}>
              {visitLabels[x]}
            </option>
          ))}
        </select>
      </label>
      {["move", "restore"].includes(action) && (
        <label>
          Nuevo horario, Guadalajara
          <input
            name="start"
            type="datetime-local"
            step={1800}
            required
            onChange={() => {
              key.current = crypto.randomUUID();
            }}
          />
        </label>
      )}
      <label className="check">
        <input type="checkbox" name="confirmed" required />
        Confirmo esta acción para la cita mostrada.
      </label>
      <button className="button secondary" disabled={busy}>
        {busy ? "Procesando…" : "Aplicar"}
      </button>
      {error && (
        <ErrorNotice>
          {error}
        </ErrorNotice>
      )}
    </form>
  );
}

function NewVisit({
  properties,
  prospects,
  onChange,
}: {
  properties: ManagedProperty[];
  prospects: Prospect[];
  onChange: () => Promise<void>;
}) {
  const [prospect, setProspect] = useState("");
  const [propertyId, setPropertyId] = useState("");
  const [start, setStart] = useState("");
  const [rules, setRules] = useState<VisitRules | null>(null);
  const [conversations, setConversations] = useState<ConversationRef[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const key = useRef(crypto.randomUUID());
  useEffect(() => {
    setRules(null);
    if (!propertyId) return;
    let live = true;
    void api<VisitRules>(`/crm/properties/${propertyId}/visits`)
      .then((value) => {
        if (live) setRules(value);
      })
      .catch(() => {
        if (live) setError("No pudimos cargar la duración de la cita.");
      });
    return () => {
      live = false;
    };
  }, [propertyId]);
  useEffect(() => {
    setConversations([]);
    if (!prospect) return;
    let live = true;
    void api<{ conversations: ConversationRef[] }>(`/crm/prospects/${prospect}`)
      .then((v) => {
        if (live) setConversations(v.conversations.filter((c) => !!c.phone));
      })
      .catch(() => {
        if (live) setError("No pudimos cargar las conversaciones.");
      });
    return () => {
      live = false;
    };
  }, [prospect]);
  return (
    <form
      className="editor"
      onChange={() => {
        key.current = crypto.randomUUID();
      }}
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError("");
        const data = new FormData(e.currentTarget);
        try {
          await api("/crm/appointments", {
            method: "POST",
            body: JSON.stringify({
              conversation_id: data.get("conversation_id"),
              property_id: Number(data.get("property_id")),
              start: data.get("start"),
              duration: rules?.duration,
              request_id: key.current,
              confirmed: data.get("confirmed") === "on",
            }),
          });
          key.current = crypto.randomUUID();
          await onChange();
          setError(
            "Solicitud registrada. Consulta su resultado en la lista de citas.",
          );
        } catch (e) {
          setError(
            e instanceof Error ? e.message : "No pudimos registrar la cita.",
          );
        } finally {
          setBusy(false);
        }
      }}
    >
      <h3>Agendar desde el CRM</h3>
      <div className="form-grid">
        <label>
          Prospecto
          <select
            required
            value={prospect}
            onChange={(e) => setProspect(e.target.value)}
          >
            <option value="">Seleccionar</option>
            {prospects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name || p.phone} · {p.phone}
              </option>
            ))}
          </select>
        </label>
        <label>
          Conversación
          <select name="conversation_id" required key={prospect}>
            <option value="">Seleccionar</option>
            {conversations.map((c) => (
              <option key={c.id} value={c.id}>
                {visitTime(c.created_at)} · {c.phone}
              </option>
            ))}
          </select>
        </label>
        <label>
          Propiedad
          <select
            name="property_id"
            required
            value={propertyId}
            onChange={(e) => setPropertyId(e.target.value)}
          >
            <option value="">Seleccionar</option>
            {properties
              .filter((p) => p.published)
              .map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title}
                </option>
              ))}
          </select>
        </label>
        <label>
          Inicio, hora de Guadalajara
          <input
            name="start"
            type="datetime-local"
            step={1800}
            required
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
        </label>
        {rules && start && (
          <p className="notice full">
            {properties.find((p) => p.id === Number(propertyId))?.title} ·{" "}
            {start.replace("T", " a las ")} · {rules.duration} minutos ·
            Guadalajara
          </p>
        )}
        <label className="check full">
          <input name="confirmed" type="checkbox" required />
          Confirmo prospecto, propiedad y horario. La plataforma validará
          duración y disponibilidad antes de confirmar.
        </label>
      </div>
      <button
        className="button primary"
        disabled={busy || !conversations.length || !rules}
      >
        {busy ? "Registrando…" : "Solicitar reserva"}
      </button>
      {error && (
        <p role="status" className="notice">
          {error}
        </p>
      )}
    </form>
  );
}

export default function Appointments() {
  const [visits, setVisits] = useState<Visit[]>([]);
  const [properties, setProperties] = useState<ManagedProperty[]>([]);
  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [property, setProperty] = useState("");
  const [error, setError] = useState("");
  const [showNew, setShowNew] = useState(false);
  async function load() {
    setVisits(await api<Visit[]>("/crm/appointments"));
  }
  useEffect(() => {
    void Promise.all([
      api<ManagedProperty[]>("/crm/properties"),
      api<Prospect[]>("/crm/prospects"),
      api<Policy>("/crm/booking-policy"),
      load(),
    ])
      .then(([p, c, s]) => {
        setProperties(p);
        setProspects(c);
        setPolicy(s);
      })
      .catch(() => setError("No pudimos cargar las citas."));
    const timer = setInterval(
      () =>
        void load().catch(() => setError("No pudimos actualizar las citas.")),
      5000,
    );
    return () => clearInterval(timer);
  }, []);
  return (
    <section className="crm-workspace">
      <h2>Citas y disponibilidad</h2>
      <p>Todos los horarios se muestran en hora de Guadalajara.</p>
      {error && (
        <ErrorNotice>
          {error}
        </ErrorNotice>
      )}
      <button className="button primary" onClick={() => setShowNew(!showNew)}>
        {showNew ? "Cerrar formulario" : "Agendar cita"}
      </button>
      {showNew && (
        <NewVisit
          properties={properties}
          prospects={prospects}
          onChange={load}
        />
      )}
      <div className="visit-list">
        {visits.length ? (
          visits.map((a) => (
            <article className="editor" key={a.id}>
              <h3>{a.property_title}</h3>
              <p>
                {visitTime(a.start)} a {visitTime(a.end)} · {a.advisor}
              </p>
              <p>
                <strong>{visitLabels[a.status] ?? a.status}</strong>
                {a.operation_status &&
                  ` · ${visitLabels[a.operation_status] ?? a.operation_status}`}
              </p>
              <a href={`/crm?conversation=${a.conversation_id}`}>
                Ver prospecto y conversación
              </a>
              {a.operation_error && (
                <p className="notice">
                  {[
                    "calendar_disconnected",
                    "calendar_connection_changed",
                  ].includes(a.operation_error)
                    ? "Reconecta Google Calendar desde Asesores. La solicitud se conserva."
                    : "La operación requiere revisión. Consulta el detalle y los logs."}
                </p>
              )}
              {a.status === "review" && (
                <details>
                  <summary>Datos observados en Google</summary>
                  {a.observed?.status === "cancelled" ? (
                    <p>El evento figura cancelado en Google.</p>
                  ) : a.observed?.start?.dateTime &&
                    a.observed?.end?.dateTime ? (
                    <p>
                      Horario en Google: {visitTime(a.observed.start.dateTime)}{" "}
                      a {visitTime(a.observed.end.dateTime)}.
                    </p>
                  ) : (
                    <p>
                      No pudimos verificar el evento. Revisa Google Calendar
                      antes de resolver.
                    </p>
                  )}
                  {a.observed?.summary && (
                    <p>Título en Google: {a.observed.summary}</p>
                  )}
                  {a.observed?.location && (
                    <p>Lugar en Google: {a.observed.location}</p>
                  )}
                </details>
              )}
              <VisitActions
                key={`${a.id}:${a.status}`}
                visit={a}
                onChange={load}
              />
            </article>
          ))
        ) : (
          <p>No hay citas registradas.</p>
        )}
      </div>
      <details>
        <summary>Configurar horarios y reglas</summary>
        {policy && (
          <form
            className="editor"
            key={JSON.stringify(policy)}
            onSubmit={async (e) => {
              e.preventDefault();
              const data = new FormData(e.currentTarget);
              try {
                setPolicy(
                  await api<Policy>("/crm/booking-policy", {
                    method: "PUT",
                    body: JSON.stringify({
                      notice_hours: Number(data.get("notice_hours")),
                      horizon_days: Number(data.get("horizon_days")),
                    }),
                  }),
                );
                setError("");
              } catch (e) {
                setError(
                  e instanceof Error
                    ? e.message
                    : "No pudimos guardar las reglas.",
                );
              }
            }}
          >
            <h3>Reglas de la inmobiliaria</h3>
            <div className="form-grid">
              <label>
                Anticipación mínima, horas
                <input
                  type="number"
                  name="notice_hours"
                  required
                  min={0}
                  max={168}
                  defaultValue={policy.notice_hours}
                />
              </label>
              <label>
                Reservar hasta, días
                <input
                  type="number"
                  name="horizon_days"
                  required
                  min={1}
                  max={90}
                  defaultValue={policy.horizon_days}
                />
              </label>
            </div>
            <button className="button secondary">Guardar reglas</button>
          </form>
        )}
        <label>
          Propiedad
          <select
            value={property}
            onChange={(e) => setProperty(e.target.value)}
          >
            <option value="">Seleccionar</option>
            {properties.map((p) => (
              <option key={p.id} value={p.id}>
                {p.title}
              </option>
            ))}
          </select>
        </label>
        {property && <Rules key={property} propertyId={Number(property)} />}
      </details>
    </section>
  );
}
