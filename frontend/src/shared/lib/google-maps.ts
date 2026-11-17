export type Coordinates = { lat: number; lng: number };
type LatLng = { lat(): number; lng(): number };
type Listener = { remove(): void };
export type GoogleMap = {
  setCenter(point: Coordinates): void;
  setZoom(zoom: number): void;
  addListener(
    name: string,
    callback: (event: { latLng?: LatLng }) => void,
  ): Listener;
};
export type GoogleMarker = {
  position: Coordinates | LatLng | null;
  map: GoogleMap | null;
  addListener(
    name: string,
    callback: (event: { latLng?: LatLng }) => void,
  ): Listener;
};
export type GoogleMaps = {
  Map: new (
    container: HTMLElement,
    options: Record<string, unknown>,
  ) => GoogleMap;
  marker: {
    AdvancedMarkerElement: new (
      options: Record<string, unknown>,
    ) => GoogleMarker;
  };
  Circle: new (options: Record<string, unknown>) => {
    setCenter(point: Coordinates): void;
    setMap(map: GoogleMap | null): void;
  };
};
declare global {
  interface Window {
    google?: { maps: GoogleMaps };
    maiaMapsReady?: () => void;
    gm_authFailure?: () => void;
  }
}

let loading: Promise<GoogleMaps> | undefined;
export function loadGoogleMaps(key: string): Promise<GoogleMaps> {
  if (window.google?.maps?.marker) return Promise.resolve(window.google.maps);
  if (loading) return loading;
  loading = new Promise<GoogleMaps>((resolve, reject) => {
    const script = document.createElement("script");
    const fail = () => {
      window.dispatchEvent(new Event("maia-maps-error"));
      clearTimeout(timer);
      loading = undefined;
      script.remove();
      reject(
        new Error(
          "No pudimos cargar el mapa. Puedes completar la ubicación manualmente.",
        ),
      );
    };
    const timer = setTimeout(fail, 15000);
    window.maiaMapsReady = () => {
      clearTimeout(timer);
      if (window.google?.maps) resolve(window.google.maps);
      else fail();
    };
    window.gm_authFailure = fail;
    const query = new URLSearchParams({
      key,
      loading: "async",
      callback: "maiaMapsReady",
      libraries: "maps,marker",
      language: "es",
      region: "MX",
      v: "quarterly",
      auth_referrer_policy: "origin",
    });
    script.src = `https://maps.googleapis.com/maps/api/js?${query}`;
    script.async = true;
    script.onerror = fail;
    document.head.append(script);
  });
  return loading;
}
