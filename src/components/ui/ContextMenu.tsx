import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useEffect, useState } from "react";
import { useWaypointActions } from "../../hooks/useWaypointActions";
import { useWorkspace } from "../../hooks/useWorkspace";
import {
  Car,
  ChevronRight,
  Copy,
  CopyPlus,
  CornerDownLeft,
  Edit,
  Edit3,
  Eye,
  EyeOff,
  Film,
  Folder,
  FolderOpen,
  Footprints,
  LinkIcon,
  Lock,
  MapPinned,
  MapPinPen,
  MapPinPlus,
  Pencil,
  Plane,
  Plus,
  Route,
  Ruler,
  Settings2,
  Ship,
  Trash2,
  UnlinkIcon,
  Unlock,
  Volume2,
  VolumeX,
  WP,
} from "../ui/icons";

export interface ContextMenuState {
  x: number;
  y: number;
  type:
    | "track-header"
    | "timeline-clip"
    | "map-canvas"
    | "waypoint-marker"
    | "empty-track"
    | "project-card"
    | "mediapool-item";
  targetId?: string;
  data?: any;
}

export function ContextMenu() {
  const [menu, setMenu] = useState<ContextMenuState | null>(null);
  const {
    timeline,
    setTimeline,
    waypoints,
    setWaypoints,
    setActiveWaypointId,
    setIsDirty,
  } = useWorkspace();
  const { addReturnStop } = useWaypointActions();

  useEffect(() => {
    const handleGlobalContextMenu = (e: MouseEvent) => {
      e.preventDefault();
      setMenu(null);
    };

    const handleOpenMenu = (e: CustomEvent<ContextMenuState>) => {
      const { x, y, type, targetId, data } = e.detail;
      setMenu({ x, y, type, targetId, data });
    };

    const handleCloseMenu = () => setMenu(null);

    const handleMouseDown = (e: MouseEvent) => {
      if (e.button === 1) {
        setMenu(null);
        return;
      }
      if (!(e.target as Element).closest("#global-context-menu")) {
        setMenu(null);
      }
    };

    window.addEventListener("contextmenu", handleGlobalContextMenu);
    window.addEventListener("open-context-menu" as any, handleOpenMenu);
    window.addEventListener("mousedown", handleMouseDown);
    window.addEventListener("close-context-menus", handleCloseMenu);
    window.addEventListener("resize", handleCloseMenu);
    window.addEventListener("scroll", handleCloseMenu, { capture: true });

    return () => {
      window.removeEventListener("contextmenu", handleGlobalContextMenu);
      window.removeEventListener("open-context-menu" as any, handleOpenMenu);
      window.removeEventListener("mousedown", handleMouseDown);
      window.removeEventListener("close-context-menus", handleCloseMenu);
      window.removeEventListener("resize", handleCloseMenu);
      window.removeEventListener("scroll", handleCloseMenu, { capture: true });
    };
  }, []);

  if (!menu) return null;

  const handleAddTrack = (type: "video" | "audio" | "subtitle") => {
    const existingTracksOfType = timeline.tracks.filter((t) => t.type === type);
    const trackCount = existingTracksOfType.length + 1;

    let newOrderIndex = 0;
    if (existingTracksOfType.length > 0) {
      newOrderIndex =
        Math.max(...existingTracksOfType.map((t) => t.orderIndex)) + 1;
    } else {
      newOrderIndex = type === "subtitle" ? 0 : type === "video" ? 100 : 200;
    }

    let trackPrefix = type.toUpperCase();
    if (type === "video") trackPrefix = "VISUAL";

    setTimeline({
      ...timeline,
      tracks: [
        ...timeline.tracks,
        {
          id: crypto.randomUUID(),
          name: `${trackPrefix} ${trackCount}`,
          type,
          orderIndex: newOrderIndex,
          isHidden: false,
          isMuted: false,
          isLocked: false,
        },
      ],
    });
    setMenu(null);
  };

  const handleDeleteTrack = (trackId?: string) => {
    if (!trackId) return;

    const trackToDelete = timeline.tracks.find((t) => t.id === trackId);
    if (trackToDelete?.type === "video") {
      const visualTracks = timeline.tracks.filter((t) => t.type === "video");
      if (visualTracks.length <= 1) {
        setMenu(null);
        return;
      }
    }

    setTimeline({
      ...timeline,
      tracks: timeline.tracks.filter((t) => t.id !== trackId),
      clips: timeline.clips.filter((c) => c.trackId !== trackId),
    });
    setMenu(null);
  };

  const handleDeleteClip = (clipId?: string) => {
    if (!clipId) return;
    setTimeline({
      ...timeline,
      clips: timeline.clips.filter((c) => c.id !== clipId),
    });
    setMenu(null);
  };

  const handleEditWaypoint = (wpId?: string) => {
    if (!wpId) return;
    setActiveWaypointId(wpId);
    setMenu(null);
  };

  const handleDupeWaypoint = (wpId?: string) => {
    if (!wpId) return;
    const targetWp = waypoints.find((w) => w.id === wpId);
    if (!targetWp) return;
    const newId = Math.random().toString(36).substring(7);
    const duplicatedWp = {
      ...targetWp,
      id: newId,
      name: `${targetWp.name} (Copy)`,
      lat: targetWp.lat + 0.0005,
      lng: targetWp.lng + 0.0005,
    };
    setWaypoints([...waypoints, duplicatedWp]);
    setActiveWaypointId(newId);
    setMenu(null);
  };

  const handleDeleteWaypoint = (wpId?: string) => {
    if (!wpId) return;
    setWaypoints(waypoints.filter((w) => w.id !== wpId));
    setMenu(null);
  };

  const handleSetRouteMode = (wpId: string | undefined, mode: string) => {
    if (!wpId) return;
    setWaypoints(
      waypoints.map((w) =>
        w.id === wpId ? { ...w, routeMode: mode as any } : w,
      ),
    );
    if (setIsDirty) setIsDirty(true);
    setMenu(null);
  };

  const handleSetWaypointType = (
    wpId: string | undefined,
    type: "start" | "end" | "stopby" | "normal",
  ) => {
    if (!wpId) return;

    const newWaypoints = [...waypoints];
    const currentIndex = newWaypoints.findIndex((w) => w.id === wpId);
    if (currentIndex === -1) return;

    const wp = newWaypoints[currentIndex];

    if (type === "start") {
      newWaypoints.splice(currentIndex, 1);
      newWaypoints.unshift({
        ...wp,
        isStopBy: false,
        connectToRoute: undefined,
      });
    } else if (type === "end") {
      newWaypoints.splice(currentIndex, 1);
      newWaypoints.push({ ...wp, isStopBy: false, connectToRoute: undefined });
    } else if (type === "stopby") {
      newWaypoints[currentIndex] = {
        ...wp,
        isStopBy: true,
        connectToRoute: false,
      };
    } else if (type === "normal") {
      newWaypoints[currentIndex] = {
        ...wp,
        isStopBy: false,
        connectToRoute: undefined,
      };
    }

    setWaypoints(newWaypoints);
    if (setIsDirty) setIsDirty(true);
    setMenu(null);
  };

  const handleDuplicateClip = (clipId?: string) => {
    if (!clipId) return;
    const targetClip = timeline.clips.find((c) => c.id === clipId);
    if (!targetClip) return;

    const newClip = {
      ...targetClip,
      id: crypto.randomUUID(),
      startTime: targetClip.startTime + targetClip.duration,
    };

    setTimeline({
      ...timeline,
      clips: [...timeline.clips, newClip],
    });
    setMenu(null);
  };

  const menuWidth = 192;
  let estimatedHeight = 200;

  if (menu.type === "timeline-clip" || menu.type === "map-canvas")
    estimatedHeight = 50;
  if (menu.type === "track-header") estimatedHeight = 320;
  if (menu.type === "waypoint-marker") estimatedHeight = 220; // ✨ Slightly increased for new option

  let top = menu.y;
  let left = menu.x;

  if (top + estimatedHeight > window.innerHeight) {
    top = menu.y - estimatedHeight;
    if (top < 0) top = window.innerHeight - estimatedHeight - 12;
  }

  if (left + menuWidth > window.innerWidth) {
    left = window.innerWidth - menuWidth - 8;
  }

  const popSubmenuLeft = left + menuWidth * 2 > window.innerWidth;

  // Find the specific waypoint if we clicked on one
  const targetWp =
    menu.type === "waypoint-marker"
      ? waypoints.find((w) => w.id === menu.targetId)
      : null;

  return (
    <div
      id="global-context-menu"
      key={`${menu.x}-${menu.y}`}
      className="fixed z-1000 w-48 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl border border-zinc-200 dark:border-white/10 rounded-xl shadow-2xl p-1 animate-in fade-in zoom-in-95 duration-100 overflow-visible"
      style={{ top, left, maxHeight: `calc(100vh - ${Math.max(12, top)}px)` }}
      onContextMenu={(e) => e.preventDefault()}
    >
      <div className="flex flex-col text-xs font-medium text-zinc-700 dark:text-zinc-300">
        {menu.type === "track-header" && (
          <>
            <button
              onClick={() => {
                window.dispatchEvent(
                  new CustomEvent("start-rename-track", {
                    detail: { trackId: menu.targetId },
                  }),
                );
                setMenu(null);
              }}
              className="ctx-btn"
            >
              <Edit className="w-3.5 h-3.5" /> <Trans>hide-track</Trans>
            </button>
            <div className="my-1 border-t border-zinc-200 dark:border-white/10" />

            {!menu.data?.isAudioTrack && (
              <button
                onClick={() => {
                  if (menu.data?.onToggleHide) menu.data.onToggleHide();
                  setMenu(null);
                }}
                className="ctx-btn"
              >
                {menu.data?.isHidden ? (
                  <Eye className="w-3.5 h-3.5" />
                ) : (
                  <EyeOff className="w-3.5 h-3.5" />
                )}
                {menu.data?.isHidden ? t`Show Track` : t`Hide Track`}
              </button>
            )}
            {menu.data?.isAudioTrack && (
              <button
                onClick={() => {
                  if (menu.data?.onToggleMute) menu.data.onToggleMute();
                  setMenu(null);
                }}
                className="ctx-btn"
              >
                {menu.data?.isMuted ? (
                  <Volume2 className="w-3.5 h-3.5" />
                ) : (
                  <VolumeX className="w-3.5 h-3.5" />
                )}
                {menu.data?.isMuted ? t`unmute-track` : t`mute-track`}
              </button>
            )}
            <button
              onClick={() => {
                if (menu.data?.onToggleLock) menu.data.onToggleLock();
                setMenu(null);
              }}
              className="ctx-btn"
            >
              {menu.data?.isLocked ? (
                <Unlock className="w-3.5 h-3.5" />
              ) : (
                <Lock className="w-3.5 h-3.5" />
              )}
              {menu.data?.isLocked ? t`unlock-track` : t`lock-track`}
            </button>

            <div className="my-1 border-t border-zinc-200 dark:border-white/10" />
            <button
              onClick={() => handleAddTrack("subtitle")}
              className="ctx-btn"
            >
              <Plus className="w-3.5 h-3.5" /> <Trans>add-subtitle-track</Trans>
            </button>
            <button onClick={() => handleAddTrack("video")} className="ctx-btn">
              <Plus className="w-3.5 h-3.5" /> <Trans>add-visual-track</Trans>
            </button>
            <button onClick={() => handleAddTrack("audio")} className="ctx-btn">
              <Plus className="w-3.5 h-3.5" /> <Trans>add-audio-track</Trans>
            </button>
            <div className="my-1 border-t border-zinc-200 dark:border-white/10" />
            <button
              onClick={() => handleDeleteTrack(menu.targetId)}
              className="ctx-btn text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10"
            >
              <Trash2 className="w-3.5 h-3.5" /> <Trans>delete-track</Trans>
            </button>
          </>
        )}

        {menu.type === "timeline-clip" && (
          <>
            <button
              onClick={() => handleDuplicateClip(menu.targetId)}
              className="ctx-btn"
            >
              <CopyPlus className="w-3.5 h-3.5" /> <Trans>duplicate-clip</Trans>
            </button>
            <div className="my-1 border-t border-zinc-200 dark:border-white/10" />
            <button
              onClick={() => handleDeleteClip(menu.targetId)}
              className="ctx-btn text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10"
            >
              <Trash2 className="w-3.5 h-3.5" /> <Trans>delete-clip</Trans>
            </button>
            <div className="my-1 border-t border-zinc-200 dark:border-white/10" />
            <button
              onClick={() => {
                window.dispatchEvent(new CustomEvent("trigger-link-clips"));
                setMenu(null);
              }}
              className="ctx-btn"
            >
              <LinkIcon className="w-3.5 h-3.5" /> <Trans>link-clips</Trans>
            </button>

            <button
              onClick={() => {
                window.dispatchEvent(new CustomEvent("trigger-unlink-clips"));
                setMenu(null);
              }}
              className="ctx-btn"
            >
              <UnlinkIcon className="w-3.5 h-3.5" /> <Trans>unlink-clips</Trans>
            </button>
          </>
        )}

        {menu.type === "map-canvas" && (
          <>
            <button
              onClick={() => {
                if (menu.data?.setAsStart) menu.data.setAsStart();
                setMenu(null);
              }}
              className="ctx-btn"
            >
              <MapPinned className="w-3.5 h-3.5" />
              <Trans>set-as-start</Trans>{" "}
            </button>
            <button
              onClick={() => {
                if (menu.data?.setAsDestination) menu.data.setAsDestination();
                setMenu(null);
              }}
              className="ctx-btn"
            >
              <div className="w-3.5 h-3.5" />
              <Trans>set-as-destination</Trans>{" "}
            </button>
            <button
              onClick={() => {
                if (menu.data?.setAsStopBy) menu.data.setAsStopBy();
                setMenu(null);
              }}
              className="ctx-btn text-amber-600 dark:text-amber-500"
            >
              <div className="w-3.5 h-3.5" />
              <Trans>add-stop-by</Trans>{" "}
            </button>
            <div className="my-1 border-t border-zinc-200 dark:border-white/10" />
            <button
              onClick={() => {
                if (menu.data?.addWaypoint) menu.data.addWaypoint();
                setMenu(null);
              }}
              className="ctx-btn"
            >
              <WP className="w-3.5 h-3.5" /> <Trans>add-waypoint-here</Trans>
            </button>
          </>
        )}

        {menu.type === "waypoint-marker" && (
          <>
            <button
              onClick={() => {
                if (menu.targetId) addReturnStop(menu.targetId);
                setMenu(null);
              }}
              className="ctx-btn"
            >
              <CornerDownLeft className="w-3.5 h-3.5" />{" "}
              <Trans>add-return-stop</Trans>
            </button>

            <div className="relative group">
              <button className="ctx-btn w-full flex items-center justify-between">
                <span className="flex items-center gap-2">
                  <MapPinPen className="w-3.5 h-3.5" />{" "}
                  <Trans>waypoint-type</Trans>
                </span>
                <ChevronRight className="w-3.5 h-3.5 opacity-50" />
              </button>

              {/* Flyout Menu */}
              <div
                className={`absolute top-0 hidden group-hover:flex flex-col w-40 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl border border-zinc-200 dark:border-white/10 rounded-xl shadow-2xl p-1 animate-in fade-in zoom-in-95 duration-100 ${
                  popSubmenuLeft ? "right-full mr-1" : "left-full ml-1"
                }`}
              >
                <button
                  onClick={() => handleSetWaypointType(menu.targetId, "start")}
                  className="ctx-btn"
                >
                  <MapPinned className="w-3.5 h-3.5" />
                  <Trans>set-as-start</Trans>{" "}
                </button>
                <button
                  onClick={() => handleSetWaypointType(menu.targetId, "end")}
                  className="ctx-btn"
                >
                  <div className="w-3.5 h-3.5" />
                  <Trans>set-as-destination</Trans>{" "}
                </button>
                <div className="my-1 border-t border-zinc-200 dark:border-white/10" />
                <button
                  onClick={() => handleSetWaypointType(menu.targetId, "normal")}
                  className="ctx-btn text-blue-600 dark:text-blue-400"
                >
                  <MapPinPlus className="w-3.5 h-3.5" />
                  <Trans>normal-node</Trans>{" "}
                </button>
                <button
                  onClick={() => handleSetWaypointType(menu.targetId, "stopby")}
                  className="ctx-btn text-amber-600 dark:text-amber-500"
                >
                  <div className="w-3.5 h-3.5" />
                  <Trans>stop-by</Trans>{" "}
                </button>
              </div>
            </div>

            <div className="relative group mt-1">
              <button className="ctx-btn w-full flex items-center justify-between">
                <span className="flex items-center gap-2">
                  <Route className="w-3.5 h-3.5" />{" "}
                  <Trans>next-route-mode</Trans>
                </span>
                <ChevronRight className="w-3.5 h-3.5 opacity-50" />
              </button>
              {/* Flyout Menu */}
              <div
                className={`absolute top-0 hidden group-hover:flex flex-col w-32 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl border border-zinc-200 dark:border-white/10 rounded-xl shadow-2xl p-1 animate-in fade-in zoom-in-95 duration-100 ${
                  popSubmenuLeft ? "right-full mr-1" : "left-full ml-1"
                }`}
              >
                {[
                  { mode: "walking", icon: Footprints, title: t`walk` },
                  { mode: "driving", icon: Car, title: t`drive` },
                  { mode: "curve", icon: Plane, title: t`fly` },
                  { mode: "direct", icon: Ruler, title: t`direct` },
                  { mode: "ferry", icon: Ship, title: t`ferry` },
                  { mode: "draw", icon: Pencil, title: t`draw` },
                ].map(({ mode, icon: Icon, title }) => (
                  <button
                    key={mode}
                    onClick={() => handleSetRouteMode(menu.targetId, mode)}
                    className="ctx-btn"
                  >
                    <Icon className="w-3.5 h-3.5" />
                    {title}
                  </button>
                ))}
              </div>
            </div>

            <div className="my-1 border-t border-zinc-200 dark:border-white/10" />

            {/* ✨ NEW: Stop-By Route Connection Toggle */}
            {targetWp?.isStopBy && (
              <>
                <button
                  onClick={() => {
                    const newValue = !targetWp.connectToRoute;
                    setWaypoints(
                      waypoints.map((w) =>
                        w.id === menu.targetId
                          ? { ...w, connectToRoute: newValue }
                          : w,
                      ),
                    );
                    if (setIsDirty) setIsDirty(true);
                    setMenu(null);
                  }}
                  className={`ctx-btn ${targetWp.connectToRoute ? "text-amber-600 dark:text-amber-500" : "text-blue-600 dark:text-blue-400"}`}
                >
                  {targetWp.connectToRoute ? (
                    <UnlinkIcon className="w-3.5 h-3.5" />
                  ) : (
                    <LinkIcon className="w-3.5 h-3.5" />
                  )}
                  {targetWp.connectToRoute
                    ? t`disconnect-route`
                    : t`connect-to-route`}
                </button>
                <div className="my-1 border-t border-zinc-200 dark:border-white/10" />
              </>
            )}

            <button
              onClick={() => handleEditWaypoint(menu.targetId)}
              className="ctx-btn"
            >
              <Edit className="w-3.5 h-3.5" /> <Trans>edit-waypoint</Trans>
            </button>

            {/* Copy Trail / Retrace Back features for empty drawn routes */}
            {targetWp &&
              targetWp.routeMode === "draw" &&
              (!targetWp.customRoute || targetWp.customRoute.length === 0) && (
                <>
                  <div className="my-1 border-t border-zinc-200 dark:border-white/10" />
                  <div className="relative group/copy-trail">
                    <button className="ctx-btn w-full flex items-center justify-between text-navi-600 dark:text-navi-400">
                      <span className="flex items-center gap-2">
                        <Copy className="w-3.5 h-3.5" />{" "}
                        <Trans>copy-trail</Trans>
                      </span>
                      <ChevronRight className="w-3.5 h-3.5 opacity-50" />
                    </button>
                    <div
                      className={`absolute top-0 hidden group-hover/copy-trail:flex flex-col w-48 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl border border-zinc-200 dark:border-white/10 rounded-xl shadow-2xl p-1 animate-in fade-in zoom-in-95 duration-100 ${
                        popSubmenuLeft ? "right-full mr-1" : "left-full ml-1"
                      }`}
                    >
                      <div className="px-3 py-1.5 text-[10px] font-bold text-zinc-500 uppercase tracking-wider border-b border-zinc-100 dark:border-white/5 mb-1">
                        <Trans>select-layer-to-copy</Trans>{" "}
                      </div>
                      <div className="max-h-40 overflow-y-auto custom-scrollbar">
                        {waypoints.filter(
                          (w) =>
                            w.id !== menu.targetId &&
                            w.customRoute &&
                            w.customRoute.length > 0,
                        ).length === 0 ? (
                          <div className="px-4 py-2 text-xs text-zinc-500 italic">
                            <Trans>no-drawn-trails-found</Trans>{" "}
                          </div>
                        ) : (
                          waypoints
                            .filter(
                              (w) =>
                                w.id !== menu.targetId &&
                                w.customRoute &&
                                w.customRoute.length > 0,
                            )
                            .map((w) => (
                              <button
                                key={w.id}
                                onClick={() => {
                                  if (w.customRoute && menu.targetId) {
                                    const routeCopy = [...w.customRoute];
                                    setWaypoints((prev) =>
                                      prev.map((wp) =>
                                        wp.id === menu.targetId
                                          ? {
                                              ...wp,
                                              customRoute: routeCopy,
                                              routeMode: "draw",
                                            }
                                          : wp,
                                      ),
                                    );
                                    setIsDirty(true);
                                    setMenu(null);
                                  }
                                }}
                                className="ctx-btn truncate block w-full text-left"
                              >
                                {w.name || t`waypoint`}
                              </button>
                            ))
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Retrace Back */}
                  {(() => {
                    const idx = waypoints.findIndex(
                      (w) => w.id === menu.targetId,
                    );
                    if (idx > 0 && waypoints[idx - 1]?.customRoute?.length) {
                      return (
                        <button
                          onClick={() => {
                            if (menu.targetId) {
                              const prevRoute = waypoints[idx - 1].customRoute;
                              if (prevRoute) {
                                const reversed = [...prevRoute].reverse();
                                setWaypoints((prev) =>
                                  prev.map((wp) =>
                                    wp.id === menu.targetId
                                      ? {
                                          ...wp,
                                          customRoute: reversed,
                                          routeMode: "draw",
                                        }
                                      : wp,
                                  ),
                                );
                                setIsDirty(true);
                                setMenu(null);
                              }
                            }
                          }}
                          className="ctx-btn text-amber-600 dark:text-amber-400"
                        >
                          <CornerDownLeft className="w-3.5 h-3.5" />{" "}
                          <Trans>retrace-previous-trail</Trans>{" "}
                        </button>
                      );
                    }
                    return null;
                  })()}
                </>
              )}

            <button
              onClick={() => handleDupeWaypoint(menu.targetId)}
              className="ctx-btn"
            >
              <CopyPlus className="w-3.5 h-3.5" />{" "}
              <Trans>duplicate-waypoint</Trans>
            </button>
            <div className="my-1 border-t border-zinc-200 dark:border-white/10" />
            <button
              onClick={() => handleDeleteWaypoint(menu.targetId)}
              className="ctx-btn text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10"
            >
              <Trash2 className="w-3.5 h-3.5" /> <Trans>delete-waypoint</Trans>
            </button>
          </>
        )}

        {menu.type === "empty-track" && (
          <>
            <button
              onClick={() => handleAddTrack("subtitle")}
              className="ctx-btn"
            >
              <Plus className="w-3.5 h-3.5" /> <Trans>add-subtitle-track</Trans>
            </button>
            <button onClick={() => handleAddTrack("video")} className="ctx-btn">
              <Plus className="w-3.5 h-3.5" /> <Trans>add-visual-track</Trans>
            </button>
            <button onClick={() => handleAddTrack("audio")} className="ctx-btn">
              <Plus className="w-3.5 h-3.5" /> <Trans>add-audio-track</Trans>
            </button>
            <div className="my-1 border-t border-zinc-200 dark:border-white/10" />
            {menu.targetId && (
              <>
                <button
                  onClick={() => handleDeleteTrack(menu.targetId)}
                  className="ctx-btn text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10"
                >
                  <Trash2 className="w-3.5 h-3.5" />{" "}
                  <Trans>delete-empty-track</Trans>
                </button>
              </>
            )}
          </>
        )}

        {menu.type === "project-card" && (
          <>
            <button
              onClick={() => {
                if (menu.data?.onOpen) menu.data.onOpen();
                setMenu(null);
              }}
              className="ctx-btn"
            >
              <FolderOpen className="w-3.5 h-3.5" /> <Trans>open-project</Trans>
            </button>
            <div className="my-1 border-t border-zinc-200 dark:border-white/10" />
            <button
              onClick={() => {
                if (menu.data?.onRename) menu.data.onRename();
                setMenu(null);
              }}
              className="ctx-btn"
            >
              <Edit3 className="w-3.5 h-3.5" /> <Trans>rename</Trans>
            </button>
            <button
              onClick={() => {
                if (menu.data?.onDuplicate) menu.data.onDuplicate();
                setMenu(null);
              }}
              className="ctx-btn"
            >
              <Copy className="w-3.5 h-3.5" /> <Trans>duplicate</Trans>
            </button>
            <button
              onClick={() => {
                if (menu.data?.onQuickRender) menu.data.onQuickRender();
                setMenu(null);
              }}
              className="ctx-btn"
            >
              <Film className="w-3.5 h-3.5" /> <Trans>Quick Render</Trans>
            </button>
            <button
              onClick={() => {
                if (menu.data?.onReveal) menu.data.onReveal();
                setMenu(null);
              }}
              className="ctx-btn"
            >
              <Folder className="w-3.5 h-3.5" />{" "}
              <Trans>Reveal in File Explorer</Trans>
            </button>

            <div className="my-1 border-t border-zinc-200 dark:border-white/10" />
            <button
              onClick={() => {
                if (menu.data?.onRemove) menu.data.onRemove();
                setMenu(null);
              }}
              className="ctx-btn text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10"
            >
              <Trash2 className="w-3.5 h-3.5" /> <Trans>remove-from-list</Trans>
            </button>
          </>
        )}

        {menu.type === "mediapool-item" && (
          <>
            <button
              onClick={() => {
                if (menu.data?.onDuplicate) menu.data.onDuplicate();
                setMenu(null);
              }}
              className="ctx-btn"
            >
              <Copy className="w-3.5 h-3.5" /> <Trans>duplicate</Trans>
            </button>
            <button
              onClick={() => {
                if (menu.data?.onQuickRender) menu.data.onQuickRender();
                setMenu(null);
              }}
              className="ctx-btn"
            >
              <Film className="w-3.5 h-3.5" /> <Trans>Quick Render</Trans>
            </button>
            <button
              onClick={() => {
                if (menu.data?.onReveal) menu.data.onReveal();
                setMenu(null);
              }}
              className="ctx-btn"
            >
              <Folder className="w-3.5 h-3.5" />{" "}
              <Trans>Reveal in File Explorer</Trans>
            </button>
            <button
              onClick={() => {
                if (menu.data?.onProperties) menu.data.onProperties();
                setMenu(null);
              }}
              className="ctx-btn"
            >
              <Settings2 className="w-3.5 h-3.5" /> <Trans>properties</Trans>
            </button>
            <div className="my-1 border-t border-zinc-200 dark:border-white/10" />
            <button
              onClick={() => {
                if (menu.data?.onRemove) menu.data.onRemove();
                setMenu(null);
              }}
              className="ctx-btn text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10"
            >
              <Trash2 className="w-3.5 h-3.5" />{" "}
              <Trans>remove-from-media-pool</Trans>
            </button>
          </>
        )}
      </div>
    </div>
  );
}
