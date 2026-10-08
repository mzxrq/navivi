import { callSidecar, sidecarBusy } from "./sidecar";
import { t } from "@lingui/core/macro";

export interface RenderEstimate {
  total_seconds: number;
  stages: Record<string, number>;
  measured_stages: number;
  active_stages: number;
  hardware: { gpu: string | null; cpu_cores: number };
}

export async function fetchRenderEstimate(projectDir: string): Promise<RenderEstimate | null> {
  if (sidecarBusy()) return null; // asking now would kill that job
  const reply = await callSidecar<RenderEstimate>("estimate", `${projectDir}/job_config.json`);
  return reply.success ? reply : null;
}

export function formatDuration(seconds: number): string {
  const m = Math.max(1, Math.round(seconds / 60));
  if (m < 60) return t`${m} min`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return rest ? t`${h} h ${rest} min` : t`${h} h`;
}
