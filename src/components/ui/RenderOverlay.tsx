import { useEffect, useState, useRef } from "react";
import { createPortal } from "react-dom";
import { listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";
import { convertFileSrc } from "@tauri-apps/api/core";
import { useUI } from "../../hooks/useUI";
import { useWorkspace } from "../../hooks/useWorkspace";
import { join } from "@tauri-apps/api/path";
import { loadTimelineManifest } from "../../services/fileSystem"; // ✨ For loading videos

import {
  Loader2,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Settings2,
  PlayCircle,
  X,
  Film,
} from "./icons";

interface LogItem {
  id: string;
  message: string;
  type: "info" | "error" | "system";
  time: string;
}

interface ScriptReviewItem {
  id: string;
  label: string;
  text: string;
  audioPath: string;
}

interface VideoReviewItem {
  name: string;
  url: string;
}

type WizardStep = "generating" | "verifying" | "finished";

export function RenderOverlay() {
  const { isRendering, setIsRendering, setEditorMode, showToast } = useUI();
  const {
    metadata,
    settings,
    waypoints,
    updateWaypoint,
    updateMetadata,
    autoLoadTimeline,
  } = useWorkspace();

  const [step, setStep] = useState<WizardStep>("generating");
  const [progress, setProgress] = useState(0);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [status, setStatus] = useState<
    "processing" | "success" | "error" | "cancelling"
  >("processing");

  // Verification State
  const [reviewItems, setReviewItems] = useState<ScriptReviewItem[]>([]);
  const [videoItems, setVideoItems] = useState<VideoReviewItem[]>([]); // ✨ NEW: Video Previews
  const [activeAudioId, setActiveAudioId] = useState<string | null>(null);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const skipVerification = (settings as any).skip_audio_verification === true;

  // Auto-scroll terminal smoothly
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  useEffect(() => {
    if (!isRendering) {
      setStep("generating");
      setProgress(0);
      setLogs([]);
      setStatus("processing");
      setActiveAudioId(null);
      setVideoItems([]);
      if (audioRef.current) audioRef.current.pause();
      return;
    }

    const configPath = `${metadata.directory_path}/job_config.json`;

    setLogs([
      {
        id: crypto.randomUUID(),
        message: "Starting Python generation pipeline...",
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
      } else if (text.includes("Step 1 complete")) {
        setProgress(10);
      } else if (text.includes("Step 4:")) {
        setProgress(90);
      } else if (
        text.includes("Step 6 complete") ||
        text.includes("timeline written")
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
                message: "Asset generation finished successfully.",
                type: "system",
                time: new Date().toLocaleTimeString([], { hour12: false }),
              },
            ]);

            if (skipVerification) {
              await handleFinalize();
            } else {
              await buildReviewItems();
              setStep("verifying");
            }
          } else {
            setStatus("error");
            setLogs((prev) => [
              ...prev,
              {
                id: crypto.randomUUID(),
                message:
                  "Generation failed or was cancelled. Review logs above.",
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
            message: `Failed to invoke Python render: ${err}`,
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
  }, [isRendering]);

  const buildReviewItems = async () => {
    if (!metadata?.directory_path) return;
    const videoDir = await join(metadata.directory_path, "video");
    const items: ScriptReviewItem[] = [];

    // 1. Build Audio Items
    if (metadata.overview_narration) {
      items.push({
        id: "overview",
        label: "Route Overview Narration",
        text: metadata.overview_narration,
        audioPath: await join(videoDir, "overview_voice.wav"),
      });
    }

    for (let i = 0; i < waypoints.length; i++) {
      const wp = waypoints[i];
      const safeLabel = wp.name.replace(/[^a-zA-Z0-9]/g, "_");
      const text =
        wp.attractionNarration || wp.narration || wp.arrivingNarration || "";

      if (text.trim()) {
        items.push({
          id: wp.id,
          label: `Stop ${i + 1}: ${wp.name}`,
          text: text,
          audioPath: await join(videoDir, `${safeLabel}_script.wav`),
        });
      }
    }
    setReviewItems(items);

    try {
      const manifest = await loadTimelineManifest(metadata.directory_path);
      if (manifest && manifest.video_tracks) {
        const vids = manifest.video_tracks.map((v) => ({
          name: v.file_path.split(/[/\\]/).pop() || "Video",
          url: convertFileSrc(v.file_path),
        }));
        setVideoItems(vids);
      }
    } catch (e) {
      console.warn("Could not load video previews for verification.");
    }
  };

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
      showToast(`Could not load audio for ${item.label}`, "error");
      setActiveAudioId(null);
    };

    audioRef.current = newAudio;
    newAudio.play();
    setActiveAudioId(item.id);
  };

  const handleUpdateItemText = (id: string, newText: string) => {
    setReviewItems((prev) =>
      prev.map((item) => (item.id === id ? { ...item, text: newText } : item)),
    );
    if (id === "overview") {
      updateMetadata({ overview_narration: newText });
    } else {
      updateWaypoint(id, { narration: newText, attractionNarration: newText });
    }
  };

  const handleFinalize = async () => {
    setStep("finished");
    setStatus("success");
    if (audioRef.current) audioRef.current.pause();

    if (metadata.directory_path) {
      await autoLoadTimeline(metadata.directory_path);
    }

    setTimeout(() => {
      setIsRendering(false);
      setEditorMode("timeline");
    }, 1200);
  };

  const handleCancel = async () => {
    setStatus("cancelling");
    setLogs((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        message: "Sending cancellation signal to backend...",
        type: "error",
        time: new Date().toLocaleTimeString([], { hour12: false }),
      },
    ]);

    try {
      await invoke("cancel_render");
    } catch (err) {
      console.warn(
        "Cancellation invoke failed or not implemented in Rust:",
        err,
      );
    }

    setTimeout(() => {
      setIsRendering(false);
    }, 1000);
  };

  if (!isRendering) return null;

  return createPortal(
    <div
      style={{ zIndex: 99999 }}
      className="fixed inset-0 backdrop-blur-sm flex items-center justify-center p-4 sm:p-4 animate-in fade-in duration-300"
    >
      <div className="w-2xl max-w-2xl bg-white dark:bg-zinc-950 rounded-2xl shadow-[0_0_80px_-15px_rgba(0,0,0,0.5)] border border-zinc-200 dark:border-zinc-800/80 flex flex-col overflow-hidden animate-in zoom-in-95 duration-400">
        {/* Header */}
        <div className="px-6 py-4 border-b border-zinc-100 dark:border-zinc-800/80 bg-zinc-50/50 dark:bg-zinc-900/20 shrink-0">
          <div className="flex items-center justify-between mb-8">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-xl bg-navi-500/10 flex items-center justify-center text-navi-500">
                <Settings2 className="w-4 h-4" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100 tracking-tight">
                  {metadata.project_name}
                </h2>
                <p className="text-xs text-zinc-500 font-medium">
                  Assets Generation
                </p>
              </div>
            </div>
            {status === "processing" && step === "generating" && (
              <button
                onClick={handleCancel}
                className="flex items-center gap-2 px-4 py-2 bg-zinc-100 hover:bg-red-50 text-zinc-600 hover:text-red-600 dark:bg-zinc-800/50 dark:hover:bg-red-500/10 dark:text-zinc-400 dark:hover:text-red-400 text-sm font-medium rounded-lg transition-all"
              >
                <X className="w-4 h-4" /> Cancel
              </button>
            )}
            {status === "error" && (
              <div className="flex items-center gap-2 text-red-500 bg-red-50 dark:bg-red-500/10 px-4 py-2 rounded-lg">
                <XCircle className="w-4 h-4" />
                <span className="text-sm font-medium">Failed</span>
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
                      ? "75%"
                      : "100%",
              }}
            />

            {[
              {
                id: "generating",
                label: "Build Assets",
                desc: "Rendering & Synthesis",
              },
              {
                id: "verifying",
                label: "Verify Output",
                desc: "Review scripts & video",
              },
              { id: "finished", label: "Timeline", desc: "Auto-arrangement" },
            ].map((s, i) => {
              const isActive = step === s.id;
              const isPast =
                ["generating", "verifying", "finished"].indexOf(step) > i;
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
        <div className="flex-1 bg-white dark:bg-zinc-950 min-h-100 max-h-[60vh] overflow-y-auto custom-scrollbar flex flex-col">
          {/* STEP 1: GENERATING */}
          {step === "generating" && (
            <div className="flex-1 flex flex-col items-center justify-center text-center animate-in fade-in duration-500 py-12 px-6">
              {status === "processing" ? (
                <div className="w-full max-w-lg mx-auto">
                  <div className="relative w-24 h-24 mx-auto mb-8">
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
                        strokeDashoffset={289.027 - (289.027 * progress) / 100}
                        strokeLinecap="round"
                      />
                    </svg>
                    <div className="absolute inset-0 flex items-center justify-center">
                      <span className="text-xl font-bold text-zinc-900 dark:text-zinc-100">
                        {progress}%
                      </span>
                    </div>
                  </div>

                  <h3 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100 mb-2">
                    Generating Assets...
                  </h3>
                  <p className="text-sm text-zinc-500">
                    Rendering map flythroughs, synthesizing AI voiceovers, and
                    preparing your timeline.
                  </p>
                </div>
              ) : status === "cancelling" ? (
                <div className="flex flex-col items-center justify-center">
                  <Loader2 className="w-12 h-12 text-red-500 animate-spin mb-6 mx-auto" />
                  <h3 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">
                    Cancelling process...
                  </h3>
                  <p className="text-sm text-zinc-500 mt-2">
                    Sending interrupt signal to renderer.
                  </p>
                </div>
              ) : status === "error" ? (
                <div className="flex flex-col items-center justify-center">
                  <div className="w-16 h-16 bg-red-50 dark:bg-red-500/10 rounded-full flex items-center justify-center mx-auto mb-6">
                    <AlertTriangle className="w-8 h-8 text-red-500" />
                  </div>
                  <h3 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100 mb-2">
                    Generation Failed
                  </h3>
                  <p className="text-sm text-zinc-500">
                    Please review the terminal logs below for more details.
                  </p>
                </div>
              ) : null}
            </div>
          )}

          {/* STEP 2: VERIFYING */}
          {step === "verifying" && (
            <div className="flex-1 flex flex-col gap-8 animate-in slide-in-from-right-8 duration-500 p-8">
              {videoItems.length > 0 && (
                <div className="space-y-4">
                  <div className="flex items-center gap-2 text-zinc-900 dark:text-zinc-100">
                    <Film className="w-5 h-5 text-navi-500" />
                    <h3 className="text-sm font-semibold tracking-wide uppercase">
                      Rendered Video
                    </h3>
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                    {videoItems.map((vid, idx) => (
                      <div
                        key={idx}
                        className="group relative bg-zinc-100 dark:bg-zinc-900 rounded-xl overflow-hidden border border-zinc-200 dark:border-zinc-800 transition-all hover:ring-2 hover:ring-navi-500/50"
                      >
                        <video
                          src={vid.url}
                          controls
                          preload="metadata"
                          className="w-full aspect-video object-cover bg-black"
                        />
                        <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent p-3 pt-8 opacity-0 group-hover:opacity-100 transition-opacity">
                          <p
                            className="text-[10px] font-mono text-zinc-200 truncate"
                            title={vid.name}
                          >
                            {vid.name}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="space-y-4">
                <div className="flex items-center gap-2 text-zinc-900 dark:text-zinc-100">
                  <Settings2 className="w-5 h-5 text-navi-500" />
                  <h3 className="text-sm font-semibold tracking-wide uppercase">
                    Audio & Script Review
                  </h3>
                </div>

                {reviewItems.length === 0 ? (
                  <div className="px-4 py-8 text-center bg-zinc-50 dark:bg-zinc-900/50 rounded-xl border border-dashed border-zinc-200 dark:border-zinc-800">
                    <p className="text-sm text-zinc-500 italic">
                      No voiceover scripts were found in this generation.
                    </p>
                  </div>
                ) : (
                  <div className="grid gap-4">
                    {reviewItems.map((item) => (
                      <div
                        key={item.id}
                        className="bg-white dark:bg-zinc-900/40 border border-zinc-200 dark:border-zinc-800/80 rounded-xl p-4 shadow-sm hover:shadow-md transition-shadow"
                      >
                        <div className="flex items-center justify-between mb-3">
                          <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                            {item.label}
                          </span>
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
                              ? "Playing..."
                              : "Listen"}
                          </button>
                        </div>
                        <textarea
                          value={item.text}
                          onChange={(e) =>
                            handleUpdateItemText(item.id, e.target.value)
                          }
                          className="w-full bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-lg p-3 text-sm text-zinc-700 dark:text-zinc-300 focus:outline-none focus:ring-2 focus:ring-navi-500/50 resize-y min-h-[80px] custom-scrollbar"
                          placeholder="Script is empty..."
                        />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* STEP 3: FINISHED */}
          {step === "finished" && (
            <div className="flex-1 flex flex-col items-center justify-center text-center animate-in zoom-in-95 duration-500 py-12 px-6">
              <div className="w-20 h-20 bg-emerald-50 dark:bg-emerald-500/10 rounded-full flex items-center justify-center mx-auto mb-6">
                <CheckCircle className="w-10 h-10 text-emerald-500" />
              </div>
              <h3 className="text-2xl font-bold text-zinc-900 dark:text-zinc-100 mb-2">
                Ready for Editing
              </h3>
              <p className="text-base text-zinc-500 max-w-md">
                All media has been successfully processed and arranged on your
                timeline.
              </p>
            </div>
          )}
        </div>

        {/* Action Footer for Verifying Step */}
        {step === "verifying" && (
          <div className="p-6 border-t border-zinc-100 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 flex items-center justify-between shrink-0">
            <span className="text-xs text-zinc-500 flex items-center gap-1.5">
              <Settings2 className="w-4 h-4" />
              Settings {">"} Generation {">"} Skip Verification
            </span>
            <button
              onClick={handleFinalize}
              className="px-6 py-2.5 bg-navi-500 hover:bg-navi-600 text-white text-sm font-semibold rounded-xl shadow-lg shadow-navi-500/20 transition-all hover:scale-[1.02] active:scale-[0.98] flex items-center gap-2"
            >
              <CheckCircle className="w-4 h-4" />
              Approve & Open Timeline
            </button>
          </div>
        )}

        {/* Terminal Log Output */}
        <div className="h-48 bg-zinc-950 p-6 overflow-hidden flex flex-col font-mono text-[11px] leading-relaxed border-t border-zinc-800 shrink-0 shadow-inner relative">
          <div className="absolute top-0 left-0 right-0 h-4 bg-gradient-to-b from-zinc-950 to-transparent z-10 pointer-events-none"></div>
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

        {/* Error Fallback */}
        {status === "error" && (
          <div className="p-4 bg-zinc-900 border-t border-zinc-800 flex justify-end shrink-0 gap-3">
            <button
              onClick={() => {
                setStatus("processing");
                setStep("generating");
                // The actual retry is complicated, so just fallback to close for now or allow UI to show retry visually.
                // A correct retry would re-invoke start_render. We can let the user close and re-render.
                setIsRendering(false);
              }}
              className="px-5 py-2.5 bg-zinc-800 text-zinc-200 text-sm font-semibold rounded-lg hover:bg-zinc-700 transition-colors"
            >
              Dismiss
            </button>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
