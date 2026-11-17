"use client";
import ErrorNotice from "@/shared/components/ErrorFeedback";
import { useEffect, useRef, useState } from "react";
import { api } from "@/shared/lib/api";
import {
  loadGoogleMaps,
  type GoogleMap,
  type GoogleMaps,
  type GoogleMarker,
} from "@/shared/lib/google-maps";

export default function LocationMap({
  latitude,
  longitude,
  onChange,
  approximate = false,
}: {
  latitude: number | null;
  longitude: number | null;
  onChange?: (latitude: number, longitude: number) => void;
  approximate?: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const instance = useRef<GoogleMap | null>(null);
  const marker = useRef<GoogleMarker | null>(null);
  const circle = useRef<InstanceType<GoogleMaps["Circle"]> | null>(null);
  const maps = useRef<GoogleMaps | null>(null);
  const callback = useRef(onChange);
  callback.current = onChange;
  const position = useRef({ latitude, longitude });
  position.current = { latitude, longitude };
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    const failed = () => {
      if (!cancelled)
        setError(
          "No pudimos cargar el mapa. Puedes completar la ubicación manualmente.",
        );
    };
    window.addEventListener("maia-maps-error", failed);
    const listeners: { remove(): void }[] = [];
    void api<{ key: string; map_id: string }>("/location/map-session", {
      method: "POST",
      body: "{}",
    })
      .then(async (config) => ({
        config,
        google: await loadGoogleMaps(config.key),
      }))
      .then(({ config, google }) => {
        if (cancelled || !container.current) return;
        maps.current = google;
        const point = position.current;
        const map = new google.Map(container.current, {
          center: {
            lat: point.latitude ?? 20.67,
            lng: point.longitude ?? -103.35,
          },
          zoom: point.latitude == null ? 9 : approximate ? 13 : 17,
          mapId: config.map_id || "DEMO_MAP_ID",
          streetViewControl: false,
          mapTypeControl: false,
          fullscreenControl: true,
          gestureHandling: "cooperative",
        });
        instance.current = map;
        if (callback.current)
          listeners.push(
            map.addListener("click", (event) => {
              if (event.latLng)
                callback.current?.(event.latLng.lat(), event.latLng.lng());
            }),
          );
        setReady(true);
      })
      .catch((error: Error) => {
        if (!cancelled) setError(error.message);
      });
    return () => {
      cancelled = true;
      window.removeEventListener("maia-maps-error", failed);
      listeners.forEach((listener) => listener.remove());
      if (marker.current) marker.current.map = null;
      circle.current?.setMap(null);
      marker.current = null;
      circle.current = null;
      instance.current = null;
    };
  }, [approximate]);
  useEffect(() => {
    const map = instance.current;
    const google = maps.current;
    if (!ready || !map || !google) return;
    if (latitude == null || longitude == null) {
      if (marker.current) marker.current.map = null;
      marker.current = null;
      circle.current?.setMap(null);
      circle.current = null;
      return;
    }
    const point = { lat: latitude, lng: longitude };
    map.setCenter(point);
    map.setZoom(approximate ? 13 : 17);
    if (approximate) {
      if (!circle.current)
        circle.current = new google.Circle({
          map,
          center: point,
          radius: 900,
          fillColor: "#285a45",
          fillOpacity: 0.12,
          strokeColor: "#285a45",
          strokeWeight: 1,
        });
      else circle.current.setCenter(point);
    } else if (!marker.current) {
      const pin = new google.marker.AdvancedMarkerElement({
        map,
        position: point,
        title: "Ubicación del inmueble",
        gmpDraggable: !!callback.current,
      });
      if (callback.current)
        pin.addListener("dragend", (event) => {
          if (event.latLng)
            callback.current?.(event.latLng.lat(), event.latLng.lng());
          else if (pin.position) {
            const value = pin.position;
            callback.current?.(
              typeof value.lat === "function" ? value.lat() : value.lat,
              typeof value.lng === "function" ? value.lng() : value.lng,
            );
          }
        });
      marker.current = pin;
    } else marker.current.position = point;
  }, [latitude, longitude, ready, approximate]);
  return (
    <div className="location-map-wrap">
      {error ? (
        <ErrorNotice>
          {onChange ? error : "El mapa no está disponible en este momento."}
        </ErrorNotice>
      ) : (
        <div
          ref={container}
          className="capture-map"
          aria-label={
            onChange
              ? "Selecciona la ubicación en el mapa"
              : "Ubicación publicada"
          }
        />
      )}
      {!ready && !error && (
        <p className="capture-hint" role="status">
          Cargando mapa…
        </p>
      )}
    </div>
  );
}
