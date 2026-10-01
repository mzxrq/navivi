import { invoke } from "@tauri-apps/api/core";
import { t } from "@lingui/core/macro";

export interface RenderEstimate {
  total_seconds: number;
  stages: Record<string, number>;
  measured_stages: number;
  active_stages: number;
  hardware: { gpu: string | null; cpu_cores: number };
}

export async function fetchRenderEstimate(projectDir: string): Promise<RenderEstimate | null> {
  try {
    const raw = await invoke<string>("run_python_blueprint", {
      action: "estimate",
      payload: `${projectDir}/job_config.json`,
    });
    const data = JSON.parse(raw.trim().split(String.fromCharCode(10)).pop() ?? "");
    return data.success ? data : null;
  } catch {
    return null;
  }
}

export function formatDuration(seconds: number): string {
  const m = Math.max(1, Math.round(seconds / 60));
  if (m < 60) return t`${m} min`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return rest ? t`${h} h ${rest} min` : t`${h} h`;
}
