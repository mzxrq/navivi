import type { ProjectSettings } from "../../types";
import { isOnlineProvider, PROVIDERS, type OnlineTarget } from "./providers";

export const DEFAULT_LOCAL_MODEL = "schroneko/gemma-2-2b-jpn-it";

// Who writes the scripts: a model name for the local Ollama, or a target on the internet.
export type AiEngine = string | OnlineTarget;

export const isOnlineEngine = (engine: AiEngine): engine is OnlineTarget => typeof engine !== "string";

type EngineSettings = Pick<ProjectSettings, "ai_model" | "ai_provider" | "ai_online_models" | "ai_online_base_url" | "ai_online_send_photos">;

export function aiEngine(settings: Partial<EngineSettings>): AiEngine {
  const provider = settings.ai_provider;
  if (!isOnlineProvider(provider)) return settings.ai_model || DEFAULT_LOCAL_MODEL;
  return {
    provider,
    model: settings.ai_online_models?.[provider] || PROVIDERS[provider].defaultModel,
    baseUrl: settings.ai_online_base_url ?? "",
    sendPhotos: settings.ai_online_send_photos !== false,
  };
}

export const engineLabel = (engine: AiEngine) => (isOnlineEngine(engine) ? `${PROVIDERS[engine.provider].label} · ${engine.model}` : engine);
