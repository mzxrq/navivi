import { Marker, Popup } from "react-leaflet";
import { Car, Footprints, Ruler, Plane, Ship } from "../../../ui/icons";
import { useWorkspace } from "../../../../hooks/useWorkspace";
import { useWaypointActions } from "../../../../hooks/useWaypointActions";
import { waypointIcon } from "../../../../utils/mapUtils";

interface WaypointLayerProps {
  isGeneratingOverview?: boolean;
}

export function WaypointLayer({ isGeneratingOverview = false }: WaypointLayerProps) {
  const { waypoints, updateWaypoint, settings } = useWorkspace();
  const { updateWaypointLocation } = useWaypointActions();

  const hexMarkerColor = "#" + settings.marker_color.map((x) => x.toString(16).padStart(2, "0")).join("");

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

              // Trigger the Global Context Menu!
              window.dispatchEvent(new CustomEvent("open-context-menu", {
                detail: {
                  x: domEvent.clientX, // Use clientX/Y to ignore scroll positions
                  y: domEvent.clientY,
                  type: "waypoint-marker",
                  targetId: wp.id,
                }
              }));
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
                    onClick={(e) => { e.stopPropagation(); updateWaypoint(wp.id, { routeMode: "driving" }); }}
                    className={`flex-1 flex justify-center p-1.5 rounded-md transition-all ${!wp.routeMode || wp.routeMode === "driving" ? "bg-white shadow-sm text-emerald-600 ring-1 ring-zinc-200" : "text-zinc-500 hover:text-zinc-800 hover:bg-zinc-200/50"}`}
                    title="Drive"
                  ><Car className="w-4 h-4" /></button>
                  <button
                    disabled={isGeneratingOverview}
                    onClick={(e) => { e.stopPropagation(); updateWaypoint(wp.id, { routeMode: "walking" }); }}
                    className={`flex-1 flex justify-center p-1.5 rounded-md transition-all ${wp.routeMode === "walking" ? "bg-white shadow-sm text-emerald-600 ring-1 ring-zinc-200" : "text-zinc-500 hover:text-zinc-800 hover:bg-zinc-200/50"}`}
                    title="Foot"
                  ><Footprints className="w-4 h-4" /></button>
                  <button
                    disabled={isGeneratingOverview}
                    onClick={(e) => { e.stopPropagation(); updateWaypoint(wp.id, { routeMode: "direct" }); }}
                    className={`flex-1 flex justify-center p-1.5 rounded-md transition-all ${wp.routeMode === "direct" ? "bg-white shadow-sm text-emerald-600 ring-1 ring-zinc-200" : "text-zinc-500 hover:text-zinc-800 hover:bg-zinc-200/50"}`}
                    title="Direct"
                  ><Ruler className="w-4 h-4" /></button>
                  <button
                    disabled={isGeneratingOverview}
                    onClick={(e) => { e.stopPropagation(); updateWaypoint(wp.id, { routeMode: "curve" }); }}
                    className={`flex-1 flex justify-center p-1.5 rounded-md transition-all ${wp.routeMode === "curve" ? "bg-white shadow-sm text-emerald-600 ring-1 ring-zinc-200" : "text-zinc-500 hover:text-zinc-800 hover:bg-zinc-200/50"}`}
                    title="Flight"
                  ><Plane className="w-4 h-4" /></button>
                  <button
                    disabled={isGeneratingOverview}
                    onClick={(e) => { e.stopPropagation(); updateWaypoint(wp.id, { routeMode: "ferry"}); }}
                    className={`flex-1 flex justify-center p-1.5 rounded-md transition-all ${wp.routeMode === "ferry" ? "bg-white shadow-sm text-blue-600 ring-1 ring-zinc-200" : "text-zinc-500 hover:text-zinc-800 hover:bg-zinc-200/50"}`}
                    title="Ferry"
                  ><Ship className="w-4 h-4" /></button>
                </div>
              </div>
            </div>
          </Popup>
        </Marker>
      ))}
    </>
  );
}