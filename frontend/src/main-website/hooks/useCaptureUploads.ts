"use client";
import { useEffect, useMemo, useRef, useSyncExternalStore } from "react";
import { api } from "@/shared/lib/api";
import { uploadAsset, type Capture } from "@/shared/lib/capture";
import {
  CaptureUploadQueue,
  type UploadLimits,
} from "@/main-website/lib/capture-upload-queue";

export function useCaptureUploads(options: {
  scope: string;
  enabled: boolean;
  blocked: boolean;
  capture: Capture | null;
  limits: UploadLimits;
  prepare(): Promise<Capture>;
  changed(capture: Capture): void;
}) {
  const latest = useRef(options);
  latest.current = options;
  const queue = useMemo(() => new CaptureUploadQueue(), [options.scope]);
  const state = useSyncExternalStore(
    queue.subscribe,
    queue.getSnapshot,
    queue.getSnapshot,
  );
  const unfinished = state.items.some((item) => item.status !== "uploaded");
  useEffect(() => {
    queue.sync(options.capture?.assets || [], options.limits);
  }, [queue, options.capture, options.limits]);
  useEffect(() => {
    if (!options.enabled || options.blocked) return;
    void queue.run({
      prepare: async () => {
        const existing = latest.current.capture;
        if (existing) return api<Capture>(`/capture/requests/${existing.id}`);
        return latest.current.prepare();
      },
      upload: (id, item, uploading) =>
        uploadAsset(id, item.kind, item.file!, item.requestId, uploading),
      refresh: (id) => api<Capture>(`/capture/requests/${id}`),
      changed: (capture) => latest.current.changed(capture),
    });
  }, [queue, state, options.enabled, options.blocked]);
  useEffect(() => {
    if (!unfinished) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    const navigate = (event: MouseEvent) => {
      const anchor =
        event.target instanceof Element
          ? event.target.closest("a[href]")
          : null;
      if (
        !anchor ||
        anchor.getAttribute("href")?.startsWith("#") ||
        anchor.getAttribute("target") === "_blank" ||
        anchor.hasAttribute("download") ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      )
        return;
      if (
        !window.confirm(
          "Hay archivos sin terminar de subir. Si sales, tendrás que seleccionarlos de nuevo. ¿Quieres salir?",
        )
      ) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    window.addEventListener("beforeunload", warn);
    document.addEventListener("click", navigate, true);
    return () => {
      window.removeEventListener("beforeunload", warn);
      document.removeEventListener("click", navigate, true);
    };
  }, [unfinished]);
  // Delay disposal one microtask so React Strict Mode can reattach the same queue.
  const mounted = useRef<CaptureUploadQueue | null>(null);
  useEffect(() => {
    mounted.current = queue;
    return () => {
      mounted.current = null;
      queueMicrotask(() => {
        if (mounted.current !== queue) queue.dispose();
      });
    };
  }, [queue]);
  const confirmDiscard = () => {
    if (state.running) return false;
    if (
      unfinished &&
      !window.confirm(
        "Hay archivos sin subir. Las fotos ya guardadas se conservan. ¿Quieres salir y descartar los pendientes?",
      )
    )
      return false;
    queue.discardUnfinished();
    return true;
  };
  return { queue, ...state, unfinished, confirmDiscard };
}
