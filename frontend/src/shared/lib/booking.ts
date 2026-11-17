export type Visit = {
  id: string;
  property_id: number;
  property_title: string;
  advisor: string;
  start: string;
  end: string;
  status: string;
  operation_status: string;
  operation_error: string;
  prospect_id?: number;
  conversation_id?: string;
  observed?: {
    status?: string;
    summary?: string;
    location?: string;
    start?: { dateTime?: string; date?: string };
    end?: { dateTime?: string; date?: string };
  };
};
export type VisitProposal = {
  id: string;
  action: string;
  property_title: string;
  advisor: string;
  start: string;
  end: string;
};
export type VisitWindow = { day: number; start: string; end: string };
export type VisitRules = { duration: number; windows: VisitWindow[] };
export const visitLabels: Record<string, string> = {
  pending: "Pendiente de confirmar",
  confirmed: "Confirmada",
  cancelled: "Cancelada",
  done: "Realizada",
  no_show: "No asistió",
  review: "Requiere revisión",
  failed: "Sin confirmar",
  queued: "En espera",
  running: "Procesando",
  verifying: "Verificando con Google",
  completed: "Completada",
  resolved: "Resuelta",
  create: "Agendar visita",
  move: "Reprogramar visita",
  cancel: "Cancelar visita",
  accept: "Aceptar el cambio de Google",
  restore: "Restablecer desde el CRM",
};
export function visitTime(value: string) {
  return new Intl.DateTimeFormat("es-MX", {
    timeZone: "America/Mexico_City",
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
