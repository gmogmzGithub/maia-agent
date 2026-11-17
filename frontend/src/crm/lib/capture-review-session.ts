import type { Capture } from "../../shared/lib/capture";

type ReviewIO = {
  request<T>(path: string, init?: RequestInit): Promise<T>;
  now(): string;
};
const initial = {
  rows: [] as Capture[],
  selected: null as Capture | null,
  loaded: false,
  busy: false,
  error: null as unknown,
  notice: "",
  lastCheck: null as { id: string; at: string } | null,
};

/** A confirmed write remains confirmed even if its following list read fails. */
export class CaptureReviewSession {
  private state = { ...initial };
  private listeners = new Set<() => void>();
  private selection = 0;
  private reads = 0;
  private active = true;
  constructor(private readonly io: ReviewIO) {}
  snapshot = () => this.state;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  private patch(patch: Partial<typeof initial>) {
    if (!this.active) return;
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((listener) => listener());
  }
  resume() {
    this.active = true;
  }
  stop() {
    this.active = false;
    this.selection++;
    this.reads++;
  }
  clearFeedback = () => this.patch({ error: null, notice: "" });
  fail = (error: unknown) => this.patch({ error });
  select = (capture: Capture | null) => {
    this.selection++;
    this.patch({ selected: capture, error: null, notice: "", lastCheck: null });
  };
  private current(selection: number, id: string) {
    return (
      this.active &&
      selection === this.selection &&
      this.state.selected?.id === id
    );
  }
  private merge(capture: Capture) {
    const rows = this.state.rows.some((row) => row.id === capture.id)
      ? this.state.rows.map((row) =>
          row.id === capture.id && row.revision <= capture.revision
            ? capture
            : row,
        )
      : [capture, ...this.state.rows];
    this.patch({ rows });
  }
  load = async () => {
    const read = ++this.reads;
    const result = await this.io.request<{ captures: Capture[] }>(
      "/crm/captures",
    );
    if (!this.active || read !== this.reads) return;
    const rows = result.captures.map((row) => {
      const known = this.state.rows.find((previous) => previous.id === row.id);
      return known && known.revision > row.revision ? known : row;
    });
    this.patch({ rows, loaded: true });
  };
  refresh = async () => {
    if (this.state.busy) return;
    const selected = this.state.selected;
    const selection = this.selection;
    this.patch({ busy: true, error: null });
    try {
      await this.load();
      if (selected) {
        const row = await this.io.request<Capture>(
          `/crm/captures/${selected.id}`,
        );
        if (!this.current(selection, selected.id)) return;
        this.merge(row);
        this.patch({
          selected: row,
          lastCheck: { id: row.id, at: this.io.now() },
          notice:
            row.status === "approved"
              ? "Estado actualizado. El propietario todavía no ha aceptado la exclusividad."
              : "Estado actualizado.",
        });
      }
    } catch (error) {
      if (selection === this.selection) this.patch({ error });
    } finally {
      this.patch({ busy: false });
    }
  };
  act = async (action: string, extra: Record<string, unknown> = {}) => {
    const selected = this.state.selected;
    if (!selected || this.state.busy) return null;
    const selection = this.selection;
    this.patch({ busy: true, error: null, notice: "" });
    let saved: Capture;
    try {
      saved = await this.io.request<Capture>(`/crm/captures/${selected.id}`, {
        method: "POST",
        body: JSON.stringify({ action, revision: selected.revision, ...extra }),
      });
    } catch (error) {
      if (this.current(selection, selected.id)) this.patch({ error });
      this.patch({ busy: false });
      return null;
    }
    if (!this.active) return null;
    this.merge(saved);
    const notice =
      action === "approve"
        ? "Revisión aprobada. Falta que el propietario acepte la exclusividad desde su cuenta."
        : "Cambios guardados.";
    if (this.current(selection, selected.id))
      this.patch({ selected: saved, notice });
    try {
      await this.load();
    } catch {
      if (this.current(selection, selected.id))
        this.patch({
          notice: `${notice} La lista no pudo actualizarse. Pulsa Actualizar.`,
        });
    } finally {
      this.patch({ busy: false });
    }
    return this.current(selection, selected.id) ? saved : null;
  };
}
