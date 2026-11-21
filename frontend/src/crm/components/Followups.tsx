"use client";
import ErrorNotice from "@/shared/components/ErrorFeedback";

import { useEffect, useState } from "react";
import { api, type ProspectDetail } from "@/shared/lib/api";

type Attempt = {
  id: number;
  day: number;
  label?: string;
  status: string;
  reason: string;
  due_at: string;
  delivery_status: string | null;
};
type Cycle = {
  id: number;
  conversation_id: string;
  started_at: string;
  ends_at: string;
  closed_at: string | null;
  suspended: boolean;
  permission: boolean;
  reason: string;
  next_at: string | null;
  pilot?: boolean;
};
type Followup = {
  cycle: Cycle | null;
  opted_out: boolean;
  attempts: Attempt[];
};
type Template = {
  id: number;
  name: string;
  language: string;
  body: string;
  status: string;
  enabled: boolean;
  fields: string[];
};
type Review = {
  events: { id: number; error_code: string; received_at: string }[];
  deliveries: {
    id: string;
    conversation_id: string;
    status: string;
    error_code: string;
    created_at: string;
  }[];
};
const fields: Record<string, string> = {
  operation: "Comprar o rentar",
  kind: "Tipo de inmueble",
  municipality: "Municipio",
  neighborhood: "Colonia",
  bedrooms: "Recámaras",
  bathrooms: "Baños",
  parking: "Estacionamientos",
  furnished: "Amueblado",
  accepts_pets: "Mascotas",
  near_schools: "Escuelas cercanas",
};
const states: Record<string, string> = {
  queued: "Pendiente",
  preparing: "Preparando",
  prepared: "Preparado",
  sent: "Aceptado por WhatsApp",
  delivered: "Entregado",
  read: "Leído",
  skipped: "Omitido",
  review: "Requiere revisión",
  uncertain: "Entrega incierta",
  blocked: "Bloqueado",
  failed: "Falló",
};
export function whatsappStatus(value: string) {
  return states[value] ?? value;
}
const reasons: Record<string, string> = {
  expired: "Fuera del horario de envío",
  recent_activity: "Conversación en las últimas 24 horas",
  paused: "Maia pausada",
  appointment: "Cita registrada",
  permission_required: "Falta permiso",
  opted_out: "No desea mensajes",
  not_interested: "Sin interés",
  completed: "Ciclo terminado",
  context_changed: "La conversación o sus datos cambiaron",
  no_approved_contextual_template:
    "Falta una plantilla aprobada que corresponda a la búsqueda",
  invalid_or_failed_generation: "No se obtuvo una propuesta válida",
  generation_interrupted: "Generación interrumpida",
  template_changed: "La plantilla cambió",
  whatsapp_not_configured: "Falta configurar WhatsApp",
  outside_service_window: "Fuera de la ventana de conversación",
  conversation_changed: "La conversación cambió",
  incoming_pending: "Llegó un mensaje que todavía se está procesando",
  schedule_changed: "El horario cambió después de preparar el intento",
  unknown_delivery: "Entrega incierta",
  process_interrupted: "Envío interrumpido",
};
function date(value: string | null) {
  return value
    ? new Date(value).toLocaleString("es-MX", {
        timeZone: "America/Mexico_City",
      })
    : "Sin programar";
}

export function FollowupPanel({
  prospect,
  refresh,
}: {
  prospect: ProspectDetail;
  refresh: () => void;
}) {
  const data = prospect.followup as unknown as Followup;
  const [source, setSource] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const cycle = data?.cycle;
  async function action(action: string) {
    setBusy(true);
    setError("");
    try {
      await api(`/crm/prospects/${prospect.id}/followup`, {
        method: "POST",
        body: JSON.stringify({
          action,
          conversation_id:
            source || cycle?.conversation_id || prospect.conversations[0]?.id,
        }),
      });
      refresh();
    } catch (error) {
      setError(error instanceof Error ? error.message : "No pudimos guardar.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="prospect-events">
      <h3>Seguimiento por WhatsApp</h3>
      {cycle ? (
        <>
          {cycle.pilot && (
            <p><strong>Prueba temporal: ocho intentos cada 30 minutos.</strong> Los primeros tres comprueban una plantilla distinta. Silencio mínimo: cinco minutos. El permiso temporal se retira al terminar.</p>
          )}
          <p>
            Inicio: {date(cycle.started_at)} · Fin: {date(cycle.ends_at)}
          </p>
          <p>
            {cycle.closed_at
              ? "Ciclo cerrado"
              : cycle.suspended
                ? "Suspendido"
                : "Ciclo abierto"}
            {cycle.reason ? ` · ${reasons[cycle.reason] ?? cycle.reason}` : ""}
          </p>
          <p>
            Permiso:{" "}
            {data.opted_out
              ? "No desea mensajes"
              : cycle.permission
                ? "Registrado"
                : "Pendiente"}
            . Próximo intento: {date(cycle.next_at)}.
          </p>
          <p>
            Los envíos se omiten si hay cita, pausa, actividad reciente o falta
            permiso. El ciclo conserva sus fechas.
          </p>
          <div className="form-actions">
            {!cycle.closed_at && (
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => void action("resume")}
              >
                Reactivar {cycle.pilot ? "intentos" : "días"} restantes
              </button>
            )}
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => void action("stop")}
            >
              Dar de baja el seguimiento
            </button>
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => void action("record_permission")}
            >
              Registrar permiso recibido
            </button>
          </div>
          <p>
            <small>
              Registra permiso solo si la persona lo otorgó. Guardaremos tu
              usuario y fecha en el historial.
            </small>
          </p>
          <ul>
            {data.attempts.map((a) => (
              <li key={a.id}>
                {a.label ?? `Día ${a.day}`}: {states[a.delivery_status ?? a.status] ?? a.status}
                {a.reason ? ` · ${cycle.pilot && a.reason === "recent_activity" ? "Conversación en los últimos cinco minutos" : reasons[a.reason] ?? a.reason}` : ""}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p>No hay ciclo registrado.</p>
      )}
      <details>
        <summary>Nueva intención de búsqueda</summary>
        <p>
          Requiere una nueva interacción después de terminar el ciclo anterior.
          No borra el historial.
        </p>
        <label>
          Conversación de origen
          <select
            value={
              source ||
              cycle?.conversation_id ||
              prospect.conversations[0]?.id ||
              ""
            }
            onChange={(e) => setSource(e.target.value)}
          >
            {prospect.conversations.map((c) => (
              <option key={c.id} value={c.id}>
                {c.channel === "whatsapp" ? "WhatsApp" : "Website"} ·{" "}
                {date(c.created_at)}
              </option>
            ))}
          </select>
        </label>
        <button
          className="button secondary"
          disabled={busy || !prospect.conversations.length}
          onClick={() => void action("new_intention")}
        >
          Confirmar nueva intención
        </button>
      </details>
      {error && (
        <ErrorNotice>
          {error}
        </ErrorNotice>
      )}
    </section>
  );
}

function TemplateEditor({
  value,
  refresh,
}: {
  value: Template;
  refresh: () => void;
}) {
  const count = [...value.body.matchAll(/\{\{(.*?)\}\}/g)].length;
  const [mapping, setMapping] = useState(value.fields);
  const [enabled, setEnabled] = useState(value.enabled);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError("");
        try {
          await api(`/crm/whatsapp/templates/${value.id}`, {
            method: "PUT",
            body: JSON.stringify({
              enabled,
              fields: Array.from({ length: count }, (_, i) => mapping[i] ?? ""),
            }),
          });
          refresh();
        } catch (error) {
          setError(
            error instanceof Error ? error.message : "No pudimos guardar.",
          );
        } finally {
          setBusy(false);
        }
      }}
    >
      <h4>
        {value.name} · {value.language} · {value.status}
      </h4>
      <p>{value.body}</p>
      <div className="form-grid">
        {Array.from({ length: count }, (_, i) => (
          <label key={i}>
            Variable {i + 1}
            <select
              required={enabled}
              value={mapping[i] ?? ""}
              onChange={(e) => {
                const next = [...mapping];
                next[i] = e.target.value;
                setMapping(next);
              }}
            >
              <option value="">Selecciona el dato</option>
              {Object.entries(fields).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      <label className="check">
        <input
          type="checkbox"
          checked={enabled}
          disabled={value.status !== "APPROVED"}
          onChange={(e) => setEnabled(e.target.checked)}
        />
        Usar para seguimiento contextual
      </label>
      {error && <ErrorNotice>{error}</ErrorNotice>}
      <button className="button secondary" disabled={busy}>
        {busy ? "Guardando…" : "Guardar plantilla"}
      </button>
    </form>
  );
}

export function FollowupSettings() {
  const [open, setOpen] = useState(false);
  const [sendTime, setSendTime] = useState("11:00");
  const [configured, setConfigured] = useState(false);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [review, setReview] = useState<Review>({ events: [], deliveries: [] });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function load() {
    try {
      const [p, t, r] = await Promise.all([
        api<{ send_time: string; whatsapp_configured: boolean }>(
          "/crm/followup-policy",
        ),
        api<Template[]>("/crm/whatsapp/templates"),
        api<Review>("/crm/whatsapp/review"),
      ]);
      setSendTime(p.send_time.slice(0, 5));
      setConfigured(p.whatsapp_configured);
      setTemplates(t);
      setReview(r);
    } catch (error) {
      setError(error instanceof Error ? error.message : "No pudimos cargar.");
    }
  }
  useEffect(() => {
    if (open) void load();
  }, [open]);
  async function run(work: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await work();
      await load();
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "No pudimos completar la acción.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <details
      className="prospect-events"
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary>WhatsApp y reglas de seguimiento</summary>
      <p>
        {configured
          ? "Credenciales de envío configuradas."
          : "Falta configurar WhatsApp en el backend y el worker."}{" "}
        Los secretos no se muestran en el CRM.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run(() =>
            api("/crm/followup-policy", {
              method: "PUT",
              body: JSON.stringify({ send_time: sendTime }),
            }),
          );
        }}
      >
        <label>
          Hora de envío, Guadalajara
          <input
            type="time"
            required
            value={sendTime}
            onChange={(e) => setSendTime(e.target.value)}
          />
        </label>
        <p>Días 1, 5, 7, 14, 18, 22, 26 y 28. Ventana de envío: una hora.</p>
        <button className="button secondary" disabled={busy}>
          Guardar horario
        </button>
      </form>
      <h3>Plantillas de Meta</h3>
      <p>
        Primero crea y aprueba las plantillas en Meta. Después sincroniza y
        asigna cada variable a un dato de búsqueda. El piloto usa plantillas de
        cuerpo textual con variables numeradas.
      </p>
      <button
        className="button secondary"
        disabled={busy}
        onClick={() =>
          void run(() =>
            api("/crm/whatsapp/templates/sync", { method: "POST" }),
          )
        }
      >
        Sincronizar plantillas de Meta
      </button>
      {templates.map((t) => (
        <TemplateEditor
          key={`${t.id}:${t.body}`}
          value={t}
          refresh={() => void load()}
        />
      ))}
      <h3>Entregas que requieren revisión</h3>
      {!review.deliveries.length && (
        <p>No hay entregas pendientes de revisión.</p>
      )}
      {review.deliveries.map((d) => (
        <p key={d.id}>
          <a href={`/crm?conversation=${d.conversation_id}`}>
            Ver conversación
          </a>{" "}
          · {states[d.status] ?? d.status} ·{" "}
          {reasons[d.error_code] ?? d.error_code} · {date(d.created_at)}{" "}
          {d.status !== "uncertain" && (
            <button
              className="link-button"
              disabled={busy}
              onClick={() =>
                void run(() =>
                  api(`/crm/whatsapp/deliveries/${d.id}/retry`, {
                    method: "POST",
                  }),
                )
              }
            >
              Reintentar entrega
            </button>
          )}
        </p>
      ))}
      {review.events.length > 0 && (
        <p>
          {review.events.length} eventos entrantes requieren revisión en los
          logs. No se reprocesan automáticamente.
        </p>
      )}
      {error && (
        <ErrorNotice>
          {error}
        </ErrorNotice>
      )}
    </details>
  );
}
