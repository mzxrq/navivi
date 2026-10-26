import { useRef, useState } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import { readTextFile } from "@tauri-apps/plugin-fs";
import { t } from "@lingui/core/macro";
import { useWorkspace } from "./useWorkspace";
import { useUI } from "./useUI";
import { probeDuration, toAbsoluteProjectPath } from "../services/fileSystem";
import { RegenKind, RouteClip, refreshRouteClip, refreshStopMedia, regenModes, routeClipModes, runRegen } from "../services/stopRegen";

/** "Make again" for one stop's voice, subtitles or photo clip (stop editor and timeline editor). */
export function useStopRegen() {
  const { waypoints, metadata, settings, saveProject, timeline, setTimeline } = useWorkspace();
  const { showToast, isRendering } = useUI();
  // index: the stop, or the intro / overview clip.
  const [busy, setBusy] = useState<{ index: number | RouteClip; kind: RegenKind | "video" } | null>(null);
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
  const regenerate = async (index: number, kind: RegenKind) => {
    const dir = metadata.directory_path;
    const stop = stopInfo(index);
    if (!dir || !stop || busy || isRendering) return;
    setBusy({ index, kind });
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
    } finally {
      setBusy(null);
    }
  };

  // The intro or overview clip: its voice (the overview narration, both files) or its video.
  const regenerateClip = async (clip: RouteClip, kind: "voice" | "video") => {
    const dir = metadata.directory_path;
    if (!dir || busy || isRendering) return;
    setBusy({ index: clip, kind });
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
    } finally {
      setBusy(null);
    }
  };

  return { busy, regenerate, regenerateClip, stopInfo };
}
