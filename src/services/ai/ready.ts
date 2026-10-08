import type { ProjectSettings } from "../../types";
import { DEFAULT_LOCAL_MODEL } from "./engine";
import { isOnlineProvider } from "./providers";

type ReadySettings = Pick<ProjectSettings, "ai_features_enabled" | "ai_provider" | "ai_model" | "ai_online_base_url">;

// Whether something can write scripts right now: a key for the chosen online provider, or the chosen model installed in the local Ollama.
export function aiReady(settings: Partial<ReadySettings>, localModels: string[], hasKey: boolean): boolean {
  if (settings.ai_features_enabled === false) return false;
  const provider = settings.ai_provider;
  if (isOnlineProvider(provider)) return hasKey && (provider !== "custom" || !!settings.ai_online_base_url);
  return localModels.includes(settings.ai_model || DEFAULT_LOCAL_MODEL);
}
