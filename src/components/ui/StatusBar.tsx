import { useState, useEffect, useRef } from "react";
import { useWorkspace } from "../../hooks/useWorkspace";
import { useUI } from "../../hooks/useUI";
import { useAnimatedUnmount } from "../../hooks/useAnimatedUnmount";
import {
  History,
  Bell,
  MapPin,
  Clock,
  Check,
  CheckCircle2,
  X,
  Copy,
  Trash2,
  Film,
  ImageIcon,
  Layers,
} from "../ui/icons";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";

const toneDot: Record<string, string> = {
  error: "bg-red-500",
  warning: "bg-amber-500",
  success: "bg-emerald-500",
  info: "bg-navi",
};

function NotificationItem({ notif }: { notif: any }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(notif.message);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="group flex items-start gap-2.5 px-2.5 py-2 rounded-lg hover:bg-zinc-50 dark:hover:bg-white/5 transition-colors">
      <span
        className={`mt-1.5 w-1.5 h-1.5 rounded-full shrink-0 ${toneDot[notif.type] ?? toneDot.info}`}
        title={notif.type}
      />
      <div className="flex-1 min-w-0">
        <p className="text-[12px] leading-snug text-zinc-700 dark:text-zinc-300 wrap-break-word select-text">
          {notif.message}
        </p>
        <p className="mt-0.5 text-[11px] text-zinc-400 tabular-nums">
          {new Date(notif.timestamp).toLocaleTimeString([], { hour12: false })}
        </p>
      </div>
      <button
        type="button"
        onClick={handleCopy}
        className="flex items-center justify-center w-6 h-6 rounded-md shrink-0 text-zinc-400 opacity-0 group-hover:opacity-100 focus:opacity-100 hover:text-zinc-700 hover:bg-zinc-100 dark:hover:text-zinc-200 dark:hover:bg-white/10 transition"
        title={t`Copy Message`}
        aria-label={t`Copy Message`}
      >
        {copied ? (
          <Check className="w-3.5 h-3.5 text-emerald-500" />
        ) : (
          <Copy className="w-3.5 h-3.5" />
        )}
      </button>
    </div>
  );
}

export function StatusBar() {
  const {
    waypoints,
    timeline,
    metadata,
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
  const actionsRef = useRef<HTMLDivElement>(null);

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

  // Close either popover on an outside click or Escape.
  useEffect(() => {
    const close = () => {
      setShowNotifications(false);
      setShowHistory(false);
    };
    const onMouseDown = (e: MouseEvent) => {
      if (actionsRef.current && !actionsRef.current.contains(e.target as Node)) close();
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("mousedown", onMouseDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onMouseDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  // Reading the log marks it read.
  useEffect(() => {
    if (showNotifications) setHasUnread(false);
  }, [showNotifications]);

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
      wp.arrivingNarration ||
      wp.attractionNarration,
  ).length;

  // Estimate: Base 2 mins for setup/routing + ~1.5 mins per waypoint for AI voice/GLSL/FFmpeg
  const estRenderMinutes = Math.max(1, Math.ceil(waypoints.length * 1.5 + 2));

  const toggleNotifications = () => {
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
    if (!metadata.directory_path || !metadata.project_id) {
      setHistoryError(t`Save the project before creating a version`);
      return;
    }
    setHistoryBusy(true);
    setHistoryError(null);
    try {
      await createVersion(versionLabel);
      setVersionLabel("");
    } catch (error) {
      console.error("Failed to create project version:", error);
      setHistoryError(t`Could not save this version`);
    } finally {
      setHistoryBusy(false);
    }
  };

  const handleRestoreVersion = async (versionId: string) => {
    setHistoryBusy(true);
    setHistoryError(null);
    try {
      const restored = await restoreVersion(versionId);
      if (!restored) setHistoryError(t`This version is no longer available`);
    } catch (error) {
      console.error("Failed to restore project version:", error);
      setHistoryError(t`Could not restore this version`);
    } finally {
      setHistoryBusy(false);
    }
  };

  const handleDeleteVersion = async (versionId: string) => {
    if (!window.confirm(t`Delete this saved version?`)) return;
    setHistoryBusy(true);
    setHistoryError(null);
    try {
      const deleted = await deleteVersion(versionId);
      if (!deleted) setHistoryError(t`This version could not be deleted`);
    } catch (error) {
      console.error("Failed to delete project version:", error);
      setHistoryError(t`Could not delete this version`);
    } finally {
      setHistoryBusy(false);
    }
  };

  const canSaveVersion = !!metadata.directory_path && !!metadata.project_id;
  const popover =
    "absolute bottom-full right-0 mb-2 max-h-[min(26rem,calc(100vh-6rem))] rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 shadow-lg flex flex-col overflow-hidden duration-150";

  return (
    <div className="relative z-9999 h-7 flex items-center justify-between gap-4 px-3 select-none bg-zinc-50/85 dark:bg-zinc-950/85 backdrop-blur-xl border-t border-zinc-200/80 dark:border-white/10 text-[11px] text-zinc-500 dark:text-zinc-400">
      {/* --- LEFT: what's in the project --- */}
      <div className="flex items-center gap-3 min-w-0 overflow-hidden whitespace-nowrap">
        {editorMode === "map" ? (
          <>
            <Stat icon={MapPin} title={t`Total stops on the map`}>
              {t`${waypoints.length} stops`}
            </Stat>
            <Stat icon={ImageIcon} title={t`Stops containing custom images or AI scripts`}>
              {t`${populatedStops} with media`}
            </Stat>
            <Stat
              icon={Clock}
              title={t`Estimated time for the Python backend to synthesize AI voiceovers and encode the video`}
            >
              {t`~${estRenderMinutes} min to render`}
            </Stat>
          </>
        ) : (
          <>
            <Stat icon={Clock} title={t`Total video duration`}>
              <span className="tabular-nums">{totalDuration.toFixed(1)}s</span>
            </Stat>
            <Stat icon={Layers} title={t`Total tracks in the timeline`}>
              {t`${timeline.tracks.length} tracks`}
            </Stat>
            <Stat icon={Film} title={t`Total individual clips`}>
              {t`${totalClips} clips`}
            </Stat>
          </>
        )}
      </div>

      {/* --- RIGHT: save state, history, notifications --- */}
      <div ref={actionsRef} className="relative flex items-center gap-1 shrink-0">
        {isDirty ? (
          <span
            className="flex items-center gap-1.5 px-1.5 text-amber-600 dark:text-amber-400 cursor-default"
            title={t`Unsaved Changes - Press Ctrl+S to save`}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
            <Trans>Unsaved</Trans>
          </span>
        ) : (
          <span
            className="flex items-center gap-1 px-1.5 cursor-default"
            title={t`All changes safely stored to disk`}
          >
            <Check className="w-3 h-3" />
            <Trans>Saved</Trans>
          </span>
        )}

        <div className="w-px h-3 mx-1 bg-zinc-200 dark:bg-white/10" />

        <button
          type="button"
          onClick={toggleHistory}
          aria-expanded={showHistory}
          className={`${barButton} gap-1 px-1.5 ${showHistory ? "bg-navi/10 text-navi" : ""}`}
        >
          <History className="w-3.5 h-3.5" /> <Trans>History</Trans>
        </button>

        <button
          type="button"
          onClick={toggleNotifications}
          aria-expanded={showNotifications}
          className={`${barButton} relative w-6 ${showNotifications ? "bg-navi/10 text-navi" : ""}`}
          title={t`System Logs & Notifications`}
          aria-label={t`System Logs & Notifications`}
        >
          <Bell className="w-3.5 h-3.5" />
          {hasUnread && (
            <span className="absolute top-0.5 right-0.5 w-1.5 h-1.5 rounded-full bg-navi ring-2 ring-zinc-50 dark:ring-zinc-950" />
          )}
        </button>

        {/* VERSION HISTORY */}
        {renderHistory && (
          <div
            className={`${popover} w-88 ${exitingHistory ? "animate-out fade-out slide-out-to-bottom-1" : "animate-in fade-in slide-in-from-bottom-1"}`}
          >
            <div className="flex items-center justify-between h-10 pl-3.5 pr-1.5 shrink-0 border-b border-zinc-100 dark:border-white/5">
              <span className="text-[13px] font-semibold text-zinc-900 dark:text-zinc-100">
                <Trans>Version History</Trans>
              </span>
              <CloseButton onClick={() => setShowHistory(false)} />
            </div>

            <div className="p-2.5 shrink-0 border-b border-zinc-100 dark:border-white/5">
              <div className="flex gap-1.5">
                <input
                  value={versionLabel}
                  onChange={(event) => setVersionLabel(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void handleCreateVersion();
                  }}
                  placeholder={t`Version label`}
                  className="min-w-0 flex-1 h-8 px-2.5 rounded-lg border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-950/40 text-[12px] text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 outline-none focus:border-navi focus:ring-2 focus:ring-navi/20 transition disabled:opacity-50"
                  disabled={historyBusy || !canSaveVersion}
                />
                <button
                  type="button"
                  onClick={() => void handleCreateVersion()}
                  disabled={historyBusy || !canSaveVersion}
                  className="h-8 px-3 rounded-lg bg-navi text-white text-[12px] font-semibold hover:brightness-110 transition disabled:opacity-40 disabled:pointer-events-none"
                  title={t`Save current version`}
                >
                  <Trans>Save</Trans>
                </button>
              </div>
              {historyError && (
                <p className="mt-1.5 text-[11px] text-red-500">{historyError}</p>
              )}
            </div>

            <div className="flex-1 overflow-y-auto custom-scrollbar p-1">
              {versions.length === 0 ? (
                <div className="px-4 py-8 text-center">
                  <History className="w-5 h-5 mx-auto mb-2 text-zinc-300 dark:text-zinc-600" />
                  <p className="text-[12px] text-zinc-600 dark:text-zinc-300">
                    {metadata.directory_path
                      ? t`No saved versions yet`
                      : t`Save the project to enable version history`}
                  </p>
                  <p className="mt-0.5 text-[11px] text-zinc-400">
                    <Trans>Save a version to create a restore point</Trans>
                  </p>
                </div>
              ) : (
                versions.map((version) => (
                  <div
                    key={version.id}
                    className="group flex items-center gap-2 px-2.5 py-2 rounded-lg hover:bg-zinc-50 dark:hover:bg-white/5 transition-colors"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="truncate text-[12px] font-medium text-zinc-800 dark:text-zinc-200">
                        {version.label}
                      </p>
                      <p className="text-[11px] text-zinc-400 tabular-nums truncate">
                        {new Date(version.createdAt).toLocaleString()} ·{" "}
                        {version.waypointCount} <Trans>stops</Trans> ·{" "}
                        {version.clipCount} <Trans>clips</Trans>
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => void handleRestoreVersion(version.id)}
                      disabled={historyBusy}
                      className="h-6 px-2 rounded-md text-[11px] font-medium text-zinc-600 dark:text-zinc-300 border border-zinc-200 dark:border-white/10 opacity-0 group-hover:opacity-100 focus:opacity-100 hover:border-navi/40 hover:text-navi transition disabled:opacity-40"
                      title={t`Restore version`}
                    >
                      <Trans>Restore</Trans>
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleDeleteVersion(version.id)}
                      disabled={historyBusy}
                      className="flex items-center justify-center w-6 h-6 rounded-md text-zinc-400 opacity-0 group-hover:opacity-100 focus:opacity-100 hover:text-red-500 hover:bg-red-500/10 transition disabled:opacity-40"
                      title={t`Delete version`}
                      aria-label={t`Delete version`}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {/* NOTIFICATIONS */}
        {renderNotifs && (
          <div
            className={`${popover} w-90 ${exitingNotifs ? "animate-out fade-out slide-out-to-bottom-1" : "animate-in fade-in slide-in-from-bottom-1"}`}
          >
            <div className="flex items-center justify-between h-10 pl-3.5 pr-1.5 shrink-0 border-b border-zinc-100 dark:border-white/5">
              <span className="text-[13px] font-semibold text-zinc-900 dark:text-zinc-100">
                <Trans>System Log</Trans>
              </span>
              <div className="flex items-center gap-0.5">
                <button
                  type="button"
                  onClick={clearNotifications}
                  disabled={!notifications || notifications.length === 0}
                  className="h-7 px-2 rounded-lg text-[12px] text-zinc-500 hover:text-red-500 hover:bg-red-500/10 transition-colors disabled:opacity-40 disabled:pointer-events-none"
                  title={t`Clear All Notifications`}
                >
                  <Trans>Clear</Trans>
                </button>
                <CloseButton onClick={() => setShowNotifications(false)} />
              </div>
            </div>

            <div className="flex-1 overflow-y-auto custom-scrollbar p-1">
              {!notifications || notifications.length === 0 ? (
                <div className="px-4 py-8 text-center">
                  <CheckCircle2 className="w-5 h-5 mx-auto mb-2 text-zinc-300 dark:text-zinc-600" />
                  <p className="text-[12px] text-zinc-500">
                    <Trans>No recent activity</Trans>
                  </p>
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

const barButton =
  "flex items-center justify-center h-5 rounded-md text-zinc-500 dark:text-zinc-400 hover:bg-zinc-200/70 hover:text-zinc-900 dark:hover:bg-white/10 dark:hover:text-zinc-100 transition-colors";

function Stat({
  icon: Icon,
  title,
  children,
}: {
  icon: any;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <span className="flex items-center gap-1.5 cursor-default" title={title}>
      <Icon className="w-3 h-3 text-zinc-400 dark:text-zinc-500" />
      {children}
    </span>
  );
}

function CloseButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={t`Close`}
      className="flex items-center justify-center w-7 h-7 rounded-lg text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 dark:hover:text-zinc-200 dark:hover:bg-white/5 transition-colors"
    >
      <X className="w-3.5 h-3.5" />
    </button>
  );
}
