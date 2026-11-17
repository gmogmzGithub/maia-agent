"use client";

import type { Conversation, Property } from "@/shared/lib/api";
import PropertyCard from "@/shared/components/PropertyCard";
import ContactCard from "@/main-website/components/ContactCard";
import VisitCard from "@/main-website/components/VisitCard";
import MessageText from "@/main-website/components/MessageText";

/** Render accepted blocks in order; never infer a question or control from text. */
export default function Replies({ conversation, sending, available, onInterest, updateConversation }: {
  conversation: Conversation;
  sending: boolean;
  available: boolean | null;
  onInterest: (property: Property) => void;
  updateConversation: (conversation: Conversation) => void;
}) {
  return <>{conversation.messages.map((message) => {
    const propertyCards = (ids?: number[]) => {
      const properties = ids
        ? ids.map((id) => message.properties.find((p) => p.id === id)).filter((p) => p !== undefined)
        : message.properties;
      return (
        <div className="chat-properties" role="region" aria-label="Propiedades de esta respuesta" tabIndex={0}>
          {properties.slice(0, 3).map((property) => (
            <PropertyCard key={property.id} property={property} compact criteria={conversation.criteria}
              interestDisabled={sending || !!conversation.processing || available !== true}
              onInterest={onInterest} />
          ))}
        </div>
      );
    };
    const active = message.id === conversation.active_message_id;
    return (
      <div className={`chat-message ${message.role}`} key={message.id}>
        <span className="message-author">{message.role === "user" ? "Tú" : "Maia"}</span>
        {message.presentation ? message.presentation.map((block, index) => (
          <div key={index}>
            {block.kind === "text" && <MessageText text={block.text ?? ""} />}
            {block.kind === "properties" && propertyCards(block.property_ids ?? [])}
            {active && block.kind === "contact" && conversation.active_control === "contact" && (
              <ContactCard conversation={conversation} onChange={updateConversation} initiallyOpen />
            )}
            {active && block.kind === "visit" && conversation.active_control === "visit"
              && block.proposal_id === conversation.active_proposal_id && (
              <VisitCard conversation={conversation} onChange={updateConversation} showAppointments={false} />
            )}
          </div>
        )) : <>
          {message.role === "assistant" ? <MessageText text={message.text} /> : <p>{message.text}</p>}
          {message.properties.length > 0 && propertyCards()}
        </>}
      </div>
    );
  })}</>;
}
