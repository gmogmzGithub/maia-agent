(() => {
  "use strict";

  const queueKey = "larevia.pending-saves.v1";
  const live = () => document.getElementById("live-region");
  const announce = (message) => { if (live()) live().textContent = message; };
  const commandKey = (prefix) => `${prefix}-${crypto.randomUUID()}`;

  document.querySelectorAll("img").forEach((image) => {
    image.addEventListener("error", () => image.closest("a,figure,div")?.classList.add("image-failed"));
  });

  const navToggle = document.querySelector("[data-nav-toggle]");
  const siteNav = document.querySelector("[data-site-nav]");
  const setNavigation = (open) => {
    if (!navToggle || !siteNav) return;
    navToggle.setAttribute("aria-expanded", String(open));
    siteNav.classList.toggle("is-open", open);
  };
  navToggle?.addEventListener("click", () => {
    setNavigation(navToggle.getAttribute("aria-expanded") !== "true");
  });
  siteNav?.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => setNavigation(false));
  });

  document.querySelectorAll("[data-prompt]").forEach((prompt) => {
    prompt.addEventListener("click", () => {
      const composer = document.querySelector(".composer textarea");
      if (!composer) return;
      composer.value = prompt.dataset.prompt || "";
      composer.focus();
    });
  });

  document.querySelector("[data-share-page]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const payload = { title: button.dataset.shareTitle || document.title, url: window.location.href };
    try {
      if (navigator.share) await navigator.share(payload);
      else {
        await navigator.clipboard.writeText(payload.url);
        announce("Enlace copiado.");
      }
    } catch (_) {
      announce("No pudimos compartir el enlace desde este navegador.");
    }
  });

  document.querySelectorAll("[data-filter-drawer]").forEach((drawer) => {
    drawer.querySelector("[data-filter-close]")?.addEventListener("click", () => {
      drawer.removeAttribute("open");
      drawer.querySelector("summary")?.focus();
    });
  });

  document.querySelectorAll("[data-property-type-filter]").forEach((select) => {
    const form = select.closest("form");
    const residentialFilters = [...(form?.querySelectorAll("[data-residential-filter]") || [])];
    const updateResidentialFilters = () => {
      const hidden = select.value === "Land";
      residentialFilters.forEach((label) => {
        label.hidden = hidden;
        const field = label.querySelector("input, select");
        if (!field) return;
        field.disabled = hidden;
        if (hidden) field.value = "";
      });
    };
    select.addEventListener("change", updateResidentialFilters);
    updateResidentialFilters();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    setNavigation(false);
    document.querySelectorAll("[data-filter-drawer][open]").forEach((drawer) => {
      drawer.removeAttribute("open");
      drawer.querySelector("summary")?.focus();
    });
  });

  function queued() {
    try { return JSON.parse(localStorage.getItem(queueKey) || "[]"); }
    catch (_) { return []; }
  }

  function storeQueue(commands) {
    localStorage.setItem(queueKey, JSON.stringify(commands.slice(-100)));
  }

  function setSaveState(form, state) {
    const button = form.querySelector(".save-button");
    const label = form.querySelector("[data-save-label]");
    if (!button || !label) return;
    button.classList.toggle("pending", state === "pending");
    button.disabled = state === "submitting";
    button.setAttribute("aria-busy", state === "submitting" ? "true" : "false");
    if (state !== "submitting") {
      button.setAttribute("aria-pressed", state === "saved" ? "true" : "false");
    }
    label.textContent = state === "saved" ? "Guardada" : state === "pending" ? "Pendiente de guardar" : state === "submitting" ? "Guardando…" : "Guardar";
    const action = form.querySelector('input[name="action"]');
    if (action && !["pending", "submitting"].includes(state)) {
      action.value = state === "saved" ? "Remove" : "Add";
    }
  }

  function refreshSaveCommand(form) {
    const input = form.querySelector('input[name="command_key"]');
    if (input) input.value = commandKey("save");
  }

  function phoneDialog(form) {
    return form.querySelector("[data-phone-dialog]");
  }

  function openPhoneDialog(form, message = "") {
    const dialog = phoneDialog(form);
    if (!dialog) return;
    const error = dialog.querySelector("[data-phone-error]");
    if (error) {
      error.textContent = message;
      error.hidden = !message;
    }
    if (!dialog.open) {
      dialog.showModal();
    }
    dialog.querySelector('input[name="phone_number"]')?.focus();
  }

  function closePhoneDialog(form) {
    const dialog = phoneDialog(form);
    if (!dialog) return;
    dialog.close();
  }

  function markPhoneClaimed() {
    document.querySelectorAll("[data-save-form]").forEach((form) => {
      form.dataset.phoneRequired = "false";
      const phone = form.querySelector('input[name="phone_number"]');
      if (phone) phone.value = "";
      closePhoneDialog(form);
    });
  }

  function syncSaveState(listingId, state) {
    document.querySelectorAll("[data-save-form]").forEach((form) => {
      if (form.querySelector('[name="listing_id"]')?.value === listingId) {
        setSaveState(form, state);
      }
    });
  }

  class SaveRequestError extends Error {
    constructor(status, detail, code) {
      super(detail || "No pudimos actualizar tus guardadas.");
      this.code = code || "";
      this.retryable = status === 0 || status >= 500;
    }
  }

  async function sendSave(payload) {
    let response;
    try {
      response = await fetch("/guardadas", {
        method: "POST",
        headers: { "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams(payload),
        credentials: "same-origin"
      });
    } catch (_) {
      throw new SaveRequestError(0, "No pudimos conectarnos.", "network_error");
    }
    let result = {};
    try { result = await response.json(); }
    catch (_) {}
    if (!response.ok) {
      throw new SaveRequestError(response.status, result.detail, result.code);
    }
    return result;
  }

  async function submitSave(form) {
    const payload = Object.fromEntries(new FormData(form).entries());
    const action = String(payload.action || "");
    const requiresPhone = form.dataset.phoneRequired === "true" && action === "Add";
    const suppliedPhone = String(payload.phone_number || "").trim();
    if (requiresPhone && !suppliedPhone) {
      openPhoneDialog(form);
      return null;
    }
    if (!requiresPhone) delete payload.phone_number;
    if (form.dataset.saveBusy === "true") return null;
    const previous = form.querySelector(".save-button")?.getAttribute("aria-pressed") === "true" ? "saved" : "idle";
    form.dataset.saveBusy = "true";
    setSaveState(form, "submitting");
    try {
      const result = await sendSave(payload);
      const saved = Array.isArray(result.items)
        ? result.items.some((item) => String(item.listing_id) === String(payload.listing_id))
        : action === "Add";
      syncSaveState(String(payload.listing_id), saved ? "saved" : "idle");
      refreshSaveCommand(form);
      if (result.phone_claimed || suppliedPhone) markPhoneClaimed();
      announce(saved ? "Propiedad guardada en el servidor." : "Propiedad quitada de guardadas.");
      channel?.postMessage({ listing_id: payload.listing_id, state: saved ? "saved" : "idle" });
      if (saved) track("ListingSaved", "Saved", payload.listing_id, { source: "save_control" });
      return result;
    } catch (error) {
      setSaveState(form, previous);
      if (error instanceof SaveRequestError && error.code === "phone_required") {
        form.dataset.phoneRequired = "true";
        openPhoneDialog(form);
        return null;
      }
      if (error instanceof SaveRequestError && error.code === "invalid_phone") {
        openPhoneDialog(form, error.message);
        return null;
      }
      if (!(error instanceof SaveRequestError) || !error.retryable) {
        announce(error?.message || "No pudimos actualizar tus guardadas.");
        return null;
      }
      if (suppliedPhone) {
        openPhoneDialog(form, "No pudimos conectarnos. Revisa tu conexión e inténtalo de nuevo.");
        return null;
      }
      const commands = queued().filter((item) => item.listing_id !== payload.listing_id);
      commands.push(payload);
      storeQueue(commands);
      setSaveState(form, "pending");
      announce("El guardado está pendiente. Lo reintentaremos cuando vuelva la conexión.");
      return null;
    } finally {
      form.dataset.saveBusy = "false";
    }
  }

  async function retryQueue() {
    const remaining = [];
    const confirmed = [];
    for (const payload of queued()) {
      try {
        const result = await sendSave(payload);
        const saved = Array.isArray(result.items)
          ? result.items.some((item) => String(item.listing_id) === String(payload.listing_id))
          : payload.action === "Add";
        confirmed.push({
          listing_id: payload.listing_id,
          state: saved ? "saved" : "idle"
        });
      }
      catch (error) {
        if (error instanceof SaveRequestError && error.retryable) remaining.push(payload);
      }
    }
    storeQueue(remaining);
    confirmed.forEach((result) => {
      syncSaveState(result.listing_id, result.state);
      document.querySelectorAll("[data-save-form]").forEach((form) => {
        if (form.querySelector('[name="listing_id"]')?.value === result.listing_id) refreshSaveCommand(form);
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
    form.addEventListener("submit", (event) => { event.preventDefault(); void submitSave(form); });
    form.querySelector("[data-phone-close]")?.addEventListener("click", () => closePhoneDialog(form));
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
    const thumbnails = Array.from(gallery.querySelectorAll("[data-gallery-thumbnail]"));
    const output = gallery.querySelector("[data-gallery-count]");
    let active = 0;
    const update = (next) => {
      active = Math.max(0, Math.min(slides.length - 1, next));
      stage?.scrollTo({
        left: active * stage.clientWidth,
        behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"
      });
      if (output) output.textContent = `${active + 1} de ${slides.length}`;
      thumbnails.forEach((thumbnail, index) => {
        if (index === active) thumbnail.setAttribute("aria-current", "true");
        else thumbnail.removeAttribute("aria-current");
      });
    };
    thumbnails.forEach((thumbnail, index) => {
      thumbnail.addEventListener("click", (event) => {
        event.preventDefault();
        update(index);
      });
    });
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
      update(active);
    });
    gallery.addEventListener("click", () => noteViewed(active));
    track("GalleryOpen", "Gallery", listingId, { count: slides.length });
    update(0);
  }
})();

(() => {
  "use strict";

  const launchers = [...document.querySelectorAll("[data-ai-launcher]")];
  const dialog = document.querySelector("[data-ai-dialog]");
  const account = document.querySelector("[data-account-demo]");
  const accountToggle = document.querySelector("[data-account-toggle]");
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const prompts = [
    "Buscar casas en Zapopan",
    "Departamentos en renta",
    "Propiedades con tres recámaras",
    "Ver las propiedades más nuevas",
    "Buscar dentro de mi presupuesto"
  ];
  let promptIndex = 0;
  let promptTimer = null;
  let lastLauncher = null;
  let lastMessage = "";

  const announce = (message) => {
    const region = document.getElementById("live-region");
    if (region) region.textContent = message;
  };

  const rotatePrompt = () => {
    promptIndex = (promptIndex + 1) % prompts.length;
    document.querySelectorAll("[data-ai-prompt]").forEach((item) => {
      item.textContent = prompts[promptIndex];
    });
  };

  const startRotation = () => {
    if (reducedMotion.matches || promptTimer) return;
    promptTimer = window.setInterval(rotatePrompt, 3600);
  };

  const stopRotation = () => {
    if (promptTimer) window.clearInterval(promptTimer);
    promptTimer = null;
  };

  reducedMotion.addEventListener?.("change", () => {
    if (reducedMotion.matches) stopRotation();
    else startRotation();
  });
  startRotation();

  const setAccount = (open) => {
    if (!account || !accountToggle) return;
    account.hidden = !open;
    accountToggle.setAttribute("aria-expanded", String(open));
    if (open) account.querySelector("button")?.focus();
  };

  accountToggle?.addEventListener("click", () => setAccount(account?.hidden ?? true));
  account?.querySelector("[data-account-close]")?.addEventListener("click", () => {
    setAccount(false);
    accountToggle?.focus();
  });

  if (!dialog) return;
  const thread = dialog.querySelector("[data-ai-thread]");
  const empty = dialog.querySelector("[data-ai-empty]");
  const form = dialog.querySelector("[data-ai-form]");
  const input = form?.querySelector("textarea");
  const status = dialog.querySelector("[data-ai-status]");
  const submit = form?.querySelector('button[type="submit"]');
  const conversationActions = [...dialog.querySelectorAll("[data-ai-conversation-action]")];
  const pageLayer = document.querySelector("[data-page-layer]");
  const header = document.querySelector("[data-site-header]");

  const setStatus = (message, error = false) => {
    if (!status) return;
    status.textContent = message;
    status.hidden = !message;
    status.classList.toggle("ai-error", error);
  };

  const setBackgroundInert = (inert) => {
    document.body.classList.toggle("ai-open", inert);
    if (pageLayer) pageLayer.inert = inert;
    if (header) header.inert = inert;
  };

  const setConversationBusy = (busy) => {
    if (submit) submit.disabled = busy;
    conversationActions.forEach((button) => { button.disabled = busy; });
    form?.setAttribute("aria-busy", String(busy));
  };

  const openDialog = (seed = "") => {
    lastLauncher = document.activeElement;
    setAccount(false);
    stopRotation();
    if (!dialog.open) dialog.showModal();
    setBackgroundInert(true);
    if (seed && input && !input.value) input.value = seed;
    window.requestAnimationFrame(() => input?.focus());
  };

  const closeDialog = () => {
    if (dialog.open) dialog.close();
  };

  dialog.addEventListener("close", () => {
    setBackgroundInert(false);
    startRotation();
    if (lastLauncher instanceof HTMLElement) lastLauncher.focus();
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) closeDialog();
  });

  launchers.forEach((launcher) => {
    launcher.addEventListener("focus", stopRotation);
    launcher.addEventListener("click", () => openDialog(launcher.dataset.aiSeed || ""));
  });
  dialog.querySelector("[data-ai-close]")?.addEventListener("click", closeDialog);

  dialog.querySelector("[data-ai-expand]")?.addEventListener("click", (event) => {
    const expanded = dialog.classList.toggle("is-expanded");
    event.currentTarget.setAttribute("aria-pressed", String(expanded));
    event.currentTarget.setAttribute("aria-label", expanded ? "Reducir conversación" : "Expandir conversación");
  });

  const clearThread = () => {
    thread?.querySelectorAll(".ai-message").forEach((message) => message.remove());
    if (empty) empty.hidden = false;
    if (input) input.value = "";
    setStatus("");
  };

  const closeConversation = async (deleteContent) => {
    setConversationBusy(true);
    setStatus(deleteContent ? "Borrando conversación…" : "Iniciando una conversación nueva…");
    try {
      const response = await fetch(`/maia/conversacion?borrar_contenido=${deleteContent}`, {
        method: "DELETE",
        headers: { "Accept": "application/json" }
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "No pudimos terminar la conversación.");
      clearThread();
      announce(payload.detail || "La conversación terminó.");
      input?.focus();
    } finally {
      setConversationBusy(false);
    }
  };

  dialog.querySelector("[data-ai-new]")?.addEventListener("click", async () => {
    try { await closeConversation(false); }
    catch (error) { setStatus(error.message, true); }
  });
  dialog.querySelector("[data-ai-delete]")?.addEventListener("click", async () => {
    if (!window.confirm("¿Borrar el contenido visible de esta conversación?")) return;
    try { await closeConversation(true); }
    catch (error) { setStatus(error.message, true); }
  });

  const messageNode = (role, body) => {
    const item = document.createElement("li");
    item.className = `ai-message ai-message-${role}`;
    const paragraph = document.createElement("p");
    paragraph.textContent = String(body).replaceAll("**", "");
    item.append(paragraph);
    thread?.append(item);
    item.scrollIntoView({ block: "nearest" });
    return item;
  };

  const money = (offer) => {
    if (offer?.price_amount == null) return offer?.consultation_copy || "Precio previa consulta";
    const amount = Number(offer.price_amount);
    const formatted = Number.isFinite(amount)
      ? new Intl.NumberFormat("es-MX", { style: "currency", currency: offer.price_currency || "MXN", maximumFractionDigits: 0 }).format(amount)
      : String(offer.price_amount);
    return offer.operation === "Rental" ? `${formatted} / mes` : formatted;
  };

  const renderResults = (container, result) => {
    const matches = Array.isArray(result.matches) ? result.matches.slice(0, 3) : [];
    if (matches.length) {
      const list = document.createElement("div");
      list.className = "ai-result-list";
      matches.forEach((match) => {
        const card = document.createElement("a");
        card.className = "ai-result-card";
        card.href = `/propiedades/${encodeURIComponent(match.slug)}`;
        if (match.cover_url) {
          const image = document.createElement("img");
          image.src = `${match.cover_url}?w=480`;
          image.alt = "";
          image.loading = "lazy";
          card.append(image);
        } else {
          const placeholder = document.createElement("span");
          placeholder.className = "image-placeholder";
          placeholder.setAttribute("aria-hidden", "true");
          card.append(placeholder);
        }
        const copy = document.createElement("span");
        const title = document.createElement("strong");
        title.textContent = match.title || "Propiedad";
        const location = document.createElement("span");
        location.textContent = match.public_location || "";
        const price = document.createElement("span");
        price.textContent = money((match.offers || [])[0]);
        copy.append(title, location, price);
        card.append(copy);
        list.append(card);
      });
      container.append(list);
    }
    if (result.public_url && String(result.public_url).startsWith("/propiedades")) {
      const link = document.createElement("a");
      link.className = "ai-results-link";
      link.href = result.public_url;
      link.textContent = `Ver las ${result.total || 0} propiedades`;
      container.append(link);
    }
    container.scrollIntoView({ block: "end" });
  };

  const poll = async (turnId) => {
    for (let attempt = 0; attempt < 150; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 800));
      const response = await fetch(`/maia/turnos/${encodeURIComponent(turnId)}`, { headers: { "Accept": "application/json" } });
      const progress = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(progress.detail || "No pudimos consultar la respuesta.");
      if (progress.status === "Complete") return progress.result || {};
      if (progress.status === "Failed") throw new Error(progress.error_message || "No pudimos completar la respuesta.");
    }
    throw new Error("La respuesta está tardando más de lo esperado.");
  };

  const send = async (text) => {
    lastMessage = text;
    if (empty) empty.hidden = true;
    messageNode("person", text);
    setStatus("Maia está revisando las propiedades…");
    setConversationBusy(true);
    try {
      const accepted = await fetch("/maia/turnos", {
        method: "POST",
        headers: { "Accept": "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, command_key: `modal-${crypto.randomUUID()}`, listing_ids: [] })
      });
      const payload = await accepted.json().catch(() => ({}));
      if (!accepted.ok) throw new Error(payload.detail || "No pudimos enviar el mensaje.");
      const result = await poll(payload.turn_id);
      const responseNode = messageNode("maia", result.reply || "Encontré estas opciones autorizadas.");
      renderResults(responseNode, result);
      setStatus("");
    } catch (error) {
      setStatus(error.message, true);
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "ai-retry";
      retry.textContent = "Reintentar";
      retry.addEventListener("click", () => {
        retry.remove();
        send(lastMessage);
      }, { once: true });
      status?.append(retry);
    } finally {
      setConversationBusy(false);
      input?.focus();
    }
  };

  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input?.value.trim() || "";
    if (!text || submit?.disabled) return;
    input.value = "";
    send(text);
  });
  input?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form?.requestSubmit();
    }
  });
  dialog.querySelectorAll("[data-ai-suggestion]").forEach((button) => {
    button.addEventListener("click", () => {
      if (input) input.value = button.dataset.aiSuggestion || button.textContent.trim();
      input?.focus();
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && account && !account.hidden) {
      setAccount(false);
      accountToggle?.focus();
    }
  });
})();
