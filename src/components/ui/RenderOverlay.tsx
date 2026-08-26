import { useEffect, useState, useRef } from "react";
import { listen } from "@tauri-apps/api/event";
import { Loader2, CheckCircle, XCircle, Info, AlertTriangle, PlayCircle } from "../ui/icons";
import { useUI } from "../../hooks/useUI";

interface LogItem {
  id: string;
  message: string;
  type: "info" | "error" | "system";
  time: string;
}

export function RenderOverlay() {
  const { isRendering, setIsRendering } = useUI();
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [progress, setProgress] = useState(0);
  const [status, setStatus] = useState<"processing" | "success" | "error">("processing");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  useEffect(() => {
    if (!isRendering) return;

    setStatus("processing");
    setProgress(0);
    setLogs([{
      id: crypto.randomUUID(),
      message: "Initializing render pipeline...",
      type: "system",
      time: new Date().toLocaleTimeString([], { hour12: false })
    }]);

    const setupListeners = async () => {
      const unlistenLog = await listen<string>("render-log", (event) => {
        const text = event.payload;

        // Intercept the progress indicator from Python
        const progressMatch = text.match(/PROGRESS:\s*(\d+)/);
        if (progressMatch) {
          setProgress(Math.min(100, Number(progressMatch[1])));
          return; // Skip adding this to the notification list
        }

        setLogs((prev) => [...prev, {
          id: crypto.randomUUID(),
          message: text,
          type: "info",
          time: new Date().toLocaleTimeString([], { hour12: false })
        }]);
      });

      const unlistenError = await listen<string>("render-error", (event) => {
        setLogs((prev) => [...prev, {
          id: crypto.randomUUID(),
          message: event.payload,
          type: "error",
          time: new Date().toLocaleTimeString([], { hour12: false })
        }]);
      });

      const unlistenFinish = await listen<string>("render-finish", (event) => {
        if (event.payload === "Success") {
          setStatus("success");
          setProgress(100);
          setLogs((prev) => [...prev, {
            id: crypto.randomUUID(),
            message: "Video rendering complete.",
            type: "system",
            time: new Date().toLocaleTimeString([], { hour12: false })
          }]);
        } else {
          setStatus("error");
          setLogs((prev) => [...prev, {
            id: crypto.randomUUID(),
            message: "Rendering failed. Check the logs above.",
            type: "system",
            time: new Date().toLocaleTimeString([], { hour12: false })
          }]);
        }
      });

      return () => {
        unlistenLog();
        unlistenError();
        unlistenFinish();
      };
    };

    let cleanupFn: (() => void) | undefined;
    setupListeners().then((cleanup) => { cleanupFn = cleanup; });

    return () => {
      if (cleanupFn) cleanupFn();
    };
  }, [isRendering]);

  if (!isRendering) return null;

  return (
    <div className="fixed inset-0 z-9999 bg-zinc-950/80 backdrop-blur-sm flex items-center justify-center p-6 animate-in fade-in duration-200">
      <div className="w-full max-w-xl bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-white/10 rounded-2xl shadow-2xl flex flex-col overflow-hidden animate-in zoom-in-95 duration-300 h-150 max-h-[90vh]">
        
        {/* Header & Progress */}
        <div className="p-6 border-b border-zinc-100 dark:border-white/5 bg-zinc-50/50 dark:bg-zinc-900/50 shrink-0">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              {status === "processing" && <Loader2 className="w-5 h-5 text-emerald-500 animate-spin" />}
              {status === "success" && <CheckCircle className="w-5 h-5 text-emerald-500" />}
              {status === "error" && <XCircle className="w-5 h-5 text-red-500" />}
              <div>
                <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
                  {status === "processing" ? "Generating Video..." : status === "success" ? "Render Complete" : "Render Failed"}
                </h2>
                <p className="text-[10px] text-zinc-500">Please do not close the application.</p>
              </div>
            </div>
            <div className="text-2xl font-black text-zinc-800 dark:text-zinc-200">
              {progress}%
            </div>
          </div>

          {/* Progress Bar */}
          <div className="h-2 w-full bg-zinc-200 dark:bg-zinc-800 rounded-full overflow-hidden">
            <div 
              className={`h-full transition-all duration-300 ease-out ${status === 'error' ? 'bg-red-500' : 'bg-emerald-500'}`}
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        {/* Notification List */}
        <div className="flex-1 overflow-y-auto custom-scrollbar p-4 bg-zinc-50 dark:bg-[#09090b]">
          <div ref={scrollRef} className="space-y-3">
            {logs.map((log) => (
              <div 
                key={log.id} 
                className="flex items-start gap-3 p-3 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/5 rounded-xl shadow-sm animate-in slide-in-from-bottom-2 duration-300"
              >
                <div className="shrink-0 mt-0.5">
                  {log.type === "system" && <PlayCircle className="w-4 h-4 text-emerald-500" />}
                  {log.type === "info" && <Info className="w-4 h-4 text-blue-500" />}
                  {log.type === "error" && <AlertTriangle className="w-4 h-4 text-red-500" />}
                </div>
                <div className="flex-1 min-w-0">
                  <p className={`text-xs font-medium leading-relaxed wrap-break-word ${log.type === "error" ? "text-red-600 dark:text-red-400" : "text-zinc-700 dark:text-zinc-300"}`}>
                    {log.message}
                  </p>
                </div>
                <span className="shrink-0 text-[9px] font-mono text-zinc-400 pt-0.5">
                  {log.time}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        {status !== "processing" && (
          <div className="px-6 py-4 border-t border-zinc-100 dark:border-white/5 bg-zinc-50/50 dark:bg-zinc-900/50 flex justify-end shrink-0">
            <button 
              onClick={() => setIsRendering(false)}
              className="px-5 py-2.5 bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 text-xs font-bold rounded-xl hover:bg-zinc-800 dark:hover:bg-zinc-200 transition-colors shadow-sm"
            >
              Close Window
            </button>
          </div>
        )}
      </div>
    </div>
  );
}