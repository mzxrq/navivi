import { useEffect, useState } from "react";
import { callSidecarShared } from "../services/sidecar";

// Font families the renderer can actually use (main.py list_fonts). Fetched once per app run, and through the shared call:
// the app runs one Python call at a time and a plain call would cancel whatever is running (a render, a voice preview).
let cached: Promise<string[]> | null = null;

function loadFonts(): Promise<string[]> {
  cached ??= callSidecarShared<{ fonts: string[] }>("list_fonts", "").then((reply) => {
    if (reply.success && Array.isArray(reply.fonts)) return reply.fonts;
    cached = null; // asked again next time, e.g. when the call was cancelled by another job
    return [];
  });
  return cached;
}

export function useInstalledFonts(): string[] {
  const [fonts, setFonts] = useState<string[]>([]);
  useEffect(() => {
    let live = true;
    loadFonts().then((f) => live && setFonts(f));
    return () => {
      live = false;
    };
  }, []);
  return fonts;
}
