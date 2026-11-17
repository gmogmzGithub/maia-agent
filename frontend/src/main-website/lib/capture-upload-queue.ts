import type { Asset, Capture } from "@/shared/lib/capture";

export type MediaKind = "photo" | "plan";
export type UploadLimits = {
  min_photos: number;
  max_photos: number;
  max_plans: number;
};
export const DEFAULT_UPLOAD_LIMITS: UploadLimits = {
  min_photos: 5,
  max_photos: 20,
  max_plans: 5,
};
export type UploadItem = {
  requestId: string;
  kind: MediaKind;
  name: string;
  file: File | null;
  status: "queued" | "preparing" | "uploading" | "uploaded" | "failed";
  assetId?: string;
  error?: string;
};
export type UploadSnapshot = { items: UploadItem[]; running: boolean };
export type UploadAdapter = {
  prepare(): Promise<Capture>;
  upload(
    captureId: string,
    item: UploadItem,
    uploading: () => void,
  ): Promise<Capture>;
  refresh(captureId: string): Promise<Capture>;
  changed(capture: Capture): void;
};

/** One queue per owner/draft. Files never enter browser storage or commercial data. */
export class CaptureUploadQueue {
  private snapshot: UploadSnapshot = { items: [], running: false };
  private listeners = new Set<() => void>();
  private assets: Asset[] = [];
  private limits: UploadLimits = DEFAULT_UPLOAD_LIMITS;
  private disposed = false;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  getSnapshot = () => this.snapshot;
  private publish(
    items = this.snapshot.items,
    running = this.snapshot.running,
  ) {
    this.snapshot = { items, running };
    this.listeners.forEach((listener) => listener());
  }
  private change(id: string, patch: Partial<UploadItem>) {
    if (!this.disposed)
      this.publish(
        this.snapshot.items.map((item) =>
          item.requestId === id ? { ...item, ...patch } : item,
        ),
      );
  }
  sync(assets: Asset[], limits: UploadLimits) {
    this.assets = assets;
    this.limits = limits;
    const accepted = new Map(assets.map((asset) => [asset.request_id, asset]));
    let changed = false;
    const items = this.snapshot.items.map((item) => {
      const asset = accepted.get(item.requestId);
      if (!asset || item.status === "uploaded") return item;
      changed = true;
      return {
        ...item,
        status: "uploaded" as const,
        assetId: asset.id,
        file: null,
        error: undefined,
      };
    });
    if (changed) this.publish(items);
  }
  enqueue(files: File[], kind: MediaKind) {
    let slots = Math.max(
      0,
      (kind === "photo" ? this.limits.max_photos : this.limits.max_plans) -
        this.assets.filter((asset) => asset.kind === kind).length -
        this.snapshot.items.filter(
          (item) => item.kind === kind && item.status !== "uploaded",
        ).length,
    );
    const added: UploadItem[] = [];
    const rejected: { name: string; reason: string }[] = [];
    for (const file of files) {
      const image =
        file.type.startsWith("image/") ||
        /\.(jpe?g|png|webp|heic|heif|avif|gif|tiff?|bmp)$/i.test(file.name);
      const pdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
      const reason =
        !image && !(kind === "plan" && pdf)
          ? kind === "photo"
            ? "Selecciona una imagen."
            : "Selecciona una imagen o un PDF."
          : file.size >
              (pdf && kind === "plan" ? 20 * 1024 * 1024 : 256 * 1024 * 1024)
            ? "El archivo supera el tamaño admitido."
            : slots === 0
              ? `Se alcanzó el máximo de ${kind === "photo" ? this.limits.max_photos + " fotos" : this.limits.max_plans + " planos"}.`
              : "";
      if (reason) {
        rejected.push({ name: file.name, reason });
        continue;
      }
      slots--;
      added.push({
        requestId: crypto.randomUUID(),
        kind,
        name: file.name,
        file,
        status: "queued",
      });
    }
    if (added.length) this.publish([...this.snapshot.items, ...added]);
    return rejected;
  }
  retry(id: string) {
    const item = this.snapshot.items.find((value) => value.requestId === id);
    if (item?.status === "failed" && item.file)
      this.change(id, { status: "queued", error: undefined });
  }
  remove(id: string) {
    const item = this.snapshot.items.find((value) => value.requestId === id);
    if (item && ["queued", "failed"].includes(item.status))
      this.publish(
        this.snapshot.items.filter((value) => value.requestId !== id),
      );
  }
  discardUnfinished() {
    if (!this.snapshot.running)
      this.publish(
        this.snapshot.items.filter((item) => item.status === "uploaded"),
      );
  }
  async run(adapter: UploadAdapter) {
    if (
      this.disposed ||
      this.snapshot.running ||
      !this.snapshot.items.some((item) => item.status === "queued")
    )
      return;
    this.publish(undefined, true);
    let capture: Capture | undefined;
    const update = (value: Capture) => {
      capture = value;
      if (!this.disposed) {
        this.sync(value.assets, this.limits);
        adapter.changed(value);
      }
    };
    try {
      // Refresh before retrying so a lost response is reconciled without uploading again.
      update(await adapter.prepare());
      while (!this.disposed) {
        const item = this.snapshot.items.find(
          (value) => value.status === "queued",
        );
        if (!item) break;
        this.change(item.requestId, { status: "preparing", error: undefined });
        try {
          update(
            await adapter.upload(capture!.id, item, () =>
              this.change(item.requestId, { status: "uploading" }),
            ),
          );
          this.change(item.requestId, { status: "uploaded", file: null });
        } catch (error) {
          this.change(item.requestId, {
            status: "failed",
            error:
              error instanceof Error
                ? error.message
                : "No pudimos subir este archivo.",
          });
          try {
            update(await adapter.refresh(capture!.id));
          } catch {
            /* Keep the file and its original request ID for retry. */
          }
        }
      }
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "No pudimos preparar la subida.";
      this.publish(
        this.snapshot.items.map((item) =>
          item.status === "queued"
            ? { ...item, status: "failed", error: message }
            : item,
        ),
      );
    } finally {
      if (!this.disposed) this.publish(undefined, false);
    }
  }
  dispose() {
    this.disposed = true;
    this.listeners.clear();
  }
}
