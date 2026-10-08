export interface GeoPoint {
  lat: number;
  lng: number;
  country?: string; // lower-case ISO code, when the service said
  weak?: boolean; // the service matched the name poorly (Mapbox falls back to the nearest neighborhood)
}

const WEAK_BELOW = 0.75; // Mapbox relevance

export interface Bounds {
  west: number;
  south: number;
  east: number;
  north: number;
}

export interface GeocodeOptions {
  mapboxToken?: string;
  near?: GeoPoint; // where the route already is: ambiguous names resolve close to it
  country?: string;
  bounds?: Bounds; // results outside are never returned
  signal?: AbortSignal;
}

export const geocodeSettings = { nominatimGapMs: 1100 };
let lastNominatim = 0;

export const boundsAround = (p: GeoPoint, degrees: number): Bounds => ({ west: p.lng - degrees, south: p.lat - degrees, east: p.lng + degrees, north: p.lat + degrees });

export function distanceKm(a: GeoPoint, b: GeoPoint): number {
  const rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad;
  const dLng = (b.lng - a.lng) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLng / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(h));
}

export function geocodeUrl(place: string, { mapboxToken, near, country, bounds }: Omit<GeocodeOptions, "signal">): string {
  const q = encodeURIComponent(place);
  if (mapboxToken) {
    const proximity = near ? `&proximity=${near.lng},${near.lat}` : "";
    const within = country ? `&country=${country}` : "";
    const box = bounds ? `&bbox=${bounds.west},${bounds.south},${bounds.east},${bounds.north}` : "";
    return `https://api.mapbox.com/geocoding/v5/mapbox.places/${q}.json?limit=1${proximity}${within}${box}&access_token=${mapboxToken}`;
  }
  // Without a hard box Nominatim only prefers the area, so a far-away exact match still wins over nothing.
  const around = bounds ?? (near ? boundsAround(near, 1) : undefined);
  const view = around ? `&viewbox=${around.west},${around.north},${around.east},${around.south}${bounds ? "&bounded=1" : ""}` : "";
  const within = country ? `&countrycodes=${country}` : "";
  return `https://nominatim.openstreetmap.org/search?format=json&limit=${near ? 5 : 1}&addressdetails=1&q=${q}${view}${within}`;
}

const aborted = () => new DOMException("Aborted", "AbortError");

async function nominatimTurn(signal?: AbortSignal) {
  const wait = lastNominatim + geocodeSettings.nominatimGapMs - Date.now();
  if (wait > 0) await new Promise((r) => setTimeout(r, wait));
  lastNominatim = Date.now();
  if (signal?.aborted) throw aborted();
}

async function ask(place: string, opts: GeocodeOptions, token: string | undefined): Promise<GeoPoint | null> {
  if (opts.signal?.aborted) throw aborted();
  if (!token) await nominatimTurn(opts.signal);
  try {
    const res = await fetch(geocodeUrl(place, { ...opts, mapboxToken: token }), { signal: opts.signal });
    const data = await res.json();
    if (token) {
      const feature = data?.features?.[0];
      if (!feature?.center) return null;
      const country = feature.context?.find((c: any) => String(c.id).startsWith("country"))?.short_code;
      return {
        lat: feature.center[1],
        lng: feature.center[0],
        country: typeof country === "string" ? country.toLowerCase() : undefined,
        weak: typeof feature.relevance === "number" && feature.relevance < WEAK_BELOW,
      };
    }
    // Several places share a name: the one closest to where the route already is, not the one OpenStreetMap ranks first.
    const hits: any[] = Array.isArray(data) ? data : [];
    const here = opts.near;
    const hit = here ? [...hits].sort((a, b) => distanceKm(here, { lat: +a.lat, lng: +a.lon }) - distanceKm(here, { lat: +b.lat, lng: +b.lon }))[0] : hits[0];
    return hit ?{ lat: parseFloat(hit.lat), lng: parseFloat(hit.lon), country: hit.address?.country_code } : null;
  } catch (e: any) {
    if (e?.name === "AbortError") throw e;
    console.warn("Geocoding failed for", place, e);
    return null;
  }
}

// A confident Mapbox hit first; otherwise OpenStreetMap, which knows many small shrines, passes and trails that Mapbox
// does not and only returns real name matches; a weak Mapbox hit is kept only when nothing else answered.
export async function geocodePlace(place: string, opts: GeocodeOptions = {}): Promise<GeoPoint | null> {
  const mapbox = opts.mapboxToken ? await ask(place, opts, opts.mapboxToken) : null;
  if (mapbox && !mapbox.weak) return mapbox;
  return (await ask(place, opts, undefined)) ?? mapbox;
}

// ── Finding a whole route ──

const TOLERANCE_KM = 0.05; // a hit this close to the region's own point is the region itself, not the place
const DEFAULT_HOP_KM = 40; // the next stop of a route is searched this close to its neighbor
const KM_PER_DEGREE = 111;
const REGION_DEGREES = 0.8;
const MAX_ROUGH = 6; // places looked up unbounded to find the route's area; the median of a spread sample is enough
const MAX_NAMES = 4; // spellings tried per place: every one is a rate-limited request when it misses

// The area most names end with: "Sainen-ji Temple, Wakayama" -> "Wakayama".
export function regionOf(places: string[]): string | null {
  // "Sainen-ji, Wakayama, Japan": the last two parts name the area, the country alone is too wide to anchor a search box.
  const shared = (parts: number): string | null => {
    const counts = new Map<string, number>();
    for (const p of places) {
      const segments = p.split(",").map((s) => s.trim());
      if (segments.length <= parts) continue;
      const tail = segments.slice(-parts).join(", ");
      if (tail) counts.set(tail, (counts.get(tail) ?? 0) + 1);
    }
    const [best, n] = [...counts.entries()].sort((a, b) => b[1] - a[1])[0] ?? [];
    return best && n >= Math.min(2, places.length) && n * 2 >= places.length ? best : null;
  };
  return shared(2) ?? shared(1);
}

// Spellings of one name a search index is likely to know: abbreviations expanded, notes dropped, generic suffixes cut.
export function nameVariants(name: string): string[] {
  const expanded = name.replace(/\bSta\./gi, "Station").replace(/\bMt\./gi, "Mount").replace(/\bSt\./gi, "Saint");
  const plain = expanded.replace(/\([^)]*\)|（[^）]*）/g, "").replace(/#\d+/g, "").replace(/\s+/g, " ").trim();
  const core = plain.replace(/\s+(?:Temple|Shrine|Pass|Park|Castle|Trail|Falls|Pond|Lake)$/i, "").replace(/-(?:toge|jinja|dake|yama)$/i, "").trim();
  return [name, expanded, plain, core].filter((n, i, all) => n && all.indexOf(n) === i);
}

export const stripRegion =(place: string, region: string | null) => (region && place.endsWith(`, ${region}`) ? place.slice(0, -(region.length + 2)).trim() : place);

export function medianPoint(points: GeoPoint[]): GeoPoint {
  const middle = (values: number[]) => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];
  return { lat: middle(points.map((p) => p.lat)), lng: middle(points.map((p) => p.lng)) };
}

export type Lookup = (place: string, constraints: Omit<GeocodeOptions, "signal">) => Promise<GeoPoint | null>;
// Local names for places whose search failed (the services index most small places under their own script).
export type Rename = (names: string[], region: string | null) => Promise<Record<string, string>>;

export interface RouteGeocode {
  // in the order of `places`; shortName is the place without the region ("Sainen-ji, Wakayama" -> "Sainen-ji"), localName its name on local maps
  found: { name: string; shortName: string; localName?: string; point: GeoPoint; uncertain: boolean }[];
  failed: string[];
}

const SPIKE_MIN_KM = 15; // a detour shorter than this is ordinary routing, not a wrong namesake

// Indexes of found points that sit far off the line between the found points before and after them.
export function spikes(points: (GeoPoint | null)[]): number[] {
  const out: number[] = [];
  const have = points.map((p, i) => (p ? i : -1)).filter((i) => i >= 0);
  for (let k = 1; k < have.length - 1; k++) {
    const [a, b, c] = [points[have[k - 1]]!, points[have[k]]!, points[have[k + 1]]!];
    const direct = distanceKm(a, c);
    if (distanceKm(a, b) + distanceKm(b, c) - direct > Math.max(SPIKE_MIN_KM, 4 * direct)) out.push(have[k]);
  }
  return out;
}

// Small places must resolve inside the area the route is in, so names shared with famous places elsewhere do not win.
// The region (or, without one, where most places land) anchors the search; each stop is then searched close to the stop
// next to it. A miss is retried under its local name; what is still unknown is placed between its neighbors and marked
// uncertain, so a stop never lands on a famous namesake far away.
export async function geocodeRoute(
  places: string[],
  opts: { mapboxToken?: string; signal?: AbortSignal; onProgress?: (done: number, name: string) => void; lookup?: Lookup; rename?: Rename; hopKm?: number },
): Promise<RouteGeocode> {
  const { mapboxToken, signal, onProgress } = opts;
  const hopDegrees = (opts.hopKm ?? DEFAULT_HOP_KM) / KM_PER_DEGREE;
  const lookup: Lookup = opts.lookup ?? ((place, c) => geocodePlace(place, { ...c, mapboxToken, signal }));
  const region = regionOf(places);

  let anchor: GeoPoint | null = region ? await lookup(region, {}) : null;
  const anchorIsRegion = anchor !== null;
  if (!anchor) {
    const rough: GeoPoint[] = [];
    const step = Math.max(1, Math.ceil(places.length / MAX_ROUGH));
    const sample = places.filter((_, i) => i % step === 0);
    for (const place of [...sample, ...places.filter((p) => !sample.includes(p))]) {
      if (rough.length > 0 && !sample.includes(place)) break;
      const hit = await lookup(place, {});
      if (hit) rough.push(hit);
    }
    if (rough.length === 0) return { found: [], failed: [...places] };
    anchor = { ...medianPoint(rough), country: rough.find((p) => p.country)?.country };
  }
  const center: GeoPoint = anchor;

  const points: (GeoPoint | null)[] = places.map(() => null);
  const uncertain = new Set<number>();
  const neighbor = (i: number): GeoPoint | null => {
    for (let d = 1; d < places.length; d++) {
      const hit = points[i - d] ?? points[i + d];
      if (hit) return hit;
    }
    return null;
  };

  // Names to try for one place, in a box around its neighbor (or the anchor); a hit that is just the region itself is a miss.
  const search = async (i: number, names: string[], tight?: { at: GeoPoint; degrees: number }): Promise<GeoPoint | null> => {
    const around = tight?.at ?? neighbor(i) ?? center;
    const size = tight?.degrees ?? (around === center ? REGION_DEGREES : hopDegrees);
    for (const name of names) {
      const hit = await lookup(name, { near: around, country: center.country, bounds: boundsAround(around, size) });
      if (!hit || hit.weak) continue;
      if (anchorIsRegion && places[i] !== region && distanceKm(hit, center) <= TOLERANCE_KM) continue;
      return hit;
    }
    return null;
  };
  const namesFor = (place: string, local?: string) =>
    [local, ...nameVariants(stripRegion(place, region)), place].filter((n, k, all): n is string => !!n && all.indexOf(n) === k).slice(0, MAX_NAMES);

  // In Japan the search indexes know small places only under their Japanese names (English spellings find nothing or a namesake
  // elsewhere), so there the local names are asked for up front and tried first; elsewhere only a miss is retried under one.
  const localFirst = !!opts.rename && center.country === "jp";
  const locals: Record<string, string> = localFirst ? await opts.rename!(places.map((p) => stripRegion(p, region)), region).catch(() => ({})) : {};
  const localOf = (place: string) => locals[stripRegion(place, region)];

  for (const [i, place] of places.entries()) {
    if (signal?.aborted) throw aborted();
    onProgress?.(i, place);
    points[i] = await search(i, namesFor(place, localOf(place)));
  }

  // A stop far off the line between the stops on either side of it is a namesake elsewhere ("西念寺" is a common name): the
  // stops are in travel order, so it is searched again close to that line and, failing that, placed between its neighbors.
  for (const i of spikes(points)) {
    if (signal?.aborted) throw aborted();
    const [before, after] = [points.slice(0, i).reverse().find(Boolean)!, points.slice(i + 1).find(Boolean)!];
    const gap = distanceKm(before, after);
    const mid = { lat: (before.lat + after.lat) / 2, lng: (before.lng + after.lng) / 2, country: before.country };
    points[i] = await search(i, namesFor(places[i], localOf(places[i])), { at: mid, degrees: Math.max(gap, SPIKE_MIN_KM) / KM_PER_DEGREE });
  }

  let missing = places.map((_, i) => i).filter((i) => !points[i]);
  if (!localFirst && missing.length > 0 && opts.rename) {
    Object.assign(locals, await opts.rename(missing.map((i) => stripRegion(places[i], region)), region).catch(() => ({})));
    for (const i of missing) {
      if (signal?.aborted) throw aborted();
      const renamed = localOf(places[i]);
      if (renamed) points[i] = await search(i, namesFor(places[i], renamed));
    }
  }

  // What no service knows by name sits between its neighbors on the route: the stops are in travel order.
  missing = places.map((_, i) => i).filter((i) => !points[i]);
  for (const i of missing) {
    const before = [...points.keys()].filter((k) => k < i && points[k]).pop();
    const after = [...points.keys()].find((k) => k > i && points[k]);
    const a = before !== undefined ? points[before]! : null;
    const b = after !== undefined ? points[after]! : null;
    if (a && b) {
      const t = (i - before!) / (after! - before!);
      points[i] = { lat: a.lat + (b.lat - a.lat) * t, lng: a.lng + (b.lng - a.lng) * t, country: a.country };
    } else if (a || b) {
      points[i] = { lat: (a ?? b)!.lat + 0.002, lng: (a ?? b)!.lng + 0.002, country: (a ?? b)!.country };
    } else continue;
    uncertain.add(i);
  }

  const found: RouteGeocode["found"] = [];
  const failed: string[] = [];
  places.forEach((name, i) => {
    const point = points[i];
    if (point) found.push({ name, shortName: stripRegion(name, region), localName: localOf(name), point, uncertain: uncertain.has(i) });
    else failed.push(name);
  });
  return { found, failed };
}
