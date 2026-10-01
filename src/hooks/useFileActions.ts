import { invoke } from "@tauri-apps/api/core";
import { useWorkspace } from "./useWorkspace";
import { useUI } from "./useUI";
import { open } from "@tauri-apps/plugin-dialog";
import { readTextFile, readFile, readDir } from "@tauri-apps/plugin-fs";
import * as exifr from "exifr";
import { t } from "@lingui/core/macro";

export function useFileActions() {
  const { setRoutePoints, waypoints, setWaypoints, setIsDirty } = useWorkspace();
  const { showToast, setAutoDirectorData } = useUI();

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

      let imageCount = 0;
      const photoPoints = [];
      for (const path of allFiles) {
        if (path.toLowerCase().endsWith(".jpg") || path.toLowerCase().endsWith(".jpeg") || path.toLowerCase().endsWith(".png")) {
          imageCount++;
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
        } else if (path.toLowerCase().endsWith(".txt") || path.toLowerCase().endsWith(".md")) {
          const fileContent = await readTextFile(path);
          setAutoDirectorData({ state: "processing", content: fileContent });
          return;
        }
      }

      if (imageCount > 0 && photoPoints.length === 0) {
        showToast(t`None of these photos has a location. Photos saved from websites or chat apps usually don't.`, "warning");
        return;
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
          } catch { }

          newWaypoints.push({
            id: newId,
            lat: pt.lat,
            lng: pt.lng,
            name: placeName,
            images: [pt.path],
            imagePans: ["none"],
            imageTransitions: [],
            arrivingNarration: "",
            routeMode: "driving",
            timestamp: pt.date.toISOString(),
          });
        }
        setWaypoints(newWaypoints);
        setIsDirty(true);
        showToast(t`Imported ${photoPoints.length} photos and generated route.`, "success");
        const skipped = imageCount - photoPoints.length;
        if (skipped > 0) showToast(t`${skipped} photos without a location were skipped.`, "info");
      }

    } catch (e) {
      console.error(e);
      showToast(t`Failed to process dropped files`, "error");
    }
  };

  const importRouteFile = async (filePath?: string) => {
    try {
      const selectedPath = filePath || await open({
        multiple: false,
        filters: [{ name: t`GPS/Text Files`, extensions: ["json", "gpx", "fit", "tcx", "kml", "txt", "md"] }],
      });

      if (typeof selectedPath !== "string") return;
      
      if (selectedPath.toLowerCase().endsWith(".txt") || selectedPath.toLowerCase().endsWith(".md")) {
        const fileContent = await readTextFile(selectedPath);
        setAutoDirectorData({ state: "processing", content: fileContent });
        return;
      }

      let fileContent = "";

      if (selectedPath.toLowerCase().endsWith(".gpx")) {
        fileContent = await readTextFile(selectedPath);
      } else {
        showToast(t`Converting GPS file format...`, "info");
        let inputFormat = "auto";
        if (selectedPath.toLowerCase().endsWith(".tcx")) inputFormat = "gtrnctr";
        else if (selectedPath.toLowerCase().endsWith(".fit")) inputFormat = "garmin_fit";
        else if (selectedPath.toLowerCase().endsWith(".kml")) inputFormat = "kml";
        
        fileContent = await invoke<string>("convert_gps_to_gpx", {
           inputPath: selectedPath,
           inputFormat
        });
      }

      const parser = new DOMParser();
      const xmlDoc = parser.parseFromString(fileContent, "text/xml");
      const trackPoints = xmlDoc.getElementsByTagName("trkpt");
      const points: number[][] = [];

      for (let i = 0; i < trackPoints.length; i++) {
        const latAttr = trackPoints[i].getAttribute("lat");
        const lonAttr = trackPoints[i].getAttribute("lon");
        if (latAttr === null || lonAttr === null) continue;
        const lat = Number.parseFloat(latAttr);
        const lon = Number.parseFloat(lonAttr);

        let ele: number | undefined = undefined;
        const eleNode = trackPoints[i].getElementsByTagName("ele")[0];
        if (eleNode && eleNode.textContent) {
          const parsedEle = Number.parseFloat(eleNode.textContent);
          if (Number.isFinite(parsedEle)) {
            ele = parsedEle;
          }
        }

        if (Number.isFinite(lat) && Number.isFinite(lon)) {
          if (ele !== undefined) {
            points.push([lat, lon, ele]);
          } else {
            points.push([lat, lon]);
          }
        }
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

      setRoutePoints(points); // Draw the solid route on the map

      // --- WAYPOINT EXTRACTION ---
      showToast(t`Extracting waypoints from GPS data...`, "info");
      const wptNodes = xmlDoc.getElementsByTagName("wpt");
      const parsedWpts: any[] = [];

      for (let i = 0; i < wptNodes.length; i++) {
        const latAttr = wptNodes[i].getAttribute("lat");
        const lonAttr = wptNodes[i].getAttribute("lon");
        if (!latAttr || !lonAttr) continue;
        const lat = parseFloat(latAttr);
        const lon = parseFloat(lonAttr);
        const name = wptNodes[i].getElementsByTagName("name")[0]?.textContent || "";
        if (Number.isFinite(lat) && Number.isFinite(lon)) {
          parsedWpts.push({ lat, lon, name });
        }
      }

      let newNaviviWaypoints: any[] = [];

      if (parsedWpts.length > 0) {
        // Use explicit GPX waypoints
        for (let i = 0; i < parsedWpts.length; i++) {
          let placeName = parsedWpts[i].name;
          if (!placeName) {
            try {
              if (i > 0) await new Promise(res => setTimeout(res, 1100)); // Rate limit OSM
              const res = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${parsedWpts[i].lat}&lon=${parsedWpts[i].lon}`);
              const data = await res.json();
              placeName = data.name || data.address?.road || data.address?.city || t`Waypoint ${i + 1}`;
            } catch { }
          }
          newNaviviWaypoints.push({
            id: crypto.randomUUID(),
            lat: parsedWpts[i].lat,
            lng: parsedWpts[i].lon,
            name: placeName,
            images: [],
            imagePans: [],
            imageTransitions: [],
            arrivingNarration: "",
            routeMode: "driving"
          });
        }
      } else if (points.length > 0) {
        // No waypoints? Auto-sample 5 stops from the track points!
        const rawForEnrich = points.map(p => ({ lat: p[0], lon: p[1] }));
        const enriched = await parseAndEnrichGPX(rawForEnrich);
        newNaviviWaypoints = enriched.map(e => ({
          id: e.id,
          lat: e.lat,
          lng: e.lng,
          name: e.name,
          images: [],
          imagePans: [],
          imageTransitions: [],
          arrivingNarration: "",
          routeMode: e.routeMode,
          customRoute: e.customRoute
        }));
      }

      if (newNaviviWaypoints.length > 0) {
        setWaypoints([...waypoints, ...newNaviviWaypoints]);
        setIsDirty(true);
      }

      if (totalDistKm > 50) {
        showToast(t`Imported ${newNaviviWaypoints.length} waypoints. Route > 50km.`, "warning");
      } else {
        showToast(t`Imported ${newNaviviWaypoints.length} waypoints successfully`, "success");
      }
    } catch (error) {
      console.error("Failed to import route:", error);
      showToast(t`Failed to parse file`, "error");
    }
  };

  const importPhotos = async () => {
    try {
      const selected = await open({
        multiple: true,
        filters: [{ name: t`Photos & Images`, extensions: ["jpg", "jpeg", "png"] }],
      });

      if (selected) {
        const paths = Array.isArray(selected) ? selected : [selected];
        if (paths.length > 0) {
          await handleDroppedFiles(paths);
        }
      }
    } catch (error) {
      console.error("Failed to select photos:", error);
      showToast(t`Failed to open file dialog`, "error");
    }
  };

  return { importRouteFile, handleDroppedFiles, importPhotos };
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

    let placeName = t`Stop ${i + 1}`;
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