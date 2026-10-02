import { invoke } from "@tauri-apps/api/core";
import { useEffect, useState } from "react";

// Font families the renderer can actually use (main.py list_fonts). Fetched once per app run.
let cached: Promise<string[]> | null = null;

function loadFonts(): Promise<string[]> {
  cached ??= invoke<string>("run_python_blueprint", { action: "list_fonts", payload: "" })
    .then((raw) => {
      const reply = JSON.parse(raw.trim().split("\n").pop() ?? "{}");
      return Array.isArray(reply.fonts) ? (reply.fonts as string[]) : [];
    })
    .catch((e) => {
      console.error("Could not list installed fonts:", e);
      cached = null;
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
