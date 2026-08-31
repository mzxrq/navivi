import { useWorkspace } from "../../hooks/useWorkspace";
import { useUI } from "../../hooks/useUI";
import { History, Bell, Map, Clock, CheckCircle2 } from "lucide-react";

export function StatusBar() {
  const { waypoints, timeline } = useWorkspace();
  const { editorMode } = useUI();
  
  // Calculate total video duration by finding the clip that ends the latest
  const totalDuration = timeline.clips.reduce((max, clip) => {
    const end = clip.startTime + clip.duration;
    return end > max ? end : max;
  }, 0);

  return (
    <div className="h-7 bg-white dark:bg-[#09090b] border-t border-zinc-200 dark:border-white/5 flex items-center justify-between px-3 text-[10px] font-medium text-zinc-500 z-50 select-none">
      
      {/* Left side: Mode-specific info */}
      <div className="flex items-center gap-4">
        {editorMode === "map" ? (
          <>
            <span className="flex items-center gap-1.5"><Map className="w-3 h-3 text-navi" /> {waypoints.length} Waypoints</span>
            <span className="flex items-center gap-1.5"><Clock className="w-3 h-3" /> Est. Gen: {waypoints.length * 5}s</span>
          </>
        ) : (
          <>
            <span className="flex items-center gap-1.5"><Clock className="w-3 h-3 text-navi" /> Timeline Duration: {totalDuration.toFixed(1)}s</span>
            <span>Tracks: {timeline.tracks.length}</span>
          </>
        )}
      </div>

      {/* Right side: Global actions & status */}
      <div className="flex items-center gap-4">
        <span className="flex items-center gap-1.5 text-green-600 dark:text-green-400">
          <CheckCircle2 className="w-3 h-3" /> Saved
        </span>
        <div className="w-px h-3 bg-zinc-300 dark:bg-zinc-700" />
        <button className="hover:text-zinc-800 dark:hover:text-zinc-200 transition-colors flex items-center gap-1">
          <History className="w-3 h-3" /> Version History
        </button>
        <button className="hover:text-zinc-800 dark:hover:text-zinc-200 transition-colors">
          <Bell className="w-3 h-3" />
        </button>
      </div>
    </div>
  );
}