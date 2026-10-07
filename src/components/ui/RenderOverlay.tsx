import { takeForcedRender } from "../../services/renderOptions";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { convertFileSrc, invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { join } from "@tauri-apps/api/path";
import { exists, readDir, readTextFile, remove } from "@tauri-apps/plugin-fs";
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
  Minimize2,
  PlayCircle,
  RotateCcw,
  Settings2,
  Sparkles,
  X,
  XCircle,
  Zap,
} from "./icons";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useUI } from "../../hooks/useUI";
import { useWorkspace } from "../../hooks/useWorkspace";
import {
  loadTimelineManifest,
  saveTimelineManifest,
} from "../../services/fileSystem";
import { detectHardwareSpec } from "../../utils/hardwareDetection";
import { exportOptionsFrom } from "../../features/editor/model";
import {
  appendPipelineOutput,
  appendSystemMessage,
  emptyPipelineLog,
  lastPipelineError,
} from "../../utils/pipelineLog";
import { PipelineLogPanel } from "./PipelineLogPanel";
import { Switch } from "./Switch";
import { PronunciationFix, ReviewEdits, ReviewRow, ReviewSelection, ReviewStep } from "./ReviewStep";
import { db } from "../../services/db";
import { runStage } from "../../services/sidecar";
import { announceSetupRequired, isSetupRequired } from "../../services/setup";
import { GLOBAL_DICTIONARY_KEY } from "../../config/constants";

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
    isBackgroundRender,
    setIsBackgroundRender,
    setIsBackgroundBusy,
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
    canUndoTimeline,
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
  const [reviewRows, setReviewRows] = useState<ReviewRow[]>([]);
  const [selection, setSelection] = useState<ReviewSelection>({});
  const [edits, setEdits] = useState<ReviewEdits>({});
  const [isRedoing, setIsRedoing] = useState(false);
  const [saveRequest, setSaveRequest] = useState<{ done: () => void; fail: (error: unknown) => void } | null>(null);
  const [activeAudioId, setActiveAudioId] = useState<string | null>(null);
  const [redoInBackground, setRedoInBackground] = useState(true);
  const [backgroundLabel, setBackgroundLabel] = useState("");
  // The finish handler lives in an effect closure, so it reads what the editor looks like now through this.
  const live = useRef({ timeline, settings, canUndoTimeline, background: isBackgroundRender, collapsed: isRenderCollapsed });
  live.current = { timeline, settings, canUndoTimeline, background: isBackgroundRender, collapsed: isRenderCollapsed };
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  // Audio Regeneration State

  // Quick Export & Exporting State
  const [isQuickExportDone, setIsQuickExportDone] = useState(false);
  const [exportedVideoPath, setExportedVideoPath] = useState<string | null>(null);

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
  const pickedClips = reviewRows.filter((r) => selection[r.id]?.video).length;
  const pickedVoices = reviewRows.filter((r) => selection[r.id]?.voice && r.voice).length;

  useEffect(() => {
    setIsBackgroundBusy(isRendering && isBackgroundRender && step === "generating" && status !== "error");
  }, [isRendering, isBackgroundRender, step, status, setIsBackgroundBusy]);

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
      setIsRedoing(false);
      setIsBackgroundRender(false);
      setBackgroundLabel("");
    }
  }, [isRendering, setIsRenderCollapsed, setIsBackgroundRender]);

  // Pipeline Execution & Event Listeners
  useEffect(() => {
    if (!isRendering) {
      setStep("generating");
      setProgress(0);
      setPipelineLog(emptyPipelineLog());
      setStatus("processing");
      setActiveAudioId(null);
      setReviewRows([]);
      setSelection({});
      setEdits({});
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

            if (live.current.background) {
              await finishBackgroundRun();
              return;
            }

            if (metadata.directory_path) {
              await autoLoadTimeline(metadata.directory_path);
            }

            // Branch: Quick Export vs Asset Review
            if (settings.quick_export) {
              await handleStitchAndExport(true);
            } else {
              await buildReviewRows();
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
      invoke("start_render", { configPath, force: takeForcedRender() || undefined }).catch((err) => {
        if (isSetupRequired(err)) announceSetupRequired();
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
  const savingRef = useRef(false);
  useEffect(() => {
    if (!saveRequest || savingRef.current) return;
    savingRef.current = true;
    saveProject().then(
      () => saveRequest.done(),
      (error) => saveRequest.fail(error),
    ).finally(() => {
      savingRef.current = false;
      setSaveRequest(null);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saveRequest]);

  const stageText = () => {
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
  };

  // ── Review step ────────────────────────────────────────────────────────────
  const pad2 = (n: number) => String(n).padStart(2, "0");

  const buildReviewRows = async () => {
    const dir = metadata?.directory_path;
    if (!dir) return;
    let audioDir = await join(dir, "assets", "audio");
    if (!(await exists(audioDir))) {
      const legacy = await join(dir, "audio");
      if (await exists(legacy)) audioDir = legacy;
    }

    let audioFiles: string[] = [];
    try {
      if (await exists(audioDir)) {
        audioFiles = (await readDir(audioDir)).map((e) => e.name).filter((n): n is string => !!n);
      }
    } catch (e) {
      console.warn("Could not inspect audio directory:", e);
    }

    // The narration of a clip: its audio file, and the script it was made from (the note beside the audio if the project has none).
    const voiceFor = async (prefix: string, script: string) => {
      const file = audioFiles.find((f) => f.startsWith(prefix) && f.endsWith(".wav"));
      if (!file) return undefined;
      const audioPath = await join(audioDir, file);
      let text = script;
      if (!text.trim()) {
        try {
          if (await exists(`${audioPath}.txt`)) text = (await readTextFile(`${audioPath}.txt`)).trim();
        } catch {
          // no note: the text stays empty
        }
      }
      return { text, audioPath };
    };

    const manifest = await loadTimelineManifest(dir);
    const rows: ReviewRow[] = [];
    for (const track of manifest?.video_tracks ?? []) {
      const filePath: string = track.file_path;
      const fileName = filePath.split(/[/\\]/).pop() || "clip";
      const base = { fileName, filePath, videoUrl: convertFileSrc(filePath) };
      const lower = fileName.toLowerCase();
      const leg = fileName.match(/^02_waypoint_(\d+)_/);
      const attraction = fileName.match(/^04_attraction_(\d+)_/);

      if (lower.includes("overview")) {
        rows.push({
          ...base,
          id: "overview",
          kind: "overview",
          title: t`Route overview`,
          voice: await voiceFor("00_overview", metadata.overview_narration || ""),
        });
      } else if (leg) {
        const n = parseInt(leg[1]);
        const from = waypoints[n - 1];
        const fromName = from ? from.name : t`Start`;
        const toName = waypoints[n] ? waypoints[n].name : t`End`;
        rows.push({
          ...base,
          id: `leg-${n}`,
          kind: "leg",
          title: t`Leg ${n}: ${fromName} → ${toName}`,
          wpId: from?.id,
          wpIndex: n - 1,
          voice: await voiceFor(`02_waypoint_${pad2(n)}_`, from?.arrivingNarration || ""),
        });
      } else if (attraction) {
        const idx = parseInt(attraction[1]);
        const wp = waypoints[idx];
        const stopName = wp ? wp.name : t`Stop`;
        rows.push({
          ...base,
          id: `attraction-${idx}`,
          kind: "attraction",
          title: t`At ${stopName}`,
          wpId: wp?.id,
          wpIndex: idx,
          voice: await voiceFor(`04_attraction_${pad2(idx)}_`, wp?.attractionNarration || ""),
        });
      } else {
        const title = lower.includes("intro") ? t`Title card` : lower.includes("outro") ? t`Ending card` : fileName;
        rows.push({ ...base, id: `other-${fileName}`, kind: "other", title });
      }
    }
    setReviewRows(rows);
  };

  // Play / pause a clip's narration
  const handlePlay = (row: ReviewRow) => {
    if (!row.voice) return;
    if (activeAudioId === row.id) {
      audioRef.current?.pause();
      setActiveAudioId(null);
      return;
    }
    audioRef.current?.pause();
    const audio = new Audio(`${convertFileSrc(row.voice.audioPath)}?t=${Date.now()}`);
    audio.onended = () => setActiveAudioId(null);
    audio.onerror = () => {
      showToast(t`Could not load audio for ${row.title}`, "error");
      setActiveAudioId(null);
    };
    audioRef.current = audio;
    audio.play();
    setActiveAudioId(row.id);
  };

  // saveProject reads the state of the render it belongs to, so changes made a moment ago need one render before saving.
  const saveAfterRender = () => new Promise<void>((resolve, reject) => setSaveRequest({ done: resolve, fail: reject }));

  const applyPronunciationFixes = async (fixes: PronunciationFix[]) => {
    const merge = (list: { word: string; reading: string }[], items: PronunciationFix[]) => {
      const next = list.map((entry) => ({ ...entry }));
      for (const fix of items) {
        const found = next.find((entry) => entry.word === fix.word);
        if (found) found.reading = fix.reading;
        else next.push({ word: fix.word, reading: fix.reading });
      }
      return next;
    };
    const project = fixes.filter((f) => f.scope === "project");
    const shared = fixes.filter((f) => f.scope === "global");
    if (project.length) updateSettings({ pronunciation_dictionary: merge(settings.pronunciation_dictionary || [], project) });
    if (shared.length) {
      const saved = (await db.appSettings.get<{ word: string; reading: string }[]>(GLOBAL_DICTIONARY_KEY)) ?? [];
      await db.appSettings.set(GLOBAL_DICTIONARY_KEY, merge(saved, shared));
    }
  };

  // Voices: apply the edits, remove the old audio, and let the pipeline's own narration step make just the missing ones.
  const prepareVoices = async (rows: ReviewRow[]) => {
    const dir = metadata.directory_path;
    if (!dir) return;
    await applyPronunciationFixes(rows.flatMap((r) => edits[r.id]?.fixes ?? []));
    for (const row of rows) {
      const text = (edits[row.id]?.text ?? row.voice?.text ?? "").trim();
      if (row.kind === "leg" && row.wpId) updateWaypoint(row.wpId, { arrivingNarration: text });
      else if (row.kind === "attraction" && row.wpId) updateWaypoint(row.wpId, { attractionNarration: text });
    }
    await saveAfterRender();

    for (const row of rows) {
      try {
        if (row.voice && (await exists(row.voice.audioPath))) await remove(row.voice.audioPath);
      } catch (e) {
        console.warn("Could not remove the old audio:", e);
      }
    }
  };

  const redoVoices = async (rows: ReviewRow[]) => {
    const dir = metadata.directory_path;
    if (!dir) return;
    await prepareVoices(rows);
    const configPath = `${dir}/job_config.json`;
    await runStage(configPath, "tts-all");
    try {
      await runStage(configPath, "subtitle-all");
    } catch (e) {
      console.warn("Subtitles were not rebuilt:", e);
    }
    await autoLoadTimeline(dir);
  };

  const removeClipFiles = async (rows: ReviewRow[]) => {
    const dir = metadata.directory_path;
    for (const row of rows) {
      const stale = [row.filePath, row.filePath.replace("_subtitled", ""), row.filePath.replace(/\.mp4$/i, ".src.json"), row.filePath.replace(/\.mp4$/i, ".orig.wav")];
      for (const path of stale) {
        try {
          if (await exists(path)) await remove(path);
        } catch (e) {
          console.warn("Could not remove a stale file:", e);
        }
      }
    }
    if (dir) {
      for (const manifest of [
        await join(dir, "assets", "video", "route", ".render_manifest.json"),
        await join(dir, "assets", "video", ".render_manifest.json"),
        await join(dir, "video", ".render_manifest.json"),
      ]) {
        try {
          if (await exists(manifest)) await remove(manifest);
        } catch (e) {
          console.warn("Could not remove the render manifest:", e);
        }
      }
    }
  };

  // Video clips: remove them so the next run makes them again, then go where the clip can be changed.
  const redoVideos = async (rows: ReviewRow[]) => {
    audioRef.current?.pause();
    const dir = metadata.directory_path;

    if (hardwareSpec.isHighSpec) {
      showToast(t`Opening the timeline editor so you can change the clip by hand.`, "info");
      updateSettings({ quick_export: false });
      await saveProject();
      if (dir) await autoLoadTimeline(dir);
      setIsRendering(false);
      setEditorMode("timeline");
      return;
    }

    await removeClipFiles(rows);

    const ids = rows.map((r) => r.wpId).filter((id): id is string => !!id);
    const first = ids[0] ?? waypoints[0]?.id ?? null;
    if (first) setActiveWaypointId(first);
    setMarkedWaypointIds((prev) => Array.from(new Set([...prev, ...ids])));
    setEditorMode("map");
    setIsRenderCollapsed(true);
    setGenerationSessionInfo({
      waypointId: first || undefined,
      activeLeg: rows.map((r) => r.title).join(", "),
      message: t`lowSpecGenSessionMessage`,
    });
    const count = rows.length;
    showToast(t`${count} clips are ready to be redone. Change their photo, script or route, then choose Resume Generation.`, "warning");
  };

  // Voices and clips redone while the user keeps working: the old files go, then the pipeline's own checkpoints make just the missing ones.
  const startBackgroundRun = (label: string) => {
    setBackgroundLabel(label);
    setIsBackgroundRender(true);
    setIsRenderCollapsed(true);
    setStep("generating");
    setProgress(0);
    setStatus("processing");
    setElapsedSeconds(0);
    setPipelineLog(emptyPipelineLog());
    setRenderAttempt((prev) => prev + 1);
  };

  const finishBackgroundRun = async () => {
    const dir = metadata.directory_path;
    const now = live.current;
    let kept = false;
    if (dir) {
      // The pipeline rewrote timeline.json. Edits made meanwhile live only in the editor, so they are written back.
      if (now.canUndoTimeline && now.timeline.segments.length > 0) {
        kept = await saveTimelineManifest(dir, metadata.project_name, now.timeline, now.settings.caption_style, exportOptionsFrom(now.settings));
      }
      if (!kept) await autoLoadTimeline(dir);
    }
    await buildReviewRows();
    setStep("verifying");
    setStatus("success");
    if (!now.collapsed) setIsBackgroundRender(false);
    showToast(kept ? t`The redone clips are ready. Your timeline edits were kept.` : t`The redone clips are ready to check.`, "success");
  };

  const redoInTheBackground = async (voiceRows: ReviewRow[], videoRows: ReviewRow[]) => {
    audioRef.current?.pause();
    if (voiceRows.length) await prepareVoices(voiceRows);
    if (videoRows.length) await removeClipFiles(videoRows);
    const voices = voiceRows.length;
    const clips = videoRows.length;
    const parts = [voices ? (voices === 1 ? t`1 voice` : t`${voices} voices`) : "", clips ? (clips === 1 ? t`1 clip` : t`${clips} clips`) : ""];
    setSelection({});
    setEdits({});
    setEditorMode("timeline");
    startBackgroundRun(parts.filter(Boolean).join(", "));
    showToast(t`Redoing in the background. You can keep working in the timeline editor.`, "info");
  };

  const handleRedo = async () => {
    const voiceRows = reviewRows.filter((r) => selection[r.id]?.voice && r.voice);
    const videoRows = reviewRows.filter((r) => selection[r.id]?.video);
    if (!voiceRows.length && !videoRows.length) return;
    setIsRedoing(true);
    try {
      if (redoInBackground) {
        await redoInTheBackground(voiceRows, videoRows);
        return;
      }
      if (voiceRows.length) {
        showToast(t`Making the new voice. The first one can take a while.`, "info");
        await redoVoices(voiceRows);
        showToast(t`The voice is ready. Listen to check it.`, "success");
      }
      if (videoRows.length) {
        await redoVideos(videoRows);
      } else {
        await buildReviewRows();
      }
      setSelection({});
      setEdits({});
    } catch (err: any) {
      console.error("Redo failed:", err);
      showToast(t`Could not redo that: ${err?.message ?? err}`, "error");
    } finally {
      setIsRedoing(false);
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

      // timeline.json is the one the pipeline just wrote (video + narration per clip); re-saving it from editor state would drop the audio.
      const exported = await invoke<string>("export_video", {
        projectDir: metadata.directory_path,
      });

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
      setExportedVideoPath(exported || null);
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
  const handleOpenExplorer = async (target?: string | null) => {
    const path = target || metadata.directory_path;
    if (!path) return;
    try {
      await invoke("open_in_explorer", { path });
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

  // --- BACKGROUND PILL (a redo is running while the user works in the timeline editor) ---
  if (isRenderCollapsed && isBackgroundRender) {
    const running = status === "processing" && step === "generating";
    const failed = status === "error";
    const ready = step === "verifying";
    const tone = failed ? "red" : ready ? "emerald" : "navi";
    return createPortal(
      <div className="fixed bottom-10 right-4 z-99999 animate-in slide-in-from-bottom-5 duration-300">
        <div className="w-[min(22rem,calc(100vw-2rem))] rounded-xl border border-zinc-200 dark:border-white/10 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl shadow-[0_10px_40px_-10px_rgba(0,0,0,0.5)] p-3.5 flex flex-col gap-2.5">
          <div className="flex items-start gap-2.5">
            <div
              className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${
                tone === "red" ? "bg-red-500/10 text-red-500" : tone === "emerald" ? "bg-emerald-500/10 text-emerald-500" : "bg-navi/10 text-navi"
              }`}
            >
              {failed ? <XCircle className="w-4 h-4" /> : ready ? <CheckCircle className="w-4 h-4" /> : <Loader2 className="w-4 h-4 animate-spin" />}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-medium text-zinc-900 dark:text-zinc-100">
                {failed ? t`The redo failed` : ready ? t`Redo finished` : status === "cancelling" ? t`Cancelling...` : t`Redoing in the background`}
              </p>
              <p className="text-[11px] text-zinc-500 dark:text-zinc-400 truncate" title={failed ? (lastPipelineError(pipelineLog) ?? "") : undefined}>
                {failed
                  ? (lastPipelineError(pipelineLog) ?? t`An unknown error occurred during rendering.`)
                  : ready
                    ? t`${backgroundLabel} ready to check`
                    : `${backgroundLabel} · ${stageText()}`}
              </p>
            </div>
            {running && (
              <span className="text-[11px] tabular-nums text-zinc-400 shrink-0">
                {Math.floor(elapsedSeconds / 60)}:{(elapsedSeconds % 60).toString().padStart(2, "0")}
              </span>
            )}
          </div>

          {running && (
            <div className="h-1 rounded-full bg-zinc-100 dark:bg-white/10 overflow-hidden">
              <div className="h-full bg-navi rounded-full transition-all duration-300" style={{ width: `${progress}%` }} />
            </div>
          )}

          <p className="text-[11px] leading-snug text-zinc-400">
            {ready
              ? t`Review them, or carry on in the timeline editor.`
              : failed
                ? t`The files that were removed will be made again the next time you generate.`
                : t`Keep working in the timeline editor. Export is available when it finishes.`}
          </p>

          <div className="flex items-center gap-1.5 -mb-0.5">
            {running && (
              <button onClick={handleCancel} className="h-7 px-2.5 rounded-md text-[12px] text-zinc-500 hover:text-red-500 hover:bg-zinc-100 dark:hover:bg-white/5 transition-colors">
                <Trans>Cancel</Trans>
              </button>
            )}
            {(ready || failed) && (
              <button onClick={() => setIsRendering(false)} className="h-7 px-2.5 rounded-md text-[12px] text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-white/5 transition-colors">
                <Trans>Dismiss</Trans>
              </button>
            )}
            {failed && (
              <button
                onClick={() => {
                  setStatus("processing");
                  setStep("generating");
                  setProgress(0);
                  setPipelineLog(emptyPipelineLog());
                  setRenderAttempt((attempt) => attempt + 1);
                }}
                className="h-7 px-2.5 rounded-md text-[12px] text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-white/5 transition-colors"
              >
                <Trans>Retry</Trans>
              </button>
            )}
            <button
              onClick={() => {
                if (ready) setIsBackgroundRender(false);
                setIsRenderCollapsed(false);
              }}
              className={`ml-auto h-7 px-3 rounded-md text-[12px] font-medium transition ${
                ready ? "bg-navi text-white hover:brightness-110" : "text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-white/5"
              }`}
            >
              {ready ? <Trans>Review</Trans> : <Trans>Details</Trans>}
            </button>
          </div>
        </div>
      </div>,
      document.body,
    );
  }

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
              className="ml-auto px-4 py-1.5 bg-navi hover:brightness-110 text-white rounded-lg text-xs font-bold shadow-md shadow-navi/20 transition-all flex items-center gap-1.5"
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
              {isBackgroundRender && status === "processing" && step === "generating" && (
                <button
                  onClick={() => setIsRenderCollapsed(true)}
                  className="flex items-center gap-2 px-4 py-2 short:py-1.5 shrink-0 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-white/5 text-sm font-medium rounded-lg transition-all text-nowrap"
                >
                  <Minimize2 className="w-4 h-4" /> <Trans>Keep working</Trans>
                </button>
              )}
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
                          className={`h-full bg-navi rounded-full origin-left transition-transform duration-700 ease-in-out ${
                            isConnectorDone ? "scale-x-100" : "scale-x-0"
                          }`}
                        />
                      </div>
                    )}
                    <div
                      className={`relative w-10 h-10 short:w-7 short:h-7 shrink-0 rounded-full flex items-center justify-center border-2 text-sm short:text-xs font-medium transition-all duration-300 ${
                        isActive
                          ? "border-navi bg-navi text-white ring-4 short:ring-2 ring-navi/20"
                          : isPast
                            ? "border-navi bg-navi text-white"
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
                        className={`text-xs font-semibold tracking-wide truncate ${isActive ? "text-navi" : isPast ? "text-zinc-800 dark:text-zinc-200" : "text-zinc-400"}`}
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
                          className="text-navi transition-all duration-300 ease-out"
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
                        <Loader2 className="w-4 h-4 text-navi animate-spin shrink-0" />
                        <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300 truncate text-left">
                          {stageText()}
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
              <ReviewStep
                rows={reviewRows}
                selection={selection}
                onSelection={setSelection}
                edits={edits}
                onEdits={setEdits}
                playingId={activeAudioId}
                onPlay={handlePlay}
                videoRedoGoesTo={redoInBackground ? "background" : hardwareSpec.isHighSpec ? "timeline" : "map"}
                busy={isRedoing}
              />
            )}

            {/* STEP 3: EXPORTING (AUTO-STITCHING) */}
            {step === "exporting" && (
              <div className="flex-1 flex flex-col items-center justify-center text-center animate-in fade-in duration-500 py-10 short:py-5 px-5 sm:px-6">
                <Loader2 className="w-14 h-14 short:w-10 short:h-10 text-navi animate-spin mb-6 short:mb-3 mx-auto" />
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
                  {exportedVideoPath && (
                    <button
                      onClick={() => handleOpenExplorer(exportedVideoPath)}
                      className="px-5 py-2.5 bg-zinc-800 hover:bg-zinc-700 text-white text-xs font-semibold rounded-xl transition-all flex items-center gap-2"
                    >
                      <Film className="w-4 h-4" /> <Trans>Show Video</Trans>
                    </button>
                  )}
                  <button
                    onClick={() => handleOpenExplorer()}
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
                    className="px-6 py-2.5 bg-navi hover:brightness-110 text-white text-xs font-bold rounded-xl shadow-lg shadow-navi/20 transition-all flex items-center gap-2"
                  >
                    <CheckCircle className="w-4 h-4" /> <Trans>Done</Trans>
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Action footer for the review step */}
          {step === "verifying" && (
            <div className="px-5 sm:px-6 py-3 border-t border-zinc-100 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 flex flex-wrap items-center justify-between gap-3 shrink-0">
              <div className="min-w-0 flex flex-wrap items-center gap-x-4 gap-y-1.5">
                <span className="text-[12px] text-zinc-500 min-w-0">
                  {pickedClips + pickedVoices === 0
                    ? t`Nothing selected. Accept to export, or mark what to redo.`
                    : t`Selected to redo: clips ${pickedClips}, voices ${pickedVoices}`}
                </span>
                {pickedClips + pickedVoices > 0 && (
                  <label className="flex items-center gap-2 text-[12px] text-zinc-600 dark:text-zinc-300 cursor-pointer">
                    <Switch checked={redoInBackground} onChange={setRedoInBackground} label={t`Redo in the background`} disabled={isRedoing} />
                    <Trans>Redo in the background</Trans>
                  </label>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-2 ml-auto">
                <button
                  disabled={isRedoing}
                  onClick={async () => {
                    if (metadata.directory_path) {
                      await autoLoadTimeline(metadata.directory_path);
                    }
                    setIsRendering(false);
                    setEditorMode("timeline");
                  }}
                  className="h-9 px-3.5 rounded-lg text-[13px] font-medium text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-white/5 disabled:opacity-40 transition-colors flex items-center gap-2"
                >
                  <Film className="w-4 h-4" />
                  <Trans>Customize in Timeline</Trans>
                </button>
                <button
                  disabled={isRedoing || pickedClips + pickedVoices === 0}
                  onClick={handleRedo}
                  className="h-9 px-3.5 rounded-lg text-[13px] font-semibold bg-amber-500 text-white hover:brightness-110 disabled:opacity-40 disabled:pointer-events-none transition flex items-center gap-2"
                >
                  {isRedoing ? <Loader2 className="w-4 h-4 animate-spin" /> : <RotateCcw className="w-4 h-4" />}
                  <Trans>Redo selected</Trans>
                </button>
                <button
                  disabled={isRedoing}
                  onClick={() => handleStitchAndExport(false)}
                  className={`h-9 px-4 rounded-lg text-[13px] font-semibold transition flex items-center gap-2 disabled:opacity-40 disabled:pointer-events-none ${
                    pickedClips + pickedVoices === 0
                      ? "bg-navi text-white hover:brightness-110"
                      : "text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-white/5"
                  }`}
                >
                  <CheckCircle className="w-4 h-4" />
                  <Trans>Accept and export</Trans>
                </button>
              </div>
            </div>
          )}

          {/* Error Fallback */}
          {status === "error" && (
            <div className="px-5 sm:px-6 py-3 bg-zinc-50 dark:bg-zinc-950 border-t border-zinc-100 dark:border-zinc-800 flex justify-end shrink-0 gap-3">
              <button
                onClick={() => setIsRendering(false)}
                className="px-5 py-2.5 text-zinc-600 dark:text-zinc-300 text-sm font-medium rounded-lg hover:bg-zinc-100 dark:hover:bg-white/5 transition-colors"
              >
                <Trans>Close</Trans>
              </button>
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
