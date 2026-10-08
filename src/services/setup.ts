import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

export interface RuntimeStatus {
  installed: boolean; // an installed app, not `tauri dev`
  pythonReady: boolean;
  uvFound: boolean;
  venvDir: string | null;
  vcRuntime: boolean; // the Visual C++ runtime GPSBabel and PyTorch load
}

export interface SetupStep {
  index: number;
  total: number;
  title: string;
}

export const SETUP_REQUIRED_EVENT = "navivi-setup-required";
const SETUP_REQUIRED = /SETUP_REQUIRED/;

export const getRuntimeStatus = () => invoke<RuntimeStatus>("runtime_status");

// The installed app has no Python for the media tools until the first-run setup has run.
export const needsSetup = (status: RuntimeStatus) => status.installed && !status.pythonReady;

export const isSetupRequired = (error: unknown) => SETUP_REQUIRED.test(error instanceof Error ? error.message : String(error));

export const announceSetupRequired = () => window.dispatchEvent(new Event(SETUP_REQUIRED_EVENT));

export const VC_RUNTIME_EVENT = "navivi-vc-runtime-missing";
export const isVcRuntimeMissing = (error: unknown) => /VC_RUNTIME_MISSING/.test(error instanceof Error ? error.message : String(error));
export const announceVcRuntimeMissing = () => window.dispatchEvent(new Event(VC_RUNTIME_EVENT));
export const installVcRuntime = () => invoke<void>("install_vc_runtime");
// Stops the first-run setup (the running uv / pip / browser download and the steps after it); `installRuntime` then rejects with "cancelled".
export const cancelRuntimeInstall = () => invoke<void>("runtime_cancel");
export const isSetupCancelled = (error: unknown) => /was cancelled/i.test(error instanceof Error ? error.message : String(error));

// A tool's own download bar (Playwright: `|■■■■    |  40% of 150 MiB`, sometimes several joined by carriage returns): the latest percentage, or null for any other line.
export function parseDownloadLine(line: string): { percent: number; size: string } | null {
  const parts = line.split("\r");
  for (let i = parts.length - 1; i >= 0; i--) {
    const match = /(\d{1,3})%(?:\s+of\s+([\d.]+\s*[KMGT]?i?B))?/i.exec(parts[i]);
    // A bar has block characters or "NN% of <size>"; a log line that only mentions a percentage and "of" is not one.
    if (match && (/■/.test(parts[i]) || match[2])) return { percent: Math.min(100, Number(match[1])), size: match[2] ?? "" };
  }
  return null;
}

// Makes the pipeline's Python and installs the media libraries and the browser that draws the route.
// Progress arrives as `setup-step` (which step of how many) and `setup-log` (what the tools print).
export async function installRuntime(onStep: (step: SetupStep) => void, onLog: (line: string) => void): Promise<void> {
  const unlisten = await Promise.all([
    listen<SetupStep>("setup-step", (e) => onStep(e.payload)),
    listen<string>("setup-log", (e) => onLog(e.payload)),
  ]);
  try {
    await invoke("runtime_install");
  } finally {
    unlisten.forEach((off) => off());
  }
}
