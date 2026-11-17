"use client";
import ErrorNotice from "@/shared/components/ErrorFeedback";
import { useEffect, useRef, useState } from "react";
import type { Asset } from "@/shared/lib/capture";
import type {
  MediaKind,
  UploadItem,
  UploadLimits,
} from "@/main-website/lib/capture-upload-queue";

const DRAG_ASSET = "application/x-maia-capture-asset";
const statusLabels = {
  queued: "En espera",
  preparing: "Preparando archivo…",
  uploading: "Subiendo…",
  uploaded: "Lista",
  failed: "No se pudo subir",
};
const hasFiles = (transfer: DataTransfer) =>
  Array.from(transfer.types).includes("Files");

type Props = {
  assets: Asset[];
  items: UploadItem[];
  running: boolean;
  disabled: boolean;
  limits: UploadLimits;
  add(files: File[], kind: MediaKind): void;
  retry(id: string): void;
  remove(id: string): void;
  reorder(ids: string[]): void;
  rotate(id: string): void;
  deleteAsset(id: string): void;
  rejected: { name: string; reason: string }[];
};

function MediaSection({ kind, ...props }: Props & { kind: MediaKind }) {
  const input = useRef<HTMLInputElement>(null);
  const depth = useRef(0);
  const [over, setOver] = useState(false);
  const photos = kind === "photo";
  const saved = props.assets.filter((asset) => asset.kind === kind);
  const waiting = props.items.filter(
    (item) => item.kind === kind && item.status !== "uploaded",
  );
  const locked = props.disabled || props.running;
  const move = (source: string, target: string) => {
    if (locked || source === target) return;
    const sourceAsset = saved.find((asset) => asset.id === source);
    if (!sourceAsset || !saved.some((asset) => asset.id === target)) return;
    const ids = props.assets
      .map((asset) => asset.id)
      .filter((id) => id !== source);
    ids.splice(ids.indexOf(target), 0, source);
    props.reorder(ids);
  };
  return (
    <section
      className={`capture-media-section${over ? " is-dragging" : ""}`}
      aria-label={photos ? "Fotos del inmueble" : "Planos del inmueble"}
      onDragEnter={(event) => {
        if (hasFiles(event.dataTransfer)) {
          event.preventDefault();
          depth.current++;
          if (!props.disabled) setOver(true);
        }
      }}
      onDragOver={(event) => {
        if (hasFiles(event.dataTransfer)) {
          event.preventDefault();
          event.dataTransfer.dropEffect = props.disabled ? "none" : "copy";
        }
      }}
      onDragLeave={(event) => {
        if (hasFiles(event.dataTransfer) && --depth.current <= 0) {
          depth.current = 0;
          setOver(false);
        }
      }}
      onDrop={(event) => {
        if (!hasFiles(event.dataTransfer)) return;
        event.preventDefault();
        event.stopPropagation();
        depth.current = 0;
        setOver(false);
        if (!props.disabled)
          props.add(Array.from(event.dataTransfer.files), kind);
      }}
    >
      <h3>{photos ? "Fotos" : "Planos (opcional)"}</h3>
      <div className="capture-upload capture-dropzone">
        <span className="capture-drop-icon" aria-hidden="true">
          ↑
        </span>
        <strong>
          {photos ? "Arrastra tus fotos aquí" : "Arrastra tus planos aquí"}
        </strong>
        <span>o</span>
        <button
          className="button secondary"
          type="button"
          disabled={props.disabled}
          onClick={() => input.current?.click()}
        >
          {photos ? "Seleccionar fotos" : "Seleccionar planos"}
        </button>
        <input
          ref={input}
          type="file"
          multiple
          className="capture-file-input"
          aria-label={
            photos
              ? "Seleccionar archivos de fotos"
              : "Seleccionar archivos de planos"
          }
          disabled={props.disabled}
          tabIndex={-1}
          accept={
            photos
              ? "image/*,.heic,.heif"
              : "image/*,.heic,.heif,application/pdf"
          }
          onChange={(event) => {
            const files = Array.from(event.target.files || []);
            event.target.value = "";
            if (files.length) props.add(files, kind);
          }}
        />
        <small>
          {photos
            ? `De ${props.limits.min_photos} a ${props.limits.max_photos} fotos. También HEIC; nosotros las optimizamos.`
            : `Hasta ${props.limits.max_plans} planos. Imágenes o PDF de hasta 20 MB.`}
        </small>
      </div>
      <p className="capture-media-count" role="status">
        {saved.length} {photos ? "fotos guardadas" : "planos guardados"}
        {waiting.length > 0 && ` · ${waiting.length} por completar`}
      </p>
      <div className="capture-photo-grid">
        {saved.map((asset, index) => (
          <article
            key={asset.id}
            draggable={!locked}
            onDragStart={(event) => {
              if (locked) {
                event.preventDefault();
                return;
              }
              event.dataTransfer.setData(DRAG_ASSET, asset.id);
              event.dataTransfer.effectAllowed = "move";
            }}
            onDragOver={(event) => {
              if (
                !locked &&
                Array.from(event.dataTransfer.types).includes(DRAG_ASSET)
              )
                event.preventDefault();
            }}
            onDrop={(event) => {
              if (hasFiles(event.dataTransfer)) return; // Bubble file drops to this section's upload queue.
              const source = event.dataTransfer.getData(DRAG_ASSET);
              if (source) {
                event.preventDefault();
                event.stopPropagation();
                move(source, asset.id);
              }
            }}
          >
            {asset.content_type === "application/pdf" ? (
              <a
                href={asset.url}
                target="_blank"
                rel="noopener noreferrer"
                className="capture-media-placeholder"
              >
                Ver plano PDF ↗
              </a>
            ) : (
              <img
                src={asset.url}
                alt={
                  photos
                    ? `Foto ${index + 1} del inmueble`
                    : `Plano ${index + 1}`
                }
                draggable={false}
                loading="lazy"
              />
            )}
            <small>
              {photos && index === 0
                ? "Portada"
                : photos
                  ? `Foto ${index + 1}`
                  : `Plano ${index + 1}`}{" "}
              · {Math.round(asset.size / 1024)} KB · Lista
            </small>
            <div>
              {photos && index !== 0 && (
                <button
                  type="button"
                  disabled={locked}
                  onClick={() => move(asset.id, saved[0].id)}
                >
                  Portada
                </button>
              )}
              {index > 0 && (
                <button
                  type="button"
                  disabled={locked}
                  aria-label={`Mover ${photos ? "foto" : "plano"} ${index + 1} antes`}
                  onClick={() => move(asset.id, saved[index - 1].id)}
                >
                  ← Mover
                </button>
              )}
              {index < saved.length - 1 && (
                <button
                  type="button"
                  disabled={locked}
                  aria-label={`Mover ${photos ? "foto" : "plano"} ${index + 1} después`}
                  onClick={() => move(saved[index + 1].id, asset.id)}
                >
                  Mover →
                </button>
              )}
              {asset.content_type === "image/webp" && (
                <button
                  type="button"
                  disabled={locked}
                  onClick={() => props.rotate(asset.id)}
                >
                  Girar ↻
                </button>
              )}
              <button
                type="button"
                disabled={locked}
                onClick={() => props.deleteAsset(asset.id)}
              >
                Eliminar
              </button>
            </div>
          </article>
        ))}
        {waiting.map((item) => (
          <article
            key={item.requestId}
            className={`capture-upload-item is-${item.status}`}
          >
            <div className="capture-media-placeholder" aria-hidden="true">
              {item.status === "failed" ? "!" : "▧"}
            </div>
            <small className="capture-media-name">{item.name}</small>
            <p role="status">{statusLabels[item.status]}</p>
            {item.error && <ErrorNotice retry={() => props.retry(item.requestId)}>{item.name}: {item.error}</ErrorNotice>}
            <div>
              {item.status === "failed" && (
                <button
                  type="button"
                  disabled={props.disabled}
                  onClick={() => props.retry(item.requestId)}
                >
                  Reintentar
                </button>
              )}
              {["queued", "failed"].includes(item.status) && (
                <button
                  type="button"
                  disabled={props.disabled}
                  onClick={() => props.remove(item.requestId)}
                >
                  Quitar de la cola
                </button>
              )}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

export default function CaptureMedia(props: Props) {
  useEffect(() => {
    const preventOpen = (event: DragEvent) => {
      if (event.dataTransfer && hasFiles(event.dataTransfer))
        event.preventDefault();
    };
    window.addEventListener("dragover", preventOpen);
    window.addEventListener("drop", preventOpen);
    return () => {
      window.removeEventListener("dragover", preventOpen);
      window.removeEventListener("drop", preventOpen);
    };
  }, []);
  return (
    <>
      <h2>Muéstranos tu propiedad</h2>
      {props.running && (
        <p role="status">
          Estamos subiendo tus archivos. Puedes agregar más mientras tanto.
        </p>
      )}
      <MediaSection {...props} kind="photo" />
      <MediaSection {...props} kind="plan" />
      {props.rejected.length > 0 && (
        <ErrorNotice>
          <p>Estos archivos no se añadieron:</p>
          <ul>
            {props.rejected.map((item, index) => (
              <li key={index}>
                {item.name}: {item.reason}
              </li>
            ))}
          </ul>
        </ErrorNotice>
      )}
    </>
  );
}
