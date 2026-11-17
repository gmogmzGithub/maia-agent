"use client";
import ErrorNotice from "@/shared/components/ErrorFeedback";
import { useEffect, useState } from "react";
import { api } from "@/shared/lib/api";

type Connection = {
  configured: boolean;
  connected: boolean;
  email: string;
  pending?: { id: string; email: string } | null;
};
export default function CalendarConnect({ advisorId }: { advisorId: number }) {
  const [value, setValue] = useState<Connection | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const path = `/crm/advisors/${advisorId}/calendar`;
  async function load() {
    setValue(await api<Connection>(path));
  }
  useEffect(() => {
    void load().catch(() =>
      setError("No pudimos consultar la conexión de Google."),
    );
  }, [advisorId]);
  async function act(action: string, payload = {}) {
    setBusy(true);
    setError("");
    try {
      const result = await api<{ url?: string }>(`${path}/${action}`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (result.url) window.location.assign(result.url);
      else await load();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "No pudimos actualizar la conexión.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="calendar-connection">
      <p>Google Calendar: {value?.connected ? value.email : "Sin conexión"}</p>
      {value?.configured === false ? (
        <p>Google Calendar todavía no está configurado en la plataforma.</p>
      ) : (
        <button
          type="button"
          className="link-button"
          disabled={busy || !value}
          onClick={() => void act("connect")}
        >
          {value?.connected
            ? "Reconectar Google Calendar"
            : "Conectar Google Calendar"}
        </button>
      )}
      {value?.connected && (
        <button
          type="button"
          className="link-button"
          disabled={busy}
          onClick={() => void act("disconnect")}
        >
          Desconectar
        </button>
      )}
      {value?.pending && (
        <div className="notice">
          <p>
            ¿Asignar el calendario principal de{" "}
            <strong>{value.pending.email}</strong> a este asesor?
          </p>
          <button
            className="button primary"
            disabled={busy}
            onClick={() =>
              void act("confirm", { authorization_id: value.pending!.id })
            }
          >
            Confirmar cuenta del asesor
          </button>
        </div>
      )}
      {error && (
        <ErrorNotice>
          {error}
        </ErrorNotice>
      )}
    </div>
  );
}
