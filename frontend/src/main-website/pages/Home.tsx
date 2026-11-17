"use client";

import { useEffect, useRef, useState } from "react";
import Header from "@/shared/components/Header";
import Chat from "@/main-website/components/Chat";
import Inventory from "@/main-website/components/Inventory";
import "@/main-website/styles/landing.css";
import "@/main-website/styles/chat-properties.css";
import "@/main-website/styles/conversation-view.css";

export default function Home() {
  const [hasConversation, setHasConversation] = useState(false);
  const [inventoryView, setInventoryView] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const expanded = hasConversation && !inventoryView;

  useEffect(() => {
    const readView = () => setInventoryView(window.location.hash === "#inventario");
    readView();
    window.addEventListener("hashchange", readView);
    return () => window.removeEventListener("hashchange", readView);
  }, []);

  useEffect(() => {
    if (!expanded) return;
    const viewport = window.visualViewport;
    const update = () => {
      root.current?.style.setProperty("--conversation-height", `${viewport?.height ?? window.innerHeight}px`);
      root.current?.style.setProperty("--conversation-top", `${viewport?.offsetTop ?? 0}px`);
    };
    update();
    viewport?.addEventListener("resize", update);
    viewport?.addEventListener("scroll", update);
    window.addEventListener("resize", update);
    return () => {
      viewport?.removeEventListener("resize", update);
      viewport?.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
      root.current?.style.removeProperty("--conversation-height");
      root.current?.style.removeProperty("--conversation-top");
    };
  }, [expanded]);

  useEffect(() => {
    if (inventoryView) document.getElementById("inventario")?.scrollIntoView();
  }, [inventoryView]);

  return (
    <div ref={root} className={`home-page${expanded ? " conversation-active" : ""}`}>
      <Header onPropertiesClick={(event) => {
        if (!hasConversation || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        setInventoryView(true);
        window.history.replaceState(window.history.state, "", `${window.location.pathname}${window.location.search}#inventario`);
      }} />
      <main>
        <section hidden={hasConversation && inventoryView} className="conversation-landing" aria-label="Busca conversando con Maia">
          <Chat onActivityChange={setHasConversation} />
          <a hidden={hasConversation} href="#inventario" className="explore-inventory">
            <span className="explore-label">
              Explora todas las propiedades
              <small>Desliza hacia abajo</small>
            </span>
            <span className="explore-arrow" aria-hidden="true">↓</span>
          </a>
        </section>
        <div hidden={expanded}>
          {hasConversation && inventoryView && <div className="inventory-return">
            <button className="button secondary" onClick={() => {
              setInventoryView(false);
              window.history.replaceState(window.history.state, "", `${window.location.pathname}${window.location.search}#conversacion`);
            }}>
              ← Volver a la conversación
            </button>
          </div>}
          <Inventory />
        </div>
      </main>
      <footer hidden={expanded}>
        <span className="footer-brand">maia.</span>
        <p>Un lugar para tu siguiente etapa.</p>
        <span>Guadalajara · Zapopan · Tlaquepaque · Tonalá</span>
      </footer>
    </div>
  );
}
