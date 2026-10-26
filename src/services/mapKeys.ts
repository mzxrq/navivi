import { invoke } from "@tauri-apps/api/core";
import { API_KEY_NAMES, type AppApiKeys } from "../utils/apiKeys";

// The map service keys live in the OS credential store (src-tauri/src/secrets.rs), like the AI keys.
const entry = (name: string) => `map-key:${name}`;

export async function loadMapKeys(): Promise<AppApiKeys> {
  const out: AppApiKeys = {};
  for (const name of API_KEY_NAMES) {
    const value = await invoke<string | null>("secret_get", { name: entry(name) });
    if (value) out[name] = value;
  }
  return out;
}

/** An empty key is removed. */
export async function saveMapKeys(keys: AppApiKeys): Promise<void> {
  for (const name of API_KEY_NAMES) {
    const value = keys[name]?.trim();
    await (value ? invoke("secret_set", { name: entry(name), value }) : invoke("secret_delete", { name: entry(name) }));
  }
}
