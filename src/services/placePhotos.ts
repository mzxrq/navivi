import { fetch } from "@tauri-apps/plugin-http";
import { getVersion } from "@tauri-apps/api/app";
import { documentDir, join } from "@tauri-apps/api/path";
import { mkdir, writeFile } from "@tauri-apps/plugin-fs";
import { fileSystem } from "../config/constants";

// Photos of a place from Wikipedia and Wikimedia Commons: free to use, and every file says who took it and under which license.
// Nothing here uses a search engine's image results, which are copyrighted. Only the place name and its coordinates leave the PC.

export interface PhotoCredit {
  title: string; // the Commons file name, e.g. "File:Sandanbeki.jpg"
  author: string;
  license: string; // e.g. "CC BY-SA 4.0"
  url: string; // the file's page on Commons
}

export interface PhotoCandidate extends PhotoCredit {
  downloadUrl: string;
  width: number;
  height: number;
  score: number;
}

export interface PlaceQuery {
  name: string;
  lat: number;
  lng: number;
  uncertain?: boolean; // the position was only guessed: search by name alone
}

export type JsonGetter = (url: string, signal?: AbortSignal) => Promise<any>;

const WIDTH = 1920; // one of the sizes Commons serves as a thumbnail; plenty for a 1080p video
const MIN_WIDTH = 1000;
const GEO_RADIUS_M = 300;
const ARTICLE_RADIUS_M = 1500;
const MAX_TITLES = 30;
const FREE_LICENSE = /^(cc0|cc[ -]by(?![ -]?(nc|nd))|public domain|pd[ -]|pd$|attribution)/i;
// Maps, logos and diagrams are not photographs of the place.
const NOT_A_PHOTO = /\b(map|logo|flag|locator|icon|diagram|chart|coat of arms|symbol|plan|route)\b|地図|路線図|ロゴ|案内図|紋章|図$/i;

export const stripHtml = (html: string) =>
  html
    .replace(/<[^>]*>/g, "")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#0?39;|&apos;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\s+/g, " ")
    .trim();

const hasCjk = (s: string) => /[぀-ヿ㐀-鿿]/.test(s);
const normal = (s: string) => s.normalize("NFKC").toLowerCase().replace(/[\s\-_・,.、。()（）'"]/g, "");

// A page or file belongs to the stop when one name contains the other (a stop "三段壁展望台" matches the article "三段壁").
export function sameName(stop: string, title: string): boolean {
  const a = normal(stop);
  const b = normal(title.replace(/^file:/i, ""));
  const shortest = Math.min(a.length, b.length);
  if (shortest < (hasCjk(a) || hasCjk(b) ? 2 : 4)) return false;
  return a.includes(b) || b.includes(a);
}

export function isFreeLicense(license: string): boolean {
  return FREE_LICENSE.test(license.trim());
}

interface FileInfo {
  title: string;
  width: number;
  height: number;
  mime: string;
  downloadUrl: string;
  license: string;
  author: string;
  pageUrl: string;
}

export function readFileInfo(page: any): FileInfo | null {
  const info = page?.imageinfo?.[0];
  if (!page || page.missing || !info) return null;
  const meta = info.extmetadata ?? {};
  const license = stripHtml(String(meta.LicenseShortName?.value ?? ""));
  const author = stripHtml(String(meta.Artist?.value ?? ""));
  return {
    title: page.title,
    width: info.width ?? 0,
    height: info.height ?? 0,
    mime: info.mime ?? "",
    downloadUrl: info.thumburl || info.url || "",
    license,
    author,
    pageUrl: info.descriptionurl || `https://commons.wikimedia.org/wiki/${encodeURIComponent(String(page.title).replace(/ /g, "_"))}`,
  };
}

// Whether a file is a photo we may use: a real picture of usable size under a free license.
export function usable(f: FileInfo): boolean {
  return (f.mime === "image/jpeg" || f.mime === "image/png") && f.width >= MIN_WIDTH && !NOT_A_PHOTO.test(f.title) && isFreeLicense(f.license) && !!f.downloadUrl;
}

// `base` is where the title came from (a Wikipedia lead image beats a nearby file), landscape photos and larger ones go first.
export function scoreFile(f: FileInfo, base: number): number {
  const ratio = f.height > 0 ? f.width / f.height : 1;
  return base + (ratio >= 1.3 ? 10 : ratio >= 1 ? 4 : -10) + Math.min(6, Math.log2(f.width / MIN_WIDTH) * 2);
}

// Articles by that name can be about another place with the same name (a station in Korea for a station in Japan).
const FAR_KM = 30;
const NEAR_FILE_M = 120; // a photo with no connection to the name has to be taken practically on the spot to count

function distanceKm(a: { lat: number; lng: number }, b: { lat: number; lng: number }): number {
  const rad = Math.PI / 180;
  const h = Math.sin(((b.lat - a.lat) * rad) / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(((b.lng - a.lng) * rad) / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(h));
}

// The same series of shots (name with its numbers dropped) should not fill every slot.
const seriesOf = (title: string) => normal(title).replace(/\d+/g, "");

const WIKIS = (name: string) => (hasCjk(name) ? ["ja", "en"] : ["en", "ja"]);
const api = (host: string, params: Record<string, string | number>) =>
  `https://${host}/w/api.php?${new URLSearchParams({ format: "json", formatversion: "2", ...Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])) })}`;

export async function userAgent(): Promise<string> {
  const version = await getVersion().catch(() => "1.0");
  return `Navivi/${version} (https://github.com/mzxrq/navivi)`;
}

let agent: Promise<string> | undefined;
export const httpGetter: JsonGetter = async (url, signal) => {
  agent ??= userAgent();
  const response = await fetch(url, { signal, headers: { "User-Agent": await agent, "Api-User-Agent": await agent } });
  if (!response.ok) throw new Error(`Wikimedia answered ${response.status}`);
  return response.json();
};

// Wikimedia asks for one request at a time.
const sequential = (get: JsonGetter): JsonGetter => {
  let tail: Promise<unknown> = Promise.resolve();
  return (url, signal) => {
    const run = tail.then(() => get(url, signal));
    tail = run.catch(() => {});
    return run;
  };
};

interface Titled {
  title: string;
  base: number;
}

export async function findPlacePhotos(
  stop: PlaceQuery,
  { limit = 3, signal, get = httpGetter }: { limit?: number; signal?: AbortSignal; get?: JsonGetter } = {},
): Promise<PhotoCandidate[]> {
  const ask = sequential(get);
  const names: Titled[] = [];
  const seen = new Set<string>();
  const add = (title: string | undefined, base: number) => {
    if (!title) return;
    const full = title.startsWith("File:") ? title : `File:${title.replace(/_/g, " ")}`;
    if (seen.has(full)) return;
    seen.add(full);
    names.push({ title: full, base });
  };
  const safe = async (url: string) => {
    try {
      return await ask(url, signal);
    } catch (e) {
      if (signal?.aborted) throw e;
      return null; // one failing lookup should not cost the others
    }
  };

  // 1. The lead photo of the article about the place: the picture Wikipedia itself uses for it.
  for (const lang of WIKIS(stop.name)) {
    const host = `${lang}.wikipedia.org`;
    // Near the stop's position when that is known, because an article found by name alone may be about a namesake elsewhere;
    // by name only when the position was a guess.
    const lookups = [
      stop.uncertain
        ? api(host, { action: "query", generator: "search", gsrsearch: stop.name, gsrlimit: 3, prop: "pageimages|coordinates", piprop: "name" })
        : api(host, { action: "query", generator: "geosearch", ggscoord: `${stop.lat}|${stop.lng}`, ggsradius: ARTICLE_RADIUS_M, ggslimit: 10, prop: "pageimages|coordinates", piprop: "name" }),
    ];
    for (const url of lookups) {
      const reply = await safe(url);
      for (const page of reply?.query?.pages ?? []) {
        if (!page.pageimage || !sameName(stop.name, page.title)) continue;
        const where = page.coordinates?.[0];
        if (!stop.uncertain && where && distanceKm(stop, { lat: where.lat, lng: where.lon }) > FAR_KM) continue;
        add(page.pageimage, 100);
      }
    }
    if (names.length >= limit) break;
  }

  // 2. Photos on Commons taken right there, nearest first, and photos whose description mentions the name.
  if (!stop.uncertain) {
    const reply = await safe(api("commons.wikimedia.org", { action: "query", list: "geosearch", gscoord: `${stop.lat}|${stop.lng}`, gsradius: GEO_RADIUS_M, gsnamespace: 6, gslimit: 15 }));
    for (const hit of reply?.query?.geosearch ?? []) if (hit.dist <= NEAR_FILE_M || sameName(stop.name, hit.title)) add(hit.title, 60 - hit.dist / 10);
  }
  const found = await safe(api("commons.wikimedia.org", { action: "query", list: "search", srsearch: stop.name, srnamespace: 6, srlimit: 8 }));
  for (const hit of found?.query?.search ?? []) add(hit.title, 40);

  const wanted = names.slice(0, MAX_TITLES);
  if (wanted.length === 0) return [];

  // 3. What each file is: size, type, license, photographer.
  const infos: FileInfo[] = [];
  for (let i = 0; i < wanted.length; i += 25) {
    const chunk = wanted.slice(i, i + 25);
    const reply = await safe(
      api("commons.wikimedia.org", {
        action: "query",
        titles: chunk.map((c) => c.title).join("|"),
        prop: "imageinfo",
        iiprop: "url|size|mime|extmetadata",
        iiurlwidth: WIDTH,
        iiextmetadatafilter: "LicenseShortName|Artist",
      }),
    );
    for (const page of reply?.query?.pages ?? []) {
      const info = readFileInfo(page);
      if (info) infos.push(info);
    }
  }

  const base = new Map(wanted.map((w) => [w.title, w.base]));
  const ranked = infos
    .filter(usable)
    .map((f) => ({
      title: f.title,
      author: f.author,
      license: f.license,
      url: f.pageUrl,
      downloadUrl: f.downloadUrl,
      width: f.width,
      height: f.height,
      score: scoreFile(f, base.get(f.title) ?? 0),
    }))
    .sort((a, b) => b.score - a.score)
    .reduce<{ chosen: PhotoCandidate[]; rest: PhotoCandidate[] }>(
      (acc, c) => {
        (acc.chosen.some((x) => seriesOf(x.title) === seriesOf(c.title)) ? acc.rest : acc.chosen).push(c);
        return acc;
      },
      { chosen: [], rest: [] },
    );
  // A photo found by name alone may show a namesake, so a guessed place gets one at most, for the user to check.
  return [...ranked.chosen, ...ranked.rest].slice(0, stop.uncertain ? Math.min(limit, 1) : limit);
}

const forbiddenInName = /[<>:"/\\|?*\u0000-\u001f]/g;
export const fileNameFor = (title: string, contentType: string) => {
  const stem = title.replace(/^File:/i, "").replace(/\.[A-Za-z0-9]{2,5}$/, "").replace(forbiddenInName, " ").replace(/\s+/g, " ").trim().slice(0, 80) || "photo";
  return `${stem}.${/png/i.test(contentType) ? "png" : "jpg"}`;
};

// Downloads the photos into the Imports folder, where the project save copies them from like any photo the user picked.
export async function downloadPhotos(candidates: PhotoCandidate[], signal?: AbortSignal): Promise<{ path: string; credit: PhotoCredit }[]> {
  if (candidates.length === 0) return [];
  agent ??= userAgent();
  const dir = await join(await documentDir(), fileSystem.rootFolder, "Imports", `photos-${Date.now()}`);
  await mkdir(dir, { recursive: true });
  const out: { path: string; credit: PhotoCredit }[] = [];
  for (const c of candidates) {
    try {
      const response = await fetch(c.downloadUrl, { signal, headers: { "User-Agent": await agent } });
      if (!response.ok) continue;
      const bytes = new Uint8Array(await response.arrayBuffer());
      const path = await join(dir, fileNameFor(c.title, response.headers.get("content-type") ?? ""));
      await writeFile(path, bytes);
      out.push({ path, credit: { title: c.title, author: c.author, license: c.license, url: c.url } });
    } catch (e) {
      if (signal?.aborted) throw e;
    }
  }
  return out;
}
