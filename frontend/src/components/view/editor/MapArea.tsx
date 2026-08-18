import { MapSettings } from "../../modal/MapSettings";
import { useUI } from "../../../hooks/useUI";
import { invoke } from "@tauri-apps/api/core";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useTheme } from "../../../hooks/useTheme";
import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { readTextFile } from "@tauri-apps/plugin-fs";
import { open } from "@tauri-apps/plugin-dialog";
import {
  MapContainer,
  Polyline,
  TileLayer,
  Marker,
  Popup,
} from "react-leaflet";
import {
  Clock,
  UploadCloud,
  CheckCircle2,
  FileCode,
  Car,
  Footprints,
  Ruler,
  Plane,
} from "lucide-react";
import { waypointIcon } from "../../../utils/mapUtils";
import {
  MapAutoZoom,
  MapClickListener,
} from "../../controllers/mapControllers";
import { useMapRouting } from "../../../hooks/useMapRouting";

export function MapArea() {
  const { theme, mapTheme } = useTheme();
  const { showToast } = useUI();

  const [uploadedRouteLine, setUplodadedRouteLine] = useState<
    [number, number][]
  >([]);
  const [isHovering, setIsHovering] = useState(false);
  const [routePoints, setRoutePoints] = useState<[number, number][]>([]);
  const [droppedFile, setDroppedFile] = useState<string | null>(null);
  const {
    waypoints,
    setWaypoints,
    updateWaypoint,
    routeSegments,
    updateMetadata,
    settings,
    updateSettings,
    metadata,
    setIsDirty,
  } = useWorkspace();

  useMapRouting();
  const hexLineColor =
    "#" +
    settings.line_color.map((x) => x.toString(16).padStart(2, "0")).join("");
  const hexMarkerColor =
    "#" +
    settings.marker_color.map((x) => x.toString(16).padStart(2, "0")).join("");

  const processFile = async (filePath: string) => {
    try {
      if (filePath.toLowerCase().endsWith(".json")) {
        const fileContent = await readTextFile(filePath);
        const data = JSON.parse(fileContent);

        updateMetadata({
          project_id: data.project_id,
          user_id: data.user_id,
          project_name: data.project_name,
          created_at: data.created_at,
          status: "loaded",
          directory_path: data.directory_path,
        });

        if (data.settings) updateSettings(data.settings);

        if (data.waypoints) {
          setWaypoints(
            data.waypoints.map((wp: any) => ({
              id: crypto.randomUUID(),
              lat: wp.lat,
              lon: wp.lng,
              name: wp.label,
              image: wp.popup_image,
              narration: wp.narration,
              routeMode: wp.routeMode || "driving",
            })),
          );
        }

        if (data.source_files?.gps_route) {
          setDroppedFile(data.source_files.gps_route);

          const gpxContent = await readTextFile(data.source_files.gps_route);
          const parser = new DOMParser();
          const xmlDoc = parser.parseFromString(gpxContent, "text/xml");
          const trkpts = xmlDoc.getElementsByTagName("trkpt");
          const rawCoords: [number, number][] = [];
          for (let i = 0; i < trkpts.length; i++) {
            const lat = parseFloat(trkpts[i].getAttribute("lat") || "0");
            const lon = parseFloat(trkpts[i].getAttribute("lon") || "0");
            if (lat && lon) rawCoords.push([lat, lon]);
          }
          setUplodadedRouteLine(rawCoords);
        }
        return;
      }

      // Load .gpx
      showToast(`Processing ${filePath.split(/[\\]/).pop()}...`, "info");

      const pythonResponse = await invoke<string>("run_python_blueprint", {
        action: "process_gps",
        payload: filePath,
      });

      if (filePath.toLowerCase().endsWith(".gpx")) {
        const fileContent = await readTextFile(filePath);
        const parser = new DOMParser();
        const xmlDoc = parser.parseFromString(fileContent, "text/xml");
        const trkpts = xmlDoc.getElementsByTagName("trkpt");
        const rawCoords: [number, number][] = [];
        for (let i = 0; i < trkpts.length; i++) {
          const lat = parseFloat(trkpts[i].getAttribute("lat") || "0");
          const lon = parseFloat(trkpts[i].getAttribute("lon") || "0");
          if (lat && lon) rawCoords.push([lat, lon]);
        }
        setUplodadedRouteLine(rawCoords);
      }

      const outputLines = pythonResponse.trim().split("\n");
      const jsonString = outputLines[outputLines.length - 1];
      const data = JSON.parse(jsonString);

      if (!data.waypoints || data.waypoints.length === 0) {
        alert("△ Route Loaded, cannot detected landmarks/stops");
        setWaypoints([]);
      } else {
        setWaypoints(
          data.waypoints.map((wp: any) => ({
            id: crypto.randomUUID(),
            lat: wp.lat,
            lon: wp.lng,
            name: wp.label,
            image: wp.popup_image || null,
            narration: wp.narration || "",
            routeMode: "driving",
          })),
        );
      }
      if (data.project_name)
        updateMetadata({ project_name: data.project_name });
      if (data.source_files?.gps_route)
        setDroppedFile(data.source_files.gps_route);
    } catch (error) {
      console.error("Failed to process file:", error);
      alert("An error occured while loading the file.");
    }
  };

  const isDarkMap =
    mapTheme === "dark" ||
    (mapTheme === "sync" &&
      (theme === "dark" ||
        (theme === "system" &&
          window.matchMedia("(prefers-color-scheme: dark)").matches)));

  // drag and drop get files
  useEffect(() => {
    const unlistenHover = listen("tauri://drag-enter", () =>
      setIsHovering(true),
    );
    const unlistenLeave = listen("tauri://drag-leave", () =>
      setIsHovering(false),
    );
    const unlistenDrop = listen<{ paths: string[] }>(
      "tauri://drag-drop",
      async (event) => {
        setIsHovering(false);
        if (event.payload.paths && event.payload.paths.length > 0) {
          await processFile(event.payload.paths[0]);
        }
      },
    );

    return () => {
      unlistenHover.then((f) => f());
      unlistenLeave.then((f) => f());
      unlistenDrop.then((f) => f());
    };
  }, []);

  // browse files (same as drag and drop)
  const handleBrowseFiles = async () => {
    const selectedPath = await open({
      multiple: false,
      filters: [
        {
          name: "Navivi & GPS",
          extensions: ["json", "gpx", "fit", "tcx", "kml"],
        },
      ],
    });

    if (typeof selectedPath === "string") {
      await processFile(selectedPath);
    }
  };

  // parse file directly if gpx (if not gpx, gpsbabel goes boom boom and reformat it to gpx/kml/csv/xlsx)
  useEffect(() => {
    if (!droppedFile) return;

    if (droppedFile.toLowerCase().endsWith(".gpx")) {
      const parseGpx = async () => {
        try {
          const fileContent = await readTextFile(droppedFile);
          const parser = new DOMParser();
          const xmlDoc = parser.parseFromString(fileContent, "text/xml");
          const trackPoints = xmlDoc.getElementsByTagName("trkpt");
          const points: [number, number][] = [];

          for (let i = 0; i < trackPoints.length; i++) {
            const lat = parseFloat(trackPoints[i].getAttribute("lat") || "0");
            const lon = parseFloat(trackPoints[i].getAttribute("lon") || "0");
            if (lat && lon) points.push([lat, lon]);
          }
          setRoutePoints(points);
        } catch (error) {
          console.error("Failed to parse GPX:", error);
        }
      };
      parseGpx();
    } else {
      setRoutePoints([]);
    }
  }, [droppedFile]);

  // waypoints on map click
  const handleAddWaypoint = async (lat: number, lng: number) => {
    const newId = Math.random().toString(36).substring(7);

    setWaypoints((prev) => [
      ...prev,
      {
        id: newId,
        lat,
        lng,
        name: "Locating...",
        images: [],
        narration: "",
        routeMode: "driving",
      },
    ]);
    setIsDirty(true);
    try {
      const res = await fetch(
        `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}`,
      );
      const data = await res.json();
      const placeName =
        data.name ||
        data.address?.road ||
        data.address?.city ||
        `Waypoint ${newId.substring(0, 4).toUpperCase()}`;

      setWaypoints((prev) =>
        prev.map((wp) => (wp.id === newId ? { ...wp, name: placeName } : wp)),
      );
    } catch (error) {
      setWaypoints((prev) =>
        prev.map((wp) =>
          wp.id === newId ? { ...wp, name: `Unknown Location` } : wp,
        ),
      );
    }
  };

  const isGpx = droppedFile?.toLowerCase().endsWith(".gpx");

  return (
    <main className="flex-1 relative bg-zinc-100 dark:bg-[#09090b] overflow-hidden transition-colors">
      <MapSettings />
      <div className="absolute inset-0 z-0">
        <MapContainer
          center={settings.start_coords || [34.6937, 135.5023]}
          zoom={10}
          zoomControl={false}
          style={{ height: "100%", width: "100%", background: "transparent" }}
        >
          <TileLayer
            key={isDarkMap ? "dark-map" : "light-map"}
            attribution="&copy; OpenStreetMap contributors &copy; CARTO"
            url={
              isDarkMap
                ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
                : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
            }
          />

          {/*routing logic*/}
          {/* Draw the exact GPX path if uploaded (Semi-transparent Blue) */}
          {uploadedRouteLine.length > 0 && (
            <Polyline
              positions={uploadedRouteLine}
              pathOptions={{ color: "#3b82f6", weight: 4, opacity: 0.5 }}
            />
          )}

          {/* Draw the Dynamic Segments */}
          {routeSegments.map((segment, idx) => {
            if (segment.mode === "direct") {
              return (
                <Polyline
                  key={`dir-${idx}`}
                  positions={segment.positions}
                  pathOptions={{
                    color: "#a1a1aa",
                    weight: 4,
                    dashArray: "8, 8",
                  }}
                />
              );
            }
            if (segment.mode === "curve") {
              return (
                <Polyline
                  key={`crv-${idx}`}
                  positions={segment.positions}
                  pathOptions={{
                    color: "#a855f7",
                    weight: 4,
                    dashArray: "10, 10",
                  }}
                />
              );
            }
            if (segment.mode === "walking") {
              return (
                <Polyline
                  key={`wlk-${idx}`}
                  positions={segment.positions}
                  pathOptions={{
                    color: hexLineColor,
                    weight: settings.line_thickness,
                    dashArray: "2, 6",
                    lineCap: "round",
                  }}
                />
              );
            }
            // Default Driving
            return (
              <Polyline
                key={`drv-${idx}`}
                positions={segment.positions}
                pathOptions={{
                  color: hexLineColor,
                  weight: settings.line_thickness,
                }}
              />
            );
          })}

          {routePoints.length > 0 && (
            <Polyline
              positions={routePoints}
              pathOptions={{
                color: "#3b82f6",
                weight: 4,
                opacity: 0.8,
                lineCap: "round",
                lineJoin: "round",
              }}
            />
          )}

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
                  updateWaypoint(wp.id, {
                    lat: position.lat,
                    lng: position.lng,
                  });
                  // get new location name
                  try {
                    const response = await fetch(
                      `https://nominatim.openstreetmap.org/reverse?format=json&lat=${position.lat}&lon=${position.lng}`,
                    );
                    const data = await response.json();

                    const newName =
                      data.address?.road ||
                      data.address?.amenity ||
                      data.name ||
                      "Unnamed Location";
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

                  {/* The Route Mode Toggle */}
                  {/* The Route Mode Toggle */}
                  <div className="flex flex-col gap-1 mt-2 pt-2 border-t border-zinc-200">
                    <span className="text-[10px] font-extrabold text-zinc-400 uppercase tracking-wider mb-1">
                      Travel to next stop:
                    </span>

                    <div className="flex items-center gap-1 bg-zinc-100 p-1 rounded-lg border border-zinc-200">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          updateWaypoint(wp.id, { routeMode: "driving" });
                        }}
                        className={`flex-1 flex justify-center p-1.5 rounded-md transition-all ${!wp.routeMode || wp.routeMode === "driving" ? "bg-white shadow-sm text-emerald-600 ring-1 ring-zinc-200" : "text-zinc-500 hover:text-zinc-800 hover:bg-zinc-200/50"}`}
                        title="Driving"
                      >
                        <Car className="w-4 h-4" />
                      </button>

                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          updateWaypoint(wp.id, { routeMode: "walking" });
                        }}
                        className={`flex-1 flex justify-center p-1.5 rounded-md transition-all ${wp.routeMode === "walking" ? "bg-white shadow-sm text-emerald-600 ring-1 ring-zinc-200" : "text-zinc-500 hover:text-zinc-800 hover:bg-zinc-200/50"}`}
                        title="Walking"
                      >
                        <Footprints className="w-4 h-4" />
                      </button>

                      <button
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
                        onClick={(e) => {
                          e.stopPropagation();
                          updateWaypoint(wp.id, { routeMode: "curve" });
                        }}
                        className={`flex-1 flex justify-center p-1.5 rounded-md transition-all ${wp.routeMode === "curve" ? "bg-white shadow-sm text-emerald-600 ring-1 ring-zinc-200" : "text-zinc-500 hover:text-zinc-800 hover:bg-zinc-200/50"}`}
                        title="Fly/Ship"
                      >
                        <Plane className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              </Popup>
            </Marker>
          ))}

          <MapAutoZoom waypoints={waypoints} projectId={metadata.project_id} />
          <MapClickListener onMapClick={handleAddWaypoint} />
        </MapContainer>
      </div>

      {/* Drag & Drop Overlay */}
      {isHovering && (
        <div className="absolute inset-0 z-50 bg-white/80 dark:bg-zinc-950/80 backdrop-blur-sm border-2 border-dashed border-zinc-400 dark:border-zinc-500 m-4 rounded-2xl flex flex-col items-center justify-center transition-all animate-in fade-in">
          <div className="w-16 h-16 rounded-2xl bg-zinc-900 dark:bg-zinc-200 text-zinc-100 dark:text-zinc-900 flex items-center justify-center mb-4 shadow-lg scale-110">
            <UploadCloud className="w-8 h-8" />
          </div>
          <p className="text-zinc-900 dark:text-zinc-200 font-medium text-lg">
            Drop any GPS file to Load
          </p>
        </div>
      )}

      {/* Floating Status Panel */}
      {!isHovering && (
        <div className="absolute top-6 left-6 z-40">
          {droppedFile ? (
            isGpx ? (
              <div className="flex items-center gap-3 bg-white/90 dark:bg-zinc-900/90 backdrop-blur-md border border-emerald-500/30 px-4 py-2.5 rounded-xl shadow-lg">
                <CheckCircle2 className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
                <div className="flex flex-col">
                  <span className="text-xs font-bold text-zinc-800 dark:text-zinc-200 uppercase tracking-wider">
                    Route Loaded
                  </span>
                  <span
                    className="text-[10px] text-zinc-500 dark:text-zinc-400 font-mono max-w-[200px] truncate"
                    title={droppedFile}
                  >
                    {droppedFile}
                  </span>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-3 bg-white/90 dark:bg-zinc-900/90 backdrop-blur-md border border-amber-500/30 px-4 py-2.5 rounded-xl shadow-lg">
                <Clock className="w-4 h-4 text-amber-500 dark:text-amber-400 animate-pulse" />
                <div className="flex flex-col">
                  <span className="text-xs font-bold text-zinc-800 dark:text-zinc-200 uppercase tracking-wider">
                    Awaiting Conversion
                  </span>
                  <span
                    className="text-[10px] text-zinc-500 dark:text-zinc-400 font-mono max-w-[200px] truncate"
                    title={droppedFile}
                  >
                    {droppedFile}
                  </span>
                </div>
              </div>
            )
          ) : (
            <button
              onClick={handleBrowseFiles}
              className="flex items-center gap-3 bg-white/90 dark:bg-zinc-900/90 hover:bg-zinc-50 dark:hover:bg-zinc-800/95 backdrop-blur-md border border-zinc-200 dark:border-white/10 hover:border-zinc-300 dark:hover:border-zinc-400/50 transition-all px-4 py-2.5 rounded-xl shadow-lg text-left group"
            >
              <FileCode className="w-4 h-4 text-zinc-500 group-hover:text-zinc-700 dark:group-hover:text-zinc-300 transition-colors" />
              <div className="flex flex-col">
                <span className="text-xs font-bold text-zinc-800 dark:text-zinc-300 uppercase tracking-wider group-hover:text-zinc-950 dark:group-hover:text-zinc-100 transition-colors">
                  No Route Loaded
                </span>
                <span className="text-[10px] text-zinc-500 dark:text-zinc-500 group-hover:text-zinc-600 dark:group-hover:text-zinc-400 transition-colors">
                  Drag or click to browse files
                </span>
              </div>
            </button>
          )}
        </div>
      )}
    </main>
  );
}
