"use client";
import ErrorNotice from "@/shared/components/ErrorFeedback";

import { useEffect, useState } from "react";
import { api, type Conversation } from "@/shared/lib/api";

export default function ContactCard({
  conversation,
  onChange,
  initiallyOpen = false,
}: {
  conversation: Conversation;
  onChange: (value: Conversation) => void;
  initiallyOpen?: boolean;
}) {
  const candidate = conversation.pending_contact;
  const [open, setOpen] = useState(initiallyOpen);
  const [dismissed, setDismissed] = useState(false);
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [followup, setFollowup] = useState(false);
  useEffect(() => {
    if (candidate?.phone) {
      setPhone(candidate.phone);
      setName(candidate.name ?? "");
      setOpen(true);
      setDismissed(false);
    }
  }, [candidate?.phone, candidate?.name]);
  if (conversation.contact_registered)
    return (
      <section className="contact-registered">
        <p>Contacto registrado. Puedes seguir conversando aquí.</p>
        <label className="check">
          <input
            type="checkbox"
            checked={conversation.followup_permission === true}
            disabled={busy}
            onChange={async (event) => {
              setBusy(true);
              setError("");
              try {
                onChange(
                  await api<Conversation>(
                    `/conversations/${conversation.id}/followup-permission`,
                    {
                      method: "PUT",
                      body: JSON.stringify({ allowed: event.target.checked }),
                    },
                  ),
                );
              } catch (error) {
                setError(
                  error instanceof Error
                    ? error.message
                    : "No pudimos guardar tu preferencia.",
                );
              } finally {
                setBusy(false);
              }
            }}
          />
          Quiero recibir seguimiento de mi búsqueda por WhatsApp. Puedo pedir la
          baja cuando quiera.
        </label>
        {error && <ErrorNotice>{error}</ErrorNotice>}
      </section>
    );
  if (!conversation.has_interest && !conversation.human_requested && !candidate)
    return null;
  if (!open || dismissed)
    return (
      <button
        className="link-button contact-invite"
        onClick={() => {
          setOpen(true);
          setDismissed(false);
        }}
      >
        Compartir mi celular para que me contacten
      </button>
    );
  const ready = candidate?.phone === phone;
  return (
    <form
      className="contact-card"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError("");
        try {
          const path = `/conversations/${conversation.id}/contact/${ready ? "confirm" : "prepare"}`;
          onChange(
            await api<Conversation>(path, {
              method: "POST",
              body: JSON.stringify({
                phone,
                name,
                ...(ready
                  ? { confirmed: true, whatsapp_followup: followup }
                  : {}),
              }),
            }),
          );
        } catch (e) {
          setError(
            e instanceof Error
              ? e.message
              : "Revisa tu número e intenta de nuevo.",
          );
        } finally {
          setBusy(false);
        }
      }}
    >
      <strong>
        {ready
          ? "¿Tu número está bien escrito?"
          : "¿A qué celular te podemos contactar?"}
      </strong>
      <p>Puedes continuar en el website. No necesitas cambiarte a WhatsApp.</p>
      <div className="contact-fields">
        <label>
          Celular
          <input
            name="phone"
            type="tel"
            autoComplete="tel"
            inputMode="tel"
            required
            maxLength={40}
            placeholder="+52 33 1234 5678"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
          />
        </label>
        <label>
          Nombre <small>(opcional)</small>
          <input
            name="name"
            autoComplete="given-name"
            maxLength={120}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
      </div>
      <label className="check">
        <input
          type="checkbox"
          checked={followup}
          onChange={(event) => setFollowup(event.target.checked)}
        />
        Quiero recibir seguimiento de mi búsqueda por WhatsApp. Puedo pedir la
        baja cuando quiera.
      </label>
      {error && (
        <ErrorNotice>
          {error}
        </ErrorNotice>
      )}
      <div className="contact-actions">
        <button
          type="button"
          className="link-button"
          onClick={() => setDismissed(true)}
        >
          Continuar sin compartirlo
        </button>
        <button className="button primary" disabled={busy}>
          {busy
            ? "Guardando…"
            : ready
              ? "Confirmar mi número"
              : "Revisar número"}
        </button>
      </div>
    </form>
  );
}
