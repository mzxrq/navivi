import { useEffect, useState } from "react";
import { useWorkspace } from "../../hooks/useWorkspace";
import { useWaypointActions } from "../../hooks/useWaypointActions";
import { 
  Plus, Trash2, MapPin,
  CornerDownLeft, Edit, CopyPlus
} from "../ui/icons";

export interface ContextMenuState {
  x: number;
  y: number;
  type: "track-header" | "timeline-clip" | "map-canvas" | "waypoint-marker";
  targetId?: string; 
  data?: any;
}

export function ContextMenu() {
  const [menu, setMenu] = useState<ContextMenuState | null>(null);
  const { timeline, setTimeline, waypoints, setWaypoints, setActiveWaypointId } = useWorkspace();
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

    // FIX: Catch Middle Clicks and Outside Clicks instantly before 'click' event
    const handleMouseDown = (e: MouseEvent) => {
      // If it's a middle click (scroll wheel), kill the menu instantly
      if (e.button === 1) {
        setMenu(null);
        return;
      }
      // If it's a left click OUTSIDE the menu, kill it.
      // (We let clicks INSIDE the menu pass through so the button onClick can fire)
      if (!(e.target as Element).closest("#global-context-menu")) {
        setMenu(null);
      }
    };

    window.addEventListener("contextmenu", handleGlobalContextMenu);
    window.addEventListener("open-context-menu" as any, handleOpenMenu);
    window.addEventListener("mousedown", handleMouseDown); 
    window.addEventListener("close-context-menus", handleCloseMenu);
    
    // Catch window resizes and timeline/map scrolling!
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
      tracks: [...timeline.tracks, { id: crypto.randomUUID(), name: `${type.toUpperCase()} ${trackCount}`, type }],
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
    setTimeline({ ...timeline, clips: timeline.clips.filter((c) => c.id !== clipId) });
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
      ...targetWp, id: newId, name: `${targetWp.name} (Copy)`, lat: targetWp.lat + 0.0005, lng: targetWp.lng + 0.0005,
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

  // --- PERFECT NATIVE POSITIONING MATH ---
  const MENU_WIDTH = 192; 
  let estimatedHeight = 200; 
  
  if (menu.type === "timeline-clip" || menu.type === "map-canvas") estimatedHeight = 50;
  if (menu.type === "track-header") estimatedHeight = 120;
  if (menu.type === "waypoint-marker") estimatedHeight = 175; 

  let top = menu.y;
  let left = menu.x;

  // 1. If it hits the bottom of the screen, flip it so it renders UPWARDS from the cursor!
  if (top + estimatedHeight > window.innerHeight) {
    top = menu.y - estimatedHeight;
    // Safety clamp in case flipping it pushes it off the top of the screen
    if (top < 0) top = window.innerHeight - estimatedHeight - 12; 
  }

  // 2. Slide left if it hits the right edge
  if (left + MENU_WIDTH > window.innerWidth) {
    left = window.innerWidth - MENU_WIDTH - 8;
  }

  return (
    <div
      id="global-context-menu" // Added ID so the mousedown listener can detect it!
      key={`${menu.x}-${menu.y}`} 
      className="fixed z-1000 w-48 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl border border-zinc-200 dark:border-white/10 rounded-xl shadow-2xl p-1 animate-in fade-in zoom-in-95 duration-100"
      style={{ top, left }}
      onContextMenu={(e) => e.preventDefault()}
    >
      <div className="flex flex-col text-xs font-medium text-zinc-700 dark:text-zinc-300">
        
        {menu.type === "track-header" && (
          <>
            <button onClick={() => {
              window.dispatchEvent(new CustomEvent("start-rename-track", { detail: { trackId: menu.targetId } }));
              setMenu(null);
            }} className="ctx-btn">
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
            <button onClick={() => handleDeleteTrack(menu.targetId)} className="ctx-btn text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10">
              <Trash2 className="w-3.5 h-3.5" /> Delete Track
            </button>
          </>
        )}

        {menu.type === "timeline-clip" && (
          <button onClick={() => handleDeleteClip(menu.targetId)} className="ctx-btn text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10">
            <Trash2 className="w-3.5 h-3.5" /> Delete Clip
          </button>
        )}

        {menu.type === "map-canvas" && (
          <button
            onClick={() => {
              if (menu.data?.handleAddWaypoint) menu.data.handleAddWaypoint(menu.data.lat, menu.data.lng);
              setMenu(null);
            }}
            className="ctx-btn"
          >
            <MapPin className="w-3.5 h-3.5" /> Add Waypoint Here
          </button>
        )}

        {menu.type === "waypoint-marker" && (
          <>
            <button onClick={() => { if (menu.targetId) addReturnStop(menu.targetId); setMenu(null); }} className="ctx-btn">
              <CornerDownLeft className="w-3.5 h-3.5"/> Add Return Stop
            </button>
            <div className="my-1 border-t border-zinc-200 dark:border-white/10" />
            <button onClick={() => handleEditWaypoint(menu.targetId)} className="ctx-btn">
              <Edit className="w-3.5 h-3.5" /> Edit Waypoint
            </button>
            <button onClick={() => handleDupeWaypoint(menu.targetId)} className="ctx-btn">
              <CopyPlus className="w-3.5 h-3.5" /> Duplicate Waypoint
            </button>
            <div className="my-1 border-t border-zinc-200 dark:border-white/10" />
            <button onClick={() => handleDeleteWaypoint(menu.targetId)} className="ctx-btn text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10">
              <Trash2 className="w-3.5 h-3.5" /> Delete Waypoint
            </button>
          </>
        )}

      </div>
    </div>
  );
}