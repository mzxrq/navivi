import { useWorkspace } from "./useWorkspace";
import { useUI } from "./useUI";
import { open } from "@tauri-apps/plugin-dialog";
import { readTextFile } from "@tauri-apps/plugin-fs";

export function useFileActions() {
  const { setRoutePoints } = useWorkspace();
  const { showToast } = useUI();

  const importRouteFile = async (filePath?: string) => {
    try {
      const selectedPath = filePath || await open({
        multiple: false,
        filters: [{ name: "Navivi & GPS", extensions: ["json", "gpx", "fit", "tcx", "kml"] }],
      });

      if (typeof selectedPath !== "string") return;

      if (selectedPath.toLowerCase().endsWith(".gpx")) {
        const fileContent = await readTextFile(selectedPath);
        const parser = new DOMParser();
        const xmlDoc = parser.parseFromString(fileContent, "text/xml");
        const trackPoints = xmlDoc.getElementsByTagName("trkpt");
        const points: [number, number][] = [];

        for (let i = 0; i < trackPoints.length; i++) {
          const latAttr = trackPoints[i].getAttribute("lat");
          const lonAttr = trackPoints[i].getAttribute("lon");
          if (latAttr === null || lonAttr === null) continue;
          const lat = Number.parseFloat(latAttr);
          const lon = Number.parseFloat(lonAttr);
          if (Number.isFinite(lat) && Number.isFinite(lon))
            points.push([lat, lon]);
        }

        // Distance calculation
        let totalDistKm = 0;
        const R = 6371; // km
        for (let i = 1; i < points.length; i++) {
          const [lat1, lon1] = points[i - 1];
          const [lat2, lon2] = points[i];
          const dLat = (lat2 - lat1) * (Math.PI / 180);
          const dLon = (lon2 - lon1) * (Math.PI / 180);
          const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(lat1 * (Math.PI / 180)) * Math.cos(lat2 * (Math.PI / 180)) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2);
          const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
          totalDistKm += R * c;
        }

        if (totalDistKm > 50) {
          showToast("This route exceeds 50km. Performance may be affected in this preview build.", "warning");
        } else {
          showToast("Route imported successfully", "success");
        }
        setRoutePoints(points);
      } else {
        // todo: call gpsbabel conversion logic for non-gpx files
        // setRoutePoints([]);
      }
    } catch (error) {
      console.error("Failed to import route:", error);
      showToast("Failed to parse file", "error");
    }
  };
  return { importRouteFile };
}

export const parseAndEnrichGPX = async (rawGpxPoints: { lat: number, lon: number }[]) => {
  // 1. DOWNSAMPLE: Keep max 5 stops to prevent API bans
  const maxStops = 5;
  let majorStops = [];

  if (rawGpxPoints.length <= maxStops) {
    majorStops = rawGpxPoints;
  } else {
    majorStops.push(rawGpxPoints[0]); // Start
    const step = rawGpxPoints.length / (maxStops - 1);
    for (let i = 1; i < maxStops - 1; i++) {
      majorStops.push(rawGpxPoints[Math.floor(i * step)]);
    }
    majorStops.push(rawGpxPoints[rawGpxPoints.length - 1]); // End
  }

  // 2. ENRICH: Fetch real names with a strict 1.1 second delay
  const enrichedWaypoints = [];
  for (let i = 0; i < majorStops.length; i++) {
    const point = majorStops[i];

    // Crucial: Wait 1.1s between requests to respect OSM limits
    if (i > 0) await new Promise(res => setTimeout(res, 1100));

    let placeName = `Stop ${i + 1}`;
    try {
      const res = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${point.lat}&lon=${point.lon}`);
      const data = await res.json();
      placeName = data.name || data.address?.road || data.address?.city || placeName;
    } catch (e) {
      console.warn("Geocoding failed for", point);
    }

    enrichedWaypoints.push({
      id: crypto.randomUUID(),
      lat: point.lat,
      lng: point.lon,
      name: placeName,
      routeMode: "driving",
      // Store the dense 1-second pings here so the route draws perfectly
      customRoute: i === 0 ? rawGpxPoints.map(p => [p.lat, p.lon]) : []
    });
  }

  return enrichedWaypoints;
};