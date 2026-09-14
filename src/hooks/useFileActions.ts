import { useWorkspace } from "./useWorkspace";
import { useUI } from "./useUI";
import { open } from "@tauri-apps/plugin-dialog";
import { readTextFile, readFile, readDir } from "@tauri-apps/plugin-fs";
import * as exifr from "exifr";

export function useFileActions() {
  const { setRoutePoints, waypoints, setWaypoints, setIsDirty } = useWorkspace();
  const { showToast } = useUI();

  const handleDroppedFiles = async (paths: string[]) => {
    try {
      const allFiles = [];
      for (const path of paths) {
        if (path.toLowerCase().endsWith(".json") || path.toLowerCase().endsWith(".navivi")) {
          // This should be handled by caller
          continue;
        }
        
        try {
          const stats = await readDir(path);
          for (const file of stats) {
            if (file.name && (file.name.toLowerCase().endsWith(".jpg") || file.name.toLowerCase().endsWith(".jpeg") || file.name.toLowerCase().endsWith(".png"))) {
              allFiles.push(path + "/" + file.name); // Assuming unix style or we can let tauri path API handle it, but for simplicity
            }
          }
        } catch {
          // Not a directory
          allFiles.push(path);
        }
      }

      const photoPoints = [];
      for (const path of allFiles) {
        if (path.toLowerCase().endsWith(".jpg") || path.toLowerCase().endsWith(".jpeg") || path.toLowerCase().endsWith(".png")) {
          try {
            const buffer = await readFile(path);
            const exifData = await exifr.parse(buffer);
            if (exifData?.latitude && exifData?.longitude) {
              photoPoints.push({
                lat: exifData.latitude,
                lng: exifData.longitude,
                date: exifData.DateTimeOriginal || new Date(),
                path,
              });
            }
          } catch (e) {
            console.warn("Failed to parse EXIF for", path, e);
          }
        } else if (path.toLowerCase().endsWith(".gpx")) {
          await importRouteFile(path);
          return;
        }
      }

      if (photoPoints.length > 0) {
        // Sort chronologically
        photoPoints.sort((a, b) => a.date.getTime() - b.date.getTime());
        
        const newWaypoints = [...waypoints];
        for (const pt of photoPoints) {
          const newId = Math.random().toString(36).substring(7);
          let placeName = `Photo ${pt.date.toLocaleTimeString()}`;
          try {
            const res = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${pt.lat}&lon=${pt.lng}`);
            const data = await res.json();
            placeName = data.name || data.address?.road || data.address?.city || placeName;
          } catch {}

          newWaypoints.push({
            id: newId,
            lat: pt.lat,
            lng: pt.lng,
            name: placeName,
            images: [pt.path],
            imagePans: ["none"],
            imageTransitions: [],
            narration: "",
            routeMode: "driving"
          });
        }
        setWaypoints(newWaypoints);
        setIsDirty(true);
        showToast(`Imported ${photoPoints.length} photos and generated route.`, "success");
      }

    } catch (e) {
      console.error(e);
      showToast("Failed to process dropped files.", "error");
    }
  };

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
        const points: [number, number, number][] = [];

        for (let i = 0; i < trackPoints.length; i++) {
          const latAttr = trackPoints[i].getAttribute("lat");
          const lonAttr = trackPoints[i].getAttribute("lon");
          if (latAttr === null || lonAttr === null) continue;
          const lat = Number.parseFloat(latAttr);
          const lon = Number.parseFloat(lonAttr);
          
          let ele = 0;
          const eleNode = trackPoints[i].getElementsByTagName("ele")[0];
          if (eleNode && eleNode.textContent) {
            ele = Number.parseFloat(eleNode.textContent);
          }

          if (Number.isFinite(lat) && Number.isFinite(lon))
            points.push([lat, lon, ele]);
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
        setRoutePoints(points); // Will need to update type if routePoints is just [number, number][]
      } else {
        // todo: call gpsbabel conversion logic for non-gpx files
        // setRoutePoints([]);
      }
    } catch (error) {
      console.error("Failed to import route:", error);
      showToast("Failed to parse file", "error");
    }
  };
  return { importRouteFile, handleDroppedFiles };
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