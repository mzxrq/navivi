import { useState } from "react";
import { MapArea } from "../view/mapeditor/MapArea";
import { Sidebar } from "../view/mapeditor/Sidebar";
import { TimelineView } from "../view/videoeditor/TimelineView";
import { MapIcon, Film } from "./icons";

export function EditorLayout() {
  // 'map' or 'timeline'
  const [editorMode, setEditorMode] = useState<"map" | "timeline">("map");

  return (
    <div className="flex flex-col h-screen w-screen bg-white dark:bg-navidark-900 overflow-hidden">
      {/* --- TOP NAV / VIEW TOGGLE --- */}
      <header className="h-12 shrink-0 border-b border-zinc-200 dark:border-navidark-300 flex items-center justify-center relative z-50 bg-zinc-50 dark:bg-navidark-700">
        {/* Floating Toggle Pill */}
        <div className="flex bg-zinc-200/50 dark:bg-navidark-900 rounded-lg p-0.5 border border-zinc-300 dark:border-navidark-400">
          <button
            onClick={() => setEditorMode("map")}
            className={`flex items-center gap-2 px-4 py-1 text-xs font-bold rounded-md transition-all ${
              editorMode === "map"
                ? "bg-white dark:bg-navidark-500 text-navi-900 dark:text-navi-400 shadow-sm"
                : "text-zinc-500 hover:text-zinc-700 dark:text-navidark-125 dark:hover:text-white"
            }`}
          >
            <MapIcon className="w-3.5 h-3.5" /> Map
          </button>

          <button
            onClick={() => setEditorMode("timeline")}
            className={`flex items-center gap-2 px-4 py-1 text-xs font-bold rounded-md transition-all ${
              editorMode === "timeline"
                ? "bg-white dark:bg-navidark-500 text-navi-900 dark:text-navi-400 shadow-sm"
                : "text-zinc-500 hover:text-zinc-700 dark:text-navidark-125 dark:hover:text-white"
            }`}
          >
            <Film className="w-3.5 h-3.5" /> Timeline
          </button>
        </div>
      </header>

      {/* --- MAIN CONTENT AREA --- */}
      <main className="flex-1 flex overflow-hidden">
        {editorMode === "map" ? (
          <>
            <Sidebar />
            <div className="flex-1 relative">
              <MapArea />
            </div>
          </>
        ) : (
          <TimelineView />
        )}
      </main>
    </div>
  );
}
