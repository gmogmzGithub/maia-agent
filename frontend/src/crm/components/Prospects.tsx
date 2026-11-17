"use client";
import ErrorNotice from "@/shared/components/ErrorFeedback";
import MoneyInput from "@/shared/components/MoneyInput";

import { useCallback, useEffect, useRef, useState } from "react";
import { FollowupPanel, FollowupSettings, whatsappStatus } from "./Followups";
import {
  api,
  labels,
  type Advisor,
  type Criteria,
  type CRMConversation,
  type Notification,
  type Prospect,
  type ProspectDetail,
} from "@/shared/lib/api";

const statuses = {
  new: "Nuevo",
  attending: "En atención",
  not_interested: "Sin interés",
  scheduled: "Cita agendada",
};
const noticeReasons: Record<string, string> = {
  new_prospect: "Nuevo prospecto",
  new_interest: "Nuevo interés",
  human_request: "Solicitud humana",
  paused_message: "Mensaje con Maia pausada",
  appointment: "Cita y seguimiento de visita",
};
const noticeStatuses: Record<string, string> = {
  pending: "Pendiente",
  sending: "En proceso",
  sent: "Enviado",
  failed: "Falló",
  blocked: "Falta configuración",
  uncertain: "Resultado incierto",
};

function Notifications({
  values,
  refresh,
}: {
  values: Notification[];
  refresh: () => void;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  return (
    <div className="notification-list">
      {values.map((n) => (
        <div key={n.id} className="notification-row">
          <div>
            <strong>{noticeReasons[n.reason] ?? n.reason}</strong>
            <small>
              {noticeStatuses[n.status] ?? n.status} ·{" "}
              {new Date(n.created_at).toLocaleString("es-MX")}
            </small>
            {n.summary && <p>{n.summary}</p>}
            {n.status === "uncertain" && (
              <p>
                El envío pudo haberse entregado. Revisa Telegram; no se
                reenviará automáticamente.
              </p>
            )}
            {n.error_code && (
              <details>
                <summary>Detalle del envío</summary>
                <code>{n.error_code}</code>
              </details>
            )}
          </div>
          {["blocked", "failed"].includes(n.status) && (
            <button
              className="button secondary"
              disabled={busy !== null}
              onClick={async () => {
                setBusy(n.id);
                setError("");
                try {
                  await api(`/crm/notifications/${n.id}/retry`, {
                    method: "POST",
                  });
                  refresh();
                } catch (e) {
                  setError(
                    e instanceof Error ? e.message : "No pudimos reintentar.",
                  );
                } finally {
                  setBusy(null);
                }
              }}
            >
              {busy === n.id ? "Programando…" : "Reintentar aviso"}
            </button>
          )}
        </div>
      ))}
      {error && (
        <ErrorNotice>
          {error}
        </ErrorNotice>
      )}
    </div>
  );
}

function ConversationPanel({
  value,
  refresh,
}: {
  value: CRMConversation;
  refresh: () => void;
}) {
  const [error, setError] = useState("");
  return (
    <section className="conversation-panel">
      <div className="conversation-panel-heading">
        <h3>
          Conversación del{" "}
          {new Date(value.created_at).toLocaleDateString("es-MX")}
        </h3>
        <span>{value.phone || "Celular no proporcionado"}</span>
      </div>
      {(value.prospect_id === null || value.conversation_paused) && (
        <label className="check">
          <input
            type="checkbox"
            checked={value.conversation_paused}
            onChange={async (e) => {
              try {
                await api(`/crm/conversations/${value.id}/pause`, {
                  method: "PUT",
                  body: JSON.stringify({ automation_paused: e.target.checked }),
                });
                refresh();
              } catch (e) {
                setError(
                  e instanceof Error
                    ? e.message
                    : "No pudimos cambiar la pausa.",
                );
              }
            }}
          />
          Pausar atención automática en esta conversación
        </label>
      )}
      {error && (
        <ErrorNotice>
          {error}
        </ErrorNotice>
      )}
      <div className="crm-conversation-messages">
        {value.messages.map((m) => (
          <div key={m.id} className={`crm-message ${m.role}`}>
            <strong>{m.role === "user" ? "Prospecto" : "Maia"}</strong>
            <p>{m.text}</p>
            {m.delivery_status && (
              <small>WhatsApp: {whatsappStatus(m.delivery_status)}</small>
            )}
            {m.properties.map((p) => (
              <a
                key={p.id}
                href={`/propiedades/${p.id}`}
                target="_blank"
                rel="noreferrer"
              >
                {p.reference} · {p.title}
              </a>
            ))}
          </div>
        ))}
      </div>
      {value.notifications.length > 0 && (
        <>
          <h4>Avisos al asesor</h4>
          <Notifications values={value.notifications} refresh={refresh} />
        </>
      )}
    </section>
  );
}

function CriteriaEditor({
  value,
  change,
}: {
  value: Criteria;
  change: (next: Criteria) => void;
}) {
  return (
    <div className="form-grid prospect-criteria">
      <label>
        Operación
        <select
          value={value.operation ?? ""}
          onChange={(e) =>
            change({
              ...value,
              operation: (e.target.value || null) as Criteria["operation"],
            })
          }
        >
          <option value="">Sin definir</option>
          <option value="rent">Renta</option>
          <option value="sale">Venta</option>
        </select>
      </label>
      <label>
        Tipo
        <select
          value={value.kind ?? ""}
          onChange={(e) =>
            change({
              ...value,
              kind: (e.target.value || null) as Criteria["kind"],
            })
          }
        >
          <option value="">Sin definir</option>
          {["house", "apartment", "land"].map((k) => (
            <option key={k} value={k}>
              {labels[k]}
            </option>
          ))}
        </select>
      </label>
      <label>
        Municipio
        <select
          value={value.municipality ?? ""}
          onChange={(e) =>
            change({
              ...value,
              municipality: (e.target.value ||
                null) as Criteria["municipality"],
            })
          }
        >
          <option value="">Sin definir</option>
          {["Guadalajara", "Zapopan", "Tlaquepaque", "Tonalá"].map((k) => (
            <option key={k}>{k}</option>
          ))}
        </select>
      </label>
      <label>
        Colonia
        <input
          maxLength={100}
          value={value.neighborhood ?? ""}
          onChange={(e) =>
            change({ ...value, neighborhood: e.target.value || null })
          }
        />
      </label>
      {(
        [
          ["min_price", "Presupuesto mínimo"],
          ["max_price", "Presupuesto máximo"],
          ["min_bedrooms", "Recámaras mínimas"],
          ["min_bathrooms", "Baños mínimos"],
          ["min_parking", "Estacionamientos mínimos"],
        ] as const
      ).map(([key, label]) => (
        <label key={key}>
          {label}
          {key === "min_price" || key === "max_price" ? (
            <MoneyInput
              currency={value.currency ?? null}
              value={value[key] ?? ""}
              onValueChange={(raw) =>
                change({
                  ...value,
                  [key]: raw === "" || raw === "." ? null : Number(raw),
                })
              }
            />
          ) : (
            <input
              type="number"
              min="0"
              step={key === "min_bathrooms" ? "0.5" : "1"}
              value={value[key] ?? ""}
              onChange={(e) =>
                change({
                  ...value,
                  [key]: e.target.value === "" ? null : Number(e.target.value),
                })
              }
            />
          )}
        </label>
      ))}
      {(
        [
          ["furnished", "Amueblado"],
          ["accepts_pets", "Mascotas"],
          ["near_schools", "Escuelas cercanas"],
        ] as const
      ).map(([key, label]) => (
        <label key={key}>
          {label}
          <select
            value={value[key] == null ? "" : String(value[key])}
            onChange={(e) =>
              change({
                ...value,
                [key]: e.target.value === "" ? null : e.target.value === "true",
              })
            }
          >
            <option value="">Sin definir</option>
            <option value="true">Sí</option>
            <option value="false">No</option>
          </select>
        </label>
      ))}
      <label className="check full">
        <input
          type="checkbox"
          checked={value.verified_only ?? false}
          onChange={(e) =>
            change({ ...value, verified_only: e.target.checked })
          }
        />
        Solo características confirmadas
      </label>
    </div>
  );
}

function ProspectEditor({
  value,
  advisors,
  saved,
}: {
  value: ProspectDetail;
  advisors: Advisor[];
  saved: (next: ProspectDetail) => void;
}) {
  const [criteria, setCriteria] = useState<Criteria>(value.criteria);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  return (
    <form
      className="prospect-editor"
      onSubmit={async (e) => {
        e.preventDefault();
        setSaving(true);
        setError("");
        setSuccess(false);
        const data = new FormData(e.currentTarget);
        try {
          const next = await api<ProspectDetail>(`/crm/prospects/${value.id}`, {
            method: "PUT",
            body: JSON.stringify({
              name: String(data.get("name")),
              advisor_id: data.get("advisor_id")
                ? Number(data.get("advisor_id"))
                : null,
              status: data.get("status"),
              criteria,
              next_step: String(data.get("next_step")),
              automation_paused: data.get("automation_paused") === "on",
            }),
          });
          saved(next);
          setSuccess(true);
        } catch (e) {
          setError(e instanceof Error ? e.message : "No pudimos guardar.");
        } finally {
          setSaving(false);
        }
      }}
    >
      <div className="prospect-title">
        <div>
          <p className="eyebrow">
            Contacto declarado · identidad sin verificar
          </p>
          <h2>{value.name || value.phone}</h2>
          <a href={`tel:${value.phone}`}>{value.phone}</a>
        </div>
      </div>
      <div className="form-grid">
        <label>
          Nombre
          <input name="name" maxLength={120} defaultValue={value.name} />
        </label>
        <label>
          Asesor responsable
          <select name="advisor_id" defaultValue={value.advisor_id ?? ""}>
            <option value="">Sin asignar</option>
            {advisors.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Estado comercial
          <select name="status" defaultValue={value.status}>
            {Object.entries(statuses).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="check pause-control">
          <input
            name="automation_paused"
            type="checkbox"
            defaultChecked={value.automation_paused}
          />
          Pausar atención automática
        </label>
        <label className="full">
          Siguiente paso
          <textarea
            name="next_step"
            maxLength={500}
            rows={2}
            defaultValue={value.next_step}
          />
        </label>
      </div>
      <p className="editor-help">
        La pausa detiene respuestas de Maia. Los mensajes se guardan. Al
        reactivarla, responderá al siguiente mensaje del prospecto.
      </p>
      <details className="criteria-details">
        <summary>Requisitos registrados en el CRM</summary>
        <p>
          Para el asesor. Cada conversación conserva sus propios criterios; el
          celular declarado no permite compartir contexto entre visitantes.
        </p>
        <CriteriaEditor value={criteria} change={setCriteria} />
      </details>
      {value.property_ids.length > 0 && (
        <p className="prospect-property-links">
          Propiedades de interés:{" "}
          {value.property_ids.map((id) => (
            <a
              href={`/propiedades/${id}`}
              key={id}
              target="_blank"
              rel="noreferrer"
            >
              #{id}
            </a>
          ))}
        </p>
      )}
      {error && (
        <ErrorNotice>
          {error}
        </ErrorNotice>
      )}
      {success && (
        <p role="status" className="notice">
          Cambios guardados.
        </p>
      )}
      <div className="form-actions">
        <button className="button primary" disabled={saving}>
          {saving ? "Guardando…" : "Guardar avance"}
        </button>
      </div>
    </form>
  );
}

export default function Prospects() {
  const [rows, setRows] = useState<Prospect[]>([]);
  const [requests, setRequests] = useState<CRMConversation[]>([]);
  const [advisors, setAdvisors] = useState<Advisor[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<ProspectDetail | null>(null);
  const [anonymous, setAnonymous] = useState<CRMConversation | null>(null);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const selection = useRef({ selected, anonymousId: anonymous?.id });
  selection.current = { selected, anonymousId: anonymous?.id };
  const refresh = useCallback(async () => {
    try {
      const [leads, pending, team] = await Promise.all([
        api<Prospect[]>("/crm/prospects"),
        api<CRMConversation[]>("/crm/requests"),
        api<Advisor[]>("/crm/advisors"),
      ]);
      setRows(leads);
      setRequests(pending);
      setAdvisors(team);
      if (selected !== null) {
        const next = await api<ProspectDetail>(`/crm/prospects/${selected}`);
        if (selection.current.selected === selected) setDetail(next);
      }
      if (anonymous) {
        const next = await api<CRMConversation>(
          `/crm/conversations/${anonymous.id}`,
        );
        if (selection.current.anonymousId === anonymous.id) setAnonymous(next);
      }
      setError("");
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "No pudimos cargar prospectos.",
      );
    } finally {
      setLoaded(true);
    }
  }, [selected, anonymous?.id]);
  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 10000);
    return () => clearInterval(timer);
  }, [refresh]);
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("conversation");
    if (!id) return;
    void api<CRMConversation>(`/crm/conversations/${encodeURIComponent(id)}`)
      .then((c) => {
        if (c.prospect_id !== null) setSelected(c.prospect_id);
        else setAnonymous(c);
      })
      .catch(() => setError("No encontramos la conversación del aviso."));
  }, []);
  return (
    <section className="crm-workspace">
      <FollowupSettings />
      <div className="workspace-heading">
        <div>
          <h2>Prospectos y solicitudes</h2>
          <p>
            {rows.length} contactos · {requests.length} solicitudes sin celular
          </p>
        </div>
        <button className="button secondary" onClick={() => void refresh()}>
          Actualizar
        </button>
      </div>
      {error && (
        <ErrorNotice>
          {error}
        </ErrorNotice>
      )}
      {!loaded ? (
        <p>Cargando…</p>
      ) : (
        <div className="prospect-workspace">
          <aside className="prospect-sidebar">
            <h3>Prospectos</h3>
            {!rows.length && (
              <p>Los contactos aparecerán cuando confirmen su celular.</p>
            )}
            {rows.map((p) => (
              <button
                key={p.id}
                className={`prospect-row ${selected === p.id ? "selected" : ""}`}
                onClick={() => {
                  setSelected(p.id);
                  setDetail(null);
                  setAnonymous(null);
                }}
              >
                <strong>{p.name || p.phone}</strong>
                <span>{p.phone}</span>
                <small>
                  {statuses[p.status]} ·{" "}
                  {advisors.find((a) => a.id === p.advisor_id)?.name ??
                    "Sin asignar"}
                  {p.automation_paused ? " · Maia pausada" : ""}
                </small>
              </button>
            ))}
            <h3>Solicitudes sin celular</h3>
            {!requests.length && <p>No hay solicitudes registradas.</p>}
            {requests.map((c) => (
              <button
                key={c.id}
                className={`prospect-row ${anonymous?.id === c.id ? "selected" : ""}`}
                onClick={() => {
                  setAnonymous(c);
                  setSelected(null);
                  setDetail(null);
                }}
              >
                <strong>Solicita atención humana</strong>
                <span>{new Date(c.created_at).toLocaleString("es-MX")}</span>
                <small>
                  {advisors.find((a) => a.id === c.advisor_id)?.name ??
                    "Sin asignar"}
                </small>
              </button>
            ))}
          </aside>
          <div className="prospect-content">
            {anonymous ? (
              <ConversationPanel
                value={anonymous}
                refresh={() => void refresh()}
              />
            ) : selected !== null ? (
              detail ? (
                <>
                  <ProspectEditor
                    key={detail.id}
                    value={detail}
                    advisors={advisors}
                    saved={(next) => {
                      setDetail(next);
                      void refresh();
                    }}
                  />
                  <FollowupPanel
                    prospect={detail}
                    refresh={() => void refresh()}
                  />
                  {detail.conversations.map((c) => (
                    <ConversationPanel
                      key={c.id}
                      value={c}
                      refresh={() => void refresh()}
                    />
                  ))}
                  {detail.events.length > 0 && (
                    <section className="prospect-events">
                      <h3>Historial de cambios</h3>
                      {detail.events.map((event, index) => (
                        <p key={index}>
                          {String(event.description)}
                          <small>
                            {String(event.actor)} ·{" "}
                            {new Date(String(event.created_at)).toLocaleString(
                              "es-MX",
                            )}
                          </small>
                        </p>
                      ))}
                    </section>
                  )}
                </>
              ) : (
                <p>Cargando ficha…</p>
              )
            ) : (
              <div className="empty-state">
                <h3>Cada contacto, con un responsable.</h3>
                <p>
                  Selecciona un prospecto o una solicitud para consultar su
                  conversación y registrar el siguiente paso.
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
