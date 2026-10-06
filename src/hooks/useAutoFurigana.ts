import { useEffect, useRef } from "react";
import { useWorkspace } from "./useWorkspace";
import { callSidecarUtility } from "../services/sidecar";
import { db } from "../services/db";
import { GLOBAL_DICTIONARY_KEY } from "../config/constants";
import { mergeAutoReadings, narrationText } from "../utils/autoReadings";

const SETTLE_MS = 1500;

// Scans every narration for place names once edits settle and keeps settings.pronunciation_dictionary's auto words in step.
export function useAutoFurigana() {
  const { waypoints, metadata, settings, updateSettings } = useWorkspace();
  const settingsRef = useRef(settings);
  const lastScanned = useRef<string | null>(null);
  settingsRef.current = settings;

  const project = metadata?.directory_path;
  const generating = waypoints.some((w) => w.generatingScriptType);
  const text = narrationText(waypoints, metadata?.overview_narration);
  const names = JSON.stringify(waypoints.map((w) => w.name));

  useEffect(() => {
    lastScanned.current = null;
  }, [project]);

  useEffect(() => {
    const scan = names + text;
    if (!project || generating || scan === lastScanned.current) return;
    let stale = false;
    const timer = setTimeout(async () => {
      const reply = text
        ? await callSidecarUtility<{ words: { word: string; reading: string }[] }>("extract_place_words", {
            text,
            names: JSON.parse(names),
          })
        : { success: true as const, words: [] };
      if (stale) return;
      if (!reply.success) {
        console.warn("Auto furigana scan failed:", reply.error);
        return;
      }
      const shared = (await db.appSettings.get<{ word: string }[]>(GLOBAL_DICTIONARY_KEY)) ?? [];
      if (stale) return;
      lastScanned.current = scan;
      const next = mergeAutoReadings(settingsRef.current.pronunciation_dictionary ?? [], reply.words ?? [], shared);
      if (next) updateSettings({ pronunciation_dictionary: next });
    }, SETTLE_MS);
    return () => {
      stale = true;
      clearTimeout(timer);
    };
  }, [project, generating, text, names, updateSettings]);
}
