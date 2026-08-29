(() => {
  "use strict";

  const queueKey = "larevia.pending-saves.v1";
  const live = () => document.getElementById("live-region");
  const announce = (message) => { if (live()) live().textContent = message; };
  const commandKey = (prefix) => `${prefix}-${crypto.randomUUID()}`;

  document.querySelectorAll("img").forEach((image) => {
    image.addEventListener("error", () => image.closest("a,figure,div")?.classList.add("image-failed"));
  });

  function queued() {
    try { return JSON.parse(localStorage.getItem(queueKey) || "[]"); }
    catch (_) { return []; }
  }

  function storeQueue(commands) {
    localStorage.setItem(queueKey, JSON.stringify(commands.slice(-100)));
  }

  function setSaveState(form, state) {
    const button = form.querySelector("button");
    const label = form.querySelector("[data-save-label]");
    if (!button || !label) return;
    button.classList.toggle("pending", state === "pending");
    button.setAttribute("aria-pressed", state === "saved" ? "true" : "false");
    label.textContent = state === "saved" ? "Guardada" : state === "pending" ? "Pendiente de guardar" : "Guardar";
    const action = form.querySelector('input[name="action"]');
    if (action && state !== "pending") action.value = state === "saved" ? "Remove" : "Add";
  }

  async function sendSave(payload) {
    const response = await fetch("/guardadas", {
      method: "POST",
      headers: { "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(payload),
      credentials: "same-origin"
    });
    if (!response.ok) throw new Error("save_failed");
    return response.json();
  }

  async function submitSave(form) {
    const payload = Object.fromEntries(new FormData(form).entries());
    try {
      const result = await sendSave(payload);
      const saved = payload.action === "Add";
      setSaveState(form, saved ? "saved" : "idle");
      announce(saved ? "Propiedad guardada en el servidor." : "Propiedad quitada de guardadas.");
      channel?.postMessage({ listing_id: payload.listing_id, state: saved ? "saved" : "idle" });
      if (saved) track("ListingSaved", "Saved", payload.listing_id, { source: "save_control" });
      return result;
    } catch (_) {
      const commands = queued().filter((item) => item.listing_id !== payload.listing_id);
      commands.push(payload);
      storeQueue(commands);
      setSaveState(form, "pending");
      announce("El guardado está pendiente. Lo reintentaremos cuando vuelva la conexión.");
      return null;
    }
  }

  async function retryQueue() {
    const remaining = [];
    const confirmed = [];
    for (const payload of queued()) {
      try {
        await sendSave(payload);
        confirmed.push({
          listing_id: payload.listing_id,
          state: payload.action === "Add" ? "saved" : "idle"
        });
      }
      catch (_) { remaining.push(payload); }
    }
    storeQueue(remaining);
    confirmed.forEach((result) => {
      document.querySelectorAll("[data-save-form]").forEach((form) => {
        if (form.querySelector('[name="listing_id"]')?.value === result.listing_id) {
          setSaveState(form, result.state);
        }
      });
    });
    if (!remaining.length && confirmed.length) {
      announce("Los guardados pendientes quedaron confirmados por el servidor.");
    }
  }

  const channel = "BroadcastChannel" in window ? new BroadcastChannel("larevia-saved") : null;
  channel?.addEventListener("message", (event) => {
    document.querySelectorAll("[data-save-form]").forEach((form) => {
      if (form.querySelector('[name="listing_id"]')?.value === event.data.listing_id) {
        setSaveState(form, event.data.state);
      }
    });
  });

  document.querySelectorAll("[data-save-form]").forEach((form) => {
    form.addEventListener("submit", (event) => { event.preventDefault(); submitSave(form); });
  });
  window.addEventListener("online", retryQueue);
  if (navigator.onLine && queued().length) retryQueue();

  function track(name, surface, listingId, properties = {}) {
    const exposure = new URLSearchParams(window.location.search).get("patrocinio");
    const body = JSON.stringify({
      event_key: commandKey("event"),
      name,
      surface,
      listing_id: listingId || null,
      properties,
      exposure_id: exposure,
      occurred_at: new Date().toISOString()
    });
    if (navigator.sendBeacon) {
      navigator.sendBeacon("/eventos", new Blob([body], { type: "application/json" }));
    } else {
      fetch("/eventos", { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true });
    }
  }

  // A paid placement reports the measured fraction and the measured duration.
  // It never reports "this was visible": the versioned threshold lives in
  // Product, so a modified client cannot manufacture a Visible Impression.
  function reportVisible(card, ratio, milliseconds) {
    const exposure = card.dataset.sponsoredExposure;
    if (!exposure) return;
    const body = JSON.stringify({
      exposure_id: exposure,
      visible_fraction: Math.min(1, Math.max(0, ratio)),
      continuous_milliseconds: milliseconds,
      occurred_at: new Date().toISOString()
    });
    if (navigator.sendBeacon) {
      navigator.sendBeacon("/patrocinadas/visible", new Blob([body], { type: "application/json" }));
    } else {
      fetch("/patrocinadas/visible", { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true });
    }
  }

  if ("IntersectionObserver" in window) {
    const timers = new WeakMap();
    const ratios = new WeakMap();
    const seen = new WeakSet();
    const VISIBLE_MS = 1000;
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        ratios.set(entry.target, entry.intersectionRatio);
        if (entry.intersectionRatio >= 0.5 && !seen.has(entry.target)) {
          timers.set(entry.target, window.setTimeout(() => {
            seen.add(entry.target);
            observer.unobserve(entry.target);
            track("ListingImpression", entry.target.dataset.surface || "Search", entry.target.dataset.listingId);
            reportVisible(entry.target, ratios.get(entry.target) || 0, VISIBLE_MS);
          }, VISIBLE_MS));
        } else if (timers.has(entry.target)) {
          clearTimeout(timers.get(entry.target));
          timers.delete(entry.target);
        }
      });
    }, { threshold: [0, 0.5, 1] });
    document.querySelectorAll('[data-analytics="ListingImpression"]').forEach((card) => observer.observe(card));
  }

  const gallery = document.querySelector("[data-gallery]");
  if (gallery) {
    const stage = gallery.querySelector(".gallery-stage");
    const slides = Array.from(gallery.querySelectorAll(".gallery-slide"));
    const output = gallery.querySelector("[data-gallery-count]");
    let active = 0;
    const update = (next) => {
      active = Math.max(0, Math.min(slides.length - 1, next));
      stage?.scrollTo({
        left: active * stage.clientWidth,
        behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"
      });
      if (output) output.textContent = `${active + 1} de ${slides.length}`;
    };
    gallery.querySelector("[data-gallery-prev]")?.addEventListener("click", () => update(active - 1));
    gallery.querySelector("[data-gallery-next]")?.addEventListener("click", () => update(active + 1));
    gallery.addEventListener("keydown", (event) => {
      if (event.key === "ArrowLeft") update(active - 1);
      if (event.key === "ArrowRight") update(active + 1);
    });
    // Gallery depth, for Significant Gallery Exploration. Only two numbers are
    // ever sent — how many photographs were reached and what share of the
    // gallery that is — and Product applies the versioned threshold. The site
    // does not track dwell time, scroll paths or anything per photograph.
    const viewed = new Set();
    const listingId = document.querySelector('[name="listing_id"]')?.value || null;
    let depthReported = false;
    const reportDepth = () => {
      if (depthReported || !slides.length) return;
      const fraction = viewed.size / slides.length;
      const body = JSON.stringify({
        event_key: commandKey("gallery"),
        listing_id: listingId,
        photographs: viewed.size,
        gallery_fraction: fraction,
        exposure_id: new URLSearchParams(window.location.search).get("patrocinio"),
        occurred_at: new Date().toISOString()
      });
      if (navigator.sendBeacon) {
        navigator.sendBeacon("/medicion/galeria", new Blob([body], { type: "application/json" }));
      } else {
        fetch("/medicion/galeria", { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true });
      }
      depthReported = true;
    };
    const noteViewed = (index) => {
      viewed.add(index);
      if (viewed.size >= 5 || viewed.size / slides.length >= 0.3) reportDepth();
    };
    noteViewed(0);
    stage?.addEventListener("scrollend", () => {
      if (!stage.clientWidth) return;
      active = Math.round(stage.scrollLeft / stage.clientWidth);
      noteViewed(active);
      if (output) output.textContent = `${active + 1} de ${slides.length}`;
    });
    gallery.addEventListener("click", () => noteViewed(active));
    track("GalleryOpen", "Gallery", listingId, { count: slides.length });
  }
})();
