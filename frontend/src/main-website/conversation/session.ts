import type { Conversation } from "../../shared/lib/api";

type Submission = { text: string; id: string; clearDraft: boolean; propertyId?: number };
export type ConversationIO = {
  request: <T>(path: string, init?: RequestInit) => Promise<T>;
  session: () => Promise<{ ai_configured: boolean }>;
  saved: { get: () => string | null; set: (id: string) => void; clear: () => void };
  id: () => string;
  schedule: (callback: () => void, delay: number) => ReturnType<typeof setTimeout>;
  cancel: (timer: ReturnType<typeof setTimeout>) => void;
};

const initialState = {
  conversation: null as Conversation | null,
  text: "", error: "", sending: false, waitingLong: false,
  available: null as boolean | null, canRetry: false, canRefresh: false,
};

/** Owns session restoration, retries and polling. Rendering never manages requests. */
export class ConversationSession {
  private state = { ...initialState };
  private listeners = new Set<() => void>();
  private activeId: string | null = null;
  private submission: Submission | null = null;
  private timer?: ReturnType<typeof setTimeout>;
  private waitingTimer?: ReturnType<typeof setTimeout>;
  private generation = 0;
  private refreshRevision = 0;
  private closed = false;

  constructor(private readonly io: ConversationIO) {}

  snapshot = () => this.state;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  private patch(value: Partial<typeof initialState>) {
    this.state = { ...this.state, ...value };
    this.listeners.forEach((listener) => listener());
  }
  private cancelPoll() {
    if (this.timer !== undefined) this.io.cancel(this.timer);
    this.timer = undefined;
  }
  private current(generation: number, id?: string) {
    return !this.closed && generation === this.generation && (!id || this.activeId === id);
  }
  private accept(value: Conversation) {
    const changed = this.state.conversation?.processing !== value.processing;
    this.patch({ conversation: value });
    if (changed) {
      if (this.waitingTimer !== undefined) this.io.cancel(this.waitingTimer);
      this.patch({ waitingLong: false });
      if (value.processing) this.waitingTimer = this.io.schedule(() => {
        if (!this.closed) this.patch({ waitingLong: true });
      }, 15000);
    }
  }

  async start(propertyId: string | null, consumeProperty: () => void) {
    this.closed = false;
    const generation = ++this.generation;
    try {
      const session = await this.io.session();
      if (!this.current(generation)) return;
      this.patch({ available: session.ai_configured });
      const saved = this.io.saved.get();
      if (saved) {
        try {
          const previous = await this.io.request<Conversation>(`/conversations/${saved}`);
          if (!this.current(generation)) return;
          this.activeId = previous.id;
          this.patch({ canRefresh: true });
          this.accept(previous);
          if (previous.processing || previous.visits_processing) void this.refresh();
        } catch {
          if (this.current(generation)) this.patch({ error: "No pudimos recuperar tu conversación. Recarga para volver a intentarlo." });
          return;
        }
      }
      if (propertyId && /^\d+$/.test(propertyId)) {
        if (!session.ai_configured) {
          this.patch({ error: "El asistente todavía no está disponible para recibir tu interés." });
          return;
        }
        consumeProperty();
        await this.send("Me interesa esta propiedad. ¿Me puedes dar más información?", false, Number(propertyId));
      }
    } catch {
      if (this.current(generation)) this.patch({ error: "No pudimos conectar. Intenta nuevamente." });
    }
  }

  stop() {
    this.closed = true;
    this.generation++;
    this.cancelPoll();
    if (this.waitingTimer !== undefined) this.io.cancel(this.waitingTimer);
  }
  setText = (text: string) => this.patch({ text });
  newSearch = () => {
    if (this.state.sending) return;
    this.generation++;
    this.cancelPoll();
    if (this.waitingTimer !== undefined) this.io.cancel(this.waitingTimer);
    this.activeId = null;
    this.submission = null;
    this.io.saved.clear();
    this.patch({ ...initialState, available: this.state.available });
  };

  send = async (message: string, clearDraft = true, propertyId?: number) => {
    const text = message.trim();
    if (!text || this.state.sending || this.closed) return;
    const generation = this.generation;
    this.cancelPoll();
    this.refreshRevision++;
    const pending = this.submission?.text === text && this.submission.propertyId === propertyId
      ? this.submission : { text, id: this.io.id(), clearDraft, propertyId };
    this.submission = pending;
    this.patch({ sending: true, error: "", canRetry: true });
    try {
      let id = this.activeId;
      if (!id) {
        const created = await this.io.request<Conversation>("/conversations", { method: "POST" });
        if (!this.current(generation)) return;
        id = created.id;
        this.activeId = id;
        this.io.saved.set(id);
        this.patch({ canRefresh: true });
      }
      const current = await this.io.request<Conversation>(`/conversations/${id}/messages`, {
        method: "POST",
        body: JSON.stringify({ text, client_message_id: pending.id, property_id: pending.propertyId }),
      });
      if (!this.current(generation, id)) return;
      this.submission = null;
      this.patch({ canRetry: false, ...(pending.clearDraft && this.state.text.trim() === text ? { text: "" } : {}) });
      this.accept(current);
      this.cancelPoll();
      void this.refresh();
    } catch (e) {
      if (this.current(generation)) this.patch({ error: e instanceof Error ? e.message : "No pudimos confirmar la recepción. Intenta nuevamente." });
    } finally {
      if (this.current(generation)) this.patch({ sending: false });
    }
  };
  retry = () => {
    const pending = this.submission;
    if (pending) void this.send(pending.text, pending.clearDraft, pending.propertyId);
  };
  update = (value: Conversation) => {
    if (this.closed || value.id !== this.activeId) return;
    this.refreshRevision++;
    this.accept(value);
    this.cancelPoll();
    if (value.processing || value.visits_processing) void this.refresh();
  };
  refresh = async () => {
    const id = this.activeId;
    if (!id || this.closed) return;
    this.cancelPoll();
    const generation = this.generation;
    const revision = ++this.refreshRevision;
    try {
      const current = await this.io.request<Conversation>(`/conversations/${id}`);
      if (!this.current(generation, id) || revision !== this.refreshRevision) return;
      this.accept(current);
      if (current.processing || current.visits_processing)
        this.timer = this.io.schedule(() => void this.refresh(), 1200);
    } catch {
      if (this.current(generation, id) && revision === this.refreshRevision)
        this.patch({ error: "No pudimos actualizar la conversación. Puedes volver a consultarla." });
    }
  };
  refreshAfterError = () => {
    this.patch({ error: "" });
    void this.refresh();
  };
}
