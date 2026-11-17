import Link from "next/link";
import type { MouseEventHandler } from "react";

export default function Header({
  crm = false,
  onPropertiesClick,
  className = "",
}: {
  crm?: boolean;
  onPropertiesClick?: MouseEventHandler<HTMLAnchorElement>;
  className?: string;
}) {
  return (
    <header className={`site-header ${className}`.trim()}>
      <Link href="/" className="brand" aria-label="Maia, inicio">
        <svg
          width="28"
          height="30"
          viewBox="0 0 28 30"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M3 26V12L14 3l11 9v14M10 26V16h8v10"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinejoin="round"
          />
        </svg>
        <span>
          maia<span className="brand-dot">.</span>
        </span>
      </Link>
      <nav aria-label="Navegación principal">
        {crm && (
          <Link className="crm-mobile-site" href="/">
            Ver sitio <span aria-hidden="true">↗</span>
          </Link>
        )}
        <Link href="/propietarios">Vende o renta tu propiedad</Link>
        <Link href="/#inventario" onClick={onPropertiesClick}>
          Propiedades
        </Link>
        {!crm && (
          <>
            <a href="/propietarios?account=register">Crear cuenta</a>
            <a href="/propietarios?account=login">Iniciar sesión</a>
          </>
        )}
        <Link className={crm ? "nav-active" : ""} href="/crm">
          Acceso al equipo <span aria-hidden="true">↗</span>
        </Link>
      </nav>
    </header>
  );
}
