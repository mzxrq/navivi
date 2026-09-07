import { useEffect, useState } from "react";
import { useWorkspace } from "../../hooks/useWorkspace";
import { useWaypointActions } from "../../hooks/useWaypointActions";
import {
  Plus,
  Trash2,
  WP,
  MapPinned,
  MapPinPlus,
  CornerDownLeft,
  Edit,
  CopyPlus,
  MapPinPen,
  ChevronRight // ✨ Imported for the submenu arrow
} from "../ui/icons";

export interface ContextMenuState {
  x: number;
  y: number;
  type: "track-header" | "timeline-clip" | "map-canvas" | "waypoint-marker" | "empty-track";
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

  const handleAddTrack = (type: "video" | "audio") => {
    const trackCount = timeline.tracks.length + 1;
    setTimeline({
      ...timeline,
      tracks: [
        ...timeline.tracks,
        {
          id: crypto.randomUUID(),
          name: `${type.toUpperCase()} ${trackCount}`,
          type,
        },
      ],
    });
    setMenu(null);
  };

  const handleDeleteTrack = (trackId?: string) => {
    if (!trackId) return;
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

  const handleSetWaypointType = (wpId: string | undefined, type: "start" | "end" | "stopby" | "normal") => {
    if (!wpId) return;
    
    const newWaypoints = [...waypoints];
    const currentIndex = newWaypoints.findIndex(w => w.id === wpId);
    if (currentIndex === -1) return;
    
    const wp = newWaypoints[currentIndex];
    
    if (type === "start") {
      newWaypoints.splice(currentIndex, 1);
      newWaypoints.unshift({ ...wp, isStopBy: false }); // Move to front, force normal
    } else if (type === "end") {
      newWaypoints.splice(currentIndex, 1);
      newWaypoints.push({ ...wp, isStopBy: false }); // Move to back, force normal
    } else if (type === "stopby") {
      newWaypoints[currentIndex] = { ...wp, isStopBy: true };
    } else if (type === "normal") {
      newWaypoints[currentIndex] = { ...wp, isStopBy: false };
    }
    
    setWaypoints(newWaypoints);
    setMenu(null);
  };

  const handleDuplicateClip = (clipId?: string) => {
    if (!clipId) return;
    const targetClip = timeline.clips.find(c => c.id === clipId);
    if (!targetClip) return;

    const newClip = {
      ...targetClip,
      id: crypto.randomUUID(),
      startTime: targetClip.startTime + targetClip.duration,
    };

    setTimeline({
      ...timeline,
      clips: [...timeline.clips, newClip]
    });
    setMenu(null);
  };

  const menuWidth = 192;
  let estimatedHeight = 200;

  if (menu.type === "timeline-clip" || menu.type === "map-canvas") estimatedHeight = 50;
  if (menu.type === "track-header") estimatedHeight = 120;
  if (menu.type === "waypoint-marker") estimatedHeight = 175;

  let top = menu.y;
  let left = menu.x;

  if (top + estimatedHeight > window.innerHeight) {
    top = menu.y - estimatedHeight;
    if (top < 0) top = window.innerHeight - estimatedHeight - 12;
  }

  if (left + menuWidth > window.innerWidth) {
    left = window.innerWidth - menuWidth - 8;
  }

  const popSubmenuLeft = left + (menuWidth * 2) > window.innerWidth;

  return (
    <div
      id="global-context-menu"
      key={`${menu.x}-${menu.y}`}
      className="fixed z-1000 w-48 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl border border-zinc-200 dark:border-white/10 rounded-xl shadow-2xl p-1 animate-in fade-in zoom-in-95 duration-100"
      style={{ top, left }}
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
              <Edit className="w-3.5 h-3.5" /> Rename Track
            </button>
            <div className="my-1 border-t border-zinc-200 dark:border-white/10" />
            <button onClick={() => handleAddTrack("video")} className="ctx-btn">
              <Plus className="w-3.5 h-3.5" /> Add Video Track
            </button>
            <button onClick={() => handleAddTrack("audio")} className="ctx-btn">
              <Plus className="w-3.5 h-3.5" /> Add Audio Track
            </button>
            <div className="my-1 border-t border-zinc-200 dark:border-white/10" />
            <button
              onClick={() => handleDeleteTrack(menu.targetId)}
              className="ctx-btn text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10"
            >
              <Trash2 className="w-3.5 h-3.5" /> Delete Track
            </button>
          </>
        )}

        {menu.type === "timeline-clip" && (
          <>
          <button
            onClick={() => handleDuplicateClip(menu.targetId)}
            className="ctx-btn"
          >
            <CopyPlus className="w-3.5 h-3.5"/> Duplicate Clip
          </button>
          <div className="my-1 border-t border-zinc-200 dark:border-white/10" />
          <button
            onClick={() => handleDeleteClip(menu.targetId)}
            className="ctx-btn text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10"
          >
            <Trash2 className="w-3.5 h-3.5" /> Delete Clip
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
              <MapPinned className="w-3.5 h-3.5" />Set as Start
            </button>
            <button
              onClick={() => {
                if (menu.data?.setAsDestination) menu.data.setAsDestination();
                setMenu(null);
              }}
              className="ctx-btn"
            >
              <div className="w-3.5 h-3.5" />Set as Destination
            </button>
            <button
              onClick={() => {
                if (menu.data?.setAsStopBy) menu.data.setAsStopBy();
                setMenu(null);
              }}
              className="ctx-btn text-amber-600 dark:text-amber-500"
            >
              <div className="w-3.5 h-3.5" />Add Stop By
            </button>
            <div className="my-1 border-t border-zinc-200 dark:border-white/10" />
            <button
              onClick={() => {
                if (menu.data?.addWaypoint) menu.data.addWaypoint();
                setMenu(null);
              }}
              className="ctx-btn"
            >
              <WP className="w-3.5 h-3.5" /> Add Waypoint Here
            </button>
          </>
        )}

        {menu.type === "waypoint-marker" && (
          <>
            <button onClick={() => { if (menu.targetId) addReturnStop(menu.targetId); setMenu(null); }} className="ctx-btn">
              <CornerDownLeft className="w-3.5 h-3.5"/> Add Return Stop
            </button>
            
            {/* ✨ NEW: The Submenu Implementation */}
            <div className="relative group">
              <button className="ctx-btn w-full flex items-center justify-between">
                <span className="flex items-center gap-2">
                  <MapPinPen className="w-3.5 h-3.5" /> Waypoint Type
                </span>
                <ChevronRight className="w-3.5 h-3.5 opacity-50" />
              </button>
              
              {/* Flyout Menu */}
              <div 
                className={`absolute top-0 hidden group-hover:flex flex-col w-40 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl border border-zinc-200 dark:border-white/10 rounded-xl shadow-2xl p-1 animate-in fade-in zoom-in-95 duration-100 ${
                  popSubmenuLeft ? "right-full mr-1" : "left-full ml-1"
                }`}
              >
                <button onClick={() => handleSetWaypointType(menu.targetId, "start")} className="ctx-btn"><MapPinned className="w-3.5 h-3.5" />Set as Start</button>
                <button onClick={() => handleSetWaypointType(menu.targetId, "end")} className="ctx-btn"><div className="w-3.5 h-3.5" />Set as Destination</button>
                <div className="my-1 border-t border-zinc-200 dark:border-white/10" />
                <button onClick={() => handleSetWaypointType(menu.targetId, "normal")} className="ctx-btn text-blue-600 dark:text-blue-400"><MapPinPlus className="w-3.5 h-3.5" />Normal Node</button>
                <button onClick={() => handleSetWaypointType(menu.targetId, "stopby")} className="ctx-btn text-amber-600 dark:text-amber-500"><div className="w-3.5 h-3.5" />Stop By</button>
              </div>
            </div>

            <div className="my-1 border-t border-zinc-200 dark:border-white/10" />
            <button
              onClick={() => handleEditWaypoint(menu.targetId)}
              className="ctx-btn"
            >
              <Edit className="w-3.5 h-3.5" /> Edit Waypoint
            </button>
            <button
              onClick={() => handleDupeWaypoint(menu.targetId)}
              className="ctx-btn"
            >
              <CopyPlus className="w-3.5 h-3.5" /> Duplicate Waypoint
            </button>
            <div className="my-1 border-t border-zinc-200 dark:border-white/10" />
            <button
              onClick={() => handleDeleteWaypoint(menu.targetId)}
              className="ctx-btn text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10"
            >
              <Trash2 className="w-3.5 h-3.5" /> Delete Waypoint
            </button>
          </>
        )}

        {menu.type === "empty-track" && (
          <>
            <button onClick={() => handleAddTrack("video")} className="ctx-btn">
              <Plus className="w-3.5 h-3.5" /> Add Video Track
            </button>
            <button onClick={() => handleAddTrack("audio")} className="ctx-btn">
              <Plus className="w-3.5 h-3.5" /> Add Audio Track
            </button>
            <div className="my-1 border-t border-zinc-200 dark:border-white/10"/>
            {menu.targetId && (
            <>
              <button
                onClick={() => handleDeleteTrack(menu.targetId)}
                className="ctx-btn text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10"
              >
                <Trash2 className="w-3.5 h-3.5" /> Delete Empty Track
              </button>
            </>
          )}
          </>
        )}
      </div>
    </div>
  );
}