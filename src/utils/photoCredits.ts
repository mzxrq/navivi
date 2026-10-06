import type { Waypoint } from "../types";
import type { PhotoCredit } from "../services/placePhotos";

export const MAX_PHOTOS_PER_STOP = 3;

export const creditLine = (c: PhotoCredit) => [c.author || undefined, c.license, c.title.replace(/^File:/i, "")].filter(Boolean).join(" · ");

// Photos found online go into the empty slots of a stop and never replace one the user chose. `null` when the stop is full.
export function withFoundPhotos(
  wp: Pick<Waypoint, "images" | "imagePans" | "imageCredits">,
  found: { path: string; credit: PhotoCredit }[],
  max = MAX_PHOTOS_PER_STOP,
): Pick<Waypoint, "images" | "imagePans" | "imageCredits"> | null {
  const images = wp.images ?? [];
  const room = Math.max(0, max - images.length);
  const take = found.filter((f) => !images.includes(f.path)).slice(0, room);
  if (take.length === 0) return null;
  const pans = [...(wp.imagePans ?? [])];
  while (pans.length < images.length) pans.push("none");
  return {
    images: [...images, ...take.map((f) => f.path)],
    imagePans: [...pans, ...take.map(() => "none")],
    imageCredits: { ...(wp.imageCredits ?? {}), ...Object.fromEntries(take.map((f) => [f.path, f.credit])) },
  };
}

// The same credits under other keys: a saved project names its photos differently from the files they were picked from.
export function renameCredits(credits: Record<string, PhotoCredit> | undefined, renames: Map<string, string>): Record<string, PhotoCredit> | undefined {
  if (!credits) return undefined;
  const out: Record<string, PhotoCredit> = {};
  for (const [key, credit] of Object.entries(credits)) {
    const to = renames.get(key);
    if (to) out[to] = credit;
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

// What the finished video has to credit: the online photos still in use on stops that are in it (one line per photo).
export function collectCredits(waypoints: Waypoint[]): string[] {
  const lines = new Set<string>();
  for (const wp of waypoints) {
    if (wp.skipAssetGeneration || (wp.videos?.length ?? 0) > 0) continue;
    for (const image of wp.images ?? []) {
      const credit = wp.imageCredits?.[image];
      if (credit) lines.add(creditLine(credit));
    }
  }
  return [...lines];
}
