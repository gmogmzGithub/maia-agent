export type SyncRun = {
  id: string;
  status: string;
  counters: { seen?: number; checked?: number; failed?: number };
  error_code: string;
};

export type BrokerConnection = {
  id: string;
  name: string;
  environment: "sandbox" | "production";
  advisor_id: number;
  enabled: boolean;
  revision: number;
  error_code: string;
  last_success_at: string | null;
  last_run: SyncRun | null;
};

export type BrokerListing = {
  id: string;
  public_id: string;
  connection_id: string;
  connection_name: string;
  status: string;
  revision: number;
  checked_at: string | null;
  facts: Record<string, unknown>;
  issues: string[];
  geography: { state?: string; municipality?: string; neighborhood?: string };
  links: { id: number; operation: string; offer_id: number; role: string }[];
  history?: { revision: number; facts: Record<string, unknown>; at: string }[];
};

export const brokerStatus: Record<string, string> = {
  published: "Disponible en origen",
  not_published: "Sin publicar en origen",
  sold: "Vendido en origen",
  rented: "Rentado en origen",
  reserved: "Reservado",
  suspended: "Suspendido",
  flagged: "Señalado por el proveedor",
  disapproved: "Rechazado por el proveedor",
  unknown: "Estado por comprobar",
  queued: "En cola",
  running: "Actualizando",
  complete: "Actualización completa",
  partial: "Actualización parcial",
  failed: "Actualización fallida",
  superseded: "Sustituida por cambio de conexión",
};
