"use client";
import ErrorNotice from "@/shared/components/ErrorFeedback";
import MoneyInput from "@/shared/components/MoneyInput";
import { useEffect, useMemo, useRef, useState } from "react";
import Header from "@/shared/components/Header";
import { api, ApiError, type ApiIssue, money, session } from "@/shared/lib/api";
import {
  captureAction,
  initialData,
  statusLabels,
  type Capture,
  type CaptureData,
  type CaptureValue,
  type Catalog,
  type Owner,
  type LocationPoint,
} from "@/shared/lib/capture";
import OwnerAccount from "@/main-website/components/OwnerAccount";
import LocationFields from "@/shared/components/LocationFields";
import CaptureMedia from "@/main-website/components/CaptureMedia";
import { useCaptureUploads } from "@/main-website/hooks/useCaptureUploads";
import {
  DEFAULT_UPLOAD_LIMITS,
  type MediaKind,
} from "@/main-website/lib/capture-upload-queue";
import { OwnerCaptureJourney } from "@/main-website/lib/owner-capture-journey";
import "@/shared/styles/capture.css";

const steps = [
  "Inmueble",
  "Ubicación",
  "Características",
  "Fotos y planos",
  "Comodidades",
  "Revisión",
];
export default function OwnerCapture() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [owner, setOwner] = useState<Owner | null>(null);
  const [rows, setRows] = useState<Capture[]>([]);
  const [capture, setCapture] = useState<Capture | null>(null);
  const [location, setLocation] = useState<LocationPoint | null>(null);
  const [locationPending, setLocationPending] = useState(false);
  const [data, setData] = useState<CaptureData>({ ...initialData });
  const [draftId, setDraftId] = useState("");
  const [step, setStep] = useState(0);
  const [showForm, setShowForm] = useState(false);
  const [showAccount, setShowAccount] = useState(false);
  const [accountMode, setAccountMode] = useState<"register" | "login">(
    "register",
  );
  const [resetToken, setResetToken] = useState("");
  const [verifyToken, setVerifyToken] = useState("");
  const [requestedCaptureId, setRequestedCaptureId] = useState("");
  const acceptancePanel = useRef<HTMLDivElement>(null);
  const accountPanel = useRef<HTMLDivElement>(null);
  const verificationPanel = useRef<HTMLElement>(null);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setErrorMessage] = useState("");
  const [errorIssues, setErrorIssues] = useState<ApiIssue[]>([]);
  const setError = (failure: unknown) => {
    setErrorMessage(
      failure instanceof Error ? failure.message : String(failure || ""),
    );
    setErrorIssues(failure instanceof ApiError ? failure.issues : []);
  };
  const [notice, setNotice] = useState("");
  const [rejectedFiles, setRejectedFiles] = useState<
    { name: string; reason: string }[]
  >([]);
  const [accepted, setAccepted] = useState(false);
  const draftKey = "maia-owner-draft";
  useEffect(() => {
    if (showAccount || (verifyToken && !owner)) {
      accountPanel.current?.scrollIntoView({
        block: "start",
        behavior: "instant",
      });
      accountPanel.current?.focus({ preventScroll: true });
    }
  }, [showAccount, verifyToken, owner]);
  useEffect(() => {
    if (!owner || owner.verified) return;
    verificationPanel.current?.scrollIntoView({
      block: "start",
      behavior: "instant",
    });
    verificationPanel.current?.focus({ preventScroll: true });
  }, [owner?.email, owner?.verified]);

  const latestUploadRunning = useRef(false);
  const journey = useMemo(
    () =>
      new OwnerCaptureJourney({
        request: api,
        session,
        changed: setCapture,
        rows: setRows,
        feedback: (value) => {
          if (value.busy !== undefined) setBusy(value.busy);
          if (value.error !== undefined) setError(value.error);
          if (value.notice !== undefined) setNotice(value.notice);
        },
        needsAccount: () => {
          setAccountMode("register");
          setShowAccount(true);
        },
        blocked: () => latestUploadRunning.current,
      }),
    [],
  );
  journey.update({ owner, capture, data, draftId });
  const loadRows = journey.loadRows;
  useEffect(() => {
    journey.resume();
    let active = true;
    const query = new URLSearchParams(window.location.search);
    const requested = query.get("capture") || "";
    const entryMode = query.get("account");
    if (entryMode === "register" || entryMode === "login") {
      setAccountMode(entryMode);
      query.delete("account");
      const search = query.toString();
      window.history.replaceState(
        null,
        "",
        window.location.pathname +
          (search ? `?${search}` : "") +
          window.location.hash,
      );
    }
    setRequestedCaptureId(requested);
    const saved = requested ? null : sessionStorage.getItem(draftKey);
    setDraftId(crypto.randomUUID());
    const hash = new URLSearchParams(window.location.hash.slice(1));
    setVerifyToken(hash.get("verify") || "");
    setResetToken(hash.get("reset") || "");
    if (hash.has("reset")) setShowAccount(true);
    if (hash.has("verify") || hash.has("reset"))
      window.history.replaceState(
        null,
        "",
        window.location.pathname + window.location.search,
      );
    void journey
      .bootstrap(saved)
      .then((result) => {
        if (!active || !result) return;
        setCatalog(result.catalog);
        setOwner(result.owner);
        if (result.draft) {
          setData(result.draft.data);
          setDraftId(result.draft.id);
          setCapture(result.draft.capture);
          setShowForm(true);
        }
        if (
          (requested || entryMode === "register" || entryMode === "login") &&
          !result.owner
        )
          setShowAccount(true);
      })
      .catch((e) => {
        if (active) setError(e);
      })
      .finally(() => {
        if (active) setReady(true);
      });
    return () => {
      active = false;
      journey.stop();
    };
  }, [journey]);
  useEffect(() => {
    if (
      ready &&
      showForm &&
      draftId &&
      (!capture || capture.status === "draft")
    )
      sessionStorage.setItem(
        draftKey,
        JSON.stringify({
          id: draftId,
          data,
          ownerEmail: owner?.email || null,
          capture: capture ? { ...capture, location: undefined } : null,
        }),
      );
  }, [ready, showForm, draftId, data, capture, owner?.email]);
  useEffect(() => {
    if (!verifyToken || !owner) return;
    let active = true;
    void journey
      .verify(verifyToken)
      .then((account) => {
        if (!active || !account) return;
        setOwner(account);
        setVerifyToken("");
        setNotice("Email verificado. Ya puedes acceder a tus propiedades.");
      })
      .catch((e) => {
        if (active) {
          setError(e);
          setVerifyToken("");
        }
      });
    return () => {
      active = false;
    };
  }, [verifyToken, owner, journey]);

  const run = journey.run;
  const ensureAccount = journey.requireAccount;
  useEffect(() => {
    if (!owner?.verified) return;
    void loadRows().catch((e) => setError(e));
    void journey.resumePending();
  }, [owner?.email, owner?.verified, journey]);
  const persist = journey.persist;
  const uploadLimits = catalog?.upload_limits || DEFAULT_UPLOAD_LIMITS;
  const uploads = useCaptureUploads({
    scope: `${owner?.email || "anonymous"}:${draftId}`,
    enabled: !!owner?.verified && showForm,
    blocked: busy,
    capture,
    limits: uploadLimits,
    prepare: persist,
    changed: setCapture,
  });
  latestUploadRunning.current = uploads.running;
  const mediaQueueRef = useRef(uploads.queue);
  mediaQueueRef.current = uploads.queue;
  const addMedia = (files: File[], kind: MediaKind) => {
    // Account creation/verification may resume this task after the queue scope changes.
    const enqueue = async () => {
      setError("");
      setNotice("");
      setRejectedFiles(mediaQueueRef.current.enqueue(files, kind));
    };
    if (owner?.verified) void enqueue();
    else ensureAccount(enqueue);
  };
  const selectCapture = (row: Capture) => {
    if (!uploads.confirmDiscard()) return;
    journey.cancelOpen();
    setCapture(row);
    setLocation(row.location || null);
    setData(row.data);
    setDraftId(row.id);
    setShowForm(true);
    setStep(0);
    setError("");
    setAccepted(false);
    setRejectedFiles([]);
  };
  useEffect(() => {
    if (!ready || !owner?.verified || !requestedCaptureId) return;
    let active = true;
    void journey
      .openRequested(requestedCaptureId)
      .then((row) => {
        if (!active || !row) return;
        selectCapture(row);
        setShowAccount(false);
        setNotice(
          row.status === "approved"
            ? "Tu propiedad fue aprobada. Revisa el acuerdo que aparece abajo para aceptar la exclusividad."
            : "Abrimos el estado actual de tu solicitud.",
        );
      })
      .catch(() => {
        if (active)
          setError(
            "No pudimos abrir esta propiedad. Inicia sesión con la cuenta que usaste para subirla o consulta Mis propiedades.",
          );
      });
    return () => {
      active = false;
    };
  }, [ready, owner?.email, owner?.verified, requestedCaptureId, journey]);
  useEffect(() => {
    if (requestedCaptureId === capture?.id && capture.status === "approved") {
      acceptancePanel.current?.scrollIntoView({
        block: "start",
        behavior: "instant",
      });
      acceptancePanel.current?.focus({ preventScroll: true });
    }
  }, [requestedCaptureId, capture?.id, capture?.status]);
  const clearRequestedCapture = () => {
    setRequestedCaptureId("");
    journey.cancelOpen();
    const url = new URL(window.location.href);
    url.searchParams.delete("capture");
    window.history.replaceState(null, "", url.pathname + url.search + url.hash);
  };
  const start = () => {
    if (!uploads.confirmDiscard()) return;
    clearRequestedCapture();
    setCapture(null);
    setLocation(null);
    setDraftId(crypto.randomUUID());
    setData({ ...initialData });
    setStep(0);
    setShowForm(true);
    setRejectedFiles([]);
    setError("");
  };
  const update = (key: string, value: CaptureValue) =>
    setData((d) => ({ ...d, [key]: value }));
  const field = (
    key: string,
    label: string,
    type = "text",
    required = false,
  ) => (
    <label key={key}>
      {label}
      {["price", "maintenance"].includes(key) ? (
        <MoneyInput
          currency={String(data.currency || "MXN")}
          name={key}
          value={String(data[key] ?? "")}
          required={required}
          onValueChange={(raw) =>
            update(key, raw === "" || raw === "." ? null : Number(raw))
          }
        />
      ) : (
        <input
          name={key}
          type={type}
          value={String(data[key] ?? "")}
          required={required}
          maxLength={
            type === "text"
              ? key === "private_address"
                ? 240
                : 180
              : undefined
          }
          min={
            type === "number" && !["latitude", "longitude"].includes(key)
              ? 0
              : undefined
          }
          step={type === "number" ? "any" : undefined}
          onChange={(e) =>
            update(
              key,
              type === "number"
                ? e.target.value === ""
                  ? null
                  : Number(e.target.value)
                : e.target.value,
            )
          }
        />
      )}
    </label>
  );
  const check = (key: string, label: string) => (
    <label className="capture-check">
      <input
        type="checkbox"
        checked={data[key] === true}
        onChange={(e) => update(key, e.target.checked)}
      />
      {label}
    </label>
  );
  const linkList = (key: string, label: string) => (
    <label>
      {label}
      <textarea
        rows={3}
        value={((data[key] as string[]) || []).join("\n")}
        placeholder="https://… (un enlace por línea)"
        onChange={(e) => update(key, e.target.value.split("\n"))}
        onBlur={() =>
          update(
            key,
            ((data[key] as string[]) || [])
              .map((x) => x.trim())
              .filter(Boolean),
          )
        }
      />
    </label>
  );
  const photos = capture?.assets.filter((x) => x.kind === "photo") || [];
  const readOnly = !!capture && capture.status !== "draft";

  return (
    <>
      <Header className="capture-header" />
      <main className="capture-page">
        <div className="capture-heading">
          <div>
            <p className="eyebrow">Propietarios · Maia</p>
            <h1>Tu propiedad, en buenas manos.</h1>
            <p>
              Cuéntanos sobre tu inmueble. Nuestro equipo lo revisará y te
              acompañará para venderlo o rentarlo en exclusiva.
            </p>
          </div>
          {owner && (
            <div className="capture-account-menu">
              <span>{owner.email}</span>
              <button
                className="link-button"
                disabled={busy || uploads.running}
                onClick={() =>
                  void run(async () => {
                    if (!uploads.confirmDiscard()) return;
                    await api("/auth/logout", { method: "POST" });
                    sessionStorage.removeItem(draftKey);
                    setOwner(null);
                    setRows([]);
                    setCapture(null);
                    setLocation(null);
                    setShowForm(false);
                    setData({ ...initialData });
                    setDraftId(crypto.randomUUID());
                  })
                }
              >
                Salir
              </button>
            </div>
          )}
          {ready && !owner && !showAccount && (
            <div className="capture-account-menu">
              <button
                className="button primary"
                onClick={() => {
                  setAccountMode("register");
                  setShowAccount(true);
                }}
              >
                Crear cuenta
              </button>
              <button
                className="button secondary"
                onClick={() => {
                  setAccountMode("login");
                  setShowAccount(true);
                }}
              >
                Iniciar sesión
              </button>
            </div>
          )}
        </div>
        {!ready && <p>Cargando…</p>}
        {error && (
          <ErrorNotice issues={errorIssues}>
            {error}
            <button
              type="button"
              className="link-button"
              onClick={() => {
                setError("");
                if (owner)
                  void run(async () => {
                    await loadRows();
                    if (capture)
                      selectCapture(
                        await api<Capture>(`/capture/requests/${capture.id}`),
                      );
                  });
              }}
            >
              Actualizar
            </button>
          </ErrorNotice>
        )}
        {notice && (
          <p className="notice" role="status">
            {notice}
          </p>
        )}
        {verifyToken && !owner && (
          <p className="notice">
            Inicia sesión con la cuenta del enlace para verificar tu email.
          </p>
        )}
        {owner && !owner.verified && !resetToken && (
          <section
            className="capture-verification"
            ref={verificationPanel}
            tabIndex={-1}
            aria-labelledby="verification-title"
          >
            <svg
              className="verification-icon"
              viewBox="0 0 48 48"
              fill="none"
              aria-hidden="true"
            >
              <rect x="7" y="14" width="34" height="24" rx="5" />
              <path d="m8 17 16 12 16-12M18 8h12M24 3v5" />
            </svg>
            <h2 id="verification-title">Verifica tu correo para continuar</h2>
            <p>
              Enviamos un enlace de verificación a<br />
              <strong>{owner.email}</strong>
            </p>
            <p>
              Abre el correo y pulsa el enlace para acceder a tus propiedades.
              Si no lo encuentras, revisa spam.
            </p>
            <p>Tu avance se conserva en este navegador.</p>
            <button
              className="button primary"
              disabled={busy || uploads.running}
              onClick={() =>
                void run(async () => {
                  await api("/capture/account", {
                    method: "POST",
                    body: JSON.stringify({ action: "resend" }),
                  });
                  setNotice("Solicitamos un nuevo correo de verificación.");
                })
              }
            >
              Reenviar correo
            </button>
            <button
              className="link-button"
              disabled={busy || uploads.running}
              onClick={() =>
                void run(async () => {
                  const result = await api<{ account: Owner }>(
                    "/capture/account",
                  );
                  setOwner(result.account);
                  if (!result.account.verified)
                    setNotice(
                      "Tu correo todavía no está verificado. Abre el enlace que te enviamos.",
                    );
                })
              }
            >
              Ya verifiqué mi correo
            </button>
            <button
              className="link-button"
              disabled={busy || uploads.running}
              onClick={() =>
                void run(async () => {
                  await api("/auth/logout", { method: "POST" });
                  setOwner(null);
                  setRows([]);
                  setAccountMode("register");
                  setShowAccount(true);
                  setVerifyToken("");
                })
              }
            >
              Usar otra cuenta
            </button>
          </section>
        )}
        {(showAccount || (verifyToken && !owner)) && (
          <div className="capture-auth-wrap" ref={accountPanel} tabIndex={-1}>
            {requestedCaptureId && (
              <p className="notice">
                Inicia sesión con la cuenta que usaste para subir esta
                propiedad. Después abriremos directamente la solicitud de tu
                correo.
              </p>
            )}
            <OwnerAccount
              purpose={
                step === 3
                  ? "subir las fotos y proteger tus archivos"
                  : "guardar el avance y consultar tu solicitud"
              }
              initialMode={
                requestedCaptureId || verifyToken ? "login" : accountMode
              }
              resetToken={resetToken}
              onReset={() => setResetToken("")}
              onAccount={(o) => {
                setOwner(o);
                setShowAccount(false);
              }}
            />
            <button
              type="button"
              className="link-button"
              onClick={() => {
                setShowAccount(false);
                journey.cancelPending();
              }}
            >
              Volver al formulario
            </button>
          </div>
        )}
        {ready &&
          !showAccount &&
          !verifyToken &&
          (!owner || owner.verified) && (
            <>
              {!showForm && (
                <section className="capture-dashboard">
                  <div className="capture-dashboard-heading">
                    <h2>
                      {owner ? "Mis propiedades" : "Vende o renta con nosotros"}
                    </h2>
                    <button className="button primary" onClick={start}>
                      + Subir mi propiedad
                    </button>
                  </div>
                  {owner &&
                    rows.map((row) => (
                      <button
                        key={row.id}
                        className="capture-list-item"
                        onClick={() => selectCapture(row)}
                      >
                        <strong>
                          {String(
                            row.data.title ||
                              row.data.neighborhood ||
                              "Nuevo inmueble",
                          )}
                        </strong>
                        <span>{statusLabels[row.status]}</span>
                        <small>
                          {new Date(row.updated_at).toLocaleDateString("es-MX")}
                        </small>
                      </button>
                    ))}
                  {owner && !rows.length && (
                    <p>Tus borradores y solicitudes aparecerán aquí.</p>
                  )}
                </section>
              )}
              {showForm && catalog && (
                <section className="capture-workspace">
                  <div className="capture-toolbar">
                    <button
                      className="link-button"
                      disabled={busy || uploads.running}
                      onClick={() => {
                        if (!uploads.confirmDiscard()) return;
                        clearRequestedCapture();
                        setShowForm(false);
                        if (owner) void run(loadRows);
                      }}
                    >
                      ← Mis propiedades
                    </button>
                    <span>
                      {capture
                        ? statusLabels[capture.status]
                        : "Nuevo borrador"}
                    </span>
                  </div>
                  {readOnly ? (
                    <>
                      <h2>
                        {String(
                          data.title ||
                            `${catalog.kinds[String(data.kind)]?.label} en ${data.neighborhood}`,
                        )}
                      </h2>
                      <p>
                        {money(String(data.price || 0), String(data.currency))}{" "}
                        {String(data.currency)} ·{" "}
                        {data.is_presale
                          ? "Preventa"
                          : data.operation === "sale"
                            ? "Venta"
                            : "Renta"}
                      </p>
                      <p>
                        {String(data.neighborhood)}, {String(data.municipality)}
                        , {String(data.state)}
                      </p>
                      <div className="capture-photo-grid">
                        {photos.map((photo) => (
                          <img
                            key={photo.id}
                            src={photo.url}
                            alt="Foto de tu propiedad"
                          />
                        ))}
                      </div>
                      <p>Solicitud: {capture.id}</p>
                      <p>Teléfono registrado: {owner?.phone}</p>
                      {capture.status === "approved" && (
                        <div
                          className="capture-contract"
                          ref={acceptancePanel}
                          tabIndex={-1}
                        >
                          <h3>Exclusividad por seis meses</h3>
                          <a
                            href={`/api/capture/requests/${capture.id}/contract`}
                            className="button secondary"
                          >
                            Descargar contrato PDF
                          </a>
                          <p>{catalog.contract_text}</p>
                          <label className="capture-check">
                            <input
                              type="checkbox"
                              checked={accepted}
                              onChange={(e) => setAccepted(e.target.checked)}
                            />
                            He leído y acepto el contrato de demostración para
                            este inmueble.
                          </label>
                          <button
                            className="button primary"
                            disabled={busy || uploads.running || !accepted}
                            onClick={() =>
                              void run(async () => {
                                setCapture(
                                  await captureAction(capture, "accept", {
                                    accepted: true,
                                    version: catalog.contract_version,
                                  }),
                                );
                                setNotice(
                                  "Aceptación registrada. El equipo ya puede publicar tu inmueble.",
                                );
                              })
                            }
                          >
                            Aceptar exclusividad
                          </button>
                        </div>
                      )}
                      {capture.agreement && (
                        <div className="notice">
                          <strong>Exclusividad aceptada</strong>
                          <p>
                            Vigente hasta{" "}
                            {new Date(
                              capture.agreement.expires_at,
                            ).toLocaleDateString("es-MX")}
                            . Sin renovación automática.
                          </p>
                          <details>
                            <summary>Ver contrato aceptado</summary>
                            <p>{capture.agreement.text}</p>
                            <a
                              href={`/api/capture/requests/${capture.id}/contract`}
                            >
                              Descargar copia del acuerdo aceptado
                            </a>
                          </details>
                        </div>
                      )}
                      {capture.valuation && (
                        <div className="notice">
                          <h3>Opinión de valor del equipo</h3>
                          <p>
                            {money(capture.valuation, String(data.currency))}{" "}
                            {String(data.currency)}
                          </p>
                          <p>{capture.valuation_notes}</p>
                        </div>
                      )}
                      {capture.property_id &&
                        capture.status === "published" && (
                          <a
                            className="button secondary"
                            href={`/propiedades/${capture.property_id}`}
                          >
                            Ver publicación
                          </a>
                        )}
                      <section className="capture-request">
                        <h3>Tu asesor</h3>
                        {capture.advisor ? (
                          <>
                            <p>
                              <strong>Nombre:</strong> {capture.advisor.name}
                            </p>
                            <p>
                              <strong>WhatsApp:</strong>{" "}
                              {capture.advisor.whatsapp ? (
                                <a
                                  href={`https://wa.me/${capture.advisor.whatsapp.replace(/\D/g, "")}`}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                >
                                  {capture.advisor.whatsapp}
                                </a>
                              ) : (
                                "Pendiente de configurar"
                              )}
                            </p>
                          </>
                        ) : (
                          <p>
                            Te asignaremos un asesor al revisar tu propiedad.
                          </p>
                        )}
                      </section>
                    </>
                  ) : (
                    <>
                      <ol
                        className="capture-steps"
                        aria-label="Pasos del formulario"
                      >
                        {steps.map((label, index) => (
                          <li
                            key={label}
                            className={
                              index === step
                                ? "current"
                                : index < step
                                  ? "complete"
                                  : ""
                            }
                          >
                            <button
                              disabled={busy || uploads.unfinished}
                              type="button"
                              onClick={() => setStep(index)}
                              aria-current={index === step ? "step" : undefined}
                            >
                              <span>{index + 1}</span>
                              {label}
                            </button>
                          </li>
                        ))}
                      </ol>
                      <form
                        onSubmit={(e) => {
                          e.preventDefault();
                          setError("");
                          if (uploads.unfinished) {
                            setError(
                              "Espera a que terminen los archivos o quita de la cola los que no se pudieron subir.",
                            );
                            return;
                          }
                          if (locationPending) {
                            setError(
                              "Espera a que termine la búsqueda de ubicación.",
                            );
                            return;
                          }
                          if (
                            step === 3 &&
                            (photos.length < uploadLimits.min_photos ||
                              photos.length > uploadLimits.max_photos)
                          ) {
                            setError(
                              `Agrega entre ${uploadLimits.min_photos} y ${uploadLimits.max_photos} fotos para continuar. Puedes guardar y salir mientras tanto.`,
                            );
                            return;
                          }
                          if (step < steps.length - 1) {
                            if (step === 1)
                              setData((value) => ({
                                ...value,
                                location_confirmed: true,
                              }));
                            setStep(step + 1);
                          } else
                            ensureAccount(async () => {
                              const saved = await persist();
                              const sent = await captureAction(saved, "submit");
                              setCapture(sent);
                              sessionStorage.removeItem(draftKey);
                              setNotice(
                                "Recibimos tu propiedad. Nuestro equipo revisará la información.",
                              );
                              await loadRows();
                            });
                        }}
                      >
                        <fieldset disabled={busy} className="capture-fields">
                          <legend>{steps[step]}</legend>
                          {step === 0 && (
                            <>
                              <h2>Cuéntanos, ¿qué quieres ofrecer?</h2>
                              <label>
                                Operación
                                <select
                                  value={
                                    data.is_presale
                                      ? "presale"
                                      : String(data.operation)
                                  }
                                  onChange={(e) =>
                                    setData((d) => ({
                                      ...d,
                                      operation:
                                        e.target.value === "rent"
                                          ? "rent"
                                          : "sale",
                                      is_presale: e.target.value === "presale",
                                    }))
                                  }
                                >
                                  <option value="sale">Venta</option>
                                  <option value="rent">Renta</option>
                                  <option value="presale">Preventa</option>
                                </select>
                              </label>
                              <div className="capture-grid">
                                <label>
                                  Tipo de inmueble
                                  <select
                                    value={String(data.kind)}
                                    onChange={(e) =>
                                      setData((d) => ({
                                        ...d,
                                        kind: e.target.value,
                                        subtype: "",
                                      }))
                                    }
                                  >
                                    {Object.entries(catalog.kinds).map(
                                      ([key, value]) => (
                                        <option key={key} value={key}>
                                          {value.label}
                                        </option>
                                      ),
                                    )}
                                  </select>
                                </label>
                                {!!catalog.kinds[String(data.kind)]?.subtypes
                                  .length && (
                                  <label>
                                    Subtipo
                                    <select
                                      value={String(data.subtype || "")}
                                      onChange={(e) =>
                                        update("subtype", e.target.value)
                                      }
                                    >
                                      <option value="">
                                        Selecciona un subtipo
                                      </option>
                                      {catalog.kinds[
                                        String(data.kind)
                                      ].subtypes.map((x) => (
                                        <option key={x}>{x}</option>
                                      ))}
                                    </select>
                                  </label>
                                )}
                              </div>
                              <div className="notice">
                                Sin cobro por subir tu propiedad. Para
                                comercializarla, nuestra inmobiliaria requiere
                                exclusividad. Revisaremos el inmueble antes de
                                presentarte el acuerdo.
                              </div>
                            </>
                          )}
                          {step === 1 && (
                            <>
                              <LocationFields
                                key={draftId}
                                data={data}
                                states={catalog.states}
                                location={location}
                                onLocation={setLocation}
                                onPendingChange={setLocationPending}
                                onChange={setData}
                                signedIn={!!owner?.verified}
                              />
                            </>
                          )}
                          {step === 2 && (
                            <>
                              <h2>Los detalles que hacen la diferencia</h2>
                              <div className="capture-grid">
                                {[
                                  ["bedrooms", "Recámaras"],
                                  ["bathrooms", "Baños"],
                                  ["half_bathrooms", "Medios baños"],
                                  ["parking", "Estacionamientos"],
                                  ["area_m2", "Superficie construida (m²)"],
                                  ["land_m2", "Superficie total (m²)"],
                                ].map(([key, label]) =>
                                  field(key, label, "number"),
                                )}
                                <label>
                                  Antigüedad
                                  <select
                                    value={String(data.age_type || "")}
                                    onChange={(e) =>
                                      update("age_type", e.target.value)
                                    }
                                  >
                                    <option value="">Por confirmar</option>
                                    <option value="new">A estrenar</option>
                                    <option value="years">
                                      Años de antigüedad
                                    </option>
                                    <option value="construction">
                                      En construcción
                                    </option>
                                  </select>
                                </label>
                                {data.age_type === "years" &&
                                  field("age_years", "Años", "number", true)}
                                {field(
                                  "price",
                                  "Precio solicitado",
                                  "number",
                                  true,
                                )}
                                <label>
                                  Moneda
                                  <select
                                    value={String(data.currency)}
                                    onChange={(e) =>
                                      update("currency", e.target.value)
                                    }
                                  >
                                    <option>MXN</option>
                                    <option>USD</option>
                                  </select>
                                </label>
                                {field(
                                  "maintenance",
                                  "Mantenimiento (opcional)",
                                  "number",
                                )}
                              </div>
                              {check("no_maintenance", "Sin mantenimiento")}
                              {field("title", "Título de tu inmueble")}
                              <label>
                                Descripción
                                <textarea
                                  value={String(data.description || "")}
                                  maxLength={5000}
                                  rows={5}
                                  onChange={(e) =>
                                    update("description", e.target.value)
                                  }
                                />
                              </label>
                              {check(
                                "valuation_requested",
                                "Solicitar una opinión de valor al equipo",
                              )}
                            </>
                          )}
                          {step === 3 && (
                            <>
                              <CaptureMedia
                                assets={capture?.assets || []}
                                items={uploads.items}
                                running={uploads.running}
                                disabled={busy}
                                limits={uploadLimits}
                                add={addMedia}
                                rejected={rejectedFiles}
                                retry={(id) => uploads.queue.retry(id)}
                                remove={(id) => uploads.queue.remove(id)}
                                reorder={(ids) => {
                                  if (!capture) return;
                                  void run(async () =>
                                    setCapture(
                                      await captureAction(capture, "reorder", {
                                        ids,
                                      }),
                                    ),
                                  );
                                }}
                                rotate={(asset_id) => {
                                  if (!capture) return;
                                  void run(async () =>
                                    setCapture(
                                      await captureAction(capture, "rotate", {
                                        asset_id,
                                      }),
                                    ),
                                  );
                                }}
                                deleteAsset={(id) => {
                                  void run(async () =>
                                    setCapture(
                                      await api<Capture>(
                                        `/capture/assets/${id}`,
                                        { method: "DELETE" },
                                      ),
                                    ),
                                  );
                                }}
                              />
                              {linkList("videos", "Videos (opcional)")}
                              {linkList("tours", "Recorrido 360° (opcional)")}
                            </>
                          )}
                          {step === 4 && (
                            <>
                              <h2>¿Qué más ofrece tu inmueble?</h2>
                              {Object.entries(catalog.amenities).map(
                                ([group, values]) => (
                                  <section key={group}>
                                    <h3>{group}</h3>
                                    <div className="capture-amenities">
                                      {values.map((value) => (
                                        <label
                                          key={value}
                                          className="capture-check"
                                        >
                                          <input
                                            type="checkbox"
                                            checked={(
                                              (data.amenities as string[]) || []
                                            ).includes(value)}
                                            onChange={(e) =>
                                              update(
                                                "amenities",
                                                e.target.checked
                                                  ? [
                                                      ...((data.amenities as string[]) ||
                                                        []),
                                                      value,
                                                    ]
                                                  : (
                                                      (data.amenities as string[]) ||
                                                      []
                                                    ).filter(
                                                      (x) => x !== value,
                                                    ),
                                              )
                                            }
                                          />
                                          {value}
                                        </label>
                                      ))}
                                    </div>
                                  </section>
                                ),
                              )}
                              <div className="capture-grid">
                                <label>
                                  Estado de conservación
                                  <select
                                    value={String(data.condition || "")}
                                    onChange={(e) =>
                                      update("condition", e.target.value)
                                    }
                                  >
                                    <option value="">Por confirmar</option>
                                    {catalog.conditions.map((x) => (
                                      <option key={x}>{x}</option>
                                    ))}
                                  </select>
                                </label>
                                {field("storage_rooms", "Bodegas", "number")}
                                {field("elevators", "Elevadores", "number")}
                                {field(
                                  "floors",
                                  "Niveles construidos",
                                  "number",
                                )}
                              </div>
                            </>
                          )}
                          {step === 5 && (
                            <>
                              <h2>Revisa tu solicitud</h2>
                              <div className="capture-preview">
                                {photos[0] && (
                                  <img
                                    src={photos[0].url}
                                    alt="Portada del inmueble"
                                  />
                                )}
                                <div>
                                  <p className="eyebrow">
                                    {catalog.kinds[String(data.kind)]?.label} ·{" "}
                                    {data.is_presale
                                      ? "Preventa"
                                      : data.operation === "sale"
                                        ? "Venta"
                                        : "Renta"}
                                  </p>
                                  <h3>
                                    {String(data.title || data.neighborhood)}
                                  </h3>
                                  <p>
                                    {money(
                                      String(data.price || 0),
                                      String(data.currency),
                                    )}{" "}
                                    {String(data.currency)}
                                  </p>
                                  <p>
                                    {String(data.neighborhood)},{" "}
                                    {String(data.municipality)},{" "}
                                    {String(data.state)}
                                  </p>
                                  <p>{String(data.description || "")}</p>
                                </div>
                              </div>
                              <div className="capture-grid">
                                {field("name", "Tu nombre", "text", true)}
                                <label>
                                  Relación con el inmueble
                                  <select
                                    value={String(data.relationship)}
                                    onChange={(e) =>
                                      update("relationship", e.target.value)
                                    }
                                  >
                                    <option value="owner">
                                      Soy propietario
                                    </option>
                                    <option value="representative">
                                      Soy representante autorizado
                                    </option>
                                  </select>
                                </label>
                              </div>
                              {owner && (
                                <p>
                                  Contacto privado: {owner.email} ·{" "}
                                  {owner.phone}
                                </p>
                              )}
                              {check(
                                "phone_confirmed",
                                "Confirmo que el teléfono de mi cuenta está bien escrito",
                              )}
                              <p className="notice">
                                Enviar no publica tu propiedad. Nuestro equipo
                                revisará la información y la representación.
                                Después podrás aceptar la exclusividad de seis
                                meses desde tu cuenta.
                              </p>
                            </>
                          )}
                        </fieldset>
                        <div className="capture-form-actions">
                          <button
                            className="button secondary"
                            type="button"
                            disabled={busy || uploads.unfinished || step === 0}
                            onClick={() => setStep(step - 1)}
                          >
                            ← Atrás
                          </button>
                          <button
                            className="button secondary"
                            type="button"
                            disabled={
                              busy || uploads.running || locationPending
                            }
                            onClick={() =>
                              ensureAccount(async () => {
                                if (!uploads.confirmDiscard()) return;
                                await persist();
                                await loadRows();
                                setShowForm(false);
                                setNotice(
                                  "Tu borrador está guardado. Puedes retomarlo desde tu cuenta.",
                                );
                              })
                            }
                          >
                            Guardar y salir
                          </button>
                          <button
                            className="button primary"
                            disabled={
                              busy || uploads.running || locationPending
                            }
                          >
                            {busy
                              ? "Guardando…"
                              : step === 5
                                ? "Enviar a revisión"
                                : step === 1
                                  ? "Confirmar ubicación y continuar →"
                                  : "Continuar →"}
                          </button>
                        </div>
                      </form>
                    </>
                  )}
                </section>
              )}
            </>
          )}
      </main>
    </>
  );
}
