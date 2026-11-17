"use client";
import ErrorNotice from "@/shared/components/ErrorFeedback";
import { useState } from "react";
import { api, type Conversation } from "@/shared/lib/api";
import {
  type Visit,
  type VisitProposal,
  visitLabels,
  visitTime,
} from "@/shared/lib/booking";

export default function VisitCard({
  conversation,
  onChange,
  showAppointments = true,
  showProposal = true,
}: {
  conversation: Conversation;
  onChange: (value: Conversation) => void;
  showAppointments?: boolean;
  showProposal?: boolean;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const proposal = showProposal ? conversation.visit_proposal as VisitProposal | null : null;
  const visits = conversation.appointments as Visit[];
  return (
    <section className="visit-cards" aria-label="Tus visitas">
      {showAppointments && visits.map((a) => (
        <article key={a.id} className="notice">
          <strong>{a.property_title}</strong>
          <p>
            {visitTime(a.start)} a {visitTime(a.end)} · Guadalajara
          </p>
          <p>
            {visitLabels[a.status] ?? a.status} · {a.advisor}
          </p>
          {["queued", "running", "verifying"].includes(a.operation_status) && (
            <p role="status">
              Estamos verificando la operación con Google. Todavía no
              confirmamos el cambio.
            </p>
          )}
          {a.status === "review" && (
            <p>El asesor debe revisar esta cita. Conservamos tu solicitud.</p>
          )}
        </article>
      ))}
      {proposal && (
        <article className="notice">
          <h3>{visitLabels[proposal.action]}</h3>
          <p>
            {proposal.property_title} · {proposal.advisor}
          </p>
          <p>
            {visitTime(proposal.start)} a {visitTime(proposal.end)} · Hora de
            Guadalajara
          </p>
          <p>Revisa los datos. Comprobaremos la disponibilidad al confirmar.</p>
          <button
            type="button"
            className="button primary"
            disabled={busy || conversation.automation_paused}
            onClick={async () => {
              setBusy(true);
              setError("");
              try {
                const result = await api<{ conversation: Conversation }>(
                  `/conversations/${conversation.id}/visits/confirm`,
                  {
                    method: "POST",
                    body: JSON.stringify({
                      proposal_id: proposal.id,
                      confirmed: true,
                    }),
                  },
                );
                onChange(result.conversation);
              } catch (e) {
                setError(
                  e instanceof Error
                    ? e.message
                    : "No pudimos confirmar la operación.",
                );
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy
              ? "Procesando…"
              : proposal.action === "cancel"
                ? "Confirmar cancelación"
                : "Confirmar visita"}
          </button>
        </article>
      )}
      {error && (
        <ErrorNotice>
          {error}
        </ErrorNotice>
      )}
    </section>
  );
}
