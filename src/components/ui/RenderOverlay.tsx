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

interface LogItem {
  id: string;
  message: string;
  type: "info" | "error" | "system";
  time: string;
}

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
  } = useUI();

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
  const [logs, setLogs] = useState<LogItem[]>([]);
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
  const scrollRef = useRef<HTMLDivElement>(null);

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

  // Auto-scroll terminal smoothly
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  // Pipeline Execution & Event Listeners
  useEffect(() => {
    if (!isRendering) {
      setStep("generating");
      setProgress(0);
      setLogs([]);
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

    setLogs([
      {
        id: crypto.randomUUID(),
        message: t`renderTerminalMessage`,
        type: "system",
        time: new Date().toLocaleTimeString([], { hour12: false }),
      },
    ]);

    const applyProgressFromText = (text: string) => {
      const ratioMatch = text.match(/\[(\d+)\/(\d+)\]/);
      if (ratioMatch) {
        const current = parseInt(ratioMatch[1]);
        const total = parseInt(ratioMatch[2]);
        setProgress(20 + Math.floor((current / total) * 70));
      } else if (text.includes(t`renderTerminalStep1`)) {
        setProgress(10);
      } else if (text.includes(t`renderTerminalStep4`)) {
        setProgress(90);
      } else if (
        text.includes(t`renderTerminalStep6`) ||
        text.includes(t`renderTerminalTimeline`)
      ) {
        setProgress(100);
      }
    };

    const isTrackerLine = (text: string) => /^\[\d{2}:\d{2}\]/.test(text);

    const setupListeners = async () => {
      const unlistenLog = await listen<string>("render-log", (event) => {
        const text = event.payload;
        applyProgressFromText(text);

        setLogs((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            message: text,
            type: text.includes("[WARNING]") ? "error" : "info",
            time: new Date().toLocaleTimeString([], { hour12: false }),
          },
        ]);
      });

      const unlistenError = await listen<string>("render-error", (event) => {
        const text = event.payload;
        const isProgress = isTrackerLine(text);
        if (isProgress) applyProgressFromText(text);

        setLogs((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            message: text,
            type: isProgress ? "info" : "error",
            time: new Date().toLocaleTimeString([], { hour12: false }),
          },
        ]);
      });

      const unlistenFinish = await listen<string>(
        "render-finish",
        async (event) => {
          if (
            event.payload === "Success" ||
            event.payload.includes("complete")
          ) {
            setProgress(100);
            setLogs((prev) => [
              ...prev,
              {
                id: crypto.randomUUID(),
                message: t`renderFinishSuccessMessage`,
                type: "system",
                time: new Date().toLocaleTimeString([], { hour12: false }),
              },
            ]);

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
            setLogs((prev) => [
              ...prev,
              {
                id: crypto.randomUUID(),
                message: t`renderFinishCancelMessage`,
                type: "system",
                time: new Date().toLocaleTimeString([], { hour12: false }),
              },
            ]);
            setIsRendering(false);
          } else {
            setStatus("error");
            setLogs((prev) => [
              ...prev,
              {
                id: crypto.randomUUID(),
                message: t`renderFinishErrorMessage`,
                type: "error",
                time: new Date().toLocaleTimeString([], { hour12: false }),
              },
            ]);
          }
        },
      );

      invoke("start_render", { configPath }).catch((err) => {
        setStatus("error");
        setLogs((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            message: t`Failed to invoke Python render: ${err}`,
            type: "error",
            time: new Date().toLocaleTimeString([], { hour12: false }),
          },
        ]);
      });

      return () => {
        unlistenLog();
        unlistenError();
        unlistenFinish();
      };
    };

    let cleanupFn: (() => void) | undefined;
    setupListeners().then((cleanup) => {
      cleanupFn = cleanup;
    });

    return () => {
      if (cleanupFn) cleanupFn();
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
    setLogs([]);
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
    setLogs((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        message: t`Sending cancellation signal to backend...`,
        type: "error",
        time: new Date().toLocaleTimeString([], { hour12: false }),
      },
    ]);

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
      <div className="fixed bottom-6 right-6 z-99999 animate-in slide-in-from-bottom-5 duration-300">
        <div className="bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl border border-amber-500/40 rounded-2xl shadow-[0_10px_40px_-10px_rgba(0,0,0,0.5)] p-4 flex flex-col gap-3 max-w-sm">
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
  return createPortal(
    <div
      style={{ zIndex: 9998 }}
      className="fixed inset-0 pointer-events-auto flex items-center justify-center p-4 sm:p-4 animate-in fade-in duration-300"
    >
      <div className="flex flex-col xl:flex-row items-center xl:items-stretch justify-center gap-4 max-h-[92vh] w-full max-w-[90vw] xl:max-w-7xl pointer-events-none">
        <div className="w-full max-w-3xl shrink-0 flex-1 bg-white dark:bg-zinc-950 rounded-2xl shadow-[0_0_80px_-15px_rgba(0,0,0,0.5)] border border-zinc-200 dark:border-zinc-800/80 flex flex-col overflow-hidden animate-in zoom-in-95 duration-400 pointer-events-auto">
          {/* Header */}
          <div className="px-6 py-4 border-b border-zinc-100 dark:border-zinc-800/80 bg-zinc-50/50 dark:bg-zinc-900/20 shrink-0">
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100 tracking-tight">
                      {metadata.project_name}
                    </h2>
                    {settings.quick_export && (
                      <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-500 text-[10px] font-bold">
                        <Zap className="w-3 h-3 fill-amber-500" />
                        <Trans>Quick Export</Trans>
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-zinc-500 font-medium flex items-center gap-1.5 mt-0.5">
                    <Cpu className="w-6 h-6" />
                    {hardwareSpec.details}
                  </p>
                </div>
              </div>
              {status === "processing" && step === "generating" && (
                <button
                  onClick={handleCancel}
                  className="flex items-center gap-2 px-4 py-2 bg-zinc-100 hover:bg-red-50 text-zinc-600 hover:text-red-600 dark:bg-zinc-800/50 dark:hover:bg-red-500/10 dark:text-zinc-400 dark:hover:text-red-400 text-sm font-medium rounded-lg transition-all text-nowrap"
                >
                  <X className="w-4 h-4" /> <Trans>Cancel</Trans>
                </button>
              )}
              {status === "error" && (
                <div className="flex items-center gap-2 text-red-500 bg-red-50 dark:bg-red-500/10 px-4 py-2 rounded-lg">
                  <XCircle className="w-4 h-4" />
                  <span className="text-sm font-medium text-nowrap">
                    <Trans>Failed</Trans>
                  </span>
                </div>
              )}
            </div>

            {/* Stepper */}
            <div className="flex items-center justify-between relative px-2">
              <div className="absolute left-0 right-0 top-1/2 -translate-y-1/2 h-0.5 bg-zinc-200 dark:bg-zinc-800 z-0 rounded-full" />
              <div
                className="absolute left-0 top-1/2 -translate-y-1/2 h-0.5 bg-navi-500 z-0 rounded-full transition-all duration-700 ease-in-out"
                style={{
                  width:
                    step === "generating"
                      ? "25%"
                      : step === "verifying"
                        ? "60%"
                        : step === "exporting"
                          ? "85%"
                          : "100%",
                }}
              />

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
              ].map((s, i) => {
                const isActive =
                  step === s.id ||
                  (s.id === "finished" && step === "exporting");
                const isPast =
                  ["generating", "verifying", "exporting", "finished"].indexOf(
                    step,
                  ) > i;
                return (
                  <div
                    key={s.id}
                    className="relative z-10 flex flex-col items-center gap-3 bg-zinc-50/50 dark:bg-zinc-950 px-2 group"
                  >
                    <div
                      className={`w-10 h-10 rounded-full flex items-center justify-center border-2 text-sm font-medium transition-all duration-300 ${
                        isActive
                          ? "border-navi-500 bg-navi-500 text-white shadow-[0_0_20px_-3px_rgba(var(--navi-500-rgb),0.4)]"
                          : isPast
                            ? "border-navi-500 bg-navi-500 text-white"
                            : "border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-400"
                      }`}
                    >
                      {isPast ? <CheckCircle className="w-5 h-5" /> : i + 1}
                    </div>
                    <div className="text-center">
                      <div
                        className={`text-xs font-semibold tracking-wide ${isActive ? "text-navi-500" : isPast ? "text-zinc-800 dark:text-zinc-200" : "text-zinc-400"}`}
                      >
                        {s.label}
                      </div>
                      <div className="text-[10px] text-zinc-500 mt-0.5 hidden sm:block">
                        {s.desc}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Dynamic Wizard Body */}
          <div className="flex-1 bg-white dark:bg-zinc-950 min-h-100 max-h-[62vh] overflow-y-auto custom-scrollbar flex flex-col">
            {/* STEP 1: GENERATING */}
            {step === "generating" && (
              <div className="flex-1 flex flex-col items-center justify-center text-center animate-in fade-in duration-500 py-12 px-6">
                {status === "processing" ? (
                  <div className="w-full max-w-2xl mx-auto flex flex-col items-center">
                    <div className="relative w-24 h-24 mx-auto mb-6">
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

                    <h3 className="text-2xl font-bold text-zinc-900 dark:text-zinc-100 mb-2">
                      {settings.quick_export
                        ? t`Generating Assets (Quick Export Mode)...`
                        : t`Generating Assets...`}
                    </h3>

                    <div className="mt-4 px-6 py-3 bg-zinc-50 dark:bg-zinc-900/60 border border-zinc-200 dark:border-zinc-800 rounded-xl flex items-center justify-between w-full max-w-sm">
                      <div className="flex items-center gap-3">
                        <Loader2 className="w-4 h-4 text-navi-500 animate-spin" />
                        <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                          {(() => {
                            const latestLog =
                              logs[logs.length - 1]?.message ||
                              t`Initializing pipeline...`;

                            const cleanLog = latestLog.replace(
                              /^\[\d{2}:\d{2}\]\s*(\[\d+\/\d+\])?\s*/,
                              "",
                            );
                            const fractionMatch =
                              cleanLog.match(/\b(\d+\/\d+)\b/);
                            const prog = fractionMatch
                              ? ` ${fractionMatch[1]}`
                              : "";

                            if (latestLog.includes("Parsing GPS track"))
                              return t`Parsing Maps & GPS Data${prog}...`;
                            if (latestLog.includes("Generating TTS"))
                              return t`Synthesizing AI Voiceovers${prog}...`;
                            if (latestLog.includes("subtitles"))
                              return t`Generating Subtitles${prog}...`;
                            if (
                              latestLog.includes("attraction video") ||
                              latestLog.includes("images")
                            )
                              return t`Rendering Media & Animations${prog}...`;
                            if (latestLog.includes("timeline"))
                              return t`Finalizing Project Timeline${prog}...`;

                            return (
                              cleanLog.substring(0, 50) +
                              (cleanLog.length > 50 ? "..." : "")
                            );
                          })()}
                        </span>
                      </div>
                      <div className="text-xs font-semibold text-zinc-400 tabular-nums ml-4 tracking-wider">
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
                  <div className="flex flex-col items-center justify-center max-w-lg mx-auto text-center">
                    <div className="w-20 h-20 bg-red-50 dark:bg-red-500/10 rounded-full flex items-center justify-center mx-auto mb-6">
                      <AlertTriangle className="w-10 h-10 text-red-500" />
                    </div>
                    <h3 className="text-2xl font-bold text-zinc-900 dark:text-zinc-100 mb-2">
                      <Trans>Generation Failed</Trans>
                    </h3>
                    <div className="mt-4 p-4 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/50 rounded-xl text-left w-full">
                      <h4 className="text-sm font-bold text-red-800 dark:text-red-400 mb-1">
                        <Trans>Error Details:</Trans>
                      </h4>
                      <p className="text-sm text-red-600 dark:text-red-300">
                        {(() => {
                          const errLog = [...logs]
                            .reverse()
                            .find(
                              (l) =>
                                l.type === "error" ||
                                l.message.includes("[ERROR]"),
                            );
                          if (!errLog)
                            return t`An unknown error occurred during rendering.`;
                          return errLog.message.replace(/^.*?\[ERROR\]\s*/, "");
                        })()}
                      </p>
                    </div>
                  </div>
                ) : null}
              </div>
            )}

            {/* STEP 2: VERIFYING / ASSET REVIEW */}
            {step === "verifying" && (
              <div className="flex-1 flex flex-col gap-8 animate-in slide-in-from-right-8 duration-500 p-8 overflow-y-auto custom-scrollbar">
                {/* Hardware Guidance Banner */}
                <div className="bg-zinc-50 dark:bg-zinc-900/60 border border-zinc-200 dark:border-zinc-800 rounded-xl p-4 flex items-center justify-between">
                  <div className="flex items-center gap-3">
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
                  <span className="text-[10px] font-mono px-2 py-1 rounded bg-zinc-200 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 shrink-0">
                    {hardwareSpec.gpuRenderer.substring(0, 30)}
                  </span>
                </div>

                {/* Video Review Section */}
                {videoItems.length > 0 && (
                  <div className="space-y-4">
                    <div className="flex items-center justify-between text-zinc-900 dark:text-zinc-100">
                      <div className="flex items-center gap-2">
                        <Film className="w-5 h-5 text-navi-500" />
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

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
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
                  <div className="flex items-center justify-between text-zinc-900 dark:text-zinc-100">
                    <div className="flex items-center gap-2">
                      <Mic className="w-5 h-5 text-navi-500" />
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
                            <div className="flex items-center justify-between mb-3">
                              <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                                {item.label}
                              </span>
                              <div className="flex items-center gap-2">
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
                              <p className="text-xs text-zinc-600 dark:text-zinc-400 bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg p-3 leading-relaxed">
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
              <div className="flex-1 flex flex-col items-center justify-center text-center animate-in fade-in duration-500 py-12 px-6">
                <Loader2 className="w-14 h-14 text-navi-500 animate-spin mb-6 mx-auto" />
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
              <div className="flex-1 flex flex-col items-center justify-center text-center animate-in zoom-in-95 duration-500 py-12 px-6">
                <div className="w-20 h-20 bg-emerald-50 dark:bg-emerald-500/10 rounded-full flex items-center justify-center mx-auto mb-6">
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

                <div className="flex items-center gap-3">
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
            <div className="p-6 border-t border-zinc-100 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 flex items-center justify-between shrink-0">
              <span className="text-xs text-zinc-500 flex items-center gap-1.5">
                <Settings2 className="w-4 h-4" />
                <Trans>Accept assets to automatically stitch and export</Trans>
              </span>
              <div className="flex items-center gap-3">
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
            <div className="p-4 bg-zinc-900 border-t border-zinc-800 flex justify-end shrink-0 gap-3">
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
                  setLogs([]);
                  setRenderAttempt((attempt) => attempt + 1);
                }}
                className="px-5 py-2.5 bg-zinc-800 text-zinc-200 text-sm font-semibold rounded-lg hover:bg-zinc-700 transition-colors"
              >
                <Trans>Retry</Trans>
              </button>
            </div>
          )}
        </div>

        {/* Terminal Log Output */}
        <div className="w-full max-w-3xl xl:w-112.5 xl:max-w-none shrink-0 bg-zinc-950 rounded-2xl border border-zinc-800 shadow-2xl flex flex-col overflow-hidden pointer-events-auto animate-in slide-in-from-top-4 xl:slide-in-from-left-4 duration-300">
          <div className="flex-1 min-h-64 xl:min-h-0 bg-zinc-950 p-6 flex flex-col font-mono text-[11px] leading-relaxed relative">
            <div className="absolute top-0 left-0 right-0 h-4 bg-linear-to-b from-zinc-950 to-transparent z-10 pointer-events-none"></div>
            <div
              ref={scrollRef}
              className="space-y-1.5 overflow-y-auto custom-scrollbar h-full pb-2"
            >
              {logs.length === 0 ? (
                <span className="text-zinc-700">Waiting for pipeline...</span>
              ) : (
                logs.map((log) => (
                  <div
                    key={log.id}
                    className="flex gap-3 hover:bg-white/5 px-2 py-0.5 rounded transition-colors"
                  >
                    <span className="text-zinc-600 shrink-0 select-none">
                      [{log.time}]
                    </span>
                    <span
                      className={`wrap-break-word whitespace-pre-wrap ${
                        log.type === "error"
                          ? "text-red-400"
                          : log.type === "system"
                            ? "text-navi-400 font-semibold"
                            : "text-zinc-300"
                      }`}
                    >
                      {log.message}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
