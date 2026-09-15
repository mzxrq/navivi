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
  Menu,
  Film,
  Volume2,
  Save,
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
  const {
    waypoints,
    timeline,
    isDirty,
    versions,
    refreshVersions,
    createVersion,
    restoreVersion,
    deleteVersion,
  } = useWorkspace();
  const { editorMode, notifications, clearNotifications } = useUI();

  // Popup States
  const [showNotifications, setShowNotifications] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [versionLabel, setVersionLabel] = useState("");
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

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

  // ✨ TIMELINE STATS
  const totalDuration = timeline.clips.reduce((max, clip) => {
    const end = clip.startTime + clip.duration;
    return end > max ? end : max;
  }, 0);
  const totalClips = timeline.clips.length;

  // ✨ MAP STATS & REALISTIC ESTIMATION
  // Count how many waypoints actually have user-added images or scripts
  const populatedStops = waypoints.filter(
    (wp) =>
      (wp.images && wp.images.length > 0) ||
      wp.narration ||
      wp.arrivingNarration ||
      wp.attractionNarration,
  ).length;

  // Estimate: Base 2 mins for setup/routing + ~1.5 mins per waypoint for AI voice/GLSL/FFmpeg
  const estRenderMinutes = Math.max(1, Math.ceil(waypoints.length * 1.5 + 2));

  const toggleNotifications = () => {
    if (showNotifications) setHasUnread(false);
    setShowNotifications(!showNotifications);
    setShowHistory(false);
  };

  const toggleHistory = () => {
    const nextValue = !showHistory;
    setShowHistory(nextValue);
    setShowNotifications(false);
    setHistoryError(null);
    if (nextValue) void refreshVersions();
  };

  const handleCreateVersion = async () => {
    setHistoryBusy(true);
    setHistoryError(null);
    try {
      await createVersion(versionLabel);
      setVersionLabel("");
    } catch (error) {
      console.error("Failed to create project version:", error);
      setHistoryError("Could not save this version.");
    } finally {
      setHistoryBusy(false);
    }
  };

  const handleRestoreVersion = async (versionId: string) => {
    setHistoryBusy(true);
    setHistoryError(null);
    try {
      const restored = await restoreVersion(versionId);
      if (!restored) setHistoryError("This version is no longer available.");
    } catch (error) {
      console.error("Failed to restore project version:", error);
      setHistoryError("Could not restore this version.");
    } finally {
      setHistoryBusy(false);
    }
  };

  const handleDeleteVersion = async (versionId: string) => {
    if (!window.confirm("Delete this saved version?")) return;
    setHistoryBusy(true);
    setHistoryError(null);
    try {
      const deleted = await deleteVersion(versionId);
      if (!deleted) setHistoryError("This version could not be deleted.");
    } catch (error) {
      console.error("Failed to delete project version:", error);
      setHistoryError("Could not delete this version.");
    } finally {
      setHistoryBusy(false);
    }
  };

  return (
    <div className="h-7 bg-white dark:bg-navidark-900 border-t border-zinc-200 dark:border-navidark-400 flex items-center justify-between px-3 text-[10px] font-medium text-zinc-500 z-900 select-none relative">
      {/* --- LEFT: MODE-SPECIFIC METRICS --- */}
      <div className="flex items-center gap-3">
        {editorMode === "map" ? (
          <>
            <span
              className="flex items-center gap-1.5 hover:text-zinc-800 dark:hover:text-zinc-200 transition-colors"
              title="Total stops on the map"
            >
              <Map className="w-3 h-3 text-navi" /> {waypoints.length} Stops
            </span>
            <div className="w-px h-3 bg-zinc-300 dark:bg-navidark-400" />
            <span
              className="flex items-center gap-1.5 hover:text-zinc-800 dark:hover:text-zinc-200 transition-colors"
              title="Stops containing custom images or AI scripts"
            >
              <Volume2 className="w-3 h-3" /> {populatedStops} Rich Media
            </span>
            <div className="w-px h-3 bg-zinc-300 dark:bg-navidark-400" />
            <span
              className="flex items-center gap-1.5 hover:text-zinc-800 dark:hover:text-zinc-200 transition-colors"
              title="Estimated time for the Python backend to synthesize AI voiceovers and encode the video"
            >
              <Clock className="w-3 h-3" /> Est. Render: ~{estRenderMinutes}m
            </span>
          </>
        ) : (
          <>
            <span
              className="flex items-center gap-1.5 hover:text-zinc-800 dark:hover:text-zinc-200 transition-colors"
              title="Total video duration"
            >
              <Clock className="w-3 h-3 text-navi" /> Duration:{" "}
              {totalDuration.toFixed(1)}s
            </span>
            <div className="w-px h-3 bg-zinc-300 dark:bg-navidark-400" />
            <span
              className="flex items-center gap-1.5 hover:text-zinc-800 dark:hover:text-zinc-200 transition-colors"
              title="Total tracks in the timeline"
            >
              <Menu className="w-3 h-3" /> {timeline.tracks.length} Tracks
            </span>
            <div className="w-px h-3 bg-zinc-300 dark:bg-navidark-400" />
            <span
              className="flex items-center gap-1.5 hover:text-zinc-800 dark:hover:text-zinc-200 transition-colors"
              title="Total individual clips"
            >
              <Film className="w-3 h-3" /> {totalClips} Clips
            </span>
          </>
        )}
      </div>

      {/* --- RIGHT: GLOBAL ACTIONS & STATUS --- */}
      <div className="flex items-center gap-4 relative">
        {/* Compact Save Status */}
        {isDirty ? (
          <span
            className="flex items-center gap-1.5 text-amber-600 dark:text-amber-500 cursor-help"
            title="Unsaved Changes - Press Ctrl+S to save"
          >
            <CircleDashed className="w-3.5 h-3.5 animate-[spin_3s_linear_infinite]" />
            Unsaved
          </span>
        ) : (
          <span
            className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-500 opacity-70 cursor-help"
            title="All changes safely stored to disk"
          >
            <CheckCircle2 className="w-3.5 h-3.5" />
            Saved
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
              <div className="p-2 border-b border-zinc-100 dark:border-navidark-400 space-y-2">
                <div className="flex gap-1.5">
                  <input
                    value={versionLabel}
                    onChange={(event) => setVersionLabel(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") void handleCreateVersion();
                    }}
                    placeholder="Version label"
                    className="min-w-0 flex-1 rounded border border-zinc-200 dark:border-navidark-500 bg-white dark:bg-navidark-900 px-2 py-1.5 text-[11px] outline-none focus:border-navi"
                    disabled={historyBusy}
                  />
                  <button
                    onClick={() => void handleCreateVersion()}
                    disabled={historyBusy}
                    className="rounded bg-navi px-2 text-white transition-opacity hover:opacity-85 disabled:opacity-50"
                    title="Save current version"
                  >
                    <Save className="w-3.5 h-3.5" />
                  </button>
                </div>
                {historyError && (
                  <p className="text-[10px] text-red-500">{historyError}</p>
                )}
              </div>

              <div className="flex-1 overflow-y-auto custom-scrollbar p-2 space-y-1">
                {versions.length === 0 ? (
                  <div className="p-4 text-center text-zinc-400 text-xs flex flex-col items-center gap-2">
                    <History className="w-6 h-6 opacity-20 mb-1" />
                    <p>No saved versions yet.</p>
                    <p className="text-[10px]">
                      Save a version to create a restore point.
                    </p>
                  </div>
                ) : (
                  versions.map((version) => (
                    <div
                      key={version.id}
                      className="p-2 rounded-md border border-transparent hover:border-zinc-200 dark:hover:border-navidark-500 hover:bg-zinc-50 dark:hover:bg-navidark-700/50 transition-colors"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate text-xs font-semibold text-zinc-700 dark:text-zinc-200">
                            {version.label}
                          </p>
                          <p className="text-[9px] text-zinc-400 font-mono">
                            {new Date(version.createdAt).toLocaleString()} ·{" "}
                            {version.waypointCount} stops · {version.clipCount}{" "}
                            clips
                          </p>
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          <button
                            onClick={() =>
                              void handleRestoreVersion(version.id)
                            }
                            disabled={historyBusy}
                            className="rounded p-1 text-zinc-400 hover:bg-zinc-200 hover:text-navi dark:hover:bg-navidark-600 disabled:opacity-50"
                            title="Restore version"
                          >
                            <History className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => void handleDeleteVersion(version.id)}
                            disabled={historyBusy}
                            className="rounded p-1 text-zinc-400 hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30 disabled:opacity-50"
                            title="Delete version"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}

        {/* NOTIFICATION BELL */}
        <button
          onClick={toggleNotifications}
          className={`transition-colors relative ${showNotifications ? "text-navi" : "hover:text-zinc-800 dark:hover:text-zinc-200"}`}
          title="System Logs & Notifications"
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
