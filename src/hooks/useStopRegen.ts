import { useRef, useSyncExternalStore } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import { readTextFile } from "@tauri-apps/plugin-fs";
import { t } from "@lingui/core/macro";
import { useWorkspace } from "./useWorkspace";
import { useUI } from "./useUI";
import { probeDuration, toAbsoluteProjectPath } from "../services/fileSystem";
import { RegenKind, RouteClip, StopNarration, onlyNarration, refreshRouteClip, refreshStopMedia, regenModes, routeClipModes, runRegen } from "../services/stopRegen";

type Job = { index: number | RouteClip; kind: RegenKind | "video"; run: () => Promise<void> };

// One queue for the whole app: the sidecar runs one stage at a time (a new call kills the running one), so
// every "make again" from the stop editor or the timeline waits its turn here.
let current: Job | null = null;
const pending: Job[] = [];
const listeners = new Set<() => void>();
type JobInfo = Pick<Job, "index" | "kind">;
let snapshot = { busy: null as JobInfo | null, waiting: [] as JobInfo[] };
const notify = () => {
  snapshot = {
    busy: current && { index: current.index, kind: current.kind },
    waiting: pending.map(({ index, kind }) => ({ index, kind })),
  };
  listeners.forEach((l) => l());
};
const subscribe = (l: () => void) => (listeners.add(l), () => void listeners.delete(l));

async function drain() {
  while ((current = pending.shift() ?? null)) {
    notify();
    await current.run();
  }
  notify();
}

/** Adds a job unless the same one is already running or waiting; returns whether it has to wait. */
export function enqueue(job: Job): boolean | null {
  const same = (j: Job | null) => !!j && j.index === job.index && j.kind === job.kind;
  if (same(current) || pending.some(same)) return null;
  const waits = !!current || pending.length > 0;
  pending.push(job);
  notify();
  if (!current) void drain();
  return waits;
}

/** Moves waiting job `i` up (-1) or down (+1) in the queue. */
export function moveQueued(i: number, delta: -1 | 1) {
  const j = i + delta;
  if (i < 0 || j < 0 || i >= pending.length || j >= pending.length) return;
  [pending[i], pending[j]] = [pending[j], pending[i]];
  notify();
}

/** Takes waiting job `i` out of the queue (the running one finishes). */
export function removeQueued(i: number) {
  if (i >= 0 && i < pending.length) pending.splice(i, 1);
  notify();
}

/** "Make again" for one stop's voice, subtitles or photo clip (stop editor and timeline editor), queued. */
export function useStopRegen() {
  const { waypoints, metadata, settings, saveProject, timeline, setTimeline } = useWorkspace();
  const { showToast, isRendering } = useUI();
  // busy.index: the stop, or the intro / overview clip; queued: requests waiting behind it.
  const { busy, waiting } = useSyncExternalStore(subscribe, () => snapshot);
  const liveTimeline = useRef(timeline);
  liveTimeline.current = timeline;

  /** What stop `index` has to make again; null when it can't be made again. */
  const stopInfo = (index: number) => {
    const wp = waypoints[index];
    if (!wp || !metadata.directory_path || wp.skipAssetGeneration || wp.isStub) return null;
    const isEndpoint = index === 0 || (index === waypoints.length - 1 && waypoints.length > 1);
    const isStopBy = !!wp.isStopBy && !isEndpoint;
    // The "Whole route first" type visits every stop-by: each is narrated, linked or not.
    const visited = !isStopBy || !!wp.connectToRoute || settings.overview_style === "course";
    return {
      hasArrivalVoice: !!wp.arrivingNarration?.trim(),
      hasAttractionVoice: !!wp.attractionNarration?.trim() && visited,
      hasPhotos: (wp.images || []).length > 0,
    };
  };

  // Redo one stop's files through the single-stop CLI modes (one sidecar call at a time), then re-read them in the timeline.
  // `narration`: from a timeline clip, only the narration that clip plays.
  const regenerate = (index: number, kind: RegenKind, narration: StopNarration | null = null) => {
    const dir = metadata.directory_path;
    const info = stopInfo(index);
    const stop = info && onlyNarration(info, narration);
    if (!dir || !stop || isRendering) return;
    queue(index, kind, () => runStop(dir, index, kind, stop));
  };

  const queue = (index: number | RouteClip, kind: RegenKind | "video", run: () => Promise<void>) => {
    const waits = enqueue({ index, kind, run });
    if (waits) showToast(t`Added to the queue. It starts when the one before it is done.`, "info");
  };

  const runStop = async (dir: string, index: number, kind: RegenKind, stop: NonNullable<ReturnType<typeof onlyNarration>>) => {
    showToast(
      kind === "voice" ? t`Making the new voice for this stop. The first one can take a while.` : kind === "subtitles" ? t`Making the subtitles for this stop.` : t`Making the photo clip for this stop. This can take a few minutes.`,
      "info",
    );
    try {
      await saveProject();
      const { skipped } = await runRegen(`${dir}/job_config.json`, regenModes(kind, index, stop));
      const next = await refreshStopMedia(liveTimeline.current, index, kind, {
        probe: async (rel, mediaKind) => probeDuration(convertFileSrc(await toAbsoluteProjectPath(rel, dir)), mediaKind, 0),
        readText: async (rel) => readTextFile(await toAbsoluteProjectPath(rel, dir)),
      });
      if (next) setTimeline(next);
      if (skipped) showToast(t`Nothing was made: ${skipped}`, "warning");
      else if (kind === "voice") showToast(stop.hasAttractionVoice ? t`The voice is ready. If its length changed, redo the photo clip so it fits.` : t`The voice is ready.`, "success");
      else showToast(kind === "subtitles" ? t`The subtitles are ready.` : t`The photo clip is ready.`, "success");
    } catch (err: any) {
      const message = String(err?.message ?? err);
      if (/process was cancelled/i.test(message)) showToast(t`Stopped before it finished.`, "info");
      else showToast(t`Could not make that again: ${message}`, "error");
    }
  };

  // The intro or overview clip: its voice (the overview narration, both files) or its video.
  const regenerateClip = (clip: RouteClip, kind: "voice" | "video") => {
    const dir = metadata.directory_path;
    if (!dir || isRendering) return;
    queue(clip, kind, () => runClip(dir, clip, kind));
  };

  const runClip = async (dir: string, clip: RouteClip, kind: "voice" | "video") => {
    showToast(kind === "voice" ? t`Making the overview narration again.` : t`Making this clip again. This can take a few minutes.`, "info");
    try {
      await saveProject();
      const { skipped } = await runRegen(`${dir}/job_config.json`, routeClipModes(clip, kind));
      const next = await refreshRouteClip(liveTimeline.current, clip, kind, {
        probe: async (rel, mediaKind) => probeDuration(convertFileSrc(await toAbsoluteProjectPath(rel, dir)), mediaKind, 0),
        readText: async (rel) => readTextFile(await toAbsoluteProjectPath(rel, dir)),
      });
      if (next) setTimeline(next);
      if (skipped) showToast(t`Nothing was made: ${skipped}`, "warning");
      else showToast(kind === "voice" ? t`The narration is ready. If its length changed, make the clip again so it fits.` : t`The clip is ready.`, "success");
    } catch (err: any) {
      const message = String(err?.message ?? err);
      if (/process was cancelled/i.test(message)) showToast(t`Stopped before it finished.`, "info");
      else showToast(t`Could not make that again: ${message}`, "error");
    }
  };

  return { busy, waiting, regenerate, regenerateClip, stopInfo };
}
