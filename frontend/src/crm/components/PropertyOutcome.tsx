"use client";

import { useEffect, useRef, useState } from "react";
import { api, type ManagedProperty, type Prospect } from "@/shared/lib/api";
import type { Closing, ClosingData, ClosingPreview } from "@/crm/lib/closings";
import { closingLabels } from "@/crm/lib/closings";
import ErrorNotice from "@/shared/components/ErrorFeedback";
import MoneyInput from "@/shared/components/MoneyInput";
import "@/crm/styles/closings.css";

type Result = {
  property: ManagedProperty;
  profile: ClosingData;
  source: Record<string, unknown>;
  missing_profile: string[];
  can_confirm: boolean;
  admin: boolean;
  operations: Closing[];
  history: {
    id: number;
    action: string;
    reason: string;
    actor_id: number | null;
    actor_email: string;
    at: string;
    snapshot: Record<string, unknown>;
  }[];
};
type Props = {
  offerId: number;
  mode: "complete" | "withdraw" | "history";
  onDismiss: () => void;
  onChanged: () => void;
  onEdit: () => void;
};
const money = (value: string | null, currency: string | null) =>
  value === null
    ? "Precio por consultar"
    : !currency
      ? "Moneda pendiente"
      : new Intl.NumberFormat("es-MX", {
          style: "currency",
          currency,
          maximumFractionDigits: 2,
        }).format(Number(value));
const names: Record<string, string> = {
  saved: "Ficha guardada",
  before_edit: "Ficha anterior",
  baseline: "Ficha conservada",
  withdraw: "Retirada de comercialización",
  restore: "Vuelta a revisión",
  confirm: "Venta o renta realizada",
  closed: "Comercialización terminada",
  reopen: "Oferta reabierta",
  annul: "Registro anulado",
  reverse: "Operación revertida",
  correct: "Operación corregida",
  approve: "Revisión aprobada",
  accepted: "Exclusividad aceptada",
  publish: "Publicada",
  expired: "Exclusividad vencida",
  update: "Ficha actualizada",
};

export default function PropertyOutcome({
  offerId,
  mode,
  onDismiss,
  onChanged,
  onEdit,
}: Props) {
  const [result, setResult] = useState<Result | null>(null);
  const [price, setPrice] = useState("");
  const [currency, setCurrency] = useState("MXN");
  const [when, setWhen] = useState("");
  const [reason, setReason] = useState("");
  const [isTest, setIsTest] = useState(false);
  const [buyer, setBuyer] = useState("");
  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [preview, setPreview] = useState<ClosingPreview | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [operation, setOperation] = useState<Closing | null>(null);
  const [action, setAction] = useState("");
  const [intents, setIntents] = useState<
    { id: string; started_at: string; resolved_at: string | null }[]
  >([]);
  const [intent, setIntent] = useState("");
  const receipt = useRef<{ body: string; key: string } | null>(null);
  const mounted = useRef(true);
  const path = `/crm/properties/${offerId}/result`;
  const label = result?.property.operation === "rent" ? "rentada" : "vendida";
  function fail(e: unknown) {
    setError(
      e instanceof Error ? e.message : "No pudimos completar la acción.",
    );
  }
  async function load() {
    const row = await api<Result>(path);
    if (mounted.current) {
      setResult(row);
      setOperation(row.operations[0] || null);
    }
    return row;
  }
  useEffect(() => {
    mounted.current = true;
    void load()
      .then((row) => {
        if (mounted.current) setCurrency(row.profile.currency || "MXN");
      })
      .catch(fail);
    void api<Prospect[]>("/crm/prospects")
      .then((rows) => {
        if (mounted.current) setProspects(rows);
      })
      .catch(fail);
    return () => {
      mounted.current = false;
    };
  }, [offerId]);
  useEffect(() => {
    let active = true;
    setIntents([]);
    setIntent("");
    if (operation?.data.buyer_id && operation.status === "confirmed")
      void api<{ items: typeof intents }>(
        `/crm/closings/searches?prospect_id=${operation.data.buyer_id}`,
      )
        .then((row) => {
          if (active) setIntents(row.items);
        })
        .catch(fail);
    return () => {
      active = false;
    };
  }, [operation?.id, operation?.revision]);
  async function write<T>(url: string, body: Record<string, unknown>) {
    const text = JSON.stringify({ url, body });
    if (receipt.current?.body !== text)
      receipt.current = { body: text, key: crypto.randomUUID() };
    const value = await api<T>(url, {
      method: "POST",
      body: JSON.stringify({ ...body, request_id: receipt.current.key }),
    });
    receipt.current = null;
    return value;
  }
  async function prepare() {
    if (!result) return;
    setBusy(true);
    setError("");
    try {
      setPreview(
        await write<ClosingPreview>(path, {
          action: "prepare",
          source: result.source,
          price,
          currency,
          date: when,
          buyer_id: buyer ? Number(buyer) : null,
          is_test: isTest,
        }),
      );
      setReviewed(false);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function complete() {
    if (!preview) return;
    setBusy(true);
    setError("");
    try {
      await write(`/crm/closings/${preview.id}/actions`, {
        action: "confirm",
        revision: preview.revision,
        preview_token: preview.preview_token,
        reviewed_duplicates: preview.duplicates,
      });
      setPreview(null);
      await load();
      onChanged();
      setNotice(
        `Propiedad marcada como ${label}. Su ficha e historial se conservan.`,
      );
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function retire(restore = false) {
    if (!result) return;
    setBusy(true);
    setError("");
    try {
      setResult(
        await write<Result>(path, {
          action: restore ? "restore" : "withdraw",
          source: result.source,
          reason,
        }),
      );
      onChanged();
      setNotice(
        restore
          ? "La ficha vuelve a revisión y permanece despublicada."
          : "Propiedad retirada. Conservamos sus datos y el historial; no se registró una venta o renta.",
      );
      setReason("");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function changeOperation() {
    if (!operation) return;
    setBusy(true);
    setError("");
    try {
      const body: Record<string, unknown> = {
        action,
        revision: operation.revision,
        reason,
      };
      if (action === "correct")
        body.data = { ...operation.data, price, currency };
      if (action === "reverse") body.reversal_date = when;
      await write(`/crm/closings/${operation.id}/actions`, body);
      await load();
      onChanged();
      setAction("");
      setReason("");
      setNotice("Cambio conservado en el historial.");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section
      className="editor property-outcome"
      aria-label="Resultado de la propiedad"
    >
      <div className="editor-heading">
        <h2>{result?.property.title || "Propiedad"}</h2>
        <button className="link-button" disabled={busy} onClick={onDismiss}>
          Volver a propiedades
        </button>
      </div>
      {error && <ErrorNotice>{error}</ErrorNotice>}
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      {!result ? (
        <p>Cargando ficha…</p>
      ) : (
        <>
          <p>
            {result.property.reference} · {result.profile.zone},{" "}
            {result.profile.municipality}
          </p>
          <h3>Datos de la ficha</h3>
          <p>
            {result.profile.address_text ||
              [
                result.profile.rural_identification,
                result.profile.rural_reference,
              ]
                .filter(Boolean)
                .join(" · ") ||
              "Dirección pendiente en la ficha"}
          </p>
          <dl className="closing-facts">
            <dt>Terreno (m²)</dt>
            <dd>{result.profile.land_m2 ?? "Desconocido"}</dd>
            <dt>Construcción (m²)</dt>
            <dd>{result.profile.construction_m2 ?? "Desconocida"}</dd>
            {result.profile.kind === "apartment" && (
              <>
                <dt>Privativa (m²)</dt>
                <dd>{result.profile.private_m2 ?? "Desconocida"}</dd>
              </>
            )}
            <dt>Precio solicitado</dt>
            <dd>{money(result.property.price, result.property.currency)}</dd>
          </dl>
          {!result.property.closing_id && (
            <button className="link-button" disabled={busy} onClick={onEdit}>
              Editar datos en la ficha de origen
            </button>
          )}
          {!result.property.closing_id &&
            result.property.commercial_status !== "withdrawn" &&
            mode === "complete" && (
              <>
                <h3>Marcar como {label}</h3>
                <p>
                  Confirma únicamente el resultado real de la operación. La
                  dirección y las características se toman de esta ficha.
                </p>
                {result.missing_profile.length > 0 && (
                  <p className="notice">
                    Completa primero en la ficha:{" "}
                    {result.missing_profile
                      .map((key) => closingLabels[key] || key)
                      .join(", ")}
                    . No es necesario volver a capturar la propiedad.
                  </p>
                )}
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    void prepare();
                  }}
                >
                  <fieldset disabled={busy}>
                    <div className="form-grid">
                      <label>
                        Precio final
                        {result.profile.operation === "rent" ? " mensual" : ""}
                        <MoneyInput
                          currency={currency}
                          value={price}
                          required
                          min="0.01"
                          onValueChange={setPrice}
                        />
                      </label>
                      <label>
                        Moneda
                        <select
                          value={currency}
                          onChange={(e) => setCurrency(e.target.value)}
                        >
                          <option>MXN</option>
                          <option>USD</option>
                        </select>
                      </label>
                      <label>
                        Fecha real de{" "}
                        {result.profile.operation === "rent"
                          ? "firma del contrato"
                          : "firma de escritura"}
                        <input
                          type="date"
                          required
                          value={when}
                          onChange={(e) => setWhen(e.target.value)}
                        />
                      </label>
                      <label>
                        Comprador o arrendatario (opcional)
                        <select
                          value={buyer}
                          onChange={(e) => setBuyer(e.target.value)}
                        >
                          <option value="">Sin vincular</option>
                          {prospects.map((p) => (
                            <option key={p.id} value={p.id}>
                              {p.name || p.phone}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="check">
                        <input
                          type="checkbox"
                          checked={isTest}
                          onChange={(e) => setIsTest(e.target.checked)}
                        />
                        Registro de prueba (las acciones siguen siendo reales)
                      </label>
                    </div>
                    <button
                      className="button primary"
                      disabled={!!result.missing_profile.length}
                    >
                      Revisar resultado
                    </button>
                  </fieldset>
                </form>
                {preview && (
                  <section className="closing-preview">
                    <h3>Confirmar operación realizada</h3>
                    <p>
                      {money(preview.data.price!, preview.data.currency)}
                      {preview.data.operation === "rent"
                        ? " por mes"
                        : ""} · {preview.data.day}/{preview.data.month}/
                      {preview.data.year}
                    </p>
                    <p>
                      Se despublicará únicamente esta oferta y terminará su
                      comercialización. Conservaremos su información y el
                      historial.
                    </p>
                    {preview.missing_characteristics.length > 0 && (
                      <p>
                        Características desconocidas:{" "}
                        {preview.missing_characteristics
                          .map((k) => closingLabels[k] || k)
                          .join(", ")}
                      </p>
                    )}
                    {preview.duplicates.length > 0 && (
                      <p className="notice">
                        Posibles operaciones repetidas:{" "}
                        {preview.duplicates.map((id) => (
                          <a
                            key={id}
                            href={`/crm?closing=${id}`}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            Revisar operación {id.slice(0, 8)}{" "}
                          </a>
                        ))}
                      </p>
                    )}
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={reviewed}
                        onChange={(e) => setReviewed(e.target.checked)}
                      />
                      Revisé la ficha y confirmo que la operación ocurrió.
                    </label>
                    <button
                      className="button primary"
                      disabled={busy || !reviewed}
                      onClick={() => void complete()}
                    >
                      Confirmar propiedad {label}
                    </button>
                  </section>
                )}
              </>
            )}
          {!result.property.closing_id &&
            (mode === "withdraw" ||
              result.property.commercial_status === "withdrawn") && (
              <section>
                <h3>
                  {result.property.commercial_status === "withdrawn"
                    ? "Propiedad retirada"
                    : "Retirar o cancelar comercialización"}
                </h3>
                <p>
                  La ficha se conserva aunque no se concrete una operación. No
                  se registra precio final ni venta o renta.
                </p>
                <label>
                  Motivo
                  <textarea
                    required
                    maxLength={1000}
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                  />
                </label>
                <button
                  className="button secondary"
                  disabled={busy || !reason.trim()}
                  onClick={() =>
                    void retire(
                      result.property.commercial_status === "withdrawn",
                    )
                  }
                >
                  {result.property.commercial_status === "withdrawn"
                    ? "Volver a revisión"
                    : "Retirar y conservar ficha"}
                </button>
              </section>
            )}
          {operation && (
            <section>
              <h3>
                Operación{" "}
                {(
                  {
                    confirmed: "confirmada",
                    annulled: "anulada",
                    reversed: "revertida",
                  } as Record<string, string>
                )[operation.status] || operation.status}
              </h3>
              <p>
                {money(operation.data.price!, operation.data.currency)} ·{" "}
                {operation.data.day}/{operation.data.month}/
                {operation.data.year}
              </p>
              {result.can_confirm && (
                <>
                  <label>
                    Acción
                    <select
                      value={action}
                      onChange={(e) => {
                        setAction(e.target.value);
                        setPrice(operation.data.price || "");
                        setCurrency(operation.data.currency);
                        setWhen("");
                        setReason("");
                      }}
                    >
                      <option value="">Consultar historial</option>
                      {operation.status === "confirmed" && (
                        <>
                          <option value="correct">Corregir precio final</option>
                          <option value="annul">
                            Anular registro de una operación que no ocurrió
                          </option>
                          <option value="reverse">
                            Registrar reversión posterior
                          </option>
                        </>
                      )}
                      {operation.status === "annulled" && (
                        <option value="reopen">
                          Reabrir oferta por cierre erróneo
                        </option>
                      )}
                    </select>
                  </label>
                  {action && (
                    <>
                      <label>
                        Motivo
                        <textarea
                          required
                          maxLength={1000}
                          value={reason}
                          onChange={(e) => setReason(e.target.value)}
                        />
                      </label>
                      {action === "correct" && (
                        <label>
                          Precio final corregido
                          <MoneyInput
                            value={price}
                            currency={currency}
                            onValueChange={setPrice}
                          />
                        </label>
                      )}
                      {action === "reverse" && (
                        <label>
                          Fecha de reversión
                          <input
                            type="date"
                            value={when}
                            onChange={(e) => setWhen(e.target.value)}
                          />
                        </label>
                      )}
                      <button
                        disabled={busy || !reason.trim()}
                        onClick={() => void changeOperation()}
                      >
                        Guardar cambio con historial
                      </button>
                    </>
                  )}
                  {operation.status === "confirmed" &&
                    operation.data.buyer_id && (
                      <div>
                        <label>
                          Búsqueda atendida
                          <select
                            value={intent}
                            onChange={(e) => setIntent(e.target.value)}
                          >
                            <option value="">Seleccionar expresamente</option>
                            {intents.map((v) => (
                              <option
                                key={v.id}
                                value={v.id}
                                disabled={!!v.resolved_at}
                              >
                                {new Date(v.started_at).toLocaleDateString(
                                  "es-MX",
                                )}
                                {v.resolved_at ? " · Atendida" : ""}
                              </option>
                            ))}
                          </select>
                        </label>
                        <button
                          disabled={busy || !intent}
                          onClick={async () => {
                            setBusy(true);
                            try {
                              await write(
                                `/crm/closings/${operation.id}/actions`,
                                { action: "resolve_search", intent_id: intent },
                              );
                              setIntent("");
                              setIntents((rows) =>
                                rows.map((row) =>
                                  row.id === intent
                                    ? {
                                        ...row,
                                        resolved_at: new Date().toISOString(),
                                      }
                                    : row,
                                ),
                              );
                              setNotice(
                                "Búsqueda atendida; permiso general de contacto conservado.",
                              );
                            } catch (e) {
                              fail(e);
                            } finally {
                              setBusy(false);
                            }
                          }}
                        >
                          Dar por atendida esa búsqueda
                        </button>
                      </div>
                    )}
                </>
              )}
              <details>
                <summary>Historial de operaciones</summary>
                {result.operations.map((op) => (
                  <section key={op.id}>
                    <h4>
                      {closingLabels[op.status]} · {op.data.year}
                    </h4>
                    {op.history?.map((h) => (
                      <p key={h.number}>
                        {closingLabels[h.action] || h.action} ·{" "}
                        {money(h.data.price || "0", h.data.currency || "MXN")} ·{" "}
                        {new Date(h.at).toLocaleString("es-MX")} ·{" "}
                        {h.actor_email || `Usuario ${h.actor_id}`}
                        {h.reason ? ` · ${h.reason}` : ""}
                      </p>
                    ))}
                  </section>
                ))}
              </details>
            </section>
          )}
          <details open={mode === "history"}>
            <summary>
              Historial de la propiedad, también sin venta o renta
            </summary>
            {result.history.map((h) => (
              <section className="closing-history" key={h.id}>
                <strong>{names[h.action] || "Cambio de la ficha"}</strong>
                <p>
                  {new Date(h.at).toLocaleString("es-MX")} ·{" "}
                  {h.actor_email ||
                    (h.actor_id ? `Usuario ${h.actor_id}` : "Sistema")}
                  {h.reason ? ` · ${h.reason}` : ""}
                </p>
                {typeof h.snapshot.title === "string" && (
                  <p>{h.snapshot.title}</p>
                )}
              </section>
            ))}
            {!result.history.length && (
              <p>
                La ficha actual se conserva. Los cambios posteriores quedarán
                registrados aquí.
              </p>
            )}
          </details>
        </>
      )}
    </section>
  );
}
