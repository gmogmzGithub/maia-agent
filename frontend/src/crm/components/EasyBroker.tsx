"use client";

import { useEffect, useMemo, useRef, useSyncExternalStore } from "react";
import ErrorNotice from "@/shared/components/ErrorFeedback";
import { api } from "@/shared/lib/api";
import { brokerStatus } from "@/crm/lib/easybroker";
import { EasyBrokerReviewSession } from "@/crm/lib/easybroker-review-session";
import "@/crm/styles/easybroker.css";

const when = (date: string | null) =>
  date ? new Date(date).toLocaleString("es-MX") : "Todavía sin comprobar";

export default function EasyBroker({ onChanged }: { onChanged: () => void }) {
  const changed = useRef(onChanged);
  changed.current = onChanged;
  const review = useMemo(
    () =>
      new EasyBrokerReviewSession({
        request: api,
        requestId: () => crypto.randomUUID(),
        changed: () => changed.current(),
      }),
    [],
  );
  const {
    accounts,
    listings,
    advisors,
    offers,
    selected,
    offset,
    busy,
    error: failure,
    notice,
  } = useSyncExternalStore(review.subscribe, review.snapshot, review.snapshot);
  const error =
    failure instanceof Error
      ? failure.message
      : failure
        ? "No pudimos completar la acción."
        : "";
  const mutate = review.mutate;
  useEffect(() => {
    review.resume();
    void review.load();
    return () => review.stop();
  }, [review]);
  const active = accounts.items.some((account) =>
    ["queued", "running"].includes(account.last_run?.status || ""),
  );
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => void review.refresh(), 5000);
    return () => clearInterval(timer);
  }, [active, review]);
  const advisorOptions = advisors.map((a) => (
    <option key={a.id} value={a.id}>
      {a.name}
    </option>
  ));

  return (
    <section className="easybroker-panel" aria-label="EasyBroker">
      <p>
        Importa cuentas autorizadas. La actualización solo consulta EasyBroker;
        cada oferta necesita revisión antes de publicarse en Maia.
      </p>
      {!accounts.public_enabled && (
        <p className="notice">
          Las importaciones permanecen privadas mientras se completa la
          aceptación de la integración.
        </p>
      )}
      {error && <ErrorNotice>{error}</ErrorNotice>}
      {notice && <p role="status">{notice}</p>}
      <button
        type="button"
        disabled={busy}
        onClick={() => void review.refresh()}
      >
        Actualizar lista
      </button>
      <h2>Cuentas de origen</h2>
      <div className="eb-accounts">
        {accounts.items.map((account) => (
          <article className="eb-account" key={account.id}>
            <h3>{account.name}</h3>
            <p>
              {account.environment === "sandbox" ? "Pruebas" : "Producción"} ·{" "}
              {account.enabled ? "Conectada" : "Desconectada"}
            </p>
            <p>
              Última actualización completa: {when(account.last_success_at)}
            </p>
            {account.last_run && (
              <p role="status">
                {brokerStatus[account.last_run.status] ||
                  account.last_run.status}{" "}
                · {account.last_run.counters.checked || 0} comprobadas ·{" "}
                {account.last_run.counters.failed || 0} incidencias
              </p>
            )}
            {account.error_code && (
              <p className="notice">
                Requiere atención: {account.error_code}. Una consulta fallida no
                acredita una baja.
              </p>
            )}
            <button
              type="button"
              disabled={busy || !account.enabled}
              onClick={() =>
                void mutate(`/connections/${account.id}/sync`, {
                  revision: account.revision,
                })
              }
            >
              Actualizar ahora
            </button>
            {accounts.admin && (
              <details>
                <summary>Configurar cuenta</summary>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    const d = new FormData(e.currentTarget);
                    void mutate(`/connections/${account.id}/actions`, {
                      action: "configure",
                      revision: account.revision,
                      name: d.get("name"),
                      advisor_id: Number(d.get("advisor_id")),
                    });
                  }}
                >
                  <label>
                    Nombre
                    <input
                      name="name"
                      defaultValue={account.name}
                      maxLength={100}
                      required
                    />
                  </label>
                  <label>
                    Responsable predeterminado
                    <select name="advisor_id" defaultValue={account.advisor_id}>
                      {advisorOptions}
                    </select>
                  </label>
                  <button disabled={busy}>Guardar configuración</button>
                </form>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    const form = e.currentTarget;
                    const key = new FormData(form).get("key");
                    form.reset();
                    void mutate(`/connections/${account.id}/actions`, {
                      action: "credential",
                      revision: account.revision,
                      key,
                    });
                  }}
                >
                  <label>
                    Nueva clave de la misma cuenta
                    <input
                      name="key"
                      type="password"
                      autoComplete="new-password"
                      required
                      maxLength={1024}
                    />
                  </label>
                  <p>
                    El cambio oculta las ofertas hasta comprobar la continuidad
                    y revisarlas. Otra cuenta necesita una conexión nueva.
                  </p>
                  <button disabled={busy}>Reemplazar clave</button>
                </form>
                <p>
                  Desconectar oculta las ofertas dependientes de esta cuenta y
                  conserva las fichas y su historial. Reconectar exige revisión
                  para publicarlas de nuevo.
                </p>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    void mutate(`/connections/${account.id}/actions`, {
                      action: account.enabled ? "disconnect" : "reconnect",
                      revision: account.revision,
                    })
                  }
                >
                  {account.enabled ? "Desconectar" : "Reconectar"}
                </button>
              </details>
            )}
          </article>
        ))}
      </div>
      {accounts.admin && (
        <details>
          <summary>Conectar otra cuenta</summary>
          <form
            className="eb-form"
            onSubmit={(e) => {
              e.preventDefault();
              const form = e.currentTarget;
              const d = new FormData(form);
              const key = d.get("key");
              form.reset();
              void mutate("/connections", {
                name: d.get("name"),
                environment: d.get("environment"),
                advisor_id: Number(d.get("advisor_id")),
                key,
              });
            }}
          >
            <label>
              Nombre de origen
              <input name="name" required maxLength={100} />
            </label>
            <label>
              Entorno
              <select name="environment">
                <option value="sandbox">Pruebas</option>
                <option value="production">Producción</option>
              </select>
            </label>
            <label>
              Responsable local
              <select name="advisor_id" required>
                {advisorOptions}
              </select>
            </label>
            <label>
              Clave autorizada
              <input
                name="key"
                type="password"
                autoComplete="new-password"
                required
                maxLength={1024}
              />
            </label>
            <button disabled={busy}>Conectar y consultar</button>
          </form>
        </details>
      )}
      <h2>Fichas importadas ({listings.count})</h2>
      <p>
        Las fichas incompletas y las bajas conservan sus datos. Un estado
        vendido o rentado en origen no registra un cierre en Maia.
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Referencia</th>
              <th>Origen</th>
              <th>Estado externo</th>
              <th>Última comprobación</th>
              <th>Revisión</th>
            </tr>
          </thead>
          <tbody>
            {listings.items.map((row) => (
              <tr key={row.id}>
                <td>{row.public_id}</td>
                <td>{row.connection_name}</td>
                <td>{brokerStatus[row.status] || "Por comprobar"}</td>
                <td>{when(row.checked_at)}</td>
                <td>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      void review.select(row.id);
                    }}
                  >
                    Revisar ficha
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="form-actions">
        <button
          disabled={!offset || busy}
          onClick={() => review.page(Math.max(0, offset - 50))}
        >
          Anterior
        </button>
        <button
          disabled={listings.next_offset === null || busy}
          onClick={() => review.page(listings.next_offset || 0)}
        >
          Siguiente
        </button>
      </div>
      {selected && (
        <section
          className="eb-review"
          key={`${selected.id}:${selected.revision}`}
        >
          <button type="button" onClick={() => void review.select(null)}>
            Cerrar revisión
          </button>
          <h2>
            {selected.public_id} · {selected.connection_name}
          </h2>
          <p>
            {brokerStatus[selected.status]} · Revisión {selected.revision}
          </p>
          <details>
            <summary>Datos privados recibidos e incidencias</summary>
            <pre>
              {JSON.stringify(
                { facts: selected.facts, issues: selected.issues },
                null,
                2,
              )}
            </pre>
          </details>
          <p>
            Confirma estado, municipio y zona. El nombre de ubicación del origen
            no se separa automáticamente. Revisa los textos para excluir
            direcciones exactas y precios que deban permanecer privados.
          </p>
          <form
            className="eb-form"
            onSubmit={(e) => {
              e.preventDefault();
              const d = new FormData(e.currentTarget);
              void mutate(`/imports/${selected.id}/actions`, {
                action: "approve",
                revision: selected.revision,
                operation: d.get("operation"),
                title: d.get("title"),
                description: d.get("description"),
                state: d.get("state"),
                municipality: d.get("municipality"),
                neighborhood: d.get("neighborhood"),
                advisor_id: Number(d.get("advisor_id")),
                reason: d.get("reason"),
                publish: d.get("publish") === "on",
              });
            }}
          >
            <label>
              Operación
              <select name="operation">
                <option value="sale">Venta</option>
                <option value="rent">Renta mensual</option>
              </select>
            </label>
            <label>
              Responsable de esta oferta
              <select
                name="advisor_id"
                defaultValue={
                  accounts.items.find((a) => a.id === selected.connection_id)
                    ?.advisor_id
                }
                required
              >
                {advisorOptions}
              </select>
            </label>
            <label>
              Estado
              <input
                name="state"
                defaultValue={selected.geography.state}
                required
                maxLength={80}
              />
            </label>
            <label>
              Municipio
              <input
                name="municipality"
                defaultValue={selected.geography.municipality}
                required
                maxLength={100}
              />
            </label>
            <label>
              Zona pública
              <input
                name="neighborhood"
                defaultValue={selected.geography.neighborhood}
                required
                maxLength={100}
              />
            </label>
            <label>
              Título público revisado
              <input name="title" required maxLength={180} />
            </label>
            <label className="full">
              Descripción pública revisada
              <textarea name="description" maxLength={5000} rows={5} />
            </label>
            <label className="full">
              Motivo y comprobación realizada
              <input name="reason" required maxLength={1000} />
            </label>
            <label className="check full">
              <input name="publish" type="checkbox" />
              Publicar después de aprobar, respetando exclusiones manuales
            </label>
            <button disabled={busy}>Aprobar esta operación</button>
          </form>
          <details>
            <summary>Vincular con una oferta existente</summary>
            <p>
              Una oferta local conserva sus datos y contratos. Una fuente
              secundaria no reemplaza automáticamente a la principal.
            </p>
            <form
              className="eb-form"
              onSubmit={(e) => {
                e.preventDefault();
                const d = new FormData(e.currentTarget);
                void mutate(`/imports/${selected.id}/actions`, {
                  action: "link",
                  revision: selected.revision,
                  operation: d.get("operation"),
                  offer_id: Number(d.get("offer_id")),
                  reason: d.get("reason"),
                });
              }}
            >
              <label>
                Oferta
                <select name="offer_id" required>
                  {offers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.reference} · {p.title}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Operación
                <select name="operation">
                  <option value="sale">Venta</option>
                  <option value="rent">Renta</option>
                </select>
              </label>
              <label>
                Motivo
                <input name="reason" required maxLength={1000} />
              </label>
              <button disabled={busy}>Vincular sin sustituir datos</button>
            </form>
          </details>
          <h3>Vinculaciones</h3>
          {selected.links.map((link) => (
            <div key={link.id}>
              <p>
                Oferta {link.offer_id} ·{" "}
                {link.operation === "sale" ? "Venta" : "Renta"} ·{" "}
                {link.role === "primary"
                  ? "Principal"
                  : link.role === "local"
                    ? "Referencia local"
                    : "Secundaria"}
              </p>
              {link.role === "secondary" && (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    const d = new FormData(e.currentTarget);
                    void mutate(`/imports/${selected.id}/actions`, {
                      action: "primary",
                      revision: selected.revision,
                      link_id: link.id,
                      reason: d.get("reason"),
                    });
                  }}
                >
                  <label>
                    Motivo del cambio de principal
                    <input name="reason" required maxLength={1000} />
                  </label>
                  <button disabled={busy}>
                    Elegir principal y volver a revisar
                  </button>
                </form>
              )}
              <details>
                <summary>Corregir esta vinculación</summary>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    const data = new FormData(e.currentTarget);
                    void mutate(`/imports/${selected.id}/actions`, {
                      action: "unlink",
                      revision: selected.revision,
                      link_id: link.id,
                      reason: data.get("reason"),
                    });
                  }}
                >
                  <p>
                    Retira la relación activa y conserva su historial. Si era la
                    fuente principal, la oferta quedará oculta hasta una nueva
                    revisión.
                  </p>
                  <label>
                    Motivo de la corrección
                    <input name="reason" required maxLength={1000} />
                  </label>
                  <button disabled={busy}>Retirar vinculación</button>
                </form>
              </details>
            </div>
          ))}
          <details>
            <summary>Historial conservado</summary>
            <pre>{JSON.stringify(selected.history, null, 2)}</pre>
          </details>
        </section>
      )}
    </section>
  );
}
