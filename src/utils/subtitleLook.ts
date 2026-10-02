import type { ProjectSettings } from "../types";

// Mirrors CAPTION_* in src-tauri/src-python/services/tuning.py: the burned-in captions are a translucent box, narrow and centred at
// the bottom so they stay clear of the walk-time card in a route clip's bottom-right corner. libass sizes everything against a
// 288-line frame, so these are in those units.
export const CAPTION = {
  lines: 288,
  defaultSize: 16,
  maxWidth: 0.5,
  marginV: 20,
  padding: 2,
  font: "Yu Gothic UI",
  textColor: "&H00FFFFFF",
  boxColor: "&H66000000",
};

const KEYS = ["subtitle_font", "subtitle_font_size", "subtitle_color", "subtitle_outline_color", "subtitle_bold"] as const;

// The caption settings that are set, as written into timeline.json for the exporter.
export function subtitleStyleOf(settings: Partial<ProjectSettings>) {
  const out: Record<string, unknown> = {};
  for (const key of KEYS) if (settings[key] !== undefined) out[key] = settings[key];
  return out;
}
