import type {
  Capture,
  CaptureData,
  Catalog,
  Owner,
} from "../../shared/lib/capture";
import { restoreOwnerDraft } from "./owner-draft";

type Context = {
  owner: Owner | null;
  capture: Capture | null;
  data: CaptureData;
  draftId: string;
};
type Feedback = { busy?: boolean; error?: unknown; notice?: string };
type JourneyIO = {
  request<T>(path: string, init?: RequestInit): Promise<T>;
  session(): Promise<unknown>;
  changed(capture: Capture): void;
  rows(captures: Capture[]): void;
  feedback(value: Feedback): void;
  needsAccount(): void;
  blocked(): boolean;
};

/** Owns authorization continuations, revisioned persistence and stale-response guards. */
export class OwnerCaptureJourney {
  private context: Context = {
    owner: null,
    capture: null,
    data: {},
    draftId: "",
  };
  private generation = 0;
  private lifetime = 0;
  private accountVersion = 0;
  private openVersion = 0;
  private opened = "";
  private active = true;
  private locked = false;
  private pending: {
    draftId: string;
    ownerEmail: string | null;
    task: () => Promise<void>;
  } | null = null;
  constructor(private readonly io: JourneyIO) {}
  resume() {
    this.active = true;
  }
  stop() {
    this.active = false;
    this.lifetime++;
    this.generation++;
    this.openVersion++;
    this.pending = null;
  }
  update(context: Context) {
    const previous = this.context;
    if (previous.owner?.email !== context.owner?.email) this.accountVersion++;
    if (
      previous.draftId !== context.draftId ||
      previous.owner?.email !== context.owner?.email
    ) {
      this.generation++;
      this.openVersion++;
      this.opened = "";
      // An anonymous draft may adopt its first account, but never another owner's pending work.
      if (
        this.pending &&
        (this.pending.draftId !== context.draftId ||
          (this.pending.ownerEmail &&
            this.pending.ownerEmail !== context.owner?.email))
      )
        this.pending = null;
      if (this.pending && !this.pending.ownerEmail && context.owner)
        this.pending.ownerEmail = context.owner.email;
    }
    this.context = context;
  }
  private current(generation: number) {
    return this.active && generation === this.generation;
  }
  async bootstrap(saved: string | null) {
    const lifetime = this.lifetime;
    await this.io.session();
    const [catalog, result] = await Promise.all([
      this.io.request<Catalog>("/capture/catalog"),
      this.io.request<{ account: Owner | null }>("/capture/account"),
    ]);
    const draft = await restoreOwnerDraft(saved, result.account, (id) =>
      this.io.request<Capture>(`/capture/requests/${encodeURIComponent(id)}`),
    );
    return this.active && lifetime === this.lifetime
      ? { catalog, owner: result.account, draft }
      : null;
  }
  async verify(token: string) {
    const owner = this.context.owner;
    if (!owner) return null;
    const generation = this.generation;
    const result = await this.io.request<{ account: Owner }>(
      "/capture/account",
      { method: "POST", body: JSON.stringify({ action: "verify", token }) },
    );
    return this.current(generation) && result.account.email === owner.email
      ? result.account
      : null;
  }
  run = async (task: () => Promise<void>) => {
    if (!this.active || this.locked || this.io.blocked()) return;
    const generation = this.generation;
    this.locked = true;
    this.io.feedback({ busy: true, error: "", notice: "" });
    try {
      await task();
    } catch (error) {
      if (this.current(generation))
        this.io.feedback({
          error:
            error instanceof Error
              ? error
              : new Error("No pudimos completar la acción."),
        });
    } finally {
      this.locked = false;
      if (this.active) this.io.feedback({ busy: false });
    }
  };
  requireAccount = (task: () => Promise<void>) => {
    const { owner, draftId } = this.context;
    if (!owner) {
      this.pending = { task, draftId, ownerEmail: null };
      this.io.needsAccount();
    } else if (owner.verified) void this.run(task);
  };
  cancelPending() {
    this.pending = null;
  }
  resumePending = async () => {
    const pending = this.pending;
    if (
      !this.context.owner?.verified ||
      !pending ||
      pending.draftId !== this.context.draftId ||
      pending.ownerEmail !== this.context.owner.email
    )
      return;
    this.pending = null;
    await this.run(pending.task);
  };
  loadRows = async () => {
    if (!this.context.owner?.verified) return;
    const account = this.accountVersion;
    const lifetime = this.lifetime;
    const result = await this.io.request<{ captures: Capture[] }>(
      "/capture/requests",
    );
    if (
      this.active &&
      account === this.accountVersion &&
      lifetime === this.lifetime
    )
      this.io.rows(result.captures);
  };
  persist = async () => {
    const { owner, capture, data, draftId } = this.context;
    if (!owner?.verified)
      throw new Error("Verifica tu email antes de guardar la propiedad.");
    const generation = this.generation;
    const saved = await this.io.request<Capture>("/capture/requests", {
      method: "POST",
      body: JSON.stringify({
        id: capture?.id || draftId,
        data,
        revision: capture?.revision ?? 0,
      }),
    });
    if (!this.current(generation))
      throw new Error(
        "La cuenta o la solicitud cambió. Vuelve a abrir tu propiedad.",
      );
    this.context = { ...this.context, capture: saved };
    this.io.changed(saved);
    return saved;
  };
  cancelOpen() {
    this.openVersion++;
    this.opened = "";
  }
  async openRequested(id: string) {
    const owner = this.context.owner;
    if (!owner?.verified) return null;
    const key = `${owner.email}:${id}`;
    if (key === this.opened) return null;
    this.opened = key;
    const generation = this.generation;
    const open = ++this.openVersion;
    const row = await this.io.request<Capture>(
      `/capture/requests/${encodeURIComponent(id)}`,
    );
    return this.current(generation) && this.openVersion === open ? row : null;
  }
}
