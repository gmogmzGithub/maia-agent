import type { Advisor, ManagedProperty } from "../../shared/lib/api";
import type { BrokerConnection, BrokerListing, SyncRun } from "./easybroker";

type Accounts = {
  items: BrokerConnection[];
  admin: boolean;
  public_enabled: boolean;
};
type Listings = {
  items: BrokerListing[];
  count: number;
  next_offset: number | null;
};
type ReviewIO = {
  request<T>(path: string, init?: RequestInit): Promise<T>;
  requestId(): string;
  changed(): void;
};
const root = "/crm/easybroker";

function mergeRevisions<T extends { id: string; revision: number }>(
  incoming: T[],
  known: T[],
) {
  return incoming.map((row) => {
    const current = known.find((item) => item.id === row.id);
    return current && current.revision > row.revision ? current : row;
  });
}

/** Own selection, ordered reads and confirmation independently of React rendering. */
export class EasyBrokerReviewSession {
  private state = {
    accounts: { items: [], admin: false, public_enabled: false } as Accounts,
    listings: { items: [], count: 0, next_offset: null } as Listings,
    advisors: [] as Advisor[],
    offers: [] as ManagedProperty[],
    selected: null as BrokerListing | null,
    offset: 0,
    busy: false,
    error: null as unknown,
    notice: "",
  };
  private listeners = new Set<() => void>();
  private active = true;
  private epoch = 0;
  private reads = 0;
  private referenceReads = 0;
  private selection = 0;
  constructor(private readonly io: ReviewIO) {}
  snapshot = () => this.state;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  private patch(patch: Partial<typeof this.state>) {
    if (!this.active) return;
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((listener) => listener());
  }
  private current(epoch: number) {
    return this.active && epoch === this.epoch;
  }
  resume() {
    this.active = true;
  }
  stop() {
    this.active = false;
    this.epoch++;
    this.reads++;
    this.referenceReads++;
    this.selection++;
  }

  private async overview() {
    const epoch = this.epoch,
      read = ++this.reads,
      offset = this.state.offset;
    const [accounts, listings] = await Promise.all([
      this.io.request<Accounts>(`${root}/connections`),
      this.io.request<Listings>(`${root}/imports?offset=${offset}`),
    ]);
    if (!this.current(epoch) || read !== this.reads) return;
    this.patch({
      accounts: {
        ...accounts,
        items: mergeRevisions(accounts.items, this.state.accounts.items),
      },
      listings: {
        ...listings,
        items: mergeRevisions(listings.items, this.state.listings.items),
      },
    });
  }
  private async references() {
    const epoch = this.epoch,
      read = ++this.referenceReads;
    const [advisors, offers] = await Promise.all([
      this.io.request<Advisor[]>("/crm/advisors"),
      this.io.request<ManagedProperty[]>("/crm/properties"),
    ]);
    if (this.current(epoch) && read === this.referenceReads)
      this.patch({ advisors, offers });
  }
  load = async () => {
    const epoch = this.epoch,
      read = this.reads + 1;
    try {
      await Promise.all([this.overview(), this.references()]);
    } catch (error) {
      if (this.current(epoch) && read === this.reads && !this.state.busy)
        this.patch({ error });
    }
  };
  refresh = async () => {
    if (this.state.busy || !this.active) return;
    const epoch = this.epoch,
      read = this.reads + 1;
    this.patch({ error: null });
    try {
      await this.overview();
    } catch (error) {
      if (this.current(epoch) && read === this.reads) this.patch({ error });
    }
  };
  page = (offset: number) => {
    if (this.state.busy || !this.active) return;
    this.selection++;
    this.patch({ offset, selected: null, error: null, notice: "" });
    return this.refresh();
  };
  select = async (id: string | null) => {
    const selection = ++this.selection,
      epoch = this.epoch;
    this.patch({ selected: null, error: null });
    if (!id) return;
    try {
      const selected = await this.io.request<BrokerListing>(
        `${root}/imports/${id}`,
      );
      if (!this.current(epoch) || selection !== this.selection) return;
      const known = this.state.listings.items.find((row) => row.id === id);
      if (known && known.revision > selected.revision) {
        this.patch({
          error: new Error(
            "La ficha cambió. Vuelve a abrirla para revisar su versión vigente.",
          ),
        });
        return;
      }
      this.patch({ selected });
    } catch (error) {
      if (this.current(epoch) && selection === this.selection)
        this.patch({ error });
    }
  };

  private applySaved(
    path: string,
    saved: BrokerConnection | BrokerListing | SyncRun,
  ) {
    if (path.startsWith("/imports/")) {
      const row = saved as BrokerListing;
      this.patch({
        listings: {
          ...this.state.listings,
          items: mergeRevisions(
            this.state.listings.items.map((item) =>
              item.id === row.id ? row : item,
            ),
            this.state.listings.items,
          ),
        },
      });
    } else if (path.endsWith("/sync")) {
      const id = path.split("/")[2];
      this.patch({
        accounts: {
          ...this.state.accounts,
          items: this.state.accounts.items.map((row) =>
            row.id === id ? { ...row, last_run: saved as SyncRun } : row,
          ),
        },
      });
    } else {
      const row = saved as BrokerConnection;
      const rows = this.state.accounts.items.some((item) => item.id === row.id)
        ? this.state.accounts.items.map((item) =>
            item.id === row.id ? row : item,
          )
        : [...this.state.accounts.items, row];
      this.patch({
        accounts: {
          ...this.state.accounts,
          items: mergeRevisions(rows, this.state.accounts.items),
        },
      });
    }
  }
  mutate = async (path: string, value: Record<string, unknown>) => {
    if (this.state.busy || !this.active) return false;
    const epoch = this.epoch,
      selection = this.selection;
    this.reads++; // A pre-write poll cannot overwrite the confirmed result.
    this.patch({ busy: true, error: null, notice: "" });
    let saved: BrokerConnection | BrokerListing | SyncRun;
    try {
      saved = await this.io.request(`${root}${path}`, {
        method: "POST",
        body: JSON.stringify({ ...value, request_id: this.io.requestId() }),
      });
    } catch (error) {
      if (this.current(epoch)) this.patch({ error, busy: false });
      return false;
    }
    if (!this.current(epoch)) return true;
    this.reads++;
    this.applySaved(path, saved);
    if (selection === this.selection) {
      this.selection++;
      this.patch({ selected: null });
    }
    this.patch({ notice: "Cambio guardado." });
    try {
      this.io.changed();
      await Promise.all([this.overview(), this.references()]);
    } catch {
      if (this.current(epoch))
        this.patch({
          notice:
            "Cambio guardado. La lista no pudo actualizarse. Pulsa Actualizar lista.",
        });
    } finally {
      if (this.current(epoch)) this.patch({ busy: false });
    }
    return true;
  };
}
