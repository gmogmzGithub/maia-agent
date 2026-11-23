import { responseError } from "./api-errors";
export { ApiError, type ApiIssue } from "./api-errors";
import type { components } from "./api-schema";

export type Property = components["schemas"]["PublicProperty"];
export type ManagedProperty = components["schemas"]["ManagedProperty"];
export type PropertyInput = components["schemas"]["PropertyInput"];
export type Criteria = components["schemas"]["SearchCriteria"];
export type SearchResult = components["schemas"]["SearchResult"];
export type Conversation = components["schemas"]["ConversationOutput"];
export type Advisor = components["schemas"]["AdvisorOutput"];
export type Prospect = components["schemas"]["ProspectOutput"];
export type ProspectDetail = components["schemas"]["ProspectDetail"];
export type CRMConversation = components["schemas"]["CRMConversation"];
export type Notification = components["schemas"]["NotificationOutput"];
export type Session = {
  csrf_token: string;
  staff: boolean;
  email: string | null;
  ai_configured: boolean;
};

let csrfToken = "";

export async function session(): Promise<Session> {
  const response = await fetch("/api/session", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok) throw new Error("No pudimos conectar. Intenta nuevamente.");
  const data: Session = await response.json();
  csrfToken = data.csrf_token;
  return data;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const write = init.method && init.method !== "GET";
  if (write && !csrfToken) await session();
  const response = await fetch(`/api${path}`, {
    ...init,
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(write ? { "X-CSRFToken": csrfToken } : {}),
      ...init.headers,
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw responseError(data, response.status);
  }
  if (data.csrf_token) csrfToken = data.csrf_token;
  return data as T;
}

export function money(value: string | number | null, currency: string | null = "MXN") {
  if (value === null) return "Precio por consultar";
  if (!currency) return "Importe sin moneda confirmada";
  return new Intl.NumberFormat("es-MX", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(Number(value));
}

export const labels: Record<string, string> = {
  house: "Casa",
  apartment: "Departamento",
  land: "Terreno / Lote",
  warehouse: "Bodega comercial",
  condominium: "Casa en condominio",
  mixed_house: "Casa con uso de suelo",
  duplex: "Dúplex",
  building: "Edificio",
  orchard: "Huerta",
  urban_income: "Inmueble productivo urbano",
  retail: "Local Comercial",
  mall_retail: "Local en centro comercial",
  industrial: "Nave industrial",
  office: "Oficina",
  country_house: "Quinta",
  ranch: "Rancho",
  commercial_land: "Terreno comercial",
  industrial_land: "Terreno industrial",
  villa: "Villa",
  rent: "Renta",
  sale: "Venta",
  bedrooms: "recámaras",
  bathrooms: "baños",
  parking: "estacionamientos",
  furnished: "amueblado",
  accepts_pets: "mascotas",
  near_schools: "escuelas cercanas",
};
