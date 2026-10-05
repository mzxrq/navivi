import { VectorTile } from "@mapbox/vector-tile";
import { PbfReader } from "pbf";

export type LatLng = [number, number];

const TILE_URL = "https://cyberjapandata.gsi.go.jp/xyz/experimental_bvmap";
const ZOOM = 16;
const SNAP_MAX_M = 60;
const GRID = 1e5; // vertices closer than ~1 m are one junction
const MAX_TILES = 9;
const MAX_CACHED_TILES = 36;
const MAX_CACHED_GRAPHS = 6;
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

class MinHeap {
  private keys: number[] = [];
  private items: number[] = [];

  get size() {
    return this.keys.length;
  }

  push(key: number, item: number) {
    let i = this.keys.length;
    this.keys.push(key);
    this.items.push(item);
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (this.keys[parent] <= key) break;
      this.move(parent, i);
      i = parent;
    }
    this.keys[i] = key;
    this.items[i] = item;
  }

  pop(): number | undefined {
    const n = this.keys.length;
    if (!n) return undefined;
    const top = this.items[0];
    const key = this.keys.pop()!;
    const item = this.items.pop()!;
    if (n > 1) {
      let i = 0;
      for (;;) {
        let child = 2 * i + 1;
        if (child >= n - 1) break;
        if (child + 1 < n - 1 && this.keys[child + 1] < this.keys[child]) child++;
        if (this.keys[child] >= key) break;
        this.move(child, i);
        i = child;
      }
      this.keys[i] = key;
      this.items[i] = item;
    }
    return top;
  }

  private move(from: number, to: number) {
    this.keys[to] = this.keys[from];
    this.items[to] = this.items[from];
  }
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
  const open = new MinHeap();
  open.push(distanceM(s.point, e.point), start);
  const done = new Set<number>();
  while (open.size) {
    const u = open.pop()!;
    if (done.has(u)) continue;
    if (u === goal) break;
    done.add(u);
    const around: [number, number][] = [...(graph.edges[u] ?? []), ...(extra.get(u) ?? [])];
    for (const [v, w] of around) {
      const next = cost.get(u)! + w;
      if (next < (cost.get(v) ?? Infinity)) {
        cost.set(v, next);
        prev.set(v, u);
        open.push(next + distanceM(coord(v), e.point), v);
      }
    }
  }
  if (!prev.has(goal)) return null;

  const path: LatLng[] = [];
  for (let id: number | undefined = goal; id !== undefined; id = prev.get(id)) path.push(coord(id));
  return path.reverse();
}

const tiles = new Map<string, Promise<LatLng[][]>>();
const graphs = new Map<string, PathGraph>();

// Oldest-used first; the Map's insertion order is the recency order.
function remember<V>(cache: Map<string, V>, key: string, value: V, max: number) {
  cache.delete(key);
  cache.set(key, value);
  for (const old of cache.keys()) {
    if (cache.size <= max) break;
    cache.delete(old);
  }
}

function loadTile(x: number, y: number): Promise<LatLng[][]> {
  const key = `${x}/${y}`;
  let tile = tiles.get(key);
  if (!tile) {
    tile = fetch(`${TILE_URL}/${ZOOM}/${x}/${y}.pbf`).then(async (res) => {
      if (!res.ok) throw new Error(`HTTP_${res.status}`);
      return decodeTile(await res.arrayBuffer(), x, y);
    });
    tile.catch(() => tiles.delete(key));
  }
  remember(tiles, key, tile, MAX_CACHED_TILES);
  return tile;
}

async function graphFor(wanted: [number, number][]): Promise<PathGraph> {
  const key = wanted.map(([x, y]) => `${x}/${y}`).join(",");
  const cached = graphs.get(key);
  if (cached) {
    remember(graphs, key, cached, MAX_CACHED_GRAPHS);
    return cached;
  }
  const lines = (await Promise.all(wanted.map(([x, y]) => loadTile(x, y)))).flat();
  const graph = buildGraph(lines);
  remember(graphs, key, graph, MAX_CACHED_GRAPHS);
  return graph;
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
    return findPath(await graphFor(wanted), from, to);
  } catch {
    return null;
  }
}

export const GAP_M = 25;

type Bridge = (from: LatLng, to: LatLng) => Promise<LatLng[] | null>;

const pathLength = (path: LatLng[]) => path.slice(1).reduce((sum, p, i) => sum + distanceM(path[i], p), 0);

// The whole walk on GSI paths, through every stop in order; null when any hop has no path.
async function throughStops(stops: LatLng[], bridge: Bridge): Promise<LatLng[] | null> {
  const out: LatLng[] = [stops[0]];
  for (let i = 1; i < stops.length; i++) {
    const hop = await bridge(stops[i - 1], stops[i]);
    if (!hop) return null;
    out.push(...hop, stops[i]);
  }
  return out;
}

// Fills the stretch a router left short of its stop; `stops` is [start, ...via points, end]. See CODEMAP.
export async function closeGaps(route: LatLng[], stops: LatLng[], bridge: Bridge = gsiPath): Promise<LatLng[]> {
  if (route.length < 2) return route;
  const start = stops[0];
  const end = stops[stops.length - 1];
  const gapAtEnd = distanceM(route[route.length - 1], end) > GAP_M;
  const gapAtStart = distanceM(route[0], start) > GAP_M;
  if (!gapAtEnd && !gapAtStart) return route;

  let filled = route;
  if (gapAtEnd) filled = [...filled, ...((await bridge(route[route.length - 1], end)) ?? []), end];
  if (gapAtStart) filled = [start, ...((await bridge(start, route[0])) ?? []), ...filled];

  const direct = await throughStops(stops, bridge);
  return direct && pathLength(direct) < pathLength(filled) ? direct : filled;
}
