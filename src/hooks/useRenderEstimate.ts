import { useEffect, useState } from "react";
import { fetchRenderEstimate, RenderEstimate } from "../services/renderEstimate";

// A new blueprint call kills the running one, so only ask while idle.
export function useRenderEstimate(projectDir: string | undefined, enabled: boolean, refreshKey: unknown) {
  const [estimate, setEstimate] = useState<RenderEstimate | null>(null);

  useEffect(() => {
    if (!enabled || !projectDir) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      const result = await fetchRenderEstimate(projectDir);
      if (!cancelled && result) setEstimate(result);
    }, 1500);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [enabled, projectDir, refreshKey]);

  return estimate;
}
