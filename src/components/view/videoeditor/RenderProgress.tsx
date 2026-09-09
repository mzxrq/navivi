import { useEffect, useState, useRef } from "react";
import { createPortal } from "react-dom";
import { listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";
import { convertFileSrc } from "@tauri-apps/api/core";
import { useUI } from "../../../hooks/useUI";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { join } from "@tauri-apps/api/path";
import { loadTimelineManifest } from "../../../services/fileSystem";

import { Loader2, CheckCircle, XCircle, AlertTriangle, Settings2, PlayCircle, X, Film } from "../../ui/icons";

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
  const { metadata, settings, waypoints, updateWaypoint, updateMetadata, autoLoadTimeline } = useWorkspace();

  const [step, setStep] = useState<WizardStep>("generating");
  const [progress, setProgress] = useState(0);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [status, setStatus] = useState<"processing" | "success" | "error" | "cancelling">("processing");

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

    setLogs([{
      id: crypto.randomUUID(),
      message: "Starting Python generation pipeline...",
      type: "system",
      time: new Date().toLocaleTimeString([], { hour12: false })
    }]);

    const setupListeners = async () => {
      const unlistenLog = await listen<string>("render-log", (event) => {
        const text = event.payload;
        
        // ✨ FIX: Smart aggressive regex for [X/Y] patterns
        const ratioMatch = text.match(/\[(\d+)\/(\d+)\]/);
        if (ratioMatch) {
          const current = parseInt(ratioMatch[1]);
          const total = parseInt(ratioMatch[2]);
          // Scale from 20% to 90% based on chunks processing
          setProgress(20 + Math.floor((current / total) * 70)); 
        } else if (text.includes("Step 1 complete")) { setProgress(10); }
        else if (text.includes("Step 4:")) { setProgress(90); }
        else if (text.includes("Step 6 complete") || text.includes("timeline written")) { setProgress(100); }

        setLogs(prev => [...prev, {
          id: crypto.randomUUID(),
          message: text,
          type: text.includes("[WARNING]") ? "error" : "info",
          time: new Date().toLocaleTimeString([], { hour12: false })
        }]);
      });

      const unlistenError = await listen<string>("render-error", (event) => {
        setLogs(prev => [...prev, {
          id: crypto.randomUUID(),
          message: event.payload,
          type: "error",
          time: new Date().toLocaleTimeString([], { hour12: false })
        }]);
      });

      const unlistenFinish = await listen<string>("render-finish", async (event) => {
        if (event.payload === "Success" || event.payload.includes("complete")) {
          setProgress(100);
          setLogs(prev => [...prev, {
            id: crypto.randomUUID(),
            message: "Asset generation finished successfully.",
            type: "system",
            time: new Date().toLocaleTimeString([], { hour12: false })
          }]);

          if (skipVerification) {
            await handleFinalize();
          } else {
            await buildReviewItems();
            setStep("verifying");
          }
        } else {
          setStatus("error");
          setLogs(prev => [...prev, {
            id: crypto.randomUUID(),
            message: "Generation failed or was cancelled. Review logs above.",
            type: "error",
            time: new Date().toLocaleTimeString([], { hour12: false })
          }]);
        }
      });

      invoke("start_render", { configPath }).catch((err) => {
        setStatus("error");
        setLogs(prev => [...prev, {
          id: crypto.randomUUID(),
          message: `Failed to invoke Python render: ${err}`,
          type: "error",
          time: new Date().toLocaleTimeString([], { hour12: false })
        }]);
      });

      return () => {
        unlistenLog();
        unlistenError();
        unlistenFinish();
      };
    };

    let cleanupFn: (() => void) | undefined;
    setupListeners().then((cleanup) => { cleanupFn = cleanup; });

    return () => { if (cleanupFn) cleanupFn(); };
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
        audioPath: await join(videoDir, "overview_voice.wav")
      });
    }

    for (let i = 0; i < waypoints.length; i++) {
      const wp = waypoints[i];
      const safeLabel = wp.name.replace(/[^a-zA-Z0-9]/g, "_");
      const text = wp.attractionNarration || wp.narration || wp.arrivingNarration || "";

      if (text.trim()) {
        items.push({
          id: wp.id,
          label: `Stop ${i + 1}: ${wp.name}`,
          text: text,
          audioPath: await join(videoDir, `${safeLabel}_script.wav`)
        });
      }
    }
    setReviewItems(items);

    // ✨ 2. Build Video Previews from Manifest
    try {
      const manifest = await loadTimelineManifest(metadata.directory_path);
      if (manifest && manifest.video_tracks) {
        const vids = manifest.video_tracks.map(v => ({
          name: v.file_path.split(/[/\\]/).pop() || "Video",
          url: convertFileSrc(v.file_path)
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
    setReviewItems(prev => prev.map(item => item.id === id ? { ...item, text: newText } : item));
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
    setLogs(prev => [...prev, {
      id: crypto.randomUUID(),
      message: "Sending cancellation signal to backend...",
      type: "error",
      time: new Date().toLocaleTimeString([], { hour12: false })
    }]);

    try {
      await invoke("cancel_render");
    } catch (err) {
      console.warn("Cancellation invoke failed or not implemented in Rust:", err);
    }

    setTimeout(() => {
      setIsRendering(false);
    }, 1000);
  };

  if (!isRendering) return null;

  return createPortal(
    <div style={{ zIndex: 99999 }} className="fixed inset-0 bg-zinc-950/70 backdrop-blur-sm flex items-center justify-center p-6 animate-in fade-in duration-200">
      <div className="w-full max-w-4xl bg-white dark:bg-[#09090b] border border-zinc-200 dark:border-white/10 rounded-2xl shadow-2xl flex flex-col overflow-hidden animate-in zoom-in-95 duration-300">
        
        {/* Header & Stepper */}
        <div className="p-6 border-b border-zinc-100 dark:border-white/5 bg-zinc-50/50 dark:bg-zinc-900/50 shrink-0">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
                Generation Pipeline: {metadata.project_name}
              </h2>
            </div>
            {status === "processing" && step === "generating" && (
              <button 
                onClick={handleCancel}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-red-50 hover:bg-red-500 text-red-600 hover:text-white dark:bg-red-500/10 dark:hover:bg-red-500 dark:text-red-400 dark:hover:text-white text-xs font-bold rounded-md transition-colors"
              >
                <X className="w-3.5 h-3.5" /> Cancel
              </button>
            )}
            {status === "error" && <XCircle className="w-5 h-5 text-red-500" />}
          </div>

          <div className="flex items-center justify-between relative">
            <div className="absolute left-0 right-0 top-1/2 -translate-y-1/2 h-1 bg-zinc-200 dark:bg-zinc-800 z-0 rounded-full" />
            <div 
              className="absolute left-0 top-1/2 -translate-y-1/2 h-1 bg-navi-500 z-0 rounded-full transition-all duration-500" 
              style={{ width: step === "generating" ? "33%" : step === "verifying" ? "66%" : "100%" }} 
            />
            
            {[
              { id: "generating", label: "Build Assets" },
              { id: "verifying", label: "Verify Output" },
              { id: "finished", label: "Timeline" }
            ].map((s, i) => {
              const isActive = step === s.id;
              const isPast = ["generating", "verifying", "finished"].indexOf(step) > i;
              return (
                // ✨ FIX: Solid background so the line doesn't pierce through the middle
                <div key={s.id} className="relative z-10 flex flex-col items-center gap-2 bg-zinc-50 dark:bg-[#0c0c0e] px-4 py-1 rounded-lg">
                  <div className={`w-7 h-7 rounded-full flex items-center justify-center border-2 font-bold text-xs transition-colors ${
                    isActive ? "border-navi-500 bg-navi-500 text-white shadow-md" : 
                    isPast ? "border-navi-500 bg-navi-500 text-white" : 
                    "border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-400"
                  }`}>
                    {isPast ? <CheckCircle className="w-3.5 h-3.5" /> : i + 1}
                  </div>
                  <span className={`text-[10px] font-bold uppercase tracking-wider ${isActive ? "text-navi-500" : isPast ? "text-zinc-800 dark:text-white" : "text-zinc-400"}`}>
                    {s.label}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Dynamic Wizard Body */}
        <div className="p-6 bg-white dark:bg-[#09090b] min-h-65 max-h-[55vh] overflow-y-auto custom-scrollbar flex flex-col">
          
          {/* STEP 1: GENERATING */}
          {step === "generating" && (
            <div className="flex-1 flex flex-col items-center justify-center text-center animate-in fade-in py-6">
              {status === "processing" ? (
                <>
                  <Loader2 className="w-10 h-10 text-navi-500 animate-spin mb-4" />
                  <h3 className="text-sm font-bold text-zinc-800 dark:text-zinc-100">
                    Generating Map Flythroughs & AI Voiceovers...
                  </h3>
                  <p className="text-xs text-zinc-400 mt-1 max-w-sm">
                    Rendering map animations and synthesizing speech via Python.
                  </p>
                  
                  <div className="w-full max-w-md bg-zinc-100 dark:bg-zinc-800 h-2 rounded-full mt-6 overflow-hidden relative">
                    <div className="h-full bg-navi-500 transition-all duration-500 ease-out" style={{ width: `${progress}%` }} />
                  </div>
                  <span className="text-[10px] font-bold text-zinc-500 mt-2">{progress}% Complete</span>
                </>
              ) : status === "cancelling" ? (
                <>
                  <Loader2 className="w-10 h-10 text-red-500 animate-spin mb-4" />
                  <h3 className="text-sm font-bold text-zinc-800 dark:text-zinc-100">Cancelling...</h3>
                </>
              ) : status === "error" ? (
                <>
                  <AlertTriangle className="w-10 h-10 text-red-500 mb-3" />
                  <h3 className="text-sm font-bold text-zinc-800 dark:text-zinc-100">Generation Error</h3>
                  <p className="text-xs text-zinc-400 mt-1">Check the logs terminal below for details.</p>
                </>
              ) : null}
            </div>
          )}

          {/* STEP 2: VERIFYING */}
          {step === "verifying" && (
            <div className="flex-1 flex flex-col gap-6 animate-in slide-in-from-right-4 duration-300">
              
              {/* ✨ NEW: Video Verification Grid */}
              {videoItems.length > 0 && (
                <div className="space-y-3">
                  <h3 className="text-xs font-bold text-zinc-800 dark:text-zinc-100 uppercase tracking-wider flex items-center gap-2">
                    <Film className="w-4 h-4 text-navi-500" /> Video Outputs
                  </h3>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                    {videoItems.map((vid, idx) => (
                      <div key={idx} className="bg-zinc-100 dark:bg-zinc-900 rounded-lg overflow-hidden border border-zinc-200 dark:border-white/5">
                        <video src={vid.url} controls preload="metadata" className="w-full aspect-video object-cover bg-black" />
                        <div className="p-2 text-[9px] font-mono text-zinc-500 truncate" title={vid.name}>
                          {vid.name}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Audio Verification */}
              <div className="space-y-3 pt-4 border-t border-zinc-100 dark:border-white/5">
                <h3 className="text-xs font-bold text-zinc-800 dark:text-zinc-100 uppercase tracking-wider">
                  Audio & Script Verification
                </h3>
                {reviewItems.length === 0 ? (
                  <p className="text-xs text-zinc-400 italic py-2">No voiceover scripts were generated.</p>
                ) : (
                  <div className="space-y-3">
                    {reviewItems.map((item) => (
                      <div key={item.id} className="bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-white/5 rounded-xl p-3 space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-bold text-navi-600 dark:text-navi-400">
                            {item.label}
                          </span>
                          <button 
                            onClick={() => handleTogglePlay(item)}
                            className="flex items-center gap-1 px-2.5 py-1 bg-navi-500 hover:bg-navi-600 text-white text-[10px] font-bold rounded-lg transition-colors shadow-sm"
                          >
                            <PlayCircle className="w-3 h-3" /> 
                            {activeAudioId === item.id ? "Pause" : "Listen"}
                          </button>
                        </div>
                        <textarea 
                          value={item.text}
                          onChange={(e) => handleUpdateItemText(item.id, e.target.value)}
                          className="w-full bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-white/10 rounded-lg p-2 text-xs text-zinc-800 dark:text-zinc-200 focus:outline-none focus:border-navi-500 custom-scrollbar resize-none h-16"
                        />
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between pt-3 border-t border-zinc-100 dark:border-white/5">
                <span className="text-[10px] text-zinc-400 flex items-center gap-1">
                  <Settings2 className="w-3 h-3" /> You can skip this step in Settings.
                </span>
                <button 
                  onClick={handleFinalize}
                  className="px-5 py-2 bg-emerald-500 hover:bg-emerald-600 text-white text-xs font-bold rounded-lg shadow-md transition-colors flex items-center gap-1.5"
                >
                  <CheckCircle className="w-4 h-4" /> Approve & Open Timeline
                </button>
              </div>
            </div>
          )}

          {/* STEP 3: FINISHED */}
          {step === "finished" && (
            <div className="flex-1 flex flex-col items-center justify-center text-center animate-in zoom-in-95 py-6">
              <CheckCircle className="w-12 h-12 text-emerald-500 mb-3" />
              <h3 className="text-base font-bold text-zinc-800 dark:text-zinc-100">Setup Complete!</h3>
              <p className="text-xs text-zinc-400 mt-1">Populating tracks and opening the Timeline Editor...</p>
            </div>
          )}
        </div>

        {/* Terminal Log Output */}
        <div ref={scrollRef} className="h-40 bg-[#09090b] p-4 overflow-y-auto custom-scrollbar font-mono text-[10px] leading-relaxed border-t border-zinc-800 shrink-0">
          <div className="space-y-1.5">
            {logs.map((log) => (
              <div key={log.id} className="flex gap-2">
                <span className="text-zinc-600 shrink-0">[{log.time}]</span>
                <span className={`wrap-break-word whitespace-pre-wrap ${
                  log.type === "error" ? "text-red-400" : 
                  log.type === "system" ? "text-emerald-400" : 
                  "text-zinc-400"
                }`}>
                  {log.message}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Error Fallback */}
        {status === "error" && (
          <div className="p-4 bg-zinc-900 border-t border-zinc-800 flex justify-end shrink-0">
            <button 
              onClick={() => setIsRendering(false)} 
              className="px-4 py-2 bg-white text-zinc-900 text-xs font-bold rounded-lg hover:bg-zinc-200 transition-colors"
            >
              Close Overlay
            </button>
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}