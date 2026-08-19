import { useState, useEffect, useRef } from "react";
import { Sidebar } from "./components/view/editor/Sidebar";
import { MapArea } from "./components/view/editor/MapArea";
import { VideoArea } from "./components/view/editor/VideoArea";
import { TitleBar } from "./components/ui/TitleBar";
import { RenderOverlay } from "./components/ui/RenderOverlay";
import { TitleScreen } from "./components/view/TitleScreen";
import { NewProject } from "./components/view/NewProject";
import { AppSettings } from "./components/modal/AppSettings";
import {  CheckCircle2,  AlertCircle,  Info,  RefreshCw,  Trash2,  Settings2, } from "lucide-react";
import { useUI } from "./hooks/useUI";
import "./App.css";
import { useWorkspace } from "./hooks/useWorkspace";

export default function App() {
  const [contextMenu, setContextMenu] = useState({ show: false, x: 0, y: 0 });
  const menuRef = useRef<HTMLDivElement>(null);
  const { isDirty } = useWorkspace();
  const { currentView, showVideoPanel, toast, setShowAppSettings } = useUI();
  useEffect(() => {
    const handleClick = () =>
      setContextMenu((prev) => ({ ...prev, show: false }));
    window.addEventListener("click", handleClick);
    return () => window.removeEventListener("click", handleClick);
  }, []);

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();

    const menuWidth = 192;
    const menuHeight = 130;
    const windowWidth = window.innerWidth;
    const windowHeight = window.innerHeight;

    // Calculate positions
    const xPos =
      e.pageX + menuWidth > windowWidth ? e.pageX - menuWidth : e.pageX;
    const yPos =
      e.pageY + menuHeight > windowHeight ? e.pageY - menuHeight : e.pageY;

    setContextMenu({ show: true, x: xPos, y: yPos });
  };

  return (
    <div
      className="flex flex-col h-screen w-screen bg-zinc-50 dark:bg-[#09090b] overflow-hidden text-zinc-900 dark:text-zinc-100 selection:bg-emerald-500/30 relative transition-colors"
      onContextMenu={handleContextMenu}
      onKeyDown={(e) => {
        if (e.key === "F12") e.preventDefault();
      }}
      tabIndex={0}
    >
      <TitleBar />
      <RenderOverlay />
      <AppSettings />

      {(currentView === "title_screen" || currentView === "new_project") && <TitleScreen />}

      {currentView === "new_project" && <NewProject />}

      {(currentView === "editor") && (
        <div className="flex flex-1 overflow-hidden relative animate-in fade-in zoom-in-95 duration-300">
          <Sidebar />
          <div className="flex flex-col flex-1 h-full relative">
            <MapArea />

            {showVideoPanel && (
              <div className="h-1/3 flex flex-col border-t border-zinc-200 dark:border-white/10 animate-in slide-in-from-bottom-2">
                <VideoArea />
              </div>
            )}
          </div>
        </div>
      )}

      {/* Custom CSS Menu with Smart Positioning */}
      {contextMenu.show && (
        <div
          key={`${contextMenu.x}-${contextMenu.y}`}
          ref={menuRef}
          className="absolute z-[100] w-48 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl border border-zinc-200 dark:border-white/10 rounded-xl shadow-2xl p-1 overflow-hidden animate-in fade-in zoom-in-95 duration-100"
          style={{ top: contextMenu.y, left: contextMenu.x }}
        >
          <div className="flex flex-col text-sm text-zinc-700 dark:text-zinc-300 font-medium">
            <button
              className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors text-left"
              onClick={() => {
                if (isDirty) {
                  if(!confirm("You have unsaved changes. Reloading will lose them. Continue?"))
                  window.location.reload();    
                } 
              }}
            >
              <RefreshCw className="w-4 h-4" /> Reload UI
            </button>

            <button className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors text-left"
              onClick={() => setShowAppSettings(true)}
            >
              <Settings2 className="w-4 h-4" /> Quick Settings
            </button>
          </div>
        </div>
      )}

      {/* Toast */}
      {toast.visible && (
        <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-[999] animate-in slide-in-from-bottom-6 fade-in zoom-in-95 duration-300 pointer-events-none">
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
    </div>
  );
}
