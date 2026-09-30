import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { convertFileSrc, invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { join } from "@tauri-apps/api/path";
import { exists, readDir, remove } from "@tauri-apps/plugin-fs";
import {
  AlertTriangle,
  CheckCircle,
  Cpu,
  Film,
  Folder,
  Info,
  Loader2,
  Maximize2,
  Mic,
  PlayCircle,
  RotateCcw,
  Settings2,
  Sparkles,
  X,
  XCircle,
  Zap,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useUI } from "../../hooks/useUI";
import { useWorkspace } from "../../hooks/useWorkspace";
import {
  loadTimelineManifest,
  saveTimelineManifest,
} from "../../services/fileSystem";
import { detectHardwareSpec } from "../../utils/hardwareDetection";
import {
  appendPipelineOutput,
  appendSystemMessage,
  emptyPipelineLog,
  lastPipelineError,
} from "../../utils/pipelineLog";
import { PipelineLogPanel } from "./PipelineLogPanel";

interface ScriptReviewItem {
  id: string;
  wpIndex: number;
  label: string;
  text: string;
  audioPath: string;
}

interface VideoReviewItem {
  name: string;
  url: string;
  filePath: string;
  wpId?: string;
  wpIndex?: number;
  type: "overview" | "residential" | "attraction" | "other";
  label: string;
}

type WizardStep = "generating" | "verifying" | "exporting" | "finished";

export function RenderOverlay() {
  const {
    isRendering,
    setIsRendering,
    setEditorMode,
    showToast,
    isRenderCollapsed,
    setIsRenderCollapsed,
    markedWaypointIds,
    setMarkedWaypointIds,
    generationSessionInfo,
    setGenerationSessionInfo,
    currentView,
  } = useUI();
  // StatusBar (h-7) is only mounted in the editor view (see App.tsx).
  const bottomInset = currentView === "editor" ? "bottom-7" : "bottom-0";

  const {
    metadata,
    settings,
    waypoints,
    updateWaypoint,
    updateMetadata,
    updateSettings,
    autoLoadTimeline,
    saveProject,
    setActiveWaypointId,
    timeline,
  } = useWorkspace();

  const [step, setStep] = useState<WizardStep>("generating");
  const [progress, setProgress] = useState(0);
  const [pipelineLog, setPipelineLog] = useState(emptyPipelineLog);
  const pushSystemLog = (message: string, kind: "system" | "error" = "system") =>
    setPipelineLog((prev) => appendSystemMessage(prev, message, kind));
  const [status, setStatus] = useState<
    "processing" | "success" | "error" | "cancelling"
  >("processing");
  const [renderAttempt, setRenderAttempt] = useState(0);

  // Review State
  const [reviewItems, setReviewItems] = useState<ScriptReviewItem[]>([]);
  const [videoItems, setVideoItems] = useState<VideoReviewItem[]>([]);
  const [activeAudioId, setActiveAudioId] = useState<string | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  // Audio Regeneration State
  const [editingAudioId, setEditingAudioId] = useState<string | null>(null);
  const [editingAudioText, setEditingAudioText] = useState<string>("");
  const [isRegeneratingAudio, setIsRegeneratingAudio] = useState(false);

  // Quick Export & Exporting State
  const [isQuickExportDone, setIsQuickExportDone] = useState(false);
  const [, setExportedVideoPath] = useState<string | null>(null);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  // Only takes effect in the stacked (< lg) layout; side-by-side always shows the log.
  const [isLogOpen, setIsLogOpen] = useState(true);

  // The ring follows the pipeline's own "[n/N]" stage counter (see
  // utils/pipelineLog.ts); finishing, resetting and exporting set it directly.
  useEffect(() => {
    if (pipelineLog.progress > 0) {
      setProgress((prev) => Math.max(prev, pipelineLog.progress));
    }
  }, [pipelineLog.progress]);

  // Hardware spec detection
  const hardwareSpec = detectHardwareSpec(settings.hardware_spec_override);

  // Track elapsed time during generation or export
  useEffect(() => {
    let interval: number | undefined;
    if (
      isRendering &&
      (step === "generating" || step === "exporting") &&
      status === "processing"
    ) {
      interval = window.setInterval(() => {
        setElapsedSeconds((prev) => prev + 1);
      }, 1000);
    }
    return () => clearInterval(interval);
  }, [isRendering, step, status]);

  // Reset timer on new render
  useEffect(() => {
    if (!isRendering) {
      setElapsedSeconds(0);
      setIsRenderCollapsed(false);
      setEditingAudioId(null);
      setIsRegeneratingAudio(false);
    }
  }, [isRendering, setIsRenderCollapsed]);

  // Pipeline Execution & Event Listeners
  useEffect(() => {
    if (!isRendering) {
      setStep("generating");
      setProgress(0);
      setPipelineLog(emptyPipelineLog());
      setStatus("processing");
      setActiveAudioId(null);
      setVideoItems([]);
      setReviewItems([]);
      setIsQuickExportDone(false);
      setExportedVideoPath(null);
      if (audioRef.current) audioRef.current.pause();
      return;
    }

    const configPath = `${metadata.directory_path}/job_config.json`;

    setPipelineLog(appendSystemMessage(emptyPipelineLog(), t`renderTerminalMessage`));

    // stdout and stderr go through the same parser: the tracker writes to
    // stderr, main.py's JSON result to stdout, and ffmpeg/Python logging to
    // either. utils/pipelineLog.ts decides what is progress, warning or error.
    const onPipelineOutput = (event: { payload: string }) =>
      setPipelineLog((prev) => appendPipelineOutput(prev, event.payload));

    // listen() resolves asynchronously: if this effect is cleaned up first
    // (retry, StrictMode re-mount), unregister as soon as it resolves instead
    // of leaking listeners that would print every line twice.
    let disposed = false;
    const unlisteners: Array<() => void> = [];
    const track = (unlisten: () => void) => {
      if (disposed) unlisten();
      else unlisteners.push(unlisten);
    };

    const setupListeners = async () => {
      track(await listen<string>("render-log", onPipelineOutput));
      track(await listen<string>("render-error", onPipelineOutput));

      track(await listen<string>(
        "render-finish",
        async (event) => {
          if (
            event.payload === "Success" ||
            event.payload.includes("complete")
          ) {
            setProgress(100);
            pushSystemLog(t`renderFinishSuccessMessage`);

            if (metadata.directory_path) {
              await autoLoadTimeline(metadata.directory_path);
            }

            // Branch: Quick Export vs Asset Review
            if (settings.quick_export) {
              await handleStitchAndExport(true);
            } else {
              await buildReviewItems();
              setStep("verifying");
            }
          } else if (event.payload === "Cancelled") {
            pushSystemLog(t`renderFinishCancelMessage`);
            setIsRendering(false);
          } else {
            setStatus("error");
            pushSystemLog(t`renderFinishErrorMessage`, "error");
          }
        },
      ));

      // Never start a render from an effect run that has already been torn down.
      if (disposed) return;
      invoke("start_render", { configPath }).catch((err) => {
        setStatus("error");
        pushSystemLog(t`Failed to invoke Python render: ${err}`, "error");
      });
    };

    setupListeners();

    return () => {
      disposed = true;
      unlisteners.splice(0).forEach((unlisten) => unlisten());
    };
  }, [isRendering, renderAttempt]);

  // Construct Review Items for Generated Assets
  const buildReviewItems = async () => {
    if (!metadata?.directory_path) return;
    let audioDir = await join(metadata.directory_path, "assets", "audio");
    if (!(await exists(audioDir))) {
      const legacyAudio = await join(metadata.directory_path, "audio");
      if (await exists(legacyAudio)) {
        audioDir = legacyAudio;
      }
    }

    let audioFiles: string[] = [];
    try {
      if (await exists(audioDir)) {
        const entries = await readDir(audioDir);
        audioFiles = entries.map((e) => e.name).filter(Boolean);
      }
    } catch (e) {
      console.warn("Could not inspect audio directory:", e);
    }

    const items: ScriptReviewItem[] = [];

    // 1. Overview Narration
    if (metadata.overview_narration) {
      const overviewFile =
        audioFiles.find(
          (f) => f.toLowerCase().includes("overview") && f.endsWith(".wav"),
        ) || "overview_voice.wav";
      items.push({
        id: "overview",
        wpIndex: -1,
        label: t`renderRouteOvvNarr`,
        text: metadata.overview_narration,
        audioPath: await join(audioDir, overviewFile),
      });
    }

    // 2. Waypoint Narrations
    for (let i = 0; i < waypoints.length; i++) {
      const wp = waypoints[i];
      if (wp.skipAssetGeneration || wp.isStub) continue;

      const text = wp.attractionNarration || wp.arrivingNarration || "";

      if (text.trim()) {
        const prefix = `02_waypoint_${String(i + 1).padStart(2, "0")}_`;
        const matchedFile = audioFiles.find(
          (f) => f.startsWith(prefix) && f.endsWith(".wav"),
        );
        const fallbackLabel =
          wp.name
            .replace(/[^\p{L}\p{N}_\- ]/gu, "")
            .trim()
            .replace(/\s+/g, "_") || `leg${i + 1}`;
        const finalFileName = matchedFile || `${prefix}${fallbackLabel}.wav`;

        const stopNum = i + 1;
        const stopName = wp.name;
        items.push({
          id: wp.id,
          wpIndex: i,
          label: t`Stop ${stopNum}: ${stopName}`,
          text: text,
          audioPath: await join(audioDir, finalFileName),
        });
      }
    }
    setReviewItems(items);

    // 3. Video Previews
    try {
      const manifest = await loadTimelineManifest(metadata.directory_path);
      if (manifest && manifest.video_tracks) {
        const vids: VideoReviewItem[] = manifest.video_tracks.map((v) => {
          const fileName = v.file_path.split(/[/\\]/).pop() || t`video-clip`;
          let label = fileName;
          let type: "overview" | "residential" | "attraction" | "other" =
            "other";
          let wpId: string | undefined;
          let wpIndex: number | undefined;

          if (fileName.includes("overview")) {
            type = "overview";
            label = t`routeOvvAnim`;
          } else {
            const resMatch = fileName.match(/02_waypoint_(\d+)_/);
            if (resMatch) {
              type = "residential";
              const departureIdx = parseInt(resMatch[1]) - 1;
              const wp = waypoints[departureIdx];
              const nextWp = waypoints[departureIdx + 1];
              wpIndex = departureIdx;
              wpId = wp?.id;
              label = t`Leg ${departureIdx + 1}: ${wp ? wp.name : t`Stop ` + (departureIdx + 1)} → ${nextWp ? nextWp.name : t`Next Stop`}`;
            } else {
              const attrMatch = fileName.match(/04_attraction_(\d+)_/);
              if (attrMatch) {
                type = "attraction";
                const attrIdx = parseInt(attrMatch[1]);
                const wp = waypoints[attrIdx];
                wpIndex = attrIdx;
                wpId = wp?.id;
                label = t`Attraction Video: ${wp ? wp.name : t`Stop ` + (attrIdx + 1)}`;
              }
            }
          }

          return {
            name: fileName,
            url: convertFileSrc(v.file_path),
            filePath: v.file_path,
            wpId,
            wpIndex,
            type,
            label,
          };
        });
        setVideoItems(vids);
      }
    } catch (e) {
      console.warn("Could not load video previews for verification:", e);
    }
  };

  // Play / Pause Audio
  const handleTogglePlay = (item: ScriptReviewItem) => {
    if (activeAudioId === item.id) {
      audioRef.current?.pause();
      setActiveAudioId(null);
      return;
    }
    if (audioRef.current) audioRef.current.pause();

    const safeUrl = convertFileSrc(item.audioPath);
    const newAudio = new Audio(safeUrl);

    newAudio.onended = () => setActiveAudioId(null);
    newAudio.onerror = () => {
      showToast(t`Could not load audio for ${item.label}`, "error");
      setActiveAudioId(null);
    };

    audioRef.current = newAudio;
    newAudio.play();
    setActiveAudioId(item.id);
  };

  // Audio Regeneration: Open script edit with Hiragana/Katakana guidance
  const handleInitiateAudioRegen = async (item: ScriptReviewItem) => {
    if (audioRef.current) audioRef.current.pause();
    setActiveAudioId(null);
    setEditingAudioId(item.id);
    setEditingAudioText(item.text);
  };

  // Execute single waypoint Audio Regeneration
  const handleExecuteAudioRegen = async (item: ScriptReviewItem) => {
    if (!metadata.directory_path) return;
    setIsRegeneratingAudio(true);

    try {
      const newText = editingAudioText.trim();
      // Update workspace state
      if (item.id === "overview") {
        updateMetadata({ overview_narration: newText });
      } else {
        updateWaypoint(item.id, {
          attractionNarration: newText,
          arrivingNarration: newText,
        });
      }
      // Save project configuration so Python reads updated script
      await saveProject();

      // Remove generated audio file to force re-synthesis
      try {
        if (await exists(item.audioPath)) {
          await remove(item.audioPath);
        }
      } catch (e) {
        console.warn("Could not remove stale audio file:", e);
      }

      // Trigger TTS CLI for this specific waypoint or overview
      const configPath = `${metadata.directory_path}/job_config.json`;
      const ttsPayload =
        item.id === "overview" || item.wpIndex < 0
          ? "tts overview"
          : `tts ${item.wpIndex}`;

      showToast(t`Regenerating audio for ${item.label}...`, "info");
      await invoke("run_python_blueprint", {
        action: configPath,
        payload: ttsPayload,
      });

      // Update local review items
      setReviewItems((prev) =>
        prev.map((i) => (i.id === item.id ? { ...i, text: newText } : i)),
      );
      setEditingAudioId(null);
      await buildReviewItems();
      showToast(
        t`Audio regenerated successfully for ${item.label}! Click Listen to verify pronunciation.`,
        "success",
      );
    } catch (err: any) {
      console.error("Audio regeneration failed:", err);
      showToast(t`Audio regeneration failed: ${err}`, "error");
    } finally {
      setIsRegeneratingAudio(false);
    }
  };

  // Video Regeneration Flow: Hardware branching
  const handleRegenerateVideo = async (vid: VideoReviewItem) => {
    if (audioRef.current) audioRef.current.pause();

    const spec = detectHardwareSpec(settings.hardware_spec_override);

    if (spec.isHighSpec) {
      // High-spec hardware: Switch to timeline editor view for custom adjustments
      showToast(
        t`High-spec system detected (${spec.gpuRenderer}). Opening Timeline Editor for custom video trimming and transition adjustments. (Quick export disabled).`,
        "info",
      );
      updateSettings({ quick_export: false });
      await saveProject();
      if (metadata.directory_path) {
        await autoLoadTimeline(metadata.directory_path);
      }
      setIsRendering(false);
      setEditorMode("timeline");
    } else {
      // Low-spec hardware (e.g. Ryzen 5 5600GE with Radeon Graphics):
      // Invalidate existing clip on disk so resumption re-renders this leg
      if (vid.filePath) {
        try {
          if (await exists(vid.filePath)) {
            await remove(vid.filePath);
          }
          if (vid.filePath.includes("_subtitled")) {
            const rawPath = vid.filePath.replace("_subtitled", "");
            if (await exists(rawPath)) {
              await remove(rawPath);
            }
          }
        } catch (e) {
          console.warn("Could not remove stale video file:", e);
        }
      }

      // Remove .render_manifest.json so render_step doesn't skip
      if (metadata.directory_path) {
        try {
          const manifests = [
            await join(
              metadata.directory_path,
              "assets",
              "video",
              "route",
              ".render_manifest.json",
            ),
            await join(
              metadata.directory_path,
              "assets",
              "video",
              ".render_manifest.json",
            ),
            await join(
              metadata.directory_path,
              "video",
              ".render_manifest.json",
            ),
          ];
          for (const m of manifests) {
            if (await exists(m)) {
              await remove(m);
            }
          }
        } catch (e) {
          console.warn("Could not remove render manifest:", e);
        }
      }

      // Return to Map Editor and pre-select that waypoint layer in WaypointEditor
      const targetWpId = vid.wpId || (waypoints[0] ? waypoints[0].id : null);
      if (targetWpId) {
        setActiveWaypointId(targetWpId);
        setMarkedWaypointIds((prev) =>
          Array.from(new Set([...prev, targetWpId])),
        );
      }

      setEditorMode("map");
      setIsRenderCollapsed(true);
      setGenerationSessionInfo({
        waypointId: targetWpId || undefined,
        activeLeg: vid.label,
        message: t`lowSpecGenSessionMessage`,
      });

      showToast(
        t`Low-spec system: Opened Waypoint Editor for ${vid.label}. Adjust image, script, or route mode, then click Resume Generation.`,
        "warning",
      );
    }
  };

  // Stitch videos together and export automatically
  const handleStitchAndExport = async (isQuickExport = false) => {
    setStep("exporting");
    setStatus("processing");
    if (audioRef.current) audioRef.current.pause();

    try {
      showToast(
        isQuickExport ? t`quickExportToastMsg1` : t`quickExportToastMsg2`,
        "info",
      );

      // 1. Ensure timeline manifest is saved if clips exist
      if (
        metadata.directory_path &&
        timeline &&
        timeline.clips &&
        timeline.clips.length > 0
      ) {
        await saveTimelineManifest(
          metadata.directory_path,
          metadata.project_name || t`saveTimelineProjectNameDefault`,
          timeline,
        );
      }

      // 2. Invoke video export stitching command
      try {
        await invoke("export_video", {
          projectDir: metadata.directory_path,
        });
      } catch (exportErr) {
        // Fallback to concat if render_timeline isn't supported
        console.warn(
          "export_video invoke failed, falling back to concat:",
          exportErr,
        );
        await invoke("run_python_blueprint", {
          action: `${metadata.directory_path}/job_config.json`,
          payload: "concat",
        });
      }

      // Play success chime
      try {
        const AudioCtx =
          window.AudioContext || (window as any).webkitAudioContext;
        const ctx = new AudioCtx();
        const playNote = (
          freq: number,
          startTime: number,
          duration: number,
        ) => {
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.type = "sine";
          osc.frequency.setValueAtTime(freq, ctx.currentTime);
          gain.gain.setValueAtTime(0, startTime);
          gain.gain.linearRampToValueAtTime(0.3, startTime + 0.05);
          gain.gain.exponentialRampToValueAtTime(0.001, startTime + duration);
          osc.connect(gain);
          gain.connect(ctx.destination);
          osc.start(startTime);
          osc.stop(startTime + duration);
        };
        playNote(523.25, ctx.currentTime, 0.4);
        playNote(659.25, ctx.currentTime + 0.15, 0.6);
      } catch (e) {
        console.warn("Audio chime failed:", e);
      }

      setIsQuickExportDone(isQuickExport);
      setExportedVideoPath(`${metadata.directory_path}/video`);
      setStep("finished");
      setStatus("success");
      showToast(t`exportSuccessToastMsg`, "success");
    } catch (err: any) {
      console.error("Stitching / export failed:", err);
      setStatus("error");
      showToast(t`Export failed: ${err?.message || err}`, "error");
    }
  };

  // Resume generation session after user finishes editing in MapEditor
  const handleResumeGeneration = async () => {
    // 1. Invalidate cached outputs for marked waypoints
    if (metadata.directory_path && markedWaypointIds.length > 0) {
      for (const wpId of markedWaypointIds) {
        const wpIdx = waypoints.findIndex((w) => w.id === wpId);
        if (wpIdx >= 0) {
          const prefix = `02_waypoint_${String(wpIdx + 1).padStart(2, "0")}_`;
          const routeVideoDir = await join(
            metadata.directory_path,
            "assets",
            "video",
            "route",
          );
          if (await exists(routeVideoDir)) {
            try {
              const entries = await readDir(routeVideoDir);
              for (const entry of entries) {
                if (entry.name && entry.name.startsWith(prefix)) {
                  await remove(await join(routeVideoDir, entry.name));
                }
              }
            } catch (e) {
              console.warn("Could not invalidate video files:", e);
            }
          }
          const manifestPath = await join(
            routeVideoDir,
            ".render_manifest.json",
          );
          if (await exists(manifestPath)) {
            await remove(manifestPath);
          }
        }
      }
      setMarkedWaypointIds([]);
    }

    // 2. Save project configuration before restarting render
    await saveProject();

    setIsRenderCollapsed(false);
    setGenerationSessionInfo(null);
    setStep("generating");
    setProgress(0);
    setStatus("processing");
    setPipelineLog(emptyPipelineLog());
    setRenderAttempt((prev) => prev + 1);
  };

  // Open output folder in OS file explorer
  const handleOpenExplorer = async () => {
    if (!metadata.directory_path) return;
    try {
      await invoke("open_in_explorer", { path: metadata.directory_path });
    } catch (e) {
      console.warn("open_in_explorer failed:", e);
    }
  };

  const handleCancel = async () => {
    setStatus("cancelling");
    pushSystemLog(t`Sending cancellation signal to backend...`);

    try {
      const result = await invoke<string>("cancel_render");
      if (result === "No active process to cancel") {
        setIsRendering(false);
        setIsRenderCollapsed(false);
      }
    } catch (err) {
      console.warn("Cancellation invoke failed:", err);
      setIsRendering(false);
      setIsRenderCollapsed(false);
    }
  };

  if (!isRendering) return null;

  // --- COLLAPSED SESSION PILL (Renders when low-spec user is returned to map editor) ---
  if (isRenderCollapsed) {
    return createPortal(
      <div className="fixed bottom-10 right-4 z-99999 animate-in slide-in-from-bottom-5 duration-300">
        <div className="bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl border border-amber-500/40 rounded-2xl shadow-[0_10px_40px_-10px_rgba(0,0,0,0.5)] p-4 flex flex-col gap-3 max-w-[min(24rem,calc(100vw-2rem))]">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-xl bg-amber-500/10 flex items-center justify-center text-amber-500">
                <Sparkles className="w-4 h-4 animate-pulse" />
              </div>
              <div>
                <h4 className="text-xs font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-1.5">
                  <Trans>Generation On Hold</Trans>
                  <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-950/60 text-amber-700 dark:text-amber-400">
                    <Trans>Low-Spec Mode</Trans>
                  </span>
                </h4>
                <p className="text-[11px] text-zinc-500 truncate max-w-56">
                  {generationSessionInfo?.activeLeg ||
                    t`Editing Waypoint on Map`}
                </p>
              </div>
            </div>
            <button
              onClick={() => setIsRenderCollapsed(false)}
              className="p-1 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400 hover:text-zinc-600 transition-colors"
              title={t`Expand Review`}
            >
              <Maximize2 className="w-4 h-4" />
            </button>
          </div>

          <p className="text-[10px] text-zinc-500 dark:text-zinc-400 leading-snug">
            <Trans>
              Edit the image, script, or route mode in the Waypoint Editor.
              Click Resume when ready to re-render
            </Trans>
          </p>

          <div className="flex items-center gap-2 pt-1 border-t border-zinc-100 dark:border-zinc-800/80">
            <button
              onClick={() => {
                setIsRendering(false);
                setIsRenderCollapsed(false);
              }}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
            >
              <Trans>Discard</Trans>
            </button>
            <button
              onClick={() => setIsRenderCollapsed(false)}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
            >
              <Trans>Review Assets</Trans>
            </button>
            <button
              onClick={handleResumeGeneration}
              className="ml-auto px-4 py-1.5 bg-navi-500 hover:bg-navi-600 text-white rounded-lg text-xs font-bold shadow-md shadow-navi-500/20 transition-all flex items-center gap-1.5"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <Trans>Resume Generation</Trans>
            </button>
          </div>
        </div>
      </div>,
      document.body,
    );
  }

  // --- FULL MODAL WIZARD ---
  // The overlay is pinned between the custom TitleBar (h-10) and StatusBar (h-7),
  // both z-9999, so no part of the modal can slide underneath them. The modal
  // never exceeds that area: the wizard body and the log scroll internally.
  return createPortal(
    <div
      style={{ zIndex: 9998 }}
      className={`fixed inset-x-0 top-10 ${bottomInset} pointer-events-auto flex overflow-hidden p-3 sm:p-5 short:p-2 animate-in fade-in duration-300`}
    >
      <div className="m-auto flex flex-col lg:flex-row gap-3 w-full max-w-7xl h-full max-h-215 min-h-0 pointer-events-none">
        <div className="flex-1 min-h-0 min-w-0 bg-white dark:bg-zinc-950 rounded-2xl shadow-[0_0_80px_-15px_rgba(0,0,0,0.5)] border border-zinc-200 dark:border-zinc-800/80 flex flex-col overflow-hidden animate-in zoom-in-95 duration-400 pointer-events-auto select-none">
          {/* Header */}
          <div className="px-5 sm:px-6 py-4 short:py-2.5 border-b border-zinc-100 dark:border-zinc-800/80 bg-zinc-50/50 dark:bg-zinc-900/20 shrink-0">
            <div className="flex items-center justify-between gap-4 mb-5 short:mb-2.5">
              <div className="min-w-0">
                <div className="flex items-center gap-2 min-w-0">
                  <h2
                    className="text-lg short:text-base font-semibold text-zinc-900 dark:text-zinc-100 tracking-tight truncate"
                    title={metadata.project_name}
                  >
                    {metadata.project_name}
                  </h2>
                  {settings.quick_export && (
                    <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-500 text-[10px] font-bold shrink-0 text-nowrap">
                      <Zap className="w-3 h-3 fill-amber-500" />
                      <Trans>Quick Export</Trans>
                    </span>
                  )}
                </div>
                <p
                  className="text-xs text-zinc-500 font-medium flex items-center gap-1.5 mt-0.5 min-w-0"
                  title={hardwareSpec.details}
                >
                  <Cpu className="w-3.5 h-3.5 shrink-0" />
                  <span className="truncate">{hardwareSpec.details}</span>
                </p>
              </div>
              {status === "processing" && step === "generating" && (
                <button
                  onClick={handleCancel}
                  className="flex items-center gap-2 px-4 py-2 short:py-1.5 shrink-0 bg-zinc-100 hover:bg-red-50 text-zinc-600 hover:text-red-600 dark:bg-zinc-800/50 dark:hover:bg-red-500/10 dark:text-zinc-400 dark:hover:text-red-400 text-sm font-medium rounded-lg transition-all text-nowrap"
                >
                  <X className="w-4 h-4" /> <Trans>Cancel</Trans>
                </button>
              )}
              {status === "error" && (
                <div className="flex items-center gap-2 shrink-0 text-red-500 bg-red-50 dark:bg-red-500/10 px-4 py-2 short:py-1.5 rounded-lg">
                  <XCircle className="w-4 h-4" />
                  <span className="text-sm font-medium text-nowrap">
                    <Trans>Failed</Trans>
                  </span>
                </div>
              )}
            </div>

            {/* Stepper */}
            {/* Equal-width columns keep every circle centred in its column, so
                each connector can span from its own circle's edge to the next
                circle's edge (left: 50% + r, right: -50% + r) at the circles'
                vertical centre, never touching the labels below. */}
            <div className="flex items-start">
              {[
                {
                  id: "generating",
                  label: t`Build Assets`,
                  desc: t`Rendering & Synthesis`,
                },
                {
                  id: "verifying",
                  label: t`Review Assets`,
                  desc: settings.quick_export
                    ? t`Auto-skipped (Quick Export)`
                    : t`Check Audio & Video`,
                },
                {
                  id: "finished",
                  label: t`Export`,
                  desc: t`Auto-stitched Video`,
                },
              ].map((s, i, steps) => {
                const stepIndex = [
                  "generating",
                  "verifying",
                  "exporting",
                  "finished",
                ].indexOf(step);
                const isActive =
                  step === s.id ||
                  (s.id === "finished" && step === "exporting");
                const isPast = stepIndex > i;
                // The connector to the next step fills once that step is reached.
                const isConnectorDone = stepIndex >= i + 1;
                return (
                  <div
                    key={s.id}
                    className="relative flex-1 min-w-0 flex flex-col items-center gap-2 short:gap-1 px-1"
                  >
                    {i < steps.length - 1 && (
                      <div
                        aria-hidden
                        className="absolute top-5 short:top-3.5 left-[calc(50%+1.75rem)] right-[calc(-50%+1.75rem)] short:left-[calc(50%+1.375rem)] short:right-[calc(-50%+1.375rem)] h-0.5 -translate-y-1/2 rounded-full bg-zinc-200 dark:bg-zinc-800 overflow-hidden"
                      >
                        <div
                          className={`h-full bg-navi-500 rounded-full origin-left transition-transform duration-700 ease-in-out ${
                            isConnectorDone ? "scale-x-100" : "scale-x-0"
                          }`}
                        />
                      </div>
                    )}
                    <div
                      className={`relative w-10 h-10 short:w-7 short:h-7 shrink-0 rounded-full flex items-center justify-center border-2 text-sm short:text-xs font-medium transition-all duration-300 ${
                        isActive
                          ? "border-navi-500 bg-navi-500 text-white ring-4 short:ring-2 ring-navi-500/20"
                          : isPast
                            ? "border-navi-500 bg-navi-500 text-white"
                            : "border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-400"
                      }`}
                    >
                      {isPast ? (
                        <CheckCircle className="w-5 h-5 short:w-4 short:h-4" />
                      ) : (
                        i + 1
                      )}
                    </div>
                    <div className="text-center min-w-0 max-w-full">
                      <div
                        className={`text-xs font-semibold tracking-wide truncate ${isActive ? "text-navi-500" : isPast ? "text-zinc-800 dark:text-zinc-200" : "text-zinc-400"}`}
                      >
                        {s.label}
                      </div>
                      <div className="text-[10px] text-zinc-500 mt-0.5 truncate hidden sm:block short:hidden">
                        {s.desc}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Dynamic Wizard Body */}
          <div className="flex-1 min-h-0 bg-white dark:bg-zinc-950 overflow-y-auto custom-scrollbar flex flex-col">
            {/* STEP 1: GENERATING */}
            {step === "generating" && (
              <div className="flex-1 flex flex-col items-center justify-center text-center animate-in fade-in duration-500 py-10 short:py-5 px-5 sm:px-6">
                {status === "processing" ? (
                  <div className="w-full max-w-2xl mx-auto flex flex-col items-center">
                    <div className="relative w-24 h-24 short:w-18 short:h-18 mx-auto mb-6 short:mb-3">
                      <div className="absolute inset-0 border-4 border-zinc-100 dark:border-zinc-800 rounded-full"></div>
                      <svg
                        className="absolute inset-0 w-full h-full -rotate-90"
                        viewBox="0 0 100 100"
                      >
                        <circle
                          className="text-navi-500 transition-all duration-300 ease-out"
                          strokeWidth="8"
                          stroke="currentColor"
                          fill="transparent"
                          r="46"
                          cx="50"
                          cy="50"
                          strokeDasharray="289.027"
                          strokeDashoffset={
                            289.027 - (289.027 * progress) / 100
                          }
                          strokeLinecap="round"
                        />
                      </svg>
                      <div className="absolute inset-0 flex items-center justify-center">
                        <span className="text-xl font-bold text-zinc-900 dark:text-zinc-100">
                          {progress}%
                        </span>
                      </div>
                    </div>

                    <h3 className="text-2xl short:text-xl font-bold text-zinc-900 dark:text-zinc-100 mb-2">
                      {settings.quick_export
                        ? t`Generating Assets (Quick Export Mode)...`
                        : t`Generating Assets...`}
                    </h3>

                    <div className="mt-4 short:mt-2 px-5 py-3 bg-zinc-50 dark:bg-zinc-900/60 border border-zinc-200 dark:border-zinc-800 rounded-xl flex items-center justify-between gap-4 w-full max-w-md">
                      <div className="flex items-center gap-3 min-w-0">
                        <Loader2 className="w-4 h-4 text-navi-500 animate-spin shrink-0" />
                        <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300 truncate text-left">
                          {(() => {
                            // Named after the current "[n/N]" stage, with the
                            // live item counter (e.g. "3/5") from the tracker's
                            // latest line — never from ffmpeg or warnings.
                            const stageTitle =
                              pipelineLog.stages[pipelineLog.stages.length - 1]
                                ?.title ?? "";
                            const current = pipelineLog.current;
                            if (!current) return t`Initializing pipeline...`;

                            const fractionMatch =
                              current.match(/\b(\d+\/\d+)\b/);
                            const prog = fractionMatch
                              ? ` ${fractionMatch[1]}`
                              : "";

                            if (/parsing gps/i.test(stageTitle))
                              return t`Parsing Maps & GPS Data${prog}...`;
                            if (/tts narration/i.test(stageTitle))
                              return t`Synthesizing AI Voiceovers${prog}...`;
                            if (/^generating subtitles/i.test(stageTitle))
                              return t`Generating Subtitles${prog}...`;
                            if (/^generating attraction videos/i.test(stageTitle))
                              return t`Rendering Media & Animations${prog}...`;
                            if (/rendering overview/i.test(stageTitle))
                              return t`Rendering Route Video${prog}...`;
                            if (/intro\/outro/i.test(stageTitle))
                              return t`Finalizing Project Timeline...`;

                            return current;
                          })()}
                        </span>
                      </div>
                      <div className="text-xs font-semibold text-zinc-400 tabular-nums tracking-wider shrink-0">
                        {Math.floor(elapsedSeconds / 60)}:
                        {(elapsedSeconds % 60).toString().padStart(2, "0")}
                      </div>
                    </div>
                  </div>
                ) : status === "cancelling" ? (
                  <div className="flex flex-col items-center justify-center">
                    <Loader2 className="w-12 h-12 text-red-500 animate-spin mb-6 mx-auto" />
                    <h3 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">
                      <Trans>Cancelling process...</Trans>
                    </h3>
                    <p className="text-sm text-zinc-500 mt-2">
                      <Trans>Sending interrupt signal to renderer.</Trans>
                    </p>
                  </div>
                ) : status === "error" ? (
                  <div className="flex flex-col items-center justify-center w-full max-w-lg mx-auto text-center">
                    <div className="w-20 h-20 short:w-14 short:h-14 bg-red-50 dark:bg-red-500/10 rounded-full flex items-center justify-center mx-auto mb-6 short:mb-3">
                      <AlertTriangle className="w-10 h-10 text-red-500" />
                    </div>
                    <h3 className="text-2xl font-bold text-zinc-900 dark:text-zinc-100 mb-2">
                      <Trans>Generation Failed</Trans>
                    </h3>
                    <div className="mt-4 p-4 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/50 rounded-xl text-left w-full">
                      <h4 className="text-sm font-bold text-red-800 dark:text-red-400 mb-1">
                        <Trans>Error Details:</Trans>
                      </h4>
                      <p className="text-sm text-red-600 dark:text-red-300 wrap-break-word select-text">
                        {lastPipelineError(pipelineLog) ??
                          t`An unknown error occurred during rendering.`}
                      </p>
                    </div>
                  </div>
                ) : null}
              </div>
            )}

            {/* STEP 2: VERIFYING / ASSET REVIEW */}
            {step === "verifying" && (
              <div className="flex-1 flex flex-col gap-6 short:gap-4 animate-in slide-in-from-right-8 duration-500 p-5 sm:p-6 short:p-4">
                {/* Hardware Guidance Banner */}
                <div className="bg-zinc-50 dark:bg-zinc-900/60 border border-zinc-200 dark:border-zinc-800 rounded-xl p-4 short:p-3 flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-3 min-w-0 flex-1 basis-64">
                    <Cpu className="w-5 h-5 text-navi-500 shrink-0" />
                    <div>
                      <h4 className="text-xs font-bold text-zinc-900 dark:text-zinc-100">
                        <Trans>System Capability Check:</Trans>
                        {hardwareSpec.isHighSpec
                          ? t`High-Spec (Discrete GPU)`
                          : t`Low-Spec (Integrated Graphics)`}
                      </h4>
                      <p className="text-[11px] text-zinc-500 mt-0.5">
                        {hardwareSpec.isHighSpec
                          ? t`Regenerating a video leg will switch to the Timeline Editor for manual customization`
                          : t`Regenerating a video leg will return to the Map Editor with the active layer opened to adjust images, script, or route mode`}
                      </p>
                    </div>
                  </div>
                  <span
                    className="text-[10px] font-mono px-2 py-1 rounded bg-zinc-200 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 max-w-full truncate"
                    title={hardwareSpec.gpuRenderer}
                  >
                    {hardwareSpec.gpuRenderer.substring(0, 30)}
                  </span>
                </div>

                {/* Video Review Section */}
                {videoItems.length > 0 && (
                  <div className="space-y-4">
                    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-zinc-900 dark:text-zinc-100">
                      <div className="flex items-center gap-2">
                        <Film className="w-5 h-5 text-navi-500 shrink-0" />
                        <h3 className="text-sm font-semibold tracking-wide uppercase">
                          <Trans>Rendered Videos ({videoItems.length})</Trans>
                        </h3>
                      </div>
                      <span className="text-xs text-zinc-500">
                        <Trans>
                          Verify that video visuals are factually correct
                        </Trans>
                      </span>
                    </div>

                    <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,17rem),1fr))] gap-4">
                      {videoItems.map((vid, idx) => (
                        <div
                          key={idx}
                          className="group bg-zinc-100 dark:bg-zinc-900 rounded-xl overflow-hidden border border-zinc-200 dark:border-zinc-800 transition-all flex flex-col"
                        >
                          <div className="relative aspect-video bg-black flex items-center justify-center">
                            <video
                              src={vid.url}
                              controls
                              preload="metadata"
                              className="w-full h-full object-cover"
                            />
                          </div>
                          <div className="p-3 bg-white dark:bg-zinc-900/90 border-t border-zinc-200 dark:border-zinc-800 flex items-center justify-between gap-2">
                            <div className="min-w-0">
                              <p
                                className="text-xs font-bold text-zinc-800 dark:text-zinc-200 truncate"
                                title={vid.label}
                              >
                                {vid.label}
                              </p>
                              <p className="text-[10px] text-zinc-400 font-mono truncate">
                                {vid.name}
                              </p>
                            </div>
                            {vid.type === "residential" && (
                              <button
                                onClick={() => handleRegenerateVideo(vid)}
                                className="px-3 py-1.5 rounded-lg bg-zinc-100 hover:bg-amber-500/10 text-zinc-700 hover:text-amber-600 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:text-amber-400 text-xs font-semibold shrink-0 transition-colors flex items-center gap-1.5"
                                title={t`Regenerate this specific residential leg`}
                              >
                                <RotateCcw className="w-3.5 h-3.5" />
                                <Trans>Regenerate</Trans>
                              </button>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Audio & Script Review Section */}
                <div className="space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-zinc-900 dark:text-zinc-100">
                    <div className="flex items-center gap-2">
                      <Mic className="w-5 h-5 text-navi-500 shrink-0" />
                      <h3 className="text-sm font-semibold tracking-wide uppercase">
                        <Trans>
                          Audio Narration & Pronunciation Review (
                          {reviewItems.length})
                        </Trans>
                      </h3>
                    </div>
                    <span className="text-xs text-zinc-500">
                      <Trans>
                        Listen to ensure Irodori TTS pronunciation is accurate
                      </Trans>
                    </span>
                  </div>

                  {reviewItems.length === 0 ? (
                    <div className="px-4 py-8 text-center bg-zinc-50 dark:bg-zinc-900/50 rounded-xl border border-dashed border-zinc-200 dark:border-zinc-800">
                      <p className="text-sm text-zinc-500 italic">
                        <Trans>
                          No voiceover scripts were found in this generation.
                        </Trans>
                      </p>
                    </div>
                  ) : (
                    <div className="grid gap-4">
                      {reviewItems.map((item) => {
                        const isEditing = editingAudioId === item.id;

                        return (
                          <div
                            key={item.id}
                            className="bg-white dark:bg-zinc-900/40 border border-zinc-200 dark:border-zinc-800/80 rounded-xl p-4 shadow-sm hover:shadow-md transition-shadow"
                          >
                            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                              <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 min-w-0 truncate">
                                {item.label}
                              </span>
                              <div className="flex items-center gap-2 shrink-0">
                                <button
                                  onClick={() => handleTogglePlay(item)}
                                  className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold transition-all ${
                                    activeAudioId === item.id
                                      ? "bg-navi-100 text-navi-700 dark:bg-navi-500/20 dark:text-navi-400"
                                      : "bg-zinc-100 text-zinc-700 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
                                  }`}
                                >
                                  <PlayCircle
                                    className={`w-4 h-4 ${activeAudioId === item.id ? "animate-pulse" : ""}`}
                                  />
                                  {activeAudioId === item.id
                                    ? t`Playing...`
                                    : t`Listen`}
                                </button>

                                {!isEditing && (
                                  <button
                                    onClick={() =>
                                      handleInitiateAudioRegen(item)
                                    }
                                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-amber-50 hover:bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400 dark:hover:bg-amber-900/50 transition-colors"
                                    title={t`Clear generated audio and re-enter pronunciation`}
                                  >
                                    <RotateCcw className="w-3.5 h-3.5" />
                                    <Trans>Regenerate Audio</Trans>
                                  </button>
                                )}
                              </div>
                            </div>

                            {/* Editing Mode: Japanese Hiragana / Katakana Guidance */}
                            {isEditing ? (
                              <div className="space-y-3 p-4 bg-amber-50/50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-900/50 rounded-xl animate-in fade-in duration-300">
                                <div className="flex items-start gap-2.5">
                                  <Info className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                                  <div>
                                    <h4 className="text-xs font-bold text-amber-900 dark:text-amber-300">
                                      <Trans>
                                        Japanese Pronunciation & Intonation
                                        Guidance
                                      </Trans>
                                    </h4>
                                    <p className="text-[11px] text-amber-800 dark:text-amber-400 leading-relaxed mt-0.5">
                                      <Trans>
                                        If Irodori TTS mispronounces words or
                                        lacks intonation, input the script
                                        reading in <strong>Hiragana</strong> or{" "}
                                        <strong>Katakana</strong> (e.g. ひらがな
                                        / カタカチE instead of Kanji. Kanji
                                        characters lack explicit pitch-accent
                                        information.
                                      </Trans>
                                    </p>
                                  </div>
                                </div>

                                <textarea
                                  value={editingAudioText}
                                  onChange={(e) =>
                                    setEditingAudioText(e.target.value)
                                  }
                                  className="w-full bg-white dark:bg-zinc-950 border border-amber-300 dark:border-amber-800 rounded-lg p-3 text-sm text-zinc-800 dark:text-zinc-200 focus:outline-none focus:ring-2 focus:ring-amber-500/50 resize-y min-h-24 custom-scrollbar"
                                  placeholder={t`Enter pronunciation reading in Hiragana/Katakana...`}
                                />

                                <div className="flex items-center justify-end gap-2">
                                  <button
                                    onClick={() => setEditingAudioId(null)}
                                    disabled={isRegeneratingAudio}
                                    className="px-3 py-1.5 text-xs font-semibold text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded-lg transition-colors"
                                  >
                                    <Trans>Cancel</Trans>
                                  </button>
                                  <button
                                    onClick={() =>
                                      handleExecuteAudioRegen(item)
                                    }
                                    disabled={isRegeneratingAudio}
                                    className="px-4 py-1.5 bg-amber-600 hover:bg-amber-700 text-white rounded-lg text-xs font-bold shadow transition-colors flex items-center gap-1.5"
                                  >
                                    {isRegeneratingAudio ? (
                                      <>
                                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                        <Trans>Synthesizing...</Trans>
                                      </>
                                    ) : (
                                      <>
                                        <Mic className="w-3.5 h-3.5" />
                                        <Trans>Synthesize Audio Now</Trans>
                                      </>
                                    )}
                                  </button>
                                </div>
                              </div>
                            ) : (
                              <p className="text-xs text-zinc-600 dark:text-zinc-400 bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg p-3 leading-relaxed wrap-break-word">
                                {item.text || t`(Empty script)`}
                              </p>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* STEP 3: EXPORTING (AUTO-STITCHING) */}
            {step === "exporting" && (
              <div className="flex-1 flex flex-col items-center justify-center text-center animate-in fade-in duration-500 py-10 short:py-5 px-5 sm:px-6">
                <Loader2 className="w-14 h-14 short:w-10 short:h-10 text-navi-500 animate-spin mb-6 short:mb-3 mx-auto" />
                <h3 className="text-2xl font-bold text-zinc-900 dark:text-zinc-100 mb-2">
                  <Trans>Stitching Videos & Finalizing Export...</Trans>
                </h3>
                <p className="text-sm text-zinc-500 max-w-md">
                  <Trans>
                    Combining all route segments, narration voiceovers, and
                    transitions into your completed master navigation video.
                  </Trans>
                </p>
              </div>
            )}

            {/* STEP 4: FINISHED / EXPORT COMPLETE */}
            {step === "finished" && (
              <div className="flex-1 flex flex-col items-center justify-center text-center animate-in zoom-in-95 duration-500 py-10 short:py-5 px-5 sm:px-6">
                <div className="w-20 h-20 short:w-14 short:h-14 bg-emerald-50 dark:bg-emerald-500/10 rounded-full flex items-center justify-center mx-auto mb-6 short:mb-3">
                  <CheckCircle className="w-10 h-10 text-emerald-500" />
                </div>
                <h3 className="text-2xl font-bold text-zinc-900 dark:text-zinc-100 mb-2">
                  {isQuickExportDone
                    ? t`Quick Export Complete!`
                    : t`Video Exported Successfully!`}
                </h3>
                <p className="text-sm text-zinc-500 max-w-md mb-6 leading-relaxed">
                  {isQuickExportDone
                    ? t`All media was automatically generated, stitched, and exported to your project folder without stopping for manual review`
                    : t`Assets accepted and stitched into your final deliverable video`}
                </p>

                {isQuickExportDone && (
                  <div className="bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-900/40 rounded-xl p-3 max-w-md text-left mb-6">
                    <p className="text-[11px] text-amber-800 dark:text-amber-300">
                      <Trans>
                        💡 <strong>Quick Export Notice:</strong> To customize
                        individual video clips or fix TTS pronunciation, uncheck
                        "Quick Export" in generation settings and re-run.
                      </Trans>
                    </p>
                  </div>
                )}

                <div className="flex flex-wrap items-center justify-center gap-3">
                  <button
                    onClick={handleOpenExplorer}
                    className="px-5 py-2.5 bg-zinc-100 hover:bg-zinc-200 text-zinc-800 dark:bg-zinc-800 dark:hover:bg-zinc-700 dark:text-zinc-200 text-xs font-semibold rounded-xl transition-all flex items-center gap-2"
                  >
                    <Folder className="w-4 h-4" />{" "}
                    <Trans>Open Project Folder</Trans>
                  </button>
                  {!isQuickExportDone && (
                    <button
                      onClick={async () => {
                        if (metadata.directory_path) {
                          await autoLoadTimeline(metadata.directory_path);
                        }
                        setIsRendering(false);
                        setEditorMode("timeline");
                      }}
                      className="px-5 py-2.5 bg-zinc-800 hover:bg-zinc-700 text-white text-xs font-semibold rounded-xl transition-all flex items-center gap-2"
                    >
                      <Film className="w-4 h-4" />{" "}
                      <Trans>View in Timeline</Trans>
                    </button>
                  )}
                  <button
                    onClick={() => setIsRendering(false)}
                    className="px-6 py-2.5 bg-navi-500 hover:bg-navi-600 text-white text-xs font-bold rounded-xl shadow-lg shadow-navi-500/20 transition-all flex items-center gap-2"
                  >
                    <CheckCircle className="w-4 h-4" /> <Trans>Done</Trans>
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Action Footer for Verifying Step */}
          {step === "verifying" && (
            <div className="px-5 sm:px-6 py-4 short:py-3 border-t border-zinc-100 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 flex flex-wrap items-center justify-between gap-3 shrink-0">
              <span className="text-xs text-zinc-500 flex items-center gap-1.5 min-w-0">
                <Settings2 className="w-4 h-4 shrink-0" />
                <Trans>Accept assets to automatically stitch and export</Trans>
              </span>
              <div className="flex flex-wrap items-center gap-3 ml-auto">
                <button
                  onClick={async () => {
                    if (metadata.directory_path) {
                      await autoLoadTimeline(metadata.directory_path);
                    }
                    setIsRendering(false);
                    setEditorMode("timeline");
                  }}
                  className="px-4 py-2.5 bg-zinc-100 hover:bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700 text-xs font-semibold rounded-xl transition-all flex items-center gap-2"
                >
                  <Film className="w-4 h-4" />
                  <Trans>Customize in Timeline</Trans>
                </button>
                <button
                  onClick={() => handleStitchAndExport(false)}
                  className="px-6 py-2.5 bg-navi-500 hover:bg-navi-600 text-white text-sm font-semibold rounded-xl shadow-lg shadow-navi-500/20 transition-all hover:scale-[1.02] active:scale-[0.98] flex items-center gap-2"
                >
                  <CheckCircle className="w-4 h-4" />
                  <Trans>Accept Assets & Export Video</Trans>
                </button>
              </div>
            </div>
          )}

          {/* Error Fallback */}
          {status === "error" && (
            <div className="px-5 sm:px-6 py-3 bg-zinc-50 dark:bg-zinc-950 border-t border-zinc-100 dark:border-zinc-800 flex justify-end shrink-0 gap-3">
              <button
                onClick={async () => {
                  try {
                    await invoke("cancel_render");
                  } catch {
                    // No live child after failure
                  }
                  setStatus("processing");
                  setStep("generating");
                  setProgress(0);
                  setPipelineLog(emptyPipelineLog());
                  setRenderAttempt((attempt) => attempt + 1);
                }}
                className="px-5 py-2.5 bg-zinc-800 text-zinc-200 text-sm font-semibold rounded-lg hover:bg-zinc-700 transition-colors"
              >
                <Trans>Retry</Trans>
              </button>
            </div>
          )}
        </div>

        {/* Pipeline log — a fixed-height, collapsible strip when stacked
            (< lg); a full-height side column when side by side. */}
        <PipelineLogPanel
          log={pipelineLog}
          isRunning={
            status === "processing" &&
            (step === "generating" || step === "exporting")
          }
          isOpen={isLogOpen}
          onToggleOpen={() => setIsLogOpen((open) => !open)}
        />
      </div>
    </div>,
    document.body,
  );
}
