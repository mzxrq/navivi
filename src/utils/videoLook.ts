import { videoLookDefaults } from "../config/constants";
import type { LookMode } from "../types";

type Rgb = [number, number, number];

// Every settings key the "Look of the video" controls write: what the Project settings dialog patches into the database.
export const LOOK_KEYS: string[] = [
  ...Object.keys(videoLookDefaults),
  "arrived_marker_color",
  "mode_line_colors",
];

// The renderer's own colors for modes the project's line color does not cover (tuning.MODE_LINE_COLORS, as RGB).
const AIRPLANE_COLOR: Rgb = [220, 60, 180];
const ARRIVED_FALLBACK: Rgb = [30, 110, 200];
const ARRIVED_DARKEN = 0.78; // render_step._ARRIVED_COLOR_DARKEN

/** The pin color after arrival when the project names none: its marker color darkened, else the stock blue. */
export function arrivedDefault(marker?: Rgb): Rgb {
  if (!marker) return ARRIVED_FALLBACK;
  return marker.map((c) => Math.max(0, Math.min(255, Math.trunc(c * ARRIVED_DARKEN)))) as Rgb;
}

/** The line color a travel mode has when mode_line_colors does not name it: the project's route line color, except flights. */
export function modeLineDefault(mode: LookMode, lineColor?: Rgb): Rgb {
  if (mode === "airplane") return AIRPLANE_COLOR;
  return lineColor ?? (mode === "walking" ? [26, 115, 232] : mode === "ferry" ? [255, 140, 0] : [60, 180, 60]);
}

const MODES: LookMode[] = ["walking", "driving", "car", "ferry", "airplane"];

/** A database merge patch for the look keys: the file's value, or null so a reset removes the key there too.
 * The database merges nested objects, so mode_line_colors names every mode (null for the ones that were reset). */
export function lookPatch(settings: Record<string, unknown>): Record<string, unknown> {
  const patch = Object.fromEntries(LOOK_KEYS.map((key) => [key, settings[key] ?? null]));
  const modes = settings.mode_line_colors as Record<string, unknown> | undefined;
  if (modes && Object.keys(modes).length) {
    patch.mode_line_colors = Object.fromEntries(MODES.map((mode) => [mode, modes[mode] ?? null]));
  }
  return patch;
}

/** Sets or, when `value` is undefined, removes keys. A reset therefore leaves no key behind in job_config.json. */
export function applyOption(settings: Record<string, unknown>, patch: Record<string, unknown>): Record<string, unknown> {
  const next = { ...settings };
  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined) delete next[key];
    else next[key] = value;
  }
  return next;
}
