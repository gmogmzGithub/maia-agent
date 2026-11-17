import type { CaptureData, LocationPoint } from "./capture";

export type LocationSuggestion = { id: string; label: string };
export type LocationEditingView = {
  term: string;
  items: LocationSuggestion[];
  enabled: boolean;
  busy: boolean;
  note: string;
  failure: string;
};
type Context = {
  data: CaptureData;
  location: LocationPoint | null;
  states: string[];
  signedIn: boolean;
  captureId?: string;
};
type Dependencies = {
  request: <T>(path: string, init?: RequestInit) => Promise<T>;
  onData: (data: CaptureData) => void;
  onLocation: (location: LocationPoint | null) => void;
  onPending?: (pending: boolean) => void;
  delay?: number;
};

export function isRuralLocation(data: CaptureData) {
  return [
    "land",
    "commercial_land",
    "industrial_land",
    "ranch",
    "orchard",
  ].includes(String(data.kind));
}

/** One edit owns its search session, private point and latest in-flight operation. */
export class LocationEditing {
  private context: Context;
  private dependencies: Dependencies;
  private listeners = new Set<(view: LocationEditingView) => void>();
  private view: LocationEditingView;
  private focused = false;
  private selected = "";
  private session: string | undefined;
  private generation = 0;
  private lifetime = 0;
  private active = true;
  private operation: "suggest" | "resolve" | "point" | null = null;
  private abort: AbortController | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private restoring: { ref: string; abort: AbortController } | undefined;
  private restoredRef = "";

  constructor(context: Context, dependencies: Dependencies) {
    this.context = context;
    this.dependencies = dependencies;
    this.view = {
      term: String(context.data.private_address || ""),
      items: [],
      enabled: false,
      busy: false,
      note: "",
      failure: "",
    };
  }

  get snapshot() {
    return this.view;
  }

  subscribe(listener: (view: LocationEditingView) => void) {
    this.listeners.add(listener);
    listener(this.view);
    return () => {
      this.listeners.delete(listener);
    };
  }

  start() {
    this.active = true;
    const lifetime = ++this.lifetime;
    this.restoredRef = "";
    void this.dependencies
      .request<{ enabled: boolean }>("/location/config")
      .then((config) => {
        if (!this.active || lifetime !== this.lifetime) return;
        this.patch({ enabled: config.enabled });
        this.scheduleSearch();
      })
      .catch(() => {
        if (this.active && lifetime === this.lifetime)
          this.patch({ enabled: false });
      });
    this.restorePoint();
    this.normalizeMode();
  }

  update(context: Context) {
    if (!this.active) return;
    const changedAccount =
      context.signedIn !== this.context.signedIn ||
      context.captureId !== this.context.captureId;
    const changedAddress =
      context.data.private_address !== this.context.data.private_address;
    this.context = context;
    if (changedAccount) {
      this.cancel();
      this.session = undefined;
      this.restoring?.abort.abort();
      this.restoring = undefined;
      this.restoredRef = "";
    }
    if (changedAddress)
      this.patch({ term: String(context.data.private_address || "") });
    this.normalizeMode();
    this.restorePoint();
  }

  focus(focused: boolean) {
    this.focused = focused;
    if (this.operation === "resolve" || this.operation === "point") return;
    this.scheduleSearch();
  }

  search(term: string) {
    this.selected = "";
    this.patch({ term });
    this.edit({ private_address: this.byReference ? "" : term });
    this.scheduleSearch();
  }

  edit(values: CaptureData) {
    if (!this.active) return;
    const clearPoint = "private_address" in values || "state" in values;
    const invalidates =
      clearPoint || "municipality" in values || "neighborhood" in values;
    if (invalidates) {
      this.cancel();
      this.restoring?.abort.abort();
      this.restoring = undefined;
      if (clearPoint) this.setLocation(null);
    }
    this.setData({
      ...this.context.data,
      ...values,
      ...(clearPoint
        ? { location_ref: null, latitude: null, longitude: null }
        : {}),
      ...(invalidates ? { location_confirmed: false } : {}),
    });
  }

  referenceMode(reference: boolean) {
    this.cancel();
    const address = reference ? "" : this.context.data.private_address;
    if (address !== this.context.data.private_address)
      this.patch({ term: String(address || "") });
    this.setData({
      ...this.context.data,
      location_mode: reference ? "reference" : "address",
      private_address: address,
      location_confirmed: false,
    });
  }

  async choose(item: LocationSuggestion) {
    if (!this.active || !this.context.signedIn) return;
    const session = this.session;
    const token = this.begin("resolve");
    try {
      const result = await this.request<{
        fields: Record<string, string>;
        location: LocationPoint;
      }>("resolve", {
        place_id: item.id,
        session,
      });
      if (!this.current(token)) return;
      const fields = { ...result.fields };
      const byReference = this.byReference;
      if (byReference) delete fields.neighborhood;
      if (fields.state && !this.context.states.includes(fields.state))
        delete fields.state;
      this.selected = fields.private_address || this.view.term;
      this.focused = false;
      this.setLocation(result.location);
      this.setData({
        ...this.context.data,
        state: "",
        municipality: "",
        neighborhood: "",
        ...fields,
        private_address: byReference ? "" : this.selected,
        location_ref: result.location.id,
        latitude: null,
        longitude: null,
        location_confirmed: false,
      });
      this.patch({
        term: this.selected,
        note: fields.municipality
          ? "Revisa colonia y punto. Puedes corregir los datos antes de continuar."
          : "",
      });
    } catch (error) {
      if (this.current(token))
        this.patch({
          failure: this.message(
            error,
            "Selecciona de nuevo o completa la dirección manualmente.",
          ),
        });
    } finally {
      if (this.current(token)) {
        this.session = undefined;
        this.finish();
      }
    }
  }

  async selectPoint(latitude: number, longitude: number) {
    if (!this.active || !this.context.signedIn) return;
    const token = this.begin("point");
    try {
      const result = await this.request<{ location: LocationPoint }>("point", {
        latitude,
        longitude,
      });
      if (!this.current(token)) return;
      this.setLocation(result.location);
      this.setData({
        ...this.context.data,
        location_ref: result.location.id,
        latitude: null,
        longitude: null,
        location_confirmed: false,
      });
      this.patch({ note: "Punto ajustado. Confirma los datos al continuar." });
    } catch (error) {
      if (this.current(token))
        this.patch({
          failure: this.message(error, "No pudimos guardar el punto."),
        });
    } finally {
      if (this.current(token)) this.finish();
    }
  }

  dispose() {
    this.active = false;
    ++this.lifetime;
    this.cancel();
    this.restoring?.abort.abort();
    this.restoring = undefined;
    this.listeners.clear();
  }

  private get byReference() {
    return (
      isRuralLocation(this.context.data) &&
      this.context.data.location_mode === "reference"
    );
  }

  private normalizeMode() {
    if (
      !isRuralLocation(this.context.data) &&
      this.context.data.location_mode === "reference"
    ) {
      this.setData({
        ...this.context.data,
        location_mode: "address",
        location_reference: "",
      });
    }
  }

  private setData(data: CaptureData) {
    this.context = { ...this.context, data };
    this.dependencies.onData(data);
  }

  private setLocation(location: LocationPoint | null) {
    this.context = { ...this.context, location };
    this.dependencies.onLocation(location);
  }

  private patch(changes: Partial<LocationEditingView>) {
    this.view = { ...this.view, ...changes };
    for (const listener of this.listeners) listener(this.view);
  }

  private cancel() {
    ++this.generation;
    clearTimeout(this.timer);
    this.timer = undefined;
    this.abort?.abort();
    this.abort = undefined;
    this.operation = null;
    const pending = this.view.busy;
    this.patch({ items: [], busy: false });
    if (pending) this.dependencies.onPending?.(false);
  }

  private begin(operation: "suggest" | "resolve" | "point") {
    this.cancel();
    this.operation = operation;
    this.abort = new AbortController();
    this.patch({ busy: true, items: [], failure: "", note: "" });
    this.dependencies.onPending?.(true);
    return this.generation;
  }

  private finish() {
    this.operation = null;
    this.abort = undefined;
    this.patch({ busy: false });
    this.dependencies.onPending?.(false);
  }

  private current(token: number) {
    return this.active && token === this.generation;
  }

  private request<T>(action: string, values: Record<string, unknown>) {
    return this.dependencies.request<T>("/location/search", {
      method: "POST",
      signal: this.abort?.signal,
      body: JSON.stringify({
        action,
        ...values,
        capture_id: this.context.captureId,
      }),
    });
  }

  private scheduleSearch() {
    if (this.operation === "resolve" || this.operation === "point") return;
    this.cancel();
    if (
      !this.active ||
      !this.view.enabled ||
      !this.context.signedIn ||
      !this.focused ||
      this.view.term.trim().length < 3 ||
      this.view.term === this.selected
    )
      return;
    this.timer = setTimeout(() => {
      void this.suggest();
    }, this.dependencies.delay ?? 400);
  }

  private async suggest() {
    if (!this.active) return;
    const token = this.begin("suggest");
    try {
      const result = await this.request<{
        session: string;
        suggestions: LocationSuggestion[];
      }>("suggest", { text: this.view.term, session: this.session });
      if (!this.current(token)) return;
      this.session = result.session;
      this.patch({
        items: result.suggestions,
        note: result.suggestions.length
          ? ""
          : "No encontramos coincidencias. Puedes completar los datos manualmente.",
      });
    } catch (error) {
      if (this.current(token)) {
        this.session = undefined;
        this.patch({
          items: [],
          failure: this.message(error, "No pudimos consultar las direcciones."),
        });
      }
    } finally {
      if (this.current(token)) this.finish();
    }
  }

  private restorePoint() {
    const ref = String(this.context.data.location_ref || "");
    if (
      !ref ||
      this.context.location?.id === ref ||
      this.restoring?.ref === ref ||
      this.restoredRef === ref
    )
      return;
    this.restoredRef = ref;
    this.restoring?.abort.abort();
    const restore = { ref, abort: new AbortController() };
    this.restoring = restore;
    void this.dependencies
      .request<{ location: LocationPoint }>(
        `/location/points/${encodeURIComponent(ref)}`,
        { signal: restore.abort.signal },
      )
      .then((result) => {
        if (
          this.active &&
          this.restoring === restore &&
          this.context.data.location_ref === ref
        )
          this.setLocation(result.location);
      })
      .catch(() => {
        if (
          this.active &&
          this.restoring === restore &&
          this.context.data.location_ref === ref
        )
          this.patch({
            note: "Vuelve a señalar el punto para confirmar esta ubicación.",
          });
      })
      .finally(() => {
        if (this.restoring === restore) this.restoring = undefined;
      });
  }

  private message(error: unknown, fallback: string) {
    return error instanceof Error ? error.message : fallback;
  }
}
