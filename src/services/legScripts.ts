import { callSidecar, type SidecarReply } from "./sidecar";

// One stop's suggestion from the sidecar's leg-scripts mode: null where nothing should change.
export interface LegScript {
  id: string;
  name: string;
  arriving: string | null;
  attraction: string | null;
}

export const fetchLegScripts = (projectDir: string): Promise<SidecarReply<{ scripts: LegScript[] }>> =>
  callSidecar<{ scripts: LegScript[] }>(`${projectDir}/job_config.json`, "leg-scripts");
