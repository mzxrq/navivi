import type { ProjectSettings } from "../types";

/** The map keys belong to the app: kept in the OS credential store (src-tauri/src/secrets.rs, `map-key:<name>`), never in
 * the database, a project file, a version or a shared archive. */

export interface AppApiKeys {
  mapbox?: string;
  ors?: string;
  mapillary?: string;
}

const FIELDS = { mapbox: "mapbox_api_key", ors: "ors_api_key", mapillary: "mapillary_api_key" } as const;
type KeyName = keyof typeof FIELDS;
const NAMES = Object.keys(FIELDS) as KeyName[];
export const API_KEY_NAMES: readonly KeyName[] = NAMES;

const filled = (value: unknown): value is string => typeof value === "string" && value.trim() !== "";

/** The keys a settings object carries (an empty value counts as no key). Used for projects saved by earlier versions. */
export function legacyApiKeys(settings: unknown): AppApiKeys {
  const source = (settings && typeof settings === "object" ? settings : {}) as Record<string, unknown>;
  const out: AppApiKeys = {};
  for (const name of NAMES) if (filled(source[FIELDS[name]])) out[name] = source[FIELDS[name]] as string;
  return out;
}

/** The keys named in an `updateSettings` patch (an empty string is a real "clear this key"). */
export function patchedApiKeys(patch: Partial<ProjectSettings>): AppApiKeys {
  const source = patch as Record<string, unknown>;
  const out: AppApiKeys = {};
  for (const name of NAMES) if (typeof source[FIELDS[name]] === "string") out[name] = source[FIELDS[name]] as string;
  return out;
}

/** A copy of the settings without the map keys: what may be written to a project. */
export function stripApiKeys<T extends object>(settings: T): T {
  const copy = { ...settings } as Record<string, unknown>;
  for (const name of NAMES) delete copy[FIELDS[name]];
  return copy as T;
}

/** The app-wide keys as the settings fields the rest of the UI reads. */
export function apiKeySettings(keys: AppApiKeys): Pick<ProjectSettings, "mapbox_api_key" | "ors_api_key" | "mapillary_api_key"> {
  return { mapbox_api_key: keys.mapbox ?? "", ors_api_key: keys.ors ?? "", mapillary_api_key: keys.mapillary ?? "" };
}

/** A project's old keys fill only the app-wide keys that are still empty; a key the user already has is never replaced. */
export function adoptLegacyKeys(current: AppApiKeys, legacy: AppApiKeys): AppApiKeys {
  const next = { ...current };
  for (const name of NAMES) if (!filled(next[name]) && filled(legacy[name])) next[name] = legacy[name];
  return next;
}

export const hasApiKeys = (keys: AppApiKeys) => NAMES.some((name) => filled(keys[name]));

export const sameApiKeys = (a: AppApiKeys, b: AppApiKeys) => NAMES.every((name) => (a[name] ?? "") === (b[name] ?? ""));
