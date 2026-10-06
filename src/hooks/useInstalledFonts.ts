import { useEffect, useState } from "react";
import { callSidecarShared } from "../services/sidecar";

/** Font picker groups, in order (fonts.py FONT_LANGUAGES). */
export const FONT_LANGUAGES = ["ja", "en"] as const;
export type FontLanguage = (typeof FONT_LANGUAGES)[number];
/** Shipped with Windows and used by the app's own defaults, so always offered. */
export const BUILT_IN_FONTS = ["Meiryo", "Yu Gothic UI"];

export interface InstalledFonts {
  /** Every family the renderer can use. */
  all: string[];
  /** Family -> its picker group; families in no group are left out of the picker. */
  language: Record<string, FontLanguage>;
  /** Families the user installed (Get more fonts), not shipped with Windows or Office. */
  downloaded: string[];
}

const EMPTY: InstalledFonts = { all: [], language: {}, downloaded: [] };

// Font families the renderer can actually use (main.py list_fonts). Fetched once per app run, and again after
// refreshInstalledFonts (a font was installed), through the shared call: a plain call would cancel a running job.
let cached: Promise<InstalledFonts> | null = null;
const listeners = new Set<(f: InstalledFonts) => void>();

export function refreshInstalledFonts(): Promise<InstalledFonts> {
  cached = null;
  return loadFonts().then((f) => {
    listeners.forEach((l) => l(f));
    return f;
  });
}

function loadFonts(): Promise<InstalledFonts> {
  cached ??= callSidecarShared<{ fonts: string[]; languages: Record<string, FontLanguage>; downloaded: string[] }>(
    "list_fonts",
    "",
  ).then((reply) => {
    if (!reply.success) {
      cached = null; // asked again next time, e.g. when the call was cancelled by another job
      return EMPTY;
    }
    return {
      all: Array.isArray(reply.fonts) ? reply.fonts : [],
      language: reply.languages && typeof reply.languages === "object" ? reply.languages : {},
      downloaded: Array.isArray(reply.downloaded) ? reply.downloaded : [],
    };
  });
  return cached;
}

export function useInstalledFonts(): InstalledFonts {
  const [fonts, setFonts] = useState<InstalledFonts>(EMPTY);
  useEffect(() => {
    let live = true;
    loadFonts().then((f) => live && setFonts(f));
    listeners.add(setFonts);
    return () => {
      live = false;
      listeners.delete(setFonts);
    };
  }, []);
  return fonts;
}
