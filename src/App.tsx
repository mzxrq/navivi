import { Sidebar } from "./components/view/mapeditor/Sidebar";
import { MapArea } from "./components/view/mapeditor/MapArea";
import { TimelineView } from "./components/view/videoeditor/TimelineView";
import { TitleBar } from "./components/ui/TitleBar";
import { RenderOverlay } from "./components/ui/RenderOverlay";
import { TitleScreen } from "./components/view/TitleScreen";
import { NewProject } from "./components/view/NewProject";
import { AppSettings } from "./components/modal/AppSettings";
import { CheckCircle2, AlertCircle, Info } from "lucide-react";
import { useUI } from "./hooks/useUI";
import "./App.css";
import { useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { StatusBar } from "./components/ui/StatusBar";
import { ContextMenu } from "./components/ui/ContextMenu";

export default function App() {
  const { currentView, editorMode, toast, showToast } = useUI();

  useEffect(() => {
    const initializeOllama = async () => {
      try {
        const res = await invoke<string>("wake_up_ollama");
        console.log(res);
      } catch (error) {
        console.warn(error);
        showToast(
          "△ Ollama not found. If you wish to use Auto Write function, please install Ollama from App Settings.",
          "warning",
        );
      }
    };
    initializeOllama();
  }, [showToast]);

  return (
    <div
      className="flex flex-col h-screen w-screen bg-zinc-50 dark:bg-[#09090b] overflow-hidden text-zinc-900 dark:text-zinc-100 selection:bg-emerald-500/30 relative transition-colors"
      onKeyDown={(e) => {
        if (e.key === "F12") e.preventDefault();
      }}
      tabIndex={0}
    >
      <TitleBar />
      <RenderOverlay />
      <AppSettings />

      {(currentView === "title_screen" || currentView === "new_project") && (
        <TitleScreen />
      )}

      {currentView === "new_project" && <NewProject />}

      {currentView === "editor" && (
        <div className="flex flex-1 overflow-hidden relative animate-in fade-in zoom-in-95 duration-300">
          {editorMode === "map" ? (
            <>
              <Sidebar />
              <div className="flex flex-col flex-1 h-full relative">
                <MapArea />
              </div>
            </>
          ) : (
            <TimelineView />
          )}
        </div>
      )}

      {/* Toast */}
      {toast.visible && (
        <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-999 animate-in slide-in-from-bottom-6 fade-in zoom-in-95 duration-300 pointer-events-none">
          <div
            className={`flex items-center gap-3 px-5 py-3 rounded-full backdrop-blur-xl border shadow-2xl ${
              toast.type === "success"
                ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-700 dark:text-emerald-400 shadow-emerald-500/10"
                : toast.type === "error"
                  ? "bg-red-500/10 border-red-500/20 text-red-700 dark:text-red-400 shadow-red-500/10"
                  : "bg-zinc-500/10 border-zinc-500/20 text-zinc-700 dark:text-zinc-300 shadow-zinc-500/10"
            }`}
          >
            {toast.type === "success" && <CheckCircle2 className="w-5 h-5" />}
            {toast.type === "error" && <AlertCircle className="w-5 h-5" />}
            {toast.type === "info" && <Info className="w-5 h-5" />}
            <span className="text-sm font-bold tracking-wide">
              {toast.message}
            </span>
          </div>
        </div>
      )}
      <ContextMenu />
      <StatusBar />
    </div>
  );
}
