import { Sidebar } from "./features/map/components/Sidebar";
import { MapArea } from "./features/map/components/MapArea";
import { EditorView } from "./features/editor/EditorView";
import { TitleBar } from "./components/ui/TitleBar";
import { RenderOverlay } from "./components/ui/RenderOverlay";
import { ProjectManager } from "./components/view/ProjectManager";
import { NewProject } from "./components/ui/NewProject";
import { AppSettings } from "./components/ui/AppSettings";
import { Toast } from "./components/ui/Toast";
import { useUI } from "./hooks/useUI";
import "./App.css";
import { StatusBar } from "./components/ui/StatusBar";
import { ContextMenu } from "./components/ui/ContextMenu";
import { useAutoSave } from "./hooks/useAutoSave";
import { AutoDirectorModal } from "./components/ui/AutoDirectorModal";

export default function App() {
  const { currentView, editorMode } = useUI();
  useAutoSave();

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
        <ProjectManager />
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
            <EditorView />
          )}
        </div>
      )}

      <ContextMenu />
      <Toast />
      {currentView === "editor" && <StatusBar />}
      <AutoDirectorModal />
    </div>
  );
}
