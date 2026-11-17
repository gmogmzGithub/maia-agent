"use client";
import ErrorNotice from "@/shared/components/ErrorFeedback";

import { useEffect, useRef } from "react";
import ContactCard from "@/main-website/components/ContactCard";
import VisitCard from "@/main-website/components/VisitCard";
import Replies from "@/main-website/conversation/Replies";
import useConversation from "@/main-website/conversation/useConversation";
import useSearchSuggestion from "@/main-website/components/useSearchSuggestion";

export default function Chat({ onActivityChange }: { onActivityChange: (active: boolean) => void }) {
  const { conversation, text, setText, error, sending, waitingLong, available,
    canRetry, canRefresh, sendMessage, updateConversation, newSearch, retry, refresh } = useConversation();
  const messages = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const pane = messages.current;
    if (pane)
      pane.scrollTo({
        top: pane.scrollHeight,
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "instant"
          : "smooth",
      });
  }, [conversation?.messages.length]);
  function send(e: React.FormEvent) {
    e.preventDefault();
    void sendMessage(text);
  }

  const hasMessages = !!conversation && (!!conversation.messages.length || conversation.processing || conversation.has_interest);
  useEffect(() => onActivityChange(hasMessages), [hasMessages, onActivityChange]);
  const searchSuggestion = useSearchSuggestion(!hasMessages && text.length === 0);
  return (
    <div
      className={`chat-shell landing-chat ${hasMessages ? "has-messages" : "is-empty"}`}
      id="conversacion"
    >
      <div className="landing-intro">
        <h1>¿Dónde te gustaría vivir?</h1>
        <p>Escribe lo que buscas. Maia te ayuda a encontrarlo.</p>
      </div>
      {hasMessages && (
        <div className="chat-heading">
          <span className="conversation-label">Tu búsqueda con Maia</span>
          <button
            className="link-button new-chat"
            disabled={sending}
            onClick={() => {
              newSearch();
              input.current?.focus();
            }}
          >
            Nueva búsqueda
          </button>
        </div>
      )}
        <div
          className={hasMessages ? "chat-messages" : "chat-feedback"}
          ref={messages}
          tabIndex={hasMessages ? 0 : undefined}
          role={hasMessages ? "region" : undefined}
          aria-label={hasMessages ? "Historial y gestiones de la conversación" : undefined}
          aria-live="polite"
          aria-busy={conversation?.processing ?? false}
        >
          {conversation && <Replies conversation={conversation} sending={sending} available={available}
            updateConversation={updateConversation}
            onInterest={(property) => void sendMessage(`Me interesa ${property.title}. ¿Me puedes dar más información?`, false, property.id)} />}
          {conversation?.processing && (
            <div className="typing" role="status">
              <span>● ● ●</span>
              {waitingLong
                ? "Estoy revisando la información para responderte."
                : "Maia está revisando tu búsqueda…"}
            </div>
          )}
      {available === false && (
        <div className="notice">
          El asistente todavía no está disponible. Puedes explorar el inventario
          con los filtros.
        </div>
      )}
      {conversation?.automation_paused && (
        <div className="notice">
          La atención automática está pausada por el equipo. Tus mensajes siguen
          guardándose para el asesor.
        </div>
      )}
      {conversation && (
        <VisitCard
          conversation={conversation}
          showProposal={!conversation.structured_reply}
          onChange={updateConversation}
        />
      )}
      {conversation && !conversation.structured_reply && (
        <ContactCard
          key={conversation.id}
          conversation={conversation}
          onChange={updateConversation}
        />
      )}
      {conversation?.structured_reply && conversation.contact_registered && (
        <details className="contact-preferences">
          <summary>Mi contacto y preferencias de WhatsApp</summary>
          <ContactCard conversation={conversation} onChange={updateConversation} />
        </details>
      )}
      {error && (
        <ErrorNotice>
          {error}{" "}
          {canRetry && <button type="button" className="link-button" disabled={sending}
            onClick={retry}>Reintentar envío</button>}{" "}
          {canRefresh && <button className="link-button" onClick={refresh}>Actualizar</button>}
        </ErrorNotice>
      )}
        </div>
      <form className="chat-form" onSubmit={send}>
        <span className="composer-home" aria-hidden="true">
          <svg width="28" height="28" viewBox="0 0 32 32" fill="none">
            <path d="M4 14 16 4l12 10M7 12v15h18V12M13 27V18h6v9" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
        <label className="sr-only" htmlFor="chat-input">
          Describe la propiedad que buscas
        </label>
        <textarea
          ref={input}
          id="chat-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={hasMessages ? "Continuemos la conversación…" : searchSuggestion}
          rows={1}
          maxLength={10000}
          disabled={available === false}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              e.currentTarget.form?.requestSubmit();
            }
          }}
        />
        <button
          type="submit"
          className="send-button"
          disabled={!text.trim() || sending || available !== true}
          aria-label="Enviar mensaje"
        >
          ↑
        </button>
      </form>
      {!hasMessages && (
        <div className="suggestions landing-suggestions">
          {[
            ["⌂", "Una casa en renta en Zapopan"],
            ["↗", "Un departamento hasta $25,000 al mes"],
            ["✧", "Todavía no sé, ayúdame a buscar"],
          ].map(([icon, label]) => (
            <button
              key={label}
              onClick={() => {
                setText(label);
                input.current?.focus();
              }}
            >
              <span className="suggestion-icon" aria-hidden="true">
                {icon}
              </span>
              {label}
              <span className="suggestion-arrow" aria-hidden="true">
                ↗
              </span>
            </button>
          ))}
        </div>
      )}
      {hasMessages && (
        <p className="chat-footnote">
          Busca a tu ritmo. Puedes cambiar lo que necesitas en cualquier
          momento.
        </p>
      )}
    </div>
  );
}
