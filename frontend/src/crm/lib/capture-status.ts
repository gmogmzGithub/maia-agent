import type { Capture } from "@/shared/lib/capture";

export const captureTabs = [
  { id: "review", label: "Por revisar" },
  { id: "process", label: "En proceso" },
  { id: "published", label: "Publicadas" },
  { id: "all", label: "Todas" },
] as const;
export type CaptureTab = (typeof captureTabs)[number]["id"];

const states: Record<
  string,
  { label: string; next: string; tone: string; icon: string }
> = {
  submitted: {
    label: "En revisión",
    next: "Revisar solicitud",
    tone: "review",
    icon: "◷",
  },
  approved: {
    label: "Espera aceptación",
    next: "El propietario debe aceptar la exclusividad",
    tone: "waiting",
    icon: "◷",
  },
  accepted: {
    label: "Lista para publicar",
    next: "Publicar inmueble",
    tone: "ready",
    icon: "✓",
  },
  published: {
    label: "Publicada",
    next: "Visible en el catálogo",
    tone: "published",
    icon: "↗",
  },
  rejected: {
    label: "Descartada",
    next: "Solicitud descartada",
    tone: "closed",
    icon: "×",
  },
  withdrawn: {
    label: "Retirada",
    next: "Fuera del catálogo",
    tone: "closed",
    icon: "−",
  },
  expired: {
    label: "Exclusividad vencida",
    next: "Renovar exige otra aceptación",
    tone: "closed",
    icon: "◷",
  },
  draft: {
    label: "Borrador",
    next: "El propietario debe completar su solicitud",
    tone: "closed",
    icon: "✎",
  },
};
export function captureState(status: string) {
  return (
    states[status] || {
      label: "Estado no reconocido",
      next: "Actualizar la solicitud",
      tone: "closed",
      icon: "?",
    }
  );
}
export function captureTabForStatus(status: string): CaptureTab {
  if (status === "submitted") return "review";
  if (status === "approved" || status === "accepted") return "process";
  if (status === "published") return "published";
  return "all";
}
export function capturesInTab(rows: Capture[], tab: CaptureTab) {
  return tab === "all"
    ? rows
    : rows.filter((row) => captureTabForStatus(row.status) === tab);
}
export function captureTitle(capture: Capture) {
  return String(
    capture.data.title || capture.data.neighborhood || "Solicitud sin título",
  );
}
