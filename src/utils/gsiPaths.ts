import { VectorTile } from "@mapbox/vector-tile";
import { PbfReader } from "pbf";

export type LatLng = [number, number];

const TILE_URL = "https://cyberjapandata.gsi.go.jp/xyz/experimental_bvmap";
const ZOOM = 16;
const SNAP_MAX_M = 60;
const GRID = 1e5; // vertices closer than ~1 m are one junction
const MAX_TILES = 9;
const PAD_M = 300;

export const distanceM = (a: LatLng, b: LatLng) =>
  Math.hypot((a[0] - b[0]) * 111_000, (a[1] - b[1]) * 111_000 * Math.cos((a[0] * Math.PI) / 180));

export const inJapan = ([lat, lng]: LatLng) => lat > 20 && lat < 46 && lng > 122 && lng < 154;

export const tileOf = ([lat, lng]: LatLng): [number, number] => {
  const n = 2 ** ZOOM;
  const sin = Math.sin((lat * Math.PI) / 180);
  return [Math.floor(((lng + 180) / 360) * n), Math.floor(((1 - Math.atanh(sin) / Math.PI) / 2) * n)];
};

const tileLatLng = (x: number, y: number, px: number, py: number, extent: number): LatLng => {
  const n = 2 ** ZOOM;
  const fy = y + py / extent;
  return [(Math.atan(Math.sinh(Math.PI * (1 - (2 * fy) / n))) * 180) / Math.PI, ((x + px / extent) / n) * 360 - 180];
};

// Road centre lines (ftCode 27xx), narrow paths included. The 22xx features are road edges and are skipped.
export function decodeTile(buffer: ArrayBuffer, x: number, y: number): LatLng[][] {
  const layer = new VectorTile(new PbfReader(new Uint8Array(buffer))).layers.road;
  if (!layer) return [];
  const lines: LatLng[][] = [];
  for (let i = 0; i < layer.length; i++) {
    const feature = layer.feature(i);
    if (feature.type !== 2 || !String(feature.properties.ftCode).startsWith("27")) continue;
    for (const line of feature.loadGeometry()) lines.push(line.map((p) => tileLatLng(x, y, p.x, p.y, layer.extent)));
  }
  return lines;
}

export interface PathGraph {
  nodes: LatLng[];
  edges: Map<number, number>[];
}

export function buildGraph(lines: LatLng[][]): PathGraph {
  const nodes: LatLng[] = [];
  const edges: Map<number, number>[] = [];
  const ids = new Map<string, number>();
  const idOf = (p: LatLng) => {
    const key = `${Math.round(p[0] * GRID)},${Math.round(p[1] * GRID)}`;
    let id = ids.get(key);
    if (id === undefined) {
      id = nodes.length;
      ids.set(key, id);
      nodes.push(p);
      edges.push(new Map());
    }
    return id;
  };
  for (const line of lines) {
    for (let i = 1; i < line.length; i++) {
      const a = idOf(line[i - 1]);
      const b = idOf(line[i]);
      if (a === b) continue;
      const w = distanceM(nodes[a], nodes[b]);
      edges[a].set(b, w);
      edges[b].set(a, w);
    }
  }
  return { nodes, edges };
}

interface Snap {
  a: number;
  b: number;
  t: number;
  point: LatLng;
  off: number;
}

function snap(graph: PathGraph, p: LatLng): Snap | null {
  const kx = Math.cos((p[0] * Math.PI) / 180);
  let best: Snap | null = null;
  graph.edges.forEach((out, a) => {
    for (const b of out.keys()) {
      if (b < a) continue;
      const [ay, ax] = graph.nodes[a];
      const [by, bx] = graph.nodes[b];
      const dx = (bx - ax) * kx;
      const dy = by - ay;
      const len2 = dx * dx + dy * dy;
      const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, (((p[1] - ax) * kx) * dx + (p[0] - ay) * dy) / len2));
      const point: LatLng = [ay + dy * t, ax + (bx - ax) * t];
      const off = distanceM(p, point);
      if (!best || off < best.off) best = { a, b, t, point, off };
    }
  });
  return best && (best as Snap).off <= SNAP_MAX_M ? best : null;
}

// Shortest walk along the graph between two free points, snapped onto the nearest path. Null when either is too far
// from any path or the two are not connected. The result starts and ends on the snapped points.
export function findPath(graph: PathGraph, from: LatLng, to: LatLng): LatLng[] | null {
  const s = snap(graph, from);
  const e = snap(graph, to);
  if (!s || !e) return null;

  const start = graph.nodes.length;
  const goal = start + 1;
  const coord = (id: number) => (id === start ? s.point : id === goal ? e.point : graph.nodes[id]);
  const extra = new Map<number, [number, number][]>();
  const link = (u: number, v: number, w: number) => {
    extra.set(u, [...(extra.get(u) ?? []), [v, w]]);
    extra.set(v, [...(extra.get(v) ?? []), [u, w]]);
  };
  for (const [id, sn] of [[start, s], [goal, e]] as const) {
    link(id, sn.a, distanceM(sn.point, graph.nodes[sn.a]));
    link(id, sn.b, distanceM(sn.point, graph.nodes[sn.b]));
  }
  if (s.a === e.a && s.b === e.b) link(start, goal, distanceM(s.point, e.point));

  const cost = new Map<number, number>([[start, 0]]);
  const prev = new Map<number, number>();
  const open: [number, number][] = [[distanceM(s.point, e.point), start]];
  const done = new Set<number>();
  while (open.length) {
    open.sort((p, q) => p[0] - q[0]);
    const [, u] = open.shift()!;
    if (done.has(u)) continue;
    if (u === goal) break;
    done.add(u);
    const around: [number, number][] = [...(graph.edges[u] ?? []), ...(extra.get(u) ?? [])];
    for (const [v, w] of around) {
      const next = cost.get(u)! + w;
      if (next < (cost.get(v) ?? Infinity)) {
        cost.set(v, next);
        prev.set(v, u);
        open.push([next + distanceM(coord(v), e.point), v]);
      }
    }
  }
  if (!prev.has(goal)) return null;

  const path: LatLng[] = [];
  for (let id: number | undefined = goal; id !== undefined; id = prev.get(id)) path.push(coord(id));
  return path.reverse();
}

const tiles = new Map<string, Promise<LatLng[][]>>();

function loadTile(x: number, y: number): Promise<LatLng[][]> {
  const key = `${x}/${y}`;
  let tile = tiles.get(key);
  if (!tile) {
    tile = fetch(`${TILE_URL}/${ZOOM}/${x}/${y}.pbf`).then(async (res) => {
      if (!res.ok) throw new Error(`HTTP_${res.status}`);
      return decodeTile(await res.arrayBuffer(), x, y);
    });
    tile.catch(() => tiles.delete(key));
    tiles.set(key, tile);
  }
  return tile;
}

// A walkable path between two points from GSI's vector tiles (Japan only), or null when the map has none.
export async function gsiPath(from: LatLng, to: LatLng): Promise<LatLng[] | null> {
  if (!inJapan(from) || !inJapan(to)) return null;
  const pad = PAD_M / 111_000;
  const lo = tileOf([Math.max(from[0], to[0]) + pad, Math.min(from[1], to[1]) - pad]);
  const hi = tileOf([Math.min(from[0], to[0]) - pad, Math.max(from[1], to[1]) + pad]);
  const wanted: [number, number][] = [];
  for (let x = lo[0]; x <= hi[0]; x++) for (let y = lo[1]; y <= hi[1]; y++) wanted.push([x, y]);
  if (wanted.length > MAX_TILES) return null;
  try {
    const lines = (await Promise.all(wanted.map(([x, y]) => loadTile(x, y)))).flat();
    return findPath(buildGraph(lines), from, to);
  } catch {
    return null;
  }
}

export const GAP_M = 25;

// Routers snap to the nearest mapped way, so a route can stop short of its stop (a trail that is not in the data). The
// missing stretch is filled from GSI's paths when they have one, otherwise it is a straight segment to the stop.
export async function closeGaps(
  route: LatLng[],
  start: LatLng,
  end: LatLng,
  bridge: (from: LatLng, to: LatLng) => Promise<LatLng[] | null> = gsiPath,
): Promise<LatLng[]> {
  if (route.length < 2) return route;
  let out = route;
  const last = out[out.length - 1];
  if (distanceM(last, end) > GAP_M) out = [...out, ...((await bridge(last, end)) ?? []), end];
  const first = out[0];
  if (distanceM(first, start) > GAP_M) out = [start, ...((await bridge(start, first)) ?? []), ...out];
  return out;
}
