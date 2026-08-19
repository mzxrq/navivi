import { Marker, Popup } from "react-leaflet";
import { Car, Footprints, Ruler, Plane } from "lucide-react";
import { useWorkspace } from "../../../../hooks/useWorkspace";
import { waypointIcon } from "../../../../utils/mapUtils";

export function WaypointLayer() {
  const { waypoints, updateWaypoint, settings } = useWorkspace();
  
  const hexMarkerColor = "#" + settings.marker_color.map((x) => x.toString(16).padStart(2, "0")).join("");

  return (
    <>
      {waypoints.map((wp, index) => (
        <Marker
          key={wp.id}
          position={[wp.lat, wp.lng]}
          draggable={true}
          icon={waypointIcon(index + 1, hexMarkerColor)}
          eventHandlers={{
            dragend: async (e) => {
              const marker = e.target;
              const position = marker.getLatLng();
              updateWaypoint(wp.id, { lat: position.lat, lng: position.lng });
              
              // Get new location name
              try {
                const response = await fetch(
                  `https://nominatim.openstreetmap.org/reverse?format=json&lat=${position.lat}&lon=${position.lng}`
                );
                const data = await response.json();
                const newName = data.address?.road || data.address?.amenity || data.name || "Unnamed Location";
                updateWaypoint(wp.id, { name: newName });
              } catch (error) {
                console.error("Failed to fetch location name:", error);
              }
            },
          }}
        >
          <Popup>
            <div className="flex flex-col gap-2 min-w-[160px] pb-1">
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
                  Travel to next stop:
                </span>
                <div className="flex items-center gap-1 bg-zinc-100 p-1 rounded-lg border border-zinc-200">
                  <button
                    onClick={(e) => { e.stopPropagation(); updateWaypoint(wp.id, { routeMode: "driving" }); }}
                    className={`flex-1 flex justify-center p-1.5 rounded-md transition-all ${!wp.routeMode || wp.routeMode === "driving" ? "bg-white shadow-sm text-emerald-600 ring-1 ring-zinc-200" : "text-zinc-500 hover:text-zinc-800 hover:bg-zinc-200/50"}`}
                    title="Driving"
                  ><Car className="w-4 h-4" /></button>

                  <button
                    onClick={(e) => { e.stopPropagation(); updateWaypoint(wp.id, { routeMode: "walking" }); }}
                    className={`flex-1 flex justify-center p-1.5 rounded-md transition-all ${wp.routeMode === "walking" ? "bg-white shadow-sm text-emerald-600 ring-1 ring-zinc-200" : "text-zinc-500 hover:text-zinc-800 hover:bg-zinc-200/50"}`}
                    title="Walking"
                  ><Footprints className="w-4 h-4" /></button>

                  <button
                    onClick={(e) => { e.stopPropagation(); updateWaypoint(wp.id, { routeMode: "direct" }); }}
                    className={`flex-1 flex justify-center p-1.5 rounded-md transition-all ${wp.routeMode === "direct" ? "bg-white shadow-sm text-emerald-600 ring-1 ring-zinc-200" : "text-zinc-500 hover:text-zinc-800 hover:bg-zinc-200/50"}`}
                    title="Direct"
                  ><Ruler className="w-4 h-4" /></button>

                  <button
                    onClick={(e) => { e.stopPropagation(); updateWaypoint(wp.id, { routeMode: "curve" }); }}
                    className={`flex-1 flex justify-center p-1.5 rounded-md transition-all ${wp.routeMode === "curve" ? "bg-white shadow-sm text-emerald-600 ring-1 ring-zinc-200" : "text-zinc-500 hover:text-zinc-800 hover:bg-zinc-200/50"}`}
                    title="Fly/Ship"
                  ><Plane className="w-4 h-4" /></button>
                </div>
              </div>
            </div>
          </Popup>
        </Marker>
      ))}
    </>
  );
}