import { useCallback, useEffect, useState } from "react";
import { getLocalModels } from "../services/ollamaApi";
import { hasApiKey } from "../services/ai/online";
import { isOnlineProvider } from "../services/ai/providers";
import { aiReady } from "../services/ai/ready";
import { AI_KEYS_CHANGED } from "../services/ai/keys";
import { useWorkspace } from "./useWorkspace";

const RECHECK_MS = 6000;

// null until the first check. Looks again on focus, when a key is saved or removed, and every few seconds while a local model is missing
// (Ollama may be installed or started after the app).
export function useAiReady(): boolean | null {
  const { settings } = useWorkspace();
  const [ready, setReady] = useState<boolean | null>(null);
  const { ai_features_enabled, ai_provider, ai_model, ai_online_base_url } = settings;

  const check = useCallback(async () => {
    const online = isOnlineProvider(ai_provider);
    const [models, keyed] = await Promise.all([online ? Promise.resolve([]) : getLocalModels(), online ? hasApiKey(ai_provider) : Promise.resolve(false)]);
    setReady(aiReady({ ai_features_enabled, ai_provider, ai_model, ai_online_base_url }, models, keyed));
  }, [ai_features_enabled, ai_provider, ai_model, ai_online_base_url]);

  useEffect(() => {
    void check();
    const again = () => void check();
    window.addEventListener("focus", again);
    window.addEventListener(AI_KEYS_CHANGED, again);
    const timer = ready ? undefined : window.setInterval(again, RECHECK_MS);
    return () => {
      window.removeEventListener("focus", again);
      window.removeEventListener(AI_KEYS_CHANGED, again);
      window.clearInterval(timer);
    };
  }, [check, ready]);

  return ready;
}
