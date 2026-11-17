"use client";
import ErrorNotice from "@/shared/components/ErrorFeedback";
import { useState } from "react";
import { api, ApiError, type ApiIssue } from "@/shared/lib/api";
import type { Owner } from "@/shared/lib/capture";

export default function OwnerAccount({
  onAccount,
  resetToken = "",
  onReset,
  initialMode = "register",
  purpose = "guardar tu propiedad",
}: {
  onAccount: (owner: Owner) => void;
  resetToken?: string;
  onReset: () => void;
  initialMode?: "register" | "login";
  purpose?: string;
}) {
  const [mode, setMode] = useState(resetToken ? "reset" : initialMode);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [issues, setIssues] = useState<ApiIssue[]>([]);
  const [notice, setNotice] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  return (
    <section className="owner-account">
      <p className="eyebrow">Tu cuenta en Maia</p>
      <h2>
        {mode === "register"
          ? "Crea tu cuenta"
          : mode === "login"
            ? "Bienvenido de nuevo"
            : "Recupera tu acceso"}
      </h2>
      {mode === "register" && (
        <p>
          Crea tu cuenta para {purpose} y continuar cuando quieras. Lo que ya
          escribiste se conserva. Subir tu propiedad no tiene costo.
        </p>
      )}
      {mode !== "reset" && (
        <div className="capture-segments">
          {[
            ["register", "Crear cuenta"],
            ["login", "Iniciar sesión"],
          ].map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={mode === id ? "selected" : ""}
              onClick={() => {
                setMode(id);
                setError("");
                setIssues([]);
                setNotice("");
                setShowPassword(false);
              }}
            >
              {label}
            </button>
          ))}
        </div>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const data = new FormData(e.currentTarget);
          setBusy(true);
          setError("");
          setIssues([]);
          setNotice("");
          void api<{ account?: Owner; detail?: string }>("/capture/account", {
            method: "POST",
            body: JSON.stringify({
              action: mode,
              email: data.get("email"),
              phone: data.get("phone"),
              password: data.get("password"),
              token: resetToken,
            }),
          })
            .then((result) => {
              if (result.account) onAccount(result.account);
              else {
                setNotice(result.detail || "Listo.");
                if (mode === "reset") {
                  onReset();
                  setMode("login");
                }
              }
            })
            .catch((e) => {
              setError(e.message);
              setIssues(e instanceof ApiError ? e.issues : []);
            })
            .finally(() => setBusy(false));
        }}
      >
        {mode !== "reset" && (
          <label>
            Email
            <input
              name="email"
              type="email"
              required
              autoComplete="email"
              maxLength={254}
            />
          </label>
        )}
        {mode === "register" && (
          <label>
            Teléfono
            <input
              name="phone"
              type="tel"
              required
              autoComplete="tel"
              placeholder="33 1234 5678"
            />
          </label>
        )}
        {mode !== "reset_request" && (
          <>
            <label>
              Contraseña
              <input
                name="password"
                type={showPassword ? "text" : "password"}
                required
                minLength={mode === "login" ? 1 : 8}
                autoComplete={
                  mode === "login" ? "current-password" : "new-password"
                }
              />
            </label>
            <button
              type="button"
              className="link-button"
              aria-pressed={showPassword}
              onClick={() => setShowPassword((value) => !value)}
            >
              {showPassword ? "Ocultar contraseña" : "Mostrar contraseña"}
            </button>
          </>
        )}
        {mode === "register" && (
          <p>
            Tu contacto es privado. Al crear tu cuenta recibirás un correo para
            verificar tu email antes de acceder. La inmobiliaria revisará el
            inmueble y solicitará exclusividad para comercializarlo.
          </p>
        )}
        {error && <ErrorNotice issues={issues}>{error}</ErrorNotice>}
        {notice && (
          <p className="notice" role="status">
            {notice}
          </p>
        )}
        <button className="button primary" disabled={busy}>
          {busy
            ? "Un momento…"
            : mode === "register"
              ? "Crear cuenta y continuar"
              : mode === "login"
                ? "Entrar"
                : mode === "reset"
                  ? "Cambiar contraseña"
                  : "Enviar enlace"}
        </button>
        {mode === "login" && (
          <button
            className="link-button"
            type="button"
            onClick={() => setMode("reset_request")}
          >
            Olvidé mi contraseña
          </button>
        )}
      </form>
    </section>
  );
}
