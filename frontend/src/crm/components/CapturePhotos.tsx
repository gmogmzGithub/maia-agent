"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { Asset } from "@/shared/lib/capture";
import "@/crm/styles/capture-photos.css";

export default function CapturePhotos({ assets }: { assets: Asset[] }) {
  const images = assets.filter((asset) =>
    asset.content_type.startsWith("image/"),
  );
  const [index, setIndex] = useState<number | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const selected = index === null ? null : images[index];

  useEffect(() => {
    const element = dialog.current;
    if (selected && element && !element.open) element.showModal();
    if (!selected && element?.open) element.close();
  }, [selected]);

  const move = (direction: number) =>
    setIndex((current) =>
      current === null
        ? null
        : (current + direction + images.length) % images.length,
    );

  return (
    <section aria-label="Fotos y planos de la captación">
      <p className="capture-hint">
        Pulsa una imagen para verla completa. Puedes recorrerlas con las flechas
        del teclado.
      </p>
      <div className="capture-photo-grid">
        {images.map((asset, position) => (
          <button
            type="button"
            className="capture-photo-open"
            key={asset.id}
            aria-label={`Ampliar ${asset.kind === "photo" ? "foto" : "plano"} ${position + 1} de ${images.length}`}
            onClick={() => setIndex(position)}
          >
            <img
              src={asset.url}
              alt={
                asset.kind === "photo"
                  ? `Foto ${position + 1} del inmueble`
                  : "Plano del inmueble"
              }
            />
            <span>Ampliar ↗</span>
          </button>
        ))}
        {assets
          .filter((asset) => !asset.content_type.startsWith("image/"))
          .map((asset) => (
            <a
              key={asset.id}
              className="capture-plan-download"
              href={asset.url}
            >
              Descargar plano PDF ↗
            </a>
          ))}
      </div>
      <dialog
        ref={dialog}
        className="capture-photo-viewer"
        aria-labelledby={titleId}
        onClose={() => setIndex(null)}
        onCancel={() => setIndex(null)}
        onKeyDown={(event) => {
          if (event.key === "ArrowLeft") {
            event.preventDefault();
            move(-1);
          }
          if (event.key === "ArrowRight") {
            event.preventDefault();
            move(1);
          }
        }}
      >
        {selected && (
          <>
            <div className="capture-photo-viewer-heading">
              <h3 id={titleId}>
                {selected.kind === "photo" ? "Foto" : "Plano"}{" "}
                {(index ?? 0) + 1} de {images.length}
              </h3>
              <button
                type="button"
                autoFocus
                onClick={() => dialog.current?.close()}
                aria-label="Cerrar vista ampliada"
              >
                Cerrar ✕
              </button>
            </div>
            <img
              key={selected.id}
              className="capture-photo-full"
              src={selected.url}
              alt={
                selected.kind === "photo"
                  ? "Fotografía completa del inmueble"
                  : "Plano completo del inmueble"
              }
            />
            <div className="capture-photo-viewer-actions">
              <button
                type="button"
                disabled={images.length < 2}
                onClick={() => move(-1)}
              >
                ← Anterior
              </button>
              <a href={selected.url} target="_blank" rel="noopener noreferrer">
                Abrir imagen en otra pestaña ↗
              </a>
              <button
                type="button"
                disabled={images.length < 2}
                onClick={() => move(1)}
              >
                Siguiente →
              </button>
            </div>
          </>
        )}
      </dialog>
    </section>
  );
}
