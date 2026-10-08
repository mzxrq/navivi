import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { callSidecar } from "./sidecar";

// Engine installs (voices, ComfyUI, Ollama) run in the background: they live here, not in the dialog that started them,
// so closing the window does not lose them. Python prints `[progress] <done>/<total>|<label>` (services/install_progress.py);
// Rust forwards every stderr line as `blueprint-log`.

export type InstallState = "running" | "done" | "failed";
export interface InstallJob {
  id: string;
  label: string;
  state: InstallState;
  fraction: number;
  step: string;
  log: string[];
  error: string;
}

const MAX_LOG_LINES = 300;
const PROGRESS = /^\[progress\]\s+(\d+)\/(\d+)\|(.*)$/;

let jobs: InstallJob[] = [];
const listeners = new Set<() => void>();
let unlisten: UnlistenFn | undefined;
let listening: Promise<void> | undefined;

const emit = () => {
  jobs = [...jobs];
  listeners.forEach((l) => l());
};

export const getInstalls = () => jobs;
export const subscribeInstalls = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

export function parseProgress(line: string): { fraction: number; step: string } | null {
  const match = PROGRESS.exec(line.trim());
  if (!match) return null;
  const done = Number(match[1]);
  const total = Math.max(1, Number(match[2]));
  return { fraction: Math.min(1, done / total), step: match[3].trim() };
}

function update(id: string, patch: Partial<InstallJob>) {
  const job = jobs.find((j) => j.id === id);
  if (!job) return;
  Object.assign(job, patch);
  emit();
}

function onLine(line: string) {
  const job = jobs.find((j) => j.state === "running");
  if (!job) return;
  const progress = parseProgress(line);
  if (progress) {
    job.fraction = progress.fraction;
    job.step = progress.step;
  } else if (line.trim()) {
    job.log = [...job.log.slice(-(MAX_LOG_LINES - 1)), line];
  }
  emit();
}

async function ensureListening() {
  listening ??= listen<string>("blueprint-log", (e) => onLine(String(e.payload))).then((fn) => {
    unlisten = fn;
  });
  await listening;
}

function stopListening() {
  if (jobs.some((j) => j.state === "running")) return;
  unlisten?.();
  unlisten = undefined;
  listening = undefined;
}

// Installs share the one tracked Python process, so only one runs at a time; a second start is ignored.
export async function startInstall(id: string, label: string, action: string): Promise<boolean> {
  if (jobs.some((j) => j.state === "running")) return false;
  jobs = jobs.filter((j) => j.id !== id);
  jobs.push({ id, label, state: "running", fraction: 0, step: "", log: [], error: "" });
  emit();
  await ensureListening().catch(() => {});
  const reply = await callSidecar(action, {});
  if (reply.success) update(id, { state: "done", fraction: 1 });
  else if (reply.cancelled) jobs = jobs.filter((j) => j.id !== id), emit();
  else update(id, { state: "failed", error: reply.error });
  stopListening();
  return reply.success;
}

// Stops the install's Python process; the call then comes back as cancelled and the job disappears. Installs resume where they stopped.
export async function cancelInstall(id: string) {
  if (!jobs.some((j) => j.id === id && j.state === "running")) return;
  await invoke("cancel_python_blueprint").catch(() => {});
}

export function dismissInstall(id: string) {
  jobs = jobs.filter((j) => j.id !== id);
  emit();
}

export const installRunning = () => jobs.some((j) => j.state === "running");

// Tests only: forget every install and the event listener.
export function resetInstalls() {
  jobs = [];
  unlisten?.();
  unlisten = undefined;
  listening = undefined;
  emit();
}
