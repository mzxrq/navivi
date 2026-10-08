import { recordedLegElevation, sampleIndexes, elevationAlongPath } from "./elevation";
import type { LatLon } from "./gpxTrack";

/** One decoded Terrain-RGB tile: metres above sea level, row-major, `size` x `size`. */
export interface TerrainTile {
  size: number;
  heights: Float32Array;
}

export type TileLoader = (z: number, x: number, y: number) => Promise<TerrainTile | null>;

const MAX_TILES = 48;
const MAX_ZOOM = 14;
const MIN_ZOOM = 9;

/** Mapbox Terrain-RGB: height = -10000 + (R*65536 + G*256 + B) * 0.1 */
export const decodeTerrainRgb = (r: number, g: number, b: number): number => -10000 + (r * 65536 + g * 256 + b) * 0.1;

export function tileCoords(lat: number, lon: number, z: number): { x: number; y: number; px: number; py: number } {
  const n = 2 ** z;
  const latRad = (Math.max(-85.0511, Math.min(85.0511, lat)) * Math.PI) / 180;
  const fx = ((lon + 180) / 360) * n;
  const fy = ((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) * n;
  const x = Math.min(n - 1, Math.max(0, Math.floor(fx)));
  const y = Math.min(n - 1, Math.max(0, Math.floor(fy)));
  return { x, y, px: fx - x, py: fy - y };
}

/** The sharpest zoom whose tiles for these points stay under the tile budget (long routes use coarser tiles). */
export function pickZoom(points: LatLon[]): number {
  for (let z = MAX_ZOOM; z > MIN_ZOOM; z--) {
    const seen = new Set<string>();
    for (const p of points) {
      const t = tileCoords(p[0], p[1], z);
      seen.add(`${t.x}/${t.y}`);
      if (seen.size > MAX_TILES) break;
    }
    if (seen.size <= MAX_TILES) return z;
  }
  return MIN_ZOOM;
}

/** Elevation (m) of each point, or null where its tile could not be loaded. Tiles are loaded once each. */
export async function sampleTerrain(points: LatLon[], load: TileLoader): Promise<(number | null)[]> {
  if (points.length === 0) return [];
  const z = pickZoom(points);
  const tiles = new Map<string, Promise<TerrainTile | null>>();
  const get = (x: number, y: number) => {
    const key = `${x}/${y}`;
    if (!tiles.has(key)) tiles.set(key, load(z, x, y).catch(() => null));
    return tiles.get(key)!;
  };
  return Promise.all(
    points.map(async (p) => {
      const t = tileCoords(p[0], p[1], z);
      const tile = await get(t.x, t.y);
      if (!tile) return null;
      const col = Math.min(tile.size - 1, Math.floor(t.px * tile.size));
      const row = Math.min(tile.size - 1, Math.floor(t.py * tile.size));
      const v = tile.heights[row * tile.size + col];
      return Number.isFinite(v) ? v : null;
    }),
  );
}

const tileCache = new Map<string, TerrainTile>();
const TILE_CACHE_MAX = 120;

/** Loads `mapbox.terrain-rgb` tiles with fetch + canvas; finished tiles are kept for the session so autosaves reuse them. */
export function mapboxTileLoader(token: string): TileLoader {
  return async (z, x, y) => {
    const key = `${z}/${x}/${y}`;
    const cached = tileCache.get(key);
    if (cached) return cached;
    const res = await fetch(`https://api.mapbox.com/v4/mapbox.terrain-rgb/${z}/${x}/${y}.pngraw?access_token=${encodeURIComponent(token)}`);
    if (!res.ok) return null;
    const bitmap = await createImageBitmap(await res.blob());
    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return null;
    ctx.drawImage(bitmap, 0, 0);
    const { data } = ctx.getImageData(0, 0, bitmap.width, bitmap.height);
    const heights = new Float32Array(bitmap.width * bitmap.height);
    for (let i = 0; i < heights.length; i++) heights[i] = decodeTerrainRgb(data[i * 4], data[i * 4 + 1], data[i * 4 + 2]);
    const tile = { size: bitmap.width, heights };
    if (tileCache.size >= TILE_CACHE_MAX) tileCache.delete(tileCache.keys().next().value as string);
    tileCache.set(key, tile);
    return tile;
  };
}

interface SegmentLike {
  positions: number[][];
  mode: string;
}
interface StopLike {
  lat: number;
  lng: number;
  isStopBy?: boolean;
  connectToRoute?: boolean;
  customRoute?: number[][];
  customRouteEle?: (number | null)[];
}

/** Elevation per point of every route segment, or null for a segment nothing could be found for.
 *  Recorded GPX elevation wins; the rest is looked up from terrain tiles (a coarse subset, then interpolated). */
export async function segmentElevations(
  segments: SegmentLike[],
  waypoints: StopLike[],
  load: TileLoader,
): Promise<(number[] | null)[]> {
  const routed = waypoints.filter((wp) => !wp.isStopBy || wp.connectToRoute);
  return Promise.all(
    segments.map(async (seg, i): Promise<number[] | null> => {
      const from = routed[i];
      const to = routed[i + 1];
      if (from && to && seg.mode === "draw") {
        const recorded = recordedLegElevation(seg.positions, from, to, from.customRoute, from.customRouteEle);
        if (recorded) return recorded;
      }
      if (seg.positions.length < 2 || seg.mode === "calculating") return null;
      const idx = sampleIndexes(seg.positions);
      const sampled = await sampleTerrain(idx.map((k) => seg.positions[k] as LatLon), load);
      if (sampled.some((v) => v === null)) return null;
      return elevationAlongPath(seg.positions, idx.map((k) => seg.positions[k]), sampled as number[]);
    }),
  );
}
