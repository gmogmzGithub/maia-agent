import { api, session } from "./api";

export type Catalog = {
  upload_limits?: { min_photos: number; max_photos: number; max_plans: number };
  kinds: Record<string, { label: string; subtypes: string[] }>;
  states: string[];
  conditions: string[];
  amenities: Record<string, string[]>;
  contract_text: string;
  contract_version: string;
};
export type CaptureValue = string | number | boolean | null | string[];
export type CaptureData = Record<string, CaptureValue>;
export type LocationPoint = {
  id: string;
  latitude: number | null;
  longitude: number | null;
  source: string;
  expires_at: string;
  needs_confirmation: boolean;
};
export type Asset = {
  request_id: string;
  id: string;
  kind: "photo" | "plan";
  url: string;
  content_type: string;
  size: number;
};
export type Capture = {
  id: string;
  data: CaptureData;
  location?: LocationPoint | null;
  revision: number;
  status: string;
  property_id: number | null;
  advisor_id: number | null;
  advisor: { name: string; whatsapp: string } | null;
  assets: Asset[];
  updated_at: string;
  agreement: {
    text: string;
    version: string;
    accepted_at: string;
    expires_at: string;
  } | null;
  pending_request: { kind?: string; message?: string };
  valuation: string;
  valuation_notes: string;
  owner?: { email: string; phone: string; verified: boolean };
  review_notes?: string;
  exact_location_approved?: boolean;
  outside_area_approved?: boolean;
  mail_configuration?: {
    provider: string;
    ready: boolean;
    local: boolean;
    issues: string[];
    webhook_ready: boolean;
  };
  events?: { action: string; summary: string; created_at: string }[];
  deliveries?: {
    id: number;
    channel: string;
    status: string;
    error_code: string;
    provider?: string;
    provider_id?: string;
    can_retry?: boolean;
    attempts?: number;
  }[];
};
export type Owner = { email: string; phone: string; verified: boolean };
export const statusLabels: Record<string, string> = {
  draft: "Borrador",
  submitted: "En revisión",
  approved: "Pendiente de aceptar exclusividad",
  accepted: "Lista para publicar",
  published: "Publicada",
  rejected: "Descartada",
  withdrawn: "Retirada",
  expired: "Exclusividad vencida",
  closed: "Comercialización terminada por cierre",
};
export const initialData: CaptureData = {
  name: "",
  relationship: "owner",
  operation: "sale",
  is_presale: false,
  kind: "house",
  subtype: "",
  state: "Jalisco",
  municipality: "",
  neighborhood: "",
  private_address: "",
  currency: "MXN",
  price: null,
  title: "",
  description: "",
  amenities: [],
  videos: [],
  tours: [],
  phone_confirmed: false,
};

export async function uploadAsset(
  captureId: string,
  kind: string,
  file: File,
  requestId: string,
  onUploading?: () => void,
): Promise<Capture> {
  const userSession = await session();
  const form = new FormData();
  form.set("file", await optimizeImage(file));
  form.set("kind", kind);
  form.set("request_id", requestId);
  onUploading?.();
  const response = await fetch(`/api/capture/requests/${captureId}/upload`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRFToken": userSession.csrf_token },
    body: form,
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(data.detail || "No pudimos subir este archivo.");
  return data;
}

async function optimizeImage(file: File): Promise<File> {
  if (!file.type.startsWith("image/")) return file;
  try {
    const bitmap = await createImageBitmap(file);
    const ratio = Math.min(1, 2400 / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(bitmap.width * ratio));
    canvas.height = Math.max(1, Math.round(bitmap.height * ratio));
    const context = canvas.getContext("2d");
    if (!context) {
      bitmap.close();
      return file;
    }
    context.fillStyle = "white";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/webp", 0.85),
    );
    return blob
      ? new File([blob], "imagen.webp", { type: "image/webp" })
      : file;
  } catch {
    return file;
  } // HEIC and other formats still normalize on the server.
}

export function captureAction(
  capture: Capture,
  action: string,
  extra: Record<string, unknown> = {},
): Promise<Capture> {
  return api(`/capture/requests/${capture.id}`, {
    method: "POST",
    body: JSON.stringify({ action, revision: capture.revision, ...extra }),
  });
}
