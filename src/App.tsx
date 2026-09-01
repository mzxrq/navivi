import { Sidebar } from "./components/view/mapeditor/Sidebar";
import { MapArea } from "./components/view/mapeditor/MapArea";
import { TimelineView } from "./components/view/videoeditor/TimelineView";
import { TitleBar } from "./components/ui/TitleBar";
import { RenderOverlay } from "./components/ui/RenderOverlay";
import { TitleScreen } from "./components/view/TitleScreen";
import { NewProject } from "./components/view/NewProject";
import { AppSettings } from "./components/modal/AppSettings";
import { Toast } from "./components/ui/Toast";
import { useUI } from "./hooks/useUI";
import "./App.css";
import { useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { StatusBar } from "./components/ui/StatusBar";
import { ContextMenu } from "./components/ui/ContextMenu";
import { useAutoSave } from "./hooks/useAutoSave";

export default function App() {
  const { currentView, editorMode, showToast } = useUI();
  useAutoSave();
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

      <ContextMenu />
      <Toast />
      <StatusBar />
    </div>
  );
}
