import { Marker, Popup } from "react-leaflet";
import { createPortal } from "react-dom";
import {
  Car,
  Footprints,
  Ruler,
  Plane,
  Trash2,
  Edit,
  CopyPlus,
  CornerDownLeft,
  Ship,
} from "lucide-react";
import { useWorkspace } from "../../../../hooks/useWorkspace";
import { useWaypointActions } from "../../../../hooks/useWaypointActions";
import { waypointIcon } from "../../../../utils/mapUtils";
import { useEffect, useState } from "react";

interface WaypointLayerProps {
  isGeneratingOverview?: boolean;
}

export function WaypointLayer({ isGeneratingOverview = false }: WaypointLayerProps) {
  const { waypoints, updateWaypoint, setWaypoints, settings, setActiveWaypointId } = useWorkspace();
  const { updateWaypointLocation, addReturnStop } = useWaypointActions();

  const [menu, setMenu] = useState<{
    show: boolean;
    x: number;
    y: number;
    wpId: string;
  } | null>(null);

  useEffect(() => {
    const closeMenu = () => setMenu(null);
    window.addEventListener("click", closeMenu);
    window.addEventListener("close-context-menus", closeMenu);

    return () => {
      window.removeEventListener("click", closeMenu);
      window.removeEventListener("close-context-menus", closeMenu);
    };
  }, []);

  const hexMarkerColor =
    "#" +
    settings.marker_color.map((x) => x.toString(16).padStart(2, "0")).join("");

  const handleDelete = (wpId: string) => {
    if (isGeneratingOverview) return;
    setWaypoints((prev) => prev.filter((w) => w.id !== wpId));
    setMenu(null);
  };

  const handleEdit = (wpId: string) => {
    setActiveWaypointId(wpId);
    setMenu(null);
  };

  const handleDupe = (wpId: string) => {
    if (isGeneratingOverview) return;
    const targetWp = waypoints.find((w) => w.id === wpId);
    if (!targetWp) return;

    const newId = Math.random().toString(36).substring(7);
    const duplicatedWp = {
      ...targetWp,
      id: newId,
      name: `${targetWp.name} (Copy)`,
      lat: targetWp.lat + 0.0005, // Offset slightly so it's visible on map
      lng: targetWp.lng + 0.0005,
    };

    setWaypoints((prev) => [...prev, duplicatedWp]);
    setActiveWaypointId(newId);
    setMenu(null);
  };

  return (
    <>
      {waypoints.map((wp, index) => (
        <Marker
          key={wp.id}
          position={[wp.lat, wp.lng]}
          draggable={!isGeneratingOverview}
          icon={waypointIcon(index + 1, hexMarkerColor)}
          eventHandlers={{
            dragend: async (e) => {
              if (isGeneratingOverview) return;
              const marker = e.target;
              const position = marker.getLatLng();
              updateWaypointLocation(wp.id, position.lat, position.lng);
            },
            contextmenu: (e) => {
              if (isGeneratingOverview) return;
              const domEvent = e.originalEvent as MouseEvent;
              domEvent.stopPropagation();
              domEvent.preventDefault();

              window.dispatchEvent(new Event("close-context-menus"));

              const xPos =
                domEvent.pageX + 160 > window.innerWidth
                  ? window.innerWidth - 160
                  : domEvent.pageX;
              const yPos =
                domEvent.pageY + 80 > window.innerHeight
                  ? window.innerHeight - 80
                  : domEvent.pageY;

              setMenu({ show: true, x: xPos, y: yPos, wpId: wp.id });
            },
          }}
        >
          <Popup>
            <div className="flex flex-col gap-2 min-w-40 pb-1">
              <div className="font-bold text-sm text-zinc-900 leading-tight">
                {wp.name}
              </div>

              {wp.narration && (
                <div className="text-xs text-zinc-600 italic border-l-2 border-zinc-300 pl-2">
                  "{wp.narration}"
                </div>
              )}

              <div className="flex flex-col gap-1 mt-2 pt-2 border-t border-zinc-200">
                <span className="text-[10px] font-extrabold text-zinc-400 uppercase tracking-wider mb-1">
                  To next stop:
                </span>
                <div className="flex items-center gap-1 bg-zinc-100 p-1 rounded-lg border border-zinc-200">
                  <button
                    disabled={isGeneratingOverview}
                    onClick={(e) => {
                      e.stopPropagation();
                      updateWaypoint(wp.id, { routeMode: "driving" });
                    }}
                    className={`flex-1 flex justify-center p-1.5 rounded-md transition-all ${!wp.routeMode || wp.routeMode === "driving" ? "bg-white shadow-sm text-emerald-600 ring-1 ring-zinc-200" : "text-zinc-500 hover:text-zinc-800 hover:bg-zinc-200/50"}`}
                    title="Drive"
                  >
                    <Car className="w-4 h-4" />
                  </button>

                  <button
                    disabled={isGeneratingOverview}
                    onClick={(e) => {
                      e.stopPropagation();
                      updateWaypoint(wp.id, { routeMode: "walking" });
                    }}
                    className={`flex-1 flex justify-center p-1.5 rounded-md transition-all ${wp.routeMode === "walking" ? "bg-white shadow-sm text-emerald-600 ring-1 ring-zinc-200" : "text-zinc-500 hover:text-zinc-800 hover:bg-zinc-200/50"}`}
                    title="Foot"
                  >
                    <Footprints className="w-4 h-4" />
                  </button>

                  <button
                    disabled={isGeneratingOverview}
                    onClick={(e) => {
                      e.stopPropagation();
                      updateWaypoint(wp.id, { routeMode: "direct" });
                    }}
                    className={`flex-1 flex justify-center p-1.5 rounded-md transition-all ${wp.routeMode === "direct" ? "bg-white shadow-sm text-emerald-600 ring-1 ring-zinc-200" : "text-zinc-500 hover:text-zinc-800 hover:bg-zinc-200/50"}`}
                    title="Direct"
                  >
                    <Ruler className="w-4 h-4" />
                  </button>

                  <button
                    disabled={isGeneratingOverview}
                    onClick={(e) => {
                      e.stopPropagation();
                      updateWaypoint(wp.id, { routeMode: "curve" });
                    }}
                    className={`flex-1 flex justify-center p-1.5 rounded-md transition-all ${wp.routeMode === "curve" ? "bg-white shadow-sm text-emerald-600 ring-1 ring-zinc-200" : "text-zinc-500 hover:text-zinc-800 hover:bg-zinc-200/50"}`}
                    title="Flight"
                  >
                    <Plane className="w-4 h-4" />
                  </button>
                  <button
                    disabled={isGeneratingOverview}
                    onClick={(e) => {
                      e.stopPropagation();
                      updateWaypoint(wp.id, { routeMode: "ferry"});
                    }}
                    className={`flex-1 flex justify-center p-1.5 rounded-md transition-all ${
                      wp.routeMode === "ferry"
                        ? "bg-white shadow-sm text-blue-600 ring-1 ring-zinc-200"
                        : "text-zinc-500 hover:text-zinc-800 hover:bg-zinc-200/50"
                    }`}
                    title="Ferry"
                  >
                    <Ship className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>
          </Popup>
        </Marker>
      ))}

      {menu?.show &&
        createPortal(
          <div
            key={`${menu.x}-${menu.y}-marker`}
            className="fixed z-1000 w-48 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl border border-zinc-200 dark:border-white/10 rounded-xl shadow-2xl p-1 animate-in fade-in zoom-in-95 duration-100"
            style={{ top: menu.y, left: menu.x }}
            onContextMenu={(e) => {
              e.preventDefault();
              e.stopPropagation();
            }}
          >
            <div className="flex flex-col text-sm text-zinc-700 dark:text-zinc-300 font-medium">
              <button
                onClick={() => {
                  addReturnStop(menu.wpId);
                  setMenu(null);                  
                }}
                className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors text-left"
              >
                <CornerDownLeft className="w-4 h-4"/> Add Return Stop
              </button>

              <div className="h-px bg-zinc-200 dark:bg-white/5 my-1" />

              <button
                onClick={() => handleEdit(menu.wpId)}
                className="flex items-center gap-2 px-3 py-2 rounded-lg text-zinc-600 hover:bg-zinc-100 dark:hover:bg-zinc-800 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors text-left"
              >
                <Edit className="w-4 h-4" /> Edit Waypoint
              </button>
              
              <button
                onClick={() => handleDupe(menu.wpId)}
                className="flex items-center gap-2 px-3 py-2 rounded-lg text-zinc-600 hover:bg-zinc-100 dark:hover:bg-zinc-800 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors text-left"
              >
                <CopyPlus className="w-4 h-4" /> Duplicate Waypoint
              </button>
            </div>

            <div className="h-px bg-zinc-200 dark:bg-white/5 my-1" />

            <div className="flex flex-col text-sm text-zinc-700 dark:text-zinc-300 font-medium">
              <button
                onClick={() => handleDelete(menu.wpId)}
                className="flex items-center gap-2 px-3 py-2 rounded-lg text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10 transition-colors text-left"
              >
                <Trash2 className="w-4 h-4" /> Delete Waypoint
              </button>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}