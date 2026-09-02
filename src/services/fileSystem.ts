import { documentDir, join, basename } from "@tauri-apps/api/path";
import { writeTextFile, mkdir, exists, copyFile, readTextFile, BaseDirectory, open as fsOpen } from "@tauri-apps/plugin-fs";
import { open as dialogOpen } from "@tauri-apps/plugin-dialog";
import { appConfig, fileSystem } from "../config/constants";
import { TimelineData, TimelineManifest, ManifestClip } from "../types";

/**
 * 
 * @param waypoints 
 * @param routeSegments 
 * @param metadata 
 * @param settings 
 * @param routingCache 
 * @param overrideName 
 * @param asDuplicate 
 * @param safeFolderName 
 * @returns 
 */

export const saveProjectData = async (
  waypoints: any[],
  routeSegments: any[],
  metadata: any,
  settings: any,
  routingCache: Record<string, [number, number][]>,
  overrideName?: string,
  asDuplicate?: boolean,
  safeFolderName?: string,
) => {
  const docsPath = await documentDir();
  const projectRoot = await join(docsPath, fileSystem.rootFolder, fileSystem.projectsFolder);

  if (!(await exists(projectRoot))) {
    await mkdir(projectRoot, { recursive: true });
  }

  let projName = overrideName || metadata.project_name || appConfig.defaultProjectName;
  let projId = asDuplicate ? "" : metadata.project_id;
  let projectDir = "";

  if (safeFolderName) {
    projId = safeFolderName;
  }

  if (projId && !asDuplicate && !safeFolderName) {
    projectDir = await join(projectRoot, projId);
  } else {
    let safeName = safeFolderName || projName.toLowerCase().replace(/[^a-z0-9]+/g, "_") || `untitled_${new Date().toISOString()}`.toLowerCase().replace(/[^a-z0-9]+/g, "_");
    projId = safeName;
    projectDir = await join(projectRoot, projId);

    if (!safeFolderName) {
      let counter = 1;
      while (await exists(projectDir)) {
        counter++;
        projName = `${overrideName || metadata.project_name || appConfig.defaultProjectName} (${counter})`;
        safeName = projName.toLowerCase().replace(/[^a-z0-9]+/g, "_");
        projId = `${safeName}_${counter}`;
        projectDir = await join(projectRoot, projId);
      }
    }
  }

  const assetsDir = await join(projectDir, "assets");
  const gpxPath = await join(projectDir, "raw_track.gpx");
  const nvvPath = await join(projectDir, `${projName}.${fileSystem.extensions.project}`);
  const jsonPath = await join(projectDir, "job_config.json");

  if (!(await exists(projectDir))) await mkdir(projectDir, { recursive: true });
  if (!(await exists(assetsDir))) await mkdir(assetsDir, { recursive: true });

  // Initialize GPX String with GPSBabel expected headers
  let gpxStr = `<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.0" creator="${appConfig.name}" xmlns="http://www.topografix.com/GPX/1/0">\n`;
  gpxStr += `  <time>${new Date().toISOString()}</time>\n`;
  gpxStr += `  <trk>\n    <name>${projName}</name>\n    <trkseg>\n`;

  let currentTime = new Date();
  let lastPos: [number, number] | null = null;

  routeSegments.forEach((segment) => {
    // Rough speed estimates: 15 m/s (~54 km/h) for driving/direct, 1.4 m/s (~5 km/h) for walking
    const speedMs = (segment.mode === "walking" || segment.mode === "direct") ? 1.4 : 15.0;

    segment.positions.forEach((pos: [number, number]) => {
      let dist = 0;

      if (lastPos) {
        // Haversine formula to get distance between coords in meters
        const R = 6371e3;
        const dLat = (pos[0] - lastPos[0]) * (Math.PI / 180);
        const dLon = (pos[1] - lastPos[1]) * (Math.PI / 180);
        const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
          Math.cos(lastPos[0] * (Math.PI / 180)) * Math.cos(pos[0] * (Math.PI / 180)) *
          Math.sin(dLon / 2) * Math.sin(dLon / 2);
        const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        dist = R * c;
      }

      // Calculate time delta based on distance and assumed speed
      const timeDeltaSeconds = lastPos ? dist / speedMs : 0;
      currentTime = new Date(currentTime.getTime() + timeDeltaSeconds * 1000);

      gpxStr += `      <trkpt lat="${pos[0]}" lon="${pos[1]}">\n`;
      gpxStr += `        <ele>35.0</ele>\n`; // Static fake elevation
      gpxStr += `        <time>${currentTime.toISOString()}</time>\n`;
      gpxStr += `        <speed>${speedMs.toFixed(6)}</speed>\n`;
      gpxStr += `        <fix>3d</fix>\n`;
      gpxStr += `        <sat>8</sat>\n`;
      gpxStr += `        <hdop>1.0</hdop>\n`;
      gpxStr += `      </trkpt>\n`;

      lastPos = pos;
    });
  });

  gpxStr += `    </trkseg>\n  </trk>\n</gpx>`;
  await writeTextFile(gpxPath, gpxStr);

  const processedWaypoints = await Promise.all(
    waypoints.map(async (wp) => {
      const absoluteImagePaths: string[] = [];
      
      if (wp.images && wp.images.length > 0) {
        for (const imgPath of wp.images) {
          const fileName = await basename(imgPath);
          const absoluteDest = await join(assetsDir, fileName);
          if (imgPath !== absoluteDest) {
            await copyFile(imgPath, absoluteDest);
          }
          absoluteImagePaths.push(absoluteDest);
        }
      }

      return {
        lat: wp.lat,
        lng: wp.lng,
        label: wp.name,
        freeze_seconds: wp.duration || settings.duration_seconds,
        popup_image: absoluteImagePaths,
        // Safely check imagePans (plural) and fallback to "panright" for each image
        camera_pans: absoluteImagePaths.length > 0 
          ? absoluteImagePaths.map((_, i) => (wp.imagePans && wp.imagePans[i] ? wp.imagePans[i] : "panright"))
          : [],
        image_display: wp.imageDisplay || "pip",
        narration: wp.narration || "", // Prevent undefined
        routeMode: wp.routeMode || "driving",
      };
    })
  );

  const startWp = processedWaypoints[0];
  const endWp = processedWaypoints[processedWaypoints.length - 1];

  const jobConfig = {
    project_id: projId,
    user_id: metadata.user_id,
    project_name: projName,
    created_at: metadata.created_at,
    status: "saved",
    directory_path: projectDir,
    source_files: { gps_route: gpxPath },
    settings: settings,
    overview_narration: metadata.overview_narration || "",
    start_point: startWp ? { lat: startWp.lat, lng: startWp.lng, label: startWp.label } : null,
    end_point: endWp ? { lat: endWp.lat, lng: endWp.lng, label: endWp.label } : null,
    waypoints: processedWaypoints,
  };

  const payload = JSON.stringify(jobConfig, null, 2);
  await writeTextFile(nvvPath, payload);
  await writeTextFile(jsonPath, payload);

  const activeKeys = new Set<string>();
  for (let i = 0; i < waypoints.length - 1; i++) {
    const wp1 = waypoints[i];
    const wp2 = waypoints[i + 1];
    const mode = wp1.routeMode || "driving";

    activeKeys.add(`${wp1.lat.toFixed(5)},${wp1.lng.toFixed(5)}|${wp2.lat.toFixed(5)},${wp2.lng.toFixed(5)}|${mode}`);
  }
  const cleanCache: Record<string, [number, number][]> = {};
  let deletedCount = 0;
  for (const [key, routeData] of Object.entries(routingCache)) {
    if (activeKeys.has(key)) {
      cleanCache[key] = routeData;
    } else {
      deletedCount++;
    }
  }

  if (deletedCount > 0) {
    console.log(`Garbage Collector pruned ${deletedCount} ghost routes.`);
  }
  const routeCachePath = await join(projectDir, ".routecache.json");
  await writeTextFile(routeCachePath, JSON.stringify(cleanCache));

  return { projectDir, projId, projName, nvvPath };
};

/**
 * 
 * @param forcePath 
 * @returns 
 */

export const loadProjectData = async (forcePath?: string) => {
  let selectedPath = forcePath;

  if (!selectedPath) {
    const res = await dialogOpen({
      multiple: false,
      filters: [{ name: `${appConfig.name} Project`, extensions: [fileSystem.extensions.project] }],
    });
    if (!res || typeof res !== 'string') return null;
    selectedPath = res;
  }

  const fileContent = await readTextFile(selectedPath);
  const data = JSON.parse(fileContent);

  return { data, selectedPath };
};

/**
 * 
 * @param message 
 */

export async function appendToRenderLog(message: string) {
  try {
    const hasDir = await exists('', { baseDir: BaseDirectory.AppLog });
    if (!hasDir) {
      await mkdir('', { baseDir: BaseDirectory.AppLog, recursive: true });
    }

    const timestamp = new Date().toISOString();
    const logEntry = `[${timestamp}] ${message}\n`;

    const file = await fsOpen('render.log', {
      write: true,
      append: true,
      create: true,
      baseDir: BaseDirectory.AppLog,
    });

    const encoder = new TextEncoder();
    await file.write(encoder.encode(logEntry));
    await file.close();
  
  } catch (error) {
    console.error("Failed to write to render.log:", error);
  }
};

/**
 * 
 * @param projectDir 
 * @param projectName 
 * @param timeline 
 * @returns 
 */

export async function saveTimelineManifest(projectDir: string, projectName: string, timeline: TimelineData): Promise<boolean> {
  /**
   * convert react timeline state into timeline.json manifest
   * and saves it for python backend to process
   */
  try {
    const manifestPath = await join(projectDir, "timeline.json");
    // find master audio track
    const audioTrack = timeline.tracks.find(t => t.type === "audio");
    const audioClip = audioTrack ? timeline.clips.find(c => c.trackId === audioTrack.id) : null;
    // map visual clips
    const videoTracks: ManifestClip[] = [];
    // Sort clips by start time so python receives them in order
    const visualClips = timeline.clips.filter(c => c.trackId !== audioTrack?.id).sort((a, b) => a.startTime - b.startTime);

    for (const clip of visualClips) {
      const track = timeline.tracks.find(t => t.id === clip.trackId);
      videoTracks.push({
        clip_id: clip.id,
        file_path: clip.source || "",
        duration: clip.duration,
        type: track?.name.toLowerCase().includes("popup") ? "static_popup" : "video"
      });
    }
    // calculate total duration (end of last clip)
    const totalDuration = timeline.clips.reduce((max, clip) => Math.max(max, clip.startTime + clip.duration), 0);
    // build final json body
    const manifest: TimelineManifest = {
      project_name: projectName,
      total_duration_seconds: totalDuration,
      video_tracks: videoTracks,
      audio_track: audioClip?.source || undefined
    };
    // write to disk
    await writeTextFile(manifestPath, JSON.stringify(manifest, null, 2));
    console.log("✓ timeline.json successfully saved.")
    return true;
  } catch (error) {
    console.error("Failed to save timeline.json:", error);
    return false;
  }
};

/**
 * 
 * @param projectDir 
 * @returns 
 */

export async function loadTimelineManifest(projectDir: string): Promise<TimelineManifest | null> {
  try {
    // construct absolute path to manifest file
    const manifestPath = await join(projectDir, "timeline.json");
    // check if file exist
    const fileExists = await exists(manifestPath);
    if (!fileExists) {
      console.warn(`Manifest not found at: ${manifestPath}`);
      return null;
    }
    // read and parse json
    const fileContents = await readTextFile(manifestPath);
    const manifest: TimelineManifest = JSON.parse(fileContents);
    return manifest;
  } catch (error) {
    console.error("Failed to load or parse timeline manifest:", error);
    return null;
  }
};

/**
 * 
 * @param projectDir 
 * @returns 
 */

export async function loadRouteCache(projectDir: string): Promise<Record<string, [number, number][]>> {
  try {
    const cachePath = await join(projectDir, ".routecache.json");
    if (await exists(cachePath)) {
      const contents = await readTextFile(cachePath);
      return JSON.parse(contents);
    }
  } catch (error) {
    console.error("Failed to load route cache:", error);
  }
  return {};
}

/**
 * 
 * @param projectDir 
 * @param cacheData 
 * @returns 
 */

export async function saveRouteCache(projectDir: string, cacheData: Record<string, [number, number][]>): Promise<boolean> {
  try {
    const cachePath = await join(projectDir, ".routecache.json");
    await writeTextFile(cachePath, JSON.stringify(cacheData));
    return true;
  } catch (error) {
    console.error("Failed to save route cache:", error);
    return false;
  }
};
