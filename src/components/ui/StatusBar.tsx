import { useState, useRef, useEffect } from "react";
import { useWorkspace } from "../../hooks/useWorkspace";
import { useUI } from "../../hooks/useUI";
import { History, Bell, Map, Clock, CheckCircle2, CircleDashed, X } from "../ui/icons";

export function StatusBar() {
  const { waypoints, timeline, isDirty } = useWorkspace();
  const { editorMode, notifications } = useUI();
  const [showNotifications, setShowNotifications] = useState(false);
  const popupRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (popupRef.current && !popupRef.current.contains(e.target as Node)) {
        setShowNotifications(false);
      }
    };
    if (showNotifications) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showNotifications]);

  const totalDuration = timeline.clips.reduce((max, clip) => {
    const end = clip.startTime + clip.duration;
    return end > max ? end : max;
  }, 0);

  return (
    <div className="h-7 bg-white dark:bg-navidark-900 border-t border-zinc-200 dark:border-navidark-400 flex items-center justify-between px-3 text-[10px] font-medium text-zinc-500 z-50 select-none relative">
      
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
      <div className="flex items-center gap-4 relative">
        {isDirty ? (
          <span className="flex items-center gap-1.5 text-amber-600 dark:text-amber-500">
            <CircleDashed className="w-3 h-3 animate-[spin_3s_linear_infinite]" /> Unsaved
          </span>
        ) : (
          <span className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-500">
            <CheckCircle2 className="w-3 h-3" /> Saved
          </span>
        )}
        
        <div className="w-px h-3 bg-zinc-300 dark:bg-navidark-200" />
        
        <button className="hover:text-zinc-800 dark:hover:text-zinc-200 transition-colors flex items-center gap-1">
          <History className="w-3 h-3" /> Version History
        </button>
        
        {/* Notification Bell */}
        <button 
          onClick={() => setShowNotifications(!showNotifications)}
          className={`transition-colors relative ${showNotifications ? "text-navi" : "hover:text-zinc-800 dark:hover:text-zinc-200"}`}
        >
          <Bell className="w-3 h-3" />
          {notifications.length > 0 && (
            <span className="absolute -top-1 -right-1 w-2 h-2 bg-navi rounded-full animate-pulse" />
          )}
        </button>

        {/* NOTIFICATION POPUP */}
        {showNotifications && (
          <div 
            ref={popupRef}
            className="absolute bottom-full right-0 mb-2 w-80 max-h-96 bg-white dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-300 rounded-xl shadow-2xl flex flex-col overflow-hidden animate-in fade-in slide-in-from-bottom-2 duration-200"
          >
            <div className="flex items-center justify-between p-3 border-b border-zinc-100 dark:border-navidark-400 bg-zinc-50 dark:bg-navidark-900/50">
              <span className="text-xs font-bold text-zinc-700 dark:text-zinc-200">System Log</span>
              <button onClick={() => setShowNotifications(false)} className="text-zinc-400 hover:text-zinc-700 dark:hover:text-white">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
            
            <div className="flex-1 overflow-y-auto custom-scrollbar p-2 space-y-1">
              {notifications.length === 0 ? (
                <div className="p-4 text-center text-zinc-400">No recent activity.</div>
              ) : (
                notifications.map((notif: any) => (
                  <div key={notif.id} className="p-2 rounded-md hover:bg-zinc-50 dark:hover:bg-navidark-700 flex flex-col gap-1 transition-colors">
                    <div className="flex items-center justify-between">
                      <span className={`font-bold uppercase tracking-wider text-[9px] ${
                        notif.type === 'error' ? 'text-red-500' :
                        notif.type === 'warning' ? 'text-amber-500' :
                        notif.type === 'success' ? 'text-emerald-500' : 'text-navi'
                      }`}>
                        {notif.type}
                      </span>
                      <span className="text-[9px] text-zinc-400 font-mono">
                        {new Date(notif.timestamp).toLocaleTimeString([], { hour12: false })}
                      </span>
                    </div>
                    <span className="text-xs text-zinc-700 dark:text-zinc-300 leading-snug">
                      {notif.message}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}