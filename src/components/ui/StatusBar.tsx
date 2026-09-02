import { useState, useEffect, useRef } from "react";
import { useWorkspace } from "../../hooks/useWorkspace";
import { useUI } from "../../hooks/useUI";
import { useAnimatedUnmount } from "../../hooks/useAnimatedUnmount";
import {
  History,
  Bell,
  Map,
  Clock,
  CheckCircle2,
  CircleDashed,
  X,
  Copy,
  Trash2,
} from "../ui/icons";

function NotificationItem({ notif }: { notif: any }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(notif.message);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="p-2 rounded-md hover:bg-zinc-50 dark:hover:bg-navidark-700 flex flex-col gap-1 transition-colors relative group">
      <div className="flex items-center justify-between">
        <span
          className={`font-bold uppercase tracking-wider text-[9px] ${
            notif.type === "error"
              ? "text-red-500"
              : notif.type === "warning"
                ? "text-amber-500"
                : notif.type === "success"
                  ? "text-emerald-500"
                  : "text-navi"
          }`}
        >
          {notif.type}
        </span>
        <span className="text-[9px] text-zinc-400 font-mono">
          {new Date(notif.timestamp).toLocaleTimeString([], { hour12: false })}
        </span>
      </div>
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs text-zinc-700 dark:text-zinc-300 leading-snug">
          {notif.message}
        </span>
        <button
          onClick={handleCopy}
          className="opacity-0 group-hover:opacity-100 p-1 bg-zinc-200 dark:bg-navidark-600 rounded text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-white transition-all shrink-0 mt-0.5"
          title="Copy message"
        >
          {copied ? (
            <CheckCircle2 className="w-3 h-3 text-emerald-500" />
          ) : (
            <Copy className="w-3 h-3" />
          )}
        </button>
      </div>
    </div>
  );
}

export function StatusBar() {
  const { waypoints, timeline, isDirty } = useWorkspace();
  const { editorMode, notifications, clearNotifications } = useUI();

  // Popup States
  const [showNotifications, setShowNotifications] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  // Unmount
  const { shouldRender: renderNotifs, isAnimatingOut: exitingNotifs } =
    useAnimatedUnmount(showNotifications, 150);
  const { shouldRender: renderHistory, isAnimatingOut: exitingHistory } =
    useAnimatedUnmount(showHistory, 150);
  // Notification Unread State
  const [hasUnread, setHasUnread] = useState(false);
  const prevNotifCount = useRef(notifications?.length || 0);

  useEffect(() => {
    const currentCount = notifications?.length || 0;
    if (currentCount > prevNotifCount.current) {
      if (!showNotifications) setHasUnread(true);
    }
    prevNotifCount.current = currentCount;
  }, [notifications, showNotifications]);

  const totalDuration = timeline.clips.reduce((max, clip) => {
    const end = clip.startTime + clip.duration;
    return end > max ? end : max;
  }, 0);

  const toggleNotifications = () => {
    if (showNotifications) {
      setHasUnread(false);
    }
    setShowNotifications(!showNotifications);
    setShowHistory(false);
  };

  const toggleHistory = () => {
    setShowHistory(!showHistory);
    setShowNotifications(false);
  };

  return (
    <div className="h-7 bg-white dark:bg-navidark-900 border-t border-zinc-200 dark:border-navidark-400 flex items-center justify-between px-3 text-[10px] font-medium text-zinc-500 z-900 select-none relative">
      {/* Left side: Mode-specific info */}
      <div className="flex items-center gap-4">
        {editorMode === "map" ? (
          <>
            <span className="flex items-center gap-1.5">
              <Map className="w-3 h-3 text-navi" /> {waypoints.length} Waypoints
            </span>
            <span className="flex items-center gap-1.5">
              <Clock className="w-3 h-3" /> Est. Gen: {waypoints.length * 5}s
            </span>
          </>
        ) : (
          <>
            <span className="flex items-center gap-1.5">
              <Clock className="w-3 h-3 text-navi" /> Timeline Duration:{" "}
              {totalDuration.toFixed(1)}s
            </span>
            <span>Tracks: {timeline.tracks.length}</span>
          </>
        )}
      </div>

      {/* Right side: Global actions & status */}
      <div className="flex items-center gap-4 relative">
        {/* Compact Save Status */}
        {isDirty ? (
          <span
            className="flex items-center gap-1 text-amber-600 dark:text-amber-500"
            title="Unsaved Changes"
          >
            <CircleDashed className="w-3.5 h-3.5 animate-[spin_3s_linear_infinite]" />
          </span>
        ) : (
          <span
            className="flex items-center gap-1 text-emerald-600 dark:text-emerald-500 opacity-70"
            title="All changes saved"
          >
            <CheckCircle2 className="w-3.5 h-3.5" />
          </span>
        )}

        <div className="w-px h-3 bg-zinc-300 dark:bg-navidark-200" />

        {/* VERSION HISTORY */}
        <button
          onClick={toggleHistory}
          className={`transition-colors flex items-center gap-1 ${showHistory ? "text-navi" : "hover:text-zinc-800 dark:hover:text-zinc-200"}`}
        >
          <History className="w-3.5 h-3.5" /> History
        </button>

        {renderHistory && (
          <div
            className={`absolute bottom-full right-6 mb-2.5 w-86 max-h-96 bg-white dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-300 rounded-lg shadow-2xl flex flex-col overflow-hidden duration-200 ${
              exitingHistory
                ? "animate-out fade-out slide-out-to-bottom-2"
                : "animate-in fade-in slide-in-from-bottom-2"
            }`}
          >
            <div className="flex items-center justify-between p-3 border-b border-zinc-100 dark:border-navidark-400 bg-zinc-50 dark:bg-navidark-900/50">
              <span className="text-xs font-bold text-zinc-700 dark:text-zinc-200">
                Version History
              </span>
              <button
                onClick={() => setShowHistory(false)}
                className="text-zinc-400 hover:text-zinc-700 dark:hover:text-white transition-colors"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto custom-scrollbar p-2 space-y-1">
              <div className="p-3 text-center text-zinc-400 text-xs flex flex-col items-center gap-2">
                <History className="w-6 h-6 opacity-20 mb-1" />
                <p>Detailed version history will be available in Sprint 5.</p>
                <p className="text-[10px]">
                  For now, use{" "}
                  <kbd className="bg-zinc-100 dark:bg-navidark-700 px-1 py-0.5 rounded border border-zinc-200 dark:border-navidark-400">
                    Ctrl+Z
                  </kbd>{" "}
                  to undo recent changes.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* NOTIFICATION BELL */}
        <button
          onClick={toggleNotifications}
          className={`transition-colors relative ${showNotifications ? "text-navi" : "hover:text-zinc-800 dark:hover:text-zinc-200"}`}
          title="Notifications"
        >
          <Bell className="w-3.5 h-3.5" />
          {hasUnread && (
            <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-navi rounded-full animate-pulse border border-white dark:border-navidark-900" />
          )}
        </button>
        {/* NOTIFICATION POPUP */}
        {renderNotifs && (
          <div
            className={`absolute bottom-full -right-2.25 mb-2.5 w-90 max-h-96 bg-white dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-300 rounded-lg shadow-2xl flex flex-col overflow-hidden duration-200 ${
              exitingNotifs
                ? "animate-out fade-out slide-out-to-bottom-2"
                : "animate-in fade-in slide-in-from-bottom-2"
            }`}
          >
            <div className="flex items-center justify-between p-3 border-b border-zinc-100 dark:border-navidark-400 bg-zinc-50 dark:bg-navidark-900/50">
              <span className="text-xs font-bold text-zinc-700 dark:text-zinc-200">
                System Log
              </span>

              <button
                onClick={clearNotifications}
                className="text-[10px] font-bold uppercase tracking-wider text-zinc-400 hover:text-red-500 transition-colors"
                disabled={!notifications || notifications.length === 0}
                title="Clear All Notifications"
              >
                <Trash2 className="w-3.5 h-3.5 hover:text-red-400" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto custom-scrollbar p-2 space-y-1">
              {!notifications || notifications.length === 0 ? (
                <div className="p-4 text-center text-zinc-400">
                  No recent activity.
                </div>
              ) : (
                notifications.map((notif: any) => (
                  <NotificationItem key={notif.id} notif={notif} />
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
