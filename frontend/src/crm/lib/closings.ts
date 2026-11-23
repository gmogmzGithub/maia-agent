export type ClosingData = {
  operation: string;
  price: string | null;
  currency: string;
  year: number | null;
  month: number | null;
  day: number | null;
  kind: string;
  subtype: string;
  state: string;
  municipality: string;
  zone_type: string;
  zone: string;
  address_mode: string;
  street: string;
  address_text: string;
  exterior_number: string;
  interior_number: string;
  interior_applicable: boolean | null;
  rural_identification: string;
  rural_reference: string;
  access_notes: string;
  land_m2: string | null;
  construction_m2: string | null;
  private_m2: string | null;
  characteristics: {
    bedrooms: number | null;
    bathrooms: string | null;
    half_bathrooms: number | null;
    parking: number | null;
    age_type: string;
    age_years: number | null;
    condition: string;
    amenities: string[] | null;
    not_applicable: string[];
  };
  charges_status: string;
  charges: { concept: string; amount: string; currency: string }[];
  notes: string;
  responsible_id: number | null;
  buyer_id: number | null;
  is_test: boolean;
};
export type Closing = {
  id: string;
  physical_property_id: string;
  canonical_physical_property_id: string;
  offer_id: number | null;
  origin: string;
  author_id: number;
  revision: number;
  status: string;
  created_at: string;
  confirmed_at: string | null;
  confirmed_by_id: number | null;
  reversal_date: string | null;
  data: ClosingData;
  missing_required: string[];
  missing_characteristics: string[];
  history?: {
    number: number;
    action: string;
    status: string;
    actor_id: number;
    actor_email: string;
    at: string;
    reason: string;
    data: ClosingData;
    reversal_date: string | null;
  }[];
  offer_periods?: {
    offer_id: number;
    period: number;
    closed_at: string;
    reopened_at: string | null;
    reopened_by_id: number | null;
    reason: string;
  }[];
  identity_links?: {
    source_id: string;
    target_id: string;
    actor_id: number;
    actor_email: string;
    reason: string;
    at: string;
  }[];
};
export type ClosingPreview = Closing & {
  preview_token: string;
  duplicates: string[];
  effects: {
    ends_offer: number | null;
    changes_search: boolean;
    sends_whatsapp: boolean;
  };
};
export type ClosingList = {
  items: Closing[];
  count: number;
  can_confirm: boolean;
  admin: boolean;
  user_id: number;
};
export const closingLabels: Record<string, string> = {
  draft: "Borrador",
  confirmed: "Confirmado",
  annulled: "Anulado",
  reversed: "Revertido",
  create: "Creación",
  edit: "Edición",
  confirm: "Confirmación",
  correct: "Corrección",
  annul: "Anulación",
  reverse: "Reversión",
  reopen: "Reapertura",
  operation: "Operación",
  price: "Precio final",
  currency: "Moneda",
  year: "Año",
  month: "Mes",
  day: "Día",
  kind: "Tipo",
  state: "Estado",
  municipality: "Municipio",
  zone_type: "Tipo de zona",
  zone: "Zona",
  street: "Calle",
  exterior_number: "Número exterior",
  interior_number: "Número interior",
  interior_applicable: "Indicar si tiene interior",
  rural_identification: "Identificación del predio",
  rural_reference: "Referencia documental del predio",
  responsible_id: "Asesor responsable",
  land_m2: "Terreno (m²)",
  construction_m2: "Construcción (m²)",
  private_m2: "Privativa (m²)",
  "characteristics.bedrooms": "Recámaras",
  "characteristics.bathrooms": "Baños",
  "characteristics.half_bathrooms": "Medios baños",
  "characteristics.parking": "Estacionamientos",
  "characteristics.age_years": "Antigüedad",
  "characteristics.condition": "Conservación",
  "characteristics.amenities": "Amenidades",
};
export const emptyClosing: ClosingData = {
  operation: "",
  price: null,
  currency: "",
  year: null,
  month: null,
  day: null,
  kind: "",
  subtype: "",
  state: "",
  municipality: "",
  zone_type: "colonia",
  zone: "",
  address_mode: "urban",
  street: "",
  address_text: "",
  exterior_number: "",
  interior_number: "",
  interior_applicable: null,
  rural_identification: "",
  rural_reference: "",
  access_notes: "",
  land_m2: null,
  construction_m2: null,
  private_m2: null,
  characteristics: {
    bedrooms: null,
    bathrooms: null,
    half_bathrooms: null,
    parking: null,
    age_type: "",
    age_years: null,
    condition: "",
    amenities: null,
    not_applicable: [],
  },
  charges_status: "unknown",
  charges: [],
  notes: "",
  responsible_id: null,
  buyer_id: null,
  is_test: false,
};
