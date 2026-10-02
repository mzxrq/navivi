import { invoke } from "@tauri-apps/api/core";
import { useEffect, useState } from "react";

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

// Font families the renderer can actually use (main.py list_fonts). Fetched once per app run,
// and again after refreshInstalledFonts (a font was installed).
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
  cached ??= invoke<string>("run_python_blueprint", { action: "list_fonts", payload: "" })
    .then((raw) => {
      const reply = JSON.parse(raw.trim().split("\n").pop() ?? "{}");
      return {
        all: Array.isArray(reply.fonts) ? (reply.fonts as string[]) : [],
        language: reply.languages && typeof reply.languages === "object" ? reply.languages : {},
        downloaded: Array.isArray(reply.downloaded) ? (reply.downloaded as string[]) : [],
      };
    })
    .catch((e) => {
      console.error("Could not list installed fonts:", e);
      cached = null;
      return EMPTY;
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
