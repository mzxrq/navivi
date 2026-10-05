import { invoke } from "@tauri-apps/api/core";
import type { OnlineProvider } from "./providers";

// Keys live in the OS credential store (src-tauri/src/secrets.rs), one per provider, and are not part of any project.
const name = (provider: OnlineProvider) => `ai-key:${provider}`;

export const getApiKey = (provider: OnlineProvider) => invoke<string | null>("secret_get", { name: name(provider) });
export const saveApiKey = (provider: OnlineProvider, key: string) => invoke<void>("secret_set", { name: name(provider), value: key.trim() });
export const deleteApiKey = (provider: OnlineProvider) => invoke<void>("secret_delete", { name: name(provider) });
