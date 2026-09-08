import { useEffect, useState, useRef } from "react";
import { listen } from "@tauri-apps/api/event";
import { invoke, convertFileSrc } from "@tauri-apps/api/core";
import { 
  Loader2, CheckCircle, XCircle, Info, AlertTriangle, 
  Play, Pause, Mic, FileText, Settings2, ArrowRight 
} from "./icons";
import { useUI } from "../../hooks/useUI";
import { useWorkspace } from "../../hooks/useWorkspace";
import { join } from "@tauri-apps/api/path";

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

type WizardStep = "generating" | "verifying" | "finished";

export function RenderOverlay() {
  const { isRendering, setIsRendering, setEditorMode, showToast } = useUI();
  const { metadata, settings, waypoints, updateWaypoint, updateMetadata, autoLoadTimeline } = useWorkspace();

  const [step, setStep] = useState<WizardStep>("generating");
  const [progress, setProgress] = useState(0);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [status, setStatus] = useState<"processing" | "success" | "error">("processing");

  // Verification State
  const [reviewItems, setReviewItems] = useState<ScriptReviewItem[]>([]);
  const [activeAudioId, setActiveAudioId] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const skipVerification = (settings as any).skip_audio_verification === true;

  // Auto-scroll logs terminal
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [logs]);

  // Main Generation Lifecycle
  useEffect(() => {
    if (!isRendering) {
      setStep("generating");
      setProgress(0);
      setLogs([]);
      setStatus("processing");
      setActiveAudioId(null);
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
        const progressMatch = text.match(/PROGRESS:\s*(\d+)/);
        if (progressMatch) {
          setProgress(Math.min(99, Number(progressMatch[1])));
          return;
        }
        setLogs(prev => [...prev, {
          id: crypto.randomUUID(),
          message: text,
          type: "info",
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
        if (event.payload === "Success") {
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
            message: "Generation failed. Review error logs above.",
            type: "error",
            time: new Date().toLocaleTimeString([], { hour12: false })
          }]);
        }
      });

      // Invoke Python Render Command
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

  // Construct audio file paths for inline verification
  const buildReviewItems = async () => {
    if (!metadata?.directory_path) return;
    const videoDir = await join(metadata.directory_path, "video");
    const items: ScriptReviewItem[] = [];

    // Overview Narration
    if (metadata.overview_narration) {
      items.push({
        id: "overview",
        label: "Route Overview Narration",
        text: metadata.overview_narration,
        audioPath: await join(videoDir, "overview_voice.wav")
      });
    }

    // Waypoint Narrations
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
  };

  // Playback Handler for Audio Preview
  const handleTogglePlay = (item: ScriptReviewItem) => {
    if (activeAudioId === item.id) {
      audioRef.current?.pause();
      setActiveAudioId(null);
      return;
    }

    if (audioRef.current) {
      audioRef.current.pause();
    }

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

    // Auto-populate the React-Konva timeline from generated assets
    if (metadata.directory_path) {
      await autoLoadTimeline(metadata.directory_path);
    }

    setTimeout(() => {
      setIsRendering(false);
      setEditorMode("timeline");
    }, 1200);
  };

  if (!isRendering) return null;

  return (
    <div className="fixed inset-0 z-1000 bg-zinc-950/80 backdrop-blur-sm flex items-center justify-center p-6 animate-in fade-in duration-200">
      <div className="w-full max-w-2xl bg-white dark:bg-[#09090b] border border-zinc-200 dark:border-white/10 rounded-2xl shadow-2xl flex flex-col overflow-hidden animate-in zoom-in-95 duration-300">
        
        {/* Header & Stepper */}
        <div className="p-6 border-b border-zinc-100 dark:border-white/5 bg-zinc-50/50 dark:bg-zinc-900/50 shrink-0">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-2">
              <Mic className="w-5 h-5 text-navi-500" />
              <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
                Generation Pipeline: {metadata.project_name}
              </h2>
            </div>
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
              { id: "verifying", label: "Verify Audio" },
              { id: "finished", label: "Timeline" }
            ].map((s, i) => {
              const isActive = step === s.id;
              const isPast = ["generating", "verifying", "finished"].indexOf(step) > i;
              return (
                <div key={s.id} className="relative z-10 flex flex-col items-center gap-2 bg-zinc-50/50 dark:bg-zinc-900/50 px-2">
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
        <div className="p-6 bg-white dark:bg-[#09090b] min-h-65 max-h-[50vh] overflow-y-auto custom-scrollbar flex flex-col">
          
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
                  <div className="w-full max-w-md bg-zinc-100 dark:bg-zinc-800 h-2 rounded-full mt-6 overflow-hidden">
                    <div className="h-full bg-navi-500 transition-all duration-300" style={{ width: `${progress}%` }} />
                  </div>
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
            <div className="flex-1 flex flex-col space-y-4 animate-in slide-in-from-right-4 duration-300">
              <div className="flex items-center justify-between pb-2 border-b border-zinc-100 dark:border-white/5">
                <div>
                  <h3 className="text-xs font-bold text-zinc-800 dark:text-zinc-100 uppercase tracking-wider">
                    Audio & Script Verification
                  </h3>
                  <p className="text-[11px] text-zinc-400">
                    Listen to the generated voiceovers. If there are mispronunciations, edit the script directly.
                  </p>
                </div>
              </div>

              <div className="space-y-3">
                {reviewItems.length === 0 ? (
                  <p className="text-xs text-zinc-400 italic text-center py-4">
                    No voiceover scripts were provided for this route.
                  </p>
                ) : (
                  reviewItems.map((item) => (
                    <div key={item.id} className="bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-white/5 rounded-xl p-3 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-navi-600 dark:text-navi-400 flex items-center gap-1.5">
                          <FileText className="w-3.5 h-3.5" /> {item.label}
                        </span>
                        <button 
                          onClick={() => handleTogglePlay(item)}
                          className="flex items-center gap-1 px-2.5 py-1 bg-navi-500 hover:bg-navi-600 text-white text-[10px] font-bold rounded-lg transition-colors shadow-sm"
                        >
                          {activeAudioId === item.id ? (
                            <><Pause className="w-3 h-3" /> Pause</>
                          ) : (
                            <><Play className="w-3 h-3" /> Listen</>
                          )}
                        </button>
                      </div>

                      <textarea 
                        value={item.text}
                        onChange={(e) => handleUpdateItemText(item.id, e.target.value)}
                        className="w-full bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-white/10 rounded-lg p-2 text-xs text-zinc-800 dark:text-zinc-200 focus:outline-none focus:border-navi-500 custom-scrollbar resize-none h-16"
                      />
                    </div>
                  ))
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

        {/* Real-Time Terminal Log Output */}
        <div className="h-32 bg-[#09090b] p-3 overflow-y-auto custom-scrollbar font-mono text-[10px] leading-relaxed border-t border-zinc-800">
          <div ref={scrollRef} className="space-y-1">
            {logs.map((log) => (
              <div key={log.id} className="flex gap-2">
                <span className="text-zinc-600 shrink-0">[{log.time}]</span>
                <span className={`wrap-break-word ${
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
    </div>
  );
}