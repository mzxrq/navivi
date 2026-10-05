import { invoke } from "@tauri-apps/api/core";
import { announceSetupRequired, isSetupRequired } from "./setup";

// The Python sidecar (src-tauri/src-python/main.py), reached through the Rust command `run_python_blueprint`.
//
// Rust tracks ONE blueprint process: starting another kills the running one, and the killed call rejects with
// "Process was cancelled". That is deliberate (one heavy job at a time), so callers get it as `cancelled: true`
// and must not show it as an error. Identical overlapping requests can share one run with `callSidecarShared`.
//
// The Rust command names its arguments `action` and `payload`; they are really argv[1] and argv[2]:
//  - utility modes (`get_furigana`, `tts_voices_list`, ...): `action` is the mode and `payload` its input;
//  - pipeline stages (`tts-all`, `concat`, ...): `action` is the path of job_config.json and `payload` the mode,
//    which `runStage` spells out.

export type SidecarReply<T> = ({ success: true } & T) | { success: false; error: string; cancelled?: boolean };

const CANCELLED = /process was cancelled/i;

const messageOf = (e: unknown) => (e instanceof Error ? e.message : String(e));

// main.py prints one JSON result as the last line of stdout; anything before it is progress or library noise.
export function parseReply<T>(stdout: string): SidecarReply<T> {
  const last = stdout.trim().split("\n").pop() ?? "";
  try {
    const parsed = JSON.parse(last);
    if (parsed && typeof parsed === "object" && typeof parsed.success === "boolean") return parsed;
  } catch {
    // fall through to the error below
  }
  return { success: false, error: "The media pipeline returned an unexpected reply" };
}

// A pipeline stage run on a project: resolves with the process's stdout, rejects with its error text.
export function runStage(configPath: string, mode: string): Promise<string> {
  return invoke<string>("run_python_blueprint", { action: configPath, payload: mode }).catch((e) => {
    if (isSetupRequired(e)) announceSetupRequired();
    throw e;
  });
}

// A utility mode with its input (a string is passed as is, anything else as JSON); never throws.
export async function callSidecar<T>(mode: string, input: string | object = {}): Promise<SidecarReply<T>> {
  const payload = typeof input === "string" ? input : JSON.stringify(input);
  try {
    return parseReply<T>(await invoke<string>("run_python_blueprint", { action: mode, payload }));
  } catch (e) {
    if (isSetupRequired(e)) announceSetupRequired();
    const error = messageOf(e);
    return { success: false, error, cancelled: CANCELLED.test(error) };
  }
}

const running = new Map<string, Promise<SidecarReply<never>>>();

// Like callSidecar, but a request identical to one still running waits for that run instead of starting another
// (which would kill it). Meant for read-only modes that screens ask for on every mount.
export function callSidecarShared<T>(mode: string, input: string | object = {}): Promise<SidecarReply<T>> {
  const key = `${mode}\u0000${typeof input === "string" ? input : JSON.stringify(input)}`;
  let run = running.get(key);
  if (!run) {
    run = callSidecar<never>(mode, input).finally(() => running.delete(key));
    running.set(key, run);
  }
  return run as Promise<SidecarReply<T>>;
}

let ramGb: Promise<number | undefined> | undefined;

// The PC's RAM never changes within a session, so the sidecar is asked once (and a failed or cancelled ask is retried).
export function systemRamGb(): Promise<number | undefined> {
  ramGb ??= callSidecarShared<{ ram_total_gb: number }>("system_info", "").then((reply) => {
    if (reply.success) return reply.ram_total_gb;
    ramGb = undefined;
    return undefined;
  });
  return ramGb;
}
