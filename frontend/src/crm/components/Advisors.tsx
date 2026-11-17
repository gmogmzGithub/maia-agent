"use client";
import ErrorNotice from "@/shared/components/ErrorFeedback";

import { useEffect, useState } from "react";
import { api, type Advisor } from "@/shared/lib/api";
import CalendarConnect from "@/crm/components/CalendarConnect";

export default function Advisors() {
  const [advisors, setAdvisors] = useState<Advisor[]>([]);
  const [editing, setEditing] = useState<Advisor | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [configured, setConfigured] = useState<boolean | null>(null);
  async function load() {
    try {
      const [rows, config] = await Promise.all([
        api<Advisor[]>("/crm/advisors"),
        api<{ telegram_configured: boolean }>("/crm/configuration"),
      ]);
      setAdvisors(rows);
      setConfigured(config.telegram_configured);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pudimos cargar asesores.");
    }
  }
  useEffect(() => {
    if (new URLSearchParams(window.location.search).has("calendar_error")) {
      setError(
        "Google no completó la autorización. Revisa la configuración y vuelve a conectar el calendario.",
      );
    }
    void load();
  }, []);
  return (
    <section className="crm-workspace">
      <h2>Asesores y avisos privados</h2>
      <p>
        Asigna un asesor a cada propiedad. El predeterminado recibe las
        solicitudes sin propiedad elegida.
      </p>
      {configured === false && (
        <div className="notice">
          Falta configurar TELEGRAM_BOT_TOKEN en el entorno del backend y del
          worker. Las solicitudes se conservan en el CRM.
        </div>
      )}
      {!advisors.some((a) => a.is_default) && (
        <div className="notice">
          Selecciona un asesor predeterminado para recibir las solicitudes
          generales.
        </div>
      )}
      <form
        key={editing?.id ?? "new"}
        className="editor advisor-editor"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          const form = e.currentTarget;
          const values = new FormData(form);
          try {
            await api(
              editing ? `/crm/advisors/${editing.id}` : "/crm/advisors",
              {
                method: editing ? "PUT" : "POST",
                body: JSON.stringify({
                  name: String(values.get("name")).trim(),
                  whatsapp: String(values.get("whatsapp")).trim(),
                  telegram_chat_id: String(
                    values.get("telegram_chat_id"),
                  ).trim(),
                  is_default: values.get("is_default") === "on",
                }),
              },
            );
            setEditing(null);
            form.reset();
            await load();
          } catch (e) {
            setError(
              e instanceof Error ? e.message : "No pudimos guardar el asesor.",
            );
          } finally {
            setBusy(false);
          }
        }}
      >
        <h3>{editing ? "Editar asesor" : "Agregar asesor"}</h3>
        <div className="form-grid">
          <label>
            Nombre
            <input
              name="name"
              required
              maxLength={120}
              defaultValue={editing?.name}
            />
          </label>
          <label>
            WhatsApp
            <input
              name="whatsapp"
              type="tel"
              pattern="\+[1-9][0-9]{7,14}"
              maxLength={16}
              placeholder="+523312345678"
              defaultValue={editing?.whatsapp}
            />
            <small>Incluye + y lada del país, sin espacios. Visible para sus propietarios.</small>
          </label>
          <label>
            ID del chat privado de Telegram
            <input
              name="telegram_chat_id"
              inputMode="numeric"
              pattern="[1-9][0-9]*"
              defaultValue={editing?.telegram_chat_id}
              placeholder="123456789"
            />
            <small>
              El asesor debe iniciar una conversación con el bot. No se admiten
              grupos.
            </small>
          </label>
          <label className="check full">
            <input
              name="is_default"
              type="checkbox"
              defaultChecked={editing?.is_default}
            />
            Asesor predeterminado
          </label>
        </div>
        {error && (
          <ErrorNotice>
            {error}
          </ErrorNotice>
        )}
        <div className="form-actions">
          {editing && (
            <button
              type="button"
              className="button secondary"
              onClick={() => setEditing(null)}
            >
              Cancelar
            </button>
          )}
          <button className="button primary" disabled={busy}>
            {busy ? "Guardando…" : "Guardar asesor"}
          </button>
        </div>
      </form>
      <div className="advisor-list">
        {advisors.map((a) => (
          <div key={a.id}>
            <div>
              <strong>{a.name}</strong>
              <p>WhatsApp: {a.whatsapp || "Pendiente de configurar"}</p>
              <p>
                {a.is_default ? "Predeterminado · " : ""}
                {a.telegram_chat_id
                  ? "Chat privado configurado"
                  : "Sin chat de Telegram"}
              </p>
              <CalendarConnect advisorId={a.id} />
            </div>
            <button className="link-button" onClick={() => setEditing(a)}>
              Editar
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}
