export interface GeoPoint {
  lat: number;
  lng: number;
}

export interface GeocodeOptions {
  mapboxToken?: string;
  near?: GeoPoint; // where the route already is: ambiguous names resolve close to it
  signal?: AbortSignal;
}

const NOMINATIM_GAP_MS = 1100;
let lastNominatim = 0;

export function geocodeUrl(place: string, { mapboxToken, near }: Pick<GeocodeOptions, "mapboxToken" | "near">): string {
  const q = encodeURIComponent(place);
  if (mapboxToken) {
    const proximity = near ? `&proximity=${near.lng},${near.lat}` : "";
    return `https://api.mapbox.com/geocoding/v5/mapbox.places/${q}.json?limit=1${proximity}&access_token=${mapboxToken}`;
  }
  // Nominatim only prefers the box (not bounded), so a far-away exact match still wins over nothing.
  const view = near ? `&viewbox=${near.lng - 1},${near.lat + 1},${near.lng + 1},${near.lat - 1}` : "";
  return `https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${q}${view}`;
}

const aborted = () => new DOMException("Aborted", "AbortError");

export async function geocodePlace(place: string, opts: GeocodeOptions = {}): Promise<GeoPoint | null> {
  if (opts.signal?.aborted) throw aborted();
  if (!opts.mapboxToken) {
    const wait = lastNominatim + NOMINATIM_GAP_MS - Date.now();
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    lastNominatim = Date.now();
    if (opts.signal?.aborted) throw aborted();
  }
  try {
    const res = await fetch(geocodeUrl(place, opts), { signal: opts.signal });
    const data = await res.json();
    if (opts.mapboxToken) {
      const c = data?.features?.[0]?.center;
      return c ? { lat: c[1], lng: c[0] } : null;
    }
    const hit = data?.[0];
    return hit ? { lat: parseFloat(hit.lat), lng: parseFloat(hit.lon) } : null;
  } catch (e: any) {
    if (e?.name === "AbortError") throw e;
    console.warn("Geocoding failed for", place, e);
    return null;
  }
}
