import { useCallback, useEffect, useState } from "react";
import { callSidecarShared } from "../services/sidecar";

// Whether the fast voice (Kokoro) has its English voices installed; null until the first check. A language version of a project needs
// them, so the menu entry waits for this. Looks again on focus, since the voices are added in Settings > Voice.
export function useEnglishVoiceReady(): boolean | null {
  const [ready, setReady] = useState<boolean | null>(null);

  const check = useCallback(async () => {
    try {
      const reply = await callSidecarShared<{ kokoro?: { ready?: boolean; english_ready?: boolean } }>("tts_engines");
      setReady(reply.success && !!reply.kokoro?.ready && !!reply.kokoro?.english_ready);
    } catch {
      setReady(false);
    }
  }, []);

  useEffect(() => {
    void check();
    const again = () => void check();
    window.addEventListener("focus", again);
    return () => window.removeEventListener("focus", again);
  }, [check]);

  return ready;
}
