import { useState, useEffect } from "react";
import { CheckCircle2, Loader2, Play, Pause, AlertCircle, FileVideo, Edit3, Settings2 } from "../../ui/icons";
import { useWorkspace } from "../../../hooks/useWorkspace";

interface RenderProgressProps {
  isOpen: boolean;
  onClose: () => void;
  // This will be called when the user officially approves the final render
  onConfirmRender: () => void; 
}

type RenderStep = "generating_assets" | "verifying_audio" | "rendering_video" | "finished";

export function RenderProgress({ isOpen, onClose, onConfirmRender }: RenderProgressProps) {
  const { settings, metadata } = useWorkspace();
  const [step, setStep] = useState<RenderStep>("generating_assets");
  const [progress, setProgress] = useState(0);
  const [log, setLog] = useState<string[]>([]);
  
  // Audio Verification States
  const [isPlaying, setIsPlaying] = useState(false);
  const [transcript, setTranscript] = useState("This is the auto-generated narration for your route. Please verify that the pronunciations are correct before we render the final video.");
  
  // Settings shortcut (You can add this to your ProjectSettings interface later)
  const skipVerification = (settings as any).skip_audio_verification === true;

  useEffect(() => {
    if (!isOpen) {
      // Reset state when closed
      setStep("generating_assets");
      setProgress(0);
      setLog([]);
      return;
    }

    const runPipeline = async () => {
      // STEP 1: GENERATE ASSETS (Simulated for UI preview)
      setLog(prev => [...prev, "Initializing rendering pipeline..."]);
      await new Promise(r => setTimeout(r, 1000));
      
      setLog(prev => [...prev, "Extracting map routes and generating GPS data..."]);
      setProgress(25);
      await new Promise(r => setTimeout(r, 1500));
      
      setLog(prev => [...prev, "Synthesizing AI Voiceover audio..."]);
      setProgress(50);
      await new Promise(r => setTimeout(r, 1500));

      if (skipVerification) {
        setLog(prev => [...prev, "Audio verification skipped via settings."]);
        startFinalRender();
      } else {
        setLog(prev => [...prev, "Assets generated. Waiting for user verification."]);
        setStep("verifying_audio");
      }
    };

    if (step === "generating_assets") {
      runPipeline();
    }
  }, [isOpen, step, skipVerification]);

  const startFinalRender = async () => {
    setStep("rendering_video");
    setProgress(60);
    setLog(prev => [...prev, "Starting FFmpeg stitcher..."]);
    
    // Simulate Render Progress
    for (let i = 60; i <= 100; i += 10) {
      await new Promise(r => setTimeout(r, 500));
      setProgress(i);
      setLog(prev => [...prev, `Rendering frames... ${i}%`]);
    }
    
    setLog(prev => [...prev, "Encoding complete! MP4 saved to disk."]);
    setStep("finished");
    onConfirmRender(); // Trigger your actual Tauri invoke here
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] bg-black/80 backdrop-blur-sm flex items-center justify-center p-6 animate-in fade-in duration-200">
      <div className="bg-white dark:bg-navidark-800 w-full max-w-3xl rounded-xl shadow-2xl border border-zinc-200 dark:border-navidark-400 overflow-hidden flex flex-col">
        
        {/* Header */}
        <div className="px-6 py-4 border-b border-zinc-200 dark:border-navidark-400 bg-zinc-50 dark:bg-navidark-900 flex items-center justify-between">
          <h2 className="text-lg font-bold text-zinc-800 dark:text-white flex items-center gap-2">
            <FileVideo className="w-5 h-5 text-navi" />
            Project Pipeline: {metadata.project_name}
          </h2>
          {step === "finished" && (
            <button onClick={onClose} className="text-sm font-bold text-zinc-500 hover:text-zinc-800 dark:hover:text-white">Close</button>
          )}
        </div>

        <div className="p-6 flex flex-col gap-6">
          
          {/* STEP INDICATORS */}
          <div className="flex items-center justify-between relative">
            <div className="absolute left-0 right-0 top-1/2 -translate-y-1/2 h-1 bg-zinc-200 dark:bg-navidark-600 z-0 rounded-full" />
            <div className="absolute left-0 top-1/2 -translate-y-1/2 h-1 bg-navi z-0 rounded-full transition-all duration-500" style={{ width: `${progress}%` }} />
            
            {[
              { id: "generating_assets", label: "Generate Assets" },
              { id: "verifying_audio", label: "Verify Audio" },
              { id: "rendering_video", label: "Final Render" }
            ].map((s, i) => {
              const isActive = step === s.id;
              const isPast = ["generating_assets", "verifying_audio", "rendering_video", "finished"].indexOf(step) > i;
              return (
                <div key={s.id} className="relative z-10 flex flex-col items-center gap-2 bg-white dark:bg-navidark-800 px-2">
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center border-2 font-bold text-xs transition-colors ${isActive ? "border-navi bg-navi text-white shadow-[0_0_15px_rgba(59,130,246,0.5)]" : isPast ? "border-navi bg-navi text-white" : "border-zinc-300 dark:border-navidark-500 bg-white dark:bg-navidark-800 text-zinc-400"}`}>
                    {isPast ? <CheckCircle2 className="w-4 h-4" /> : i + 1}
                  </div>
                  <span className={`text-[10px] font-bold uppercase tracking-wider ${isActive ? "text-navi" : isPast ? "text-zinc-800 dark:text-white" : "text-zinc-400"}`}>{s.label}</span>
                </div>
              );
            })}
          </div>

          {/* DYNAMIC CONTENT AREA */}
          <div className="bg-zinc-50 dark:bg-navidark-900 rounded-lg border border-zinc-200 dark:border-navidark-600 min-h-[250px] p-6 flex flex-col">
            
            {step === "verifying_audio" && (
              <div className="flex-1 flex flex-col animate-in fade-in slide-in-from-bottom-4">
                <div className="flex items-start gap-3 mb-4">
                  <AlertCircle className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
                  <div>
                    <h3 className="text-sm font-bold text-zinc-800 dark:text-zinc-100">Review Auto-Generated Audio</h3>
                    <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">Listen to the synthesized voiceover. If there are mispronunciations, you can edit the text and regenerate the audio before rendering the final video.</p>
                  </div>
                </div>

                {/* Mock Audio Player */}
                <div className="flex items-center gap-4 bg-white dark:bg-navidark-800 p-3 rounded-lg border border-zinc-200 dark:border-navidark-600 mb-4">
                  <button onClick={() => setIsPlaying(!isPlaying)} className="w-10 h-10 rounded-full bg-navi hover:bg-navi-600 flex items-center justify-center text-white shrink-0 shadow-md transition-colors">
                    {isPlaying ? <Pause className="w-5 h-5" fill="currentColor" /> : <Play className="w-5 h-5 ml-1" fill="currentColor" />}
                  </button>
                  <div className="flex-1 h-8 bg-zinc-100 dark:bg-navidark-900 rounded flex items-center px-2">
                     {/* Fake Waveform */}
                     <div className="w-full flex items-center justify-between h-4 opacity-50">
                        {Array.from({length: 40}).map((_, i) => (
                          <div key={i} className="w-1 bg-navi rounded-full" style={{ height: `${Math.max(20, Math.random() * 100)}%` }} />
                        ))}
                     </div>
                  </div>
                </div>

                <textarea 
                  value={transcript}
                  onChange={(e) => setTranscript(e.target.value)}
                  className="flex-1 w-full bg-white dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-600 rounded-lg p-3 text-sm text-zinc-800 dark:text-zinc-200 focus:outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all resize-none custom-scrollbar"
                />

                <div className="flex items-center justify-between mt-4">
                  <button className="flex items-center gap-2 text-xs font-bold text-zinc-500 hover:text-zinc-800 dark:hover:text-white transition-colors">
                    <Settings2 className="w-4 h-4" /> Skip this step in the future
                  </button>
                  <div className="flex items-center gap-3">
                    <button className="px-4 py-2 bg-zinc-200 dark:bg-navidark-600 hover:bg-zinc-300 dark:hover:bg-navidark-500 text-zinc-800 dark:text-white text-xs font-bold rounded-lg transition-colors flex items-center gap-2">
                      <Edit3 className="w-4 h-4" /> Edit & Regenerate
                    </button>
                    <button onClick={startFinalRender} className="px-6 py-2 bg-green-500 hover:bg-green-600 text-white text-xs font-bold rounded-lg shadow-md transition-colors flex items-center gap-2">
                      <CheckCircle2 className="w-4 h-4" /> Audio is Perfect
                    </button>
                  </div>
                </div>
              </div>
            )}

            {(step === "generating_assets" || step === "rendering_video") && (
              <div className="flex-1 flex flex-col items-center justify-center text-center animate-in fade-in">
                <Loader2 className="w-12 h-12 text-navi animate-spin mb-4" />
                <h3 className="text-base font-bold text-zinc-800 dark:text-white mb-2">
                  {step === "generating_assets" ? "Building Project Assets..." : "Rendering Final Video..."}
                </h3>
                <p className="text-xs text-zinc-500 max-w-sm">This may take a few minutes depending on your hardware. Please do not close the application.</p>
              </div>
            )}

            {step === "finished" && (
              <div className="flex-1 flex flex-col items-center justify-center text-center animate-in zoom-in-95 duration-300">
                <div className="w-16 h-16 bg-green-100 dark:bg-green-900/30 rounded-full flex items-center justify-center mb-4">
                  <CheckCircle2 className="w-8 h-8 text-green-500" />
                </div>
                <h3 className="text-lg font-bold text-zinc-800 dark:text-white mb-2">Render Complete!</h3>
                <p className="text-xs text-zinc-500 mb-6">Your video has been successfully generated and saved to your project folder.</p>
                <button onClick={onClose} className="px-8 py-2.5 bg-navi hover:bg-navi-600 text-white text-sm font-bold rounded-lg shadow-md transition-all">
                  Return to Timeline
                </button>
              </div>
            )}
          </div>

          {/* Terminal Logs */}
          <div className="h-32 bg-[#0C0C0C] rounded-lg p-3 overflow-y-auto custom-scrollbar font-mono text-[10px] leading-relaxed text-zinc-400 border border-zinc-800">
            {log.map((line, index) => (
              <div key={index} className="flex gap-2">
                <span className="text-zinc-600">[{new Date().toLocaleTimeString()}]</span>
                <span className={line.includes("complete") || line.includes("saved") ? "text-green-400" : line.includes("error") ? "text-red-400" : ""}>{line}</span>
              </div>
            ))}
            {step !== "finished" && step !== "verifying_audio" && (
              <div className="flex gap-2 animate-pulse mt-1">
                <span className="text-zinc-600">[{new Date().toLocaleTimeString()}]</span>
                <span>_</span>
              </div>
            )}
          </div>

        </div>
      </div>
    </div>
  );
}