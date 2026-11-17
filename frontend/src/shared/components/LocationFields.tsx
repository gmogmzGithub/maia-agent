"use client";
import ErrorNotice from "@/shared/components/ErrorFeedback";
import { useEffect, useId, useRef, useState } from "react";
import LocationMap from "@/shared/components/LocationMap";
import { api } from "@/shared/lib/api";
import type { CaptureData, LocationPoint } from "@/shared/lib/capture";

import {
  LocationEditing,
  isRuralLocation,
  type LocationSuggestion,
} from "@/shared/lib/location-editing";
export default function LocationFields({
  data,
  states,
  location,
  onChange,
  onLocation,
  signedIn,
  captureId,
  onPendingChange,
}: {
  captureId?: string;
  onPendingChange?: (pending: boolean) => void;
  data: CaptureData;
  states: string[];
  location: LocationPoint | null;
  onChange: (data: CaptureData) => void;
  onLocation: (point: LocationPoint | null) => void;
  signedIn: boolean;
}) {
  const callbacks = useRef({ onChange, onLocation, onPendingChange });
  callbacks.current = { onChange, onLocation, onPendingChange };
  const editorRef = useRef<LocationEditing | null>(null);
  if (!editorRef.current) {
    editorRef.current = new LocationEditing(
      { data, states, location, signedIn, captureId },
      {
        request: api,
        onData: (value) => callbacks.current.onChange(value),
        onLocation: (value) => callbacks.current.onLocation(value),
        onPending: (value) => callbacks.current.onPendingChange?.(value),
      },
    );
  }
  const editor = editorRef.current;
  const [view, setView] = useState(editor.snapshot);
  const [active, setActive] = useState(-1);
  const listId = useId();
  const { term, items, enabled, busy, note, failure } = view;
  const rural = isRuralLocation(data);
  const reference = rural && data.location_mode === "reference";
  useEffect(() => {
    const unsubscribe = editor.subscribe(setView);
    editor.start();
    return () => {
      unsubscribe();
      editor.dispose();
    };
  }, [editor]);
  useEffect(() => {
    editor.update({ data, states, location, signedIn, captureId });
  }, [editor, data, states, location, signedIn, captureId]);
  useEffect(() => setActive(-1), [items]);
  const choose = (item: LocationSuggestion) => editor.choose(item);
  const invalidate = (values: CaptureData) => editor.edit(values);
  return (
    <>
      <h2>¿Dónde está tu inmueble?</h2>
      {rural && (
        <label className="capture-check">
          <input
            type="checkbox"
            checked={reference}
            onChange={(e) => editor.referenceMode(e.target.checked)}
          />
          El inmueble no tiene dirección convencional
        </label>
      )}
      <label>
        {reference
          ? "Busca una dirección cercana (opcional)"
          : "Busca la dirección de tu inmueble"}
        <input
          value={term}
          required={!reference}
          maxLength={240}
          placeholder="Calle y número, colonia o municipio"
          autoComplete="off"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={items.length > 0}
          aria-controls={listId}
          aria-activedescendant={
            active >= 0 ? `${listId}-${active}` : undefined
          }
          onFocus={() => editor.focus(true)}
          onBlur={() => editor.focus(false)}
          onChange={(e) => {
            editor.search(e.target.value);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              editor.focus(false);
            }
            if (
              items.length &&
              (e.key === "ArrowDown" || e.key === "ArrowUp")
            ) {
              e.preventDefault();
              setActive(
                (v) =>
                  (v +
                    (e.key === "ArrowDown" ? 1 : items.length - 1) +
                    items.length) %
                  items.length,
              );
            }
            if (e.key === "Enter" && items.length) {
              e.preventDefault();
              if (active >= 0) void choose(items[active]);
            }
          }}
        />
      </label>
      {items.length > 0 && (
        <div className="address-suggestions">
          <ul id={listId} role="listbox" aria-label="Direcciones sugeridas">
            {items.map((item, index) => (
              <li
                key={item.id}
                id={`${listId}-${index}`}
                role="option"
                aria-selected={active === index}
              >
                <button
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => void choose(item)}
                >
                  {item.label}
                </button>
              </li>
            ))}
          </ul>
          <span className="maps-attribution">
            <img
              src="/google-maps-attribution.svg"
              alt="Google Maps"
              height={18}
            />
          </span>
        </div>
      )}
      {!enabled && (
        <p className="capture-hint">
          La búsqueda automática no está disponible en este momento. Puedes
          completar la dirección manualmente.
        </p>
      )}
      {!signedIn && (
        <p className="capture-hint">
          Inicia sesión para usar la búsqueda y guardar el punto.
        </p>
      )}
      {busy && <p role="status">Buscando ubicación…</p>}
      {failure && <ErrorNotice>{failure}</ErrorNotice>}
      {note && (
        <p className="notice" role="status">
          {note}
        </p>
      )}
      <div className="capture-grid">
        <label>
          Estado
          <select
            required
            value={String(data.state)}
            onChange={(e) => invalidate({ state: e.target.value })}
          >
            <option value="">Selecciona el estado</option>
            {states.map((state) => (
              <option key={state}>{state}</option>
            ))}
          </select>
        </label>
        <label>
          Municipio
          <input
            value={String(data.municipality || "")}
            maxLength={100}
            required
            onChange={(e) => invalidate({ municipality: e.target.value })}
          />
        </label>
        <label>
          Colonia{reference ? " (si tiene)" : ""}
          <input
            value={String(data.neighborhood || "")}
            maxLength={100}
            required={!reference}
            onChange={(e) => invalidate({ neighborhood: e.target.value })}
          />
        </label>
        <label>
          Fraccionamiento o subdivisión (opcional)
          <input
            value={String(data.subdivision || "")}
            maxLength={100}
            onChange={(e) => editor.edit({ subdivision: e.target.value })}
          />
        </label>
      </div>
      {reference && (
        <label>
          Referencia para localizar el inmueble
          <textarea
            value={String(data.location_reference || "")}
            maxLength={500}
            required
            onChange={(e) =>
              editor.edit({ location_reference: e.target.value })
            }
          />
        </label>
      )}
      {location?.needs_confirmation && (
        <p className="notice">
          Vuelve a señalar el punto del inmueble. Su ubicación anterior necesita
          confirmación.
        </p>
      )}
      <p>
        {(location?.latitude != null && location?.longitude != null) ||
        (data.latitude != null && data.longitude != null)
          ? "Arrastra el marcador o toca el mapa para ajustar el punto exacto."
          : "Toca el mapa para colocar el punto exacto del inmueble."}{" "}
        La dirección exacta será privada y el catálogo mostrará solo la zona,
        salvo autorización del equipo.
      </p>
      <LocationMap
        latitude={
          location?.latitude ??
          (data.latitude == null ? null : Number(data.latitude))
        }
        longitude={
          location?.longitude ??
          (data.longitude == null ? null : Number(data.longitude))
        }
        onChange={
          signedIn ? (lat, lng) => void editor.selectPoint(lat, lng) : undefined
        }
      />
      <p className="capture-hint">
        Atendemos desde Guadalajara y su zona metropolitana. El equipo revisa
        también inmuebles de todo México.
      </p>
    </>
  );
}
