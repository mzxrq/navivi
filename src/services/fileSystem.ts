import { documentDir, join, basename, dirname } from "@tauri-apps/api/path";
import { writeTextFile, writeFile, mkdir, exists, copyFile, readTextFile, readDir, BaseDirectory, open as fsOpen } from "@tauri-apps/plugin-fs";
import { open as dialogOpen, save as dialogSave } from "@tauri-apps/plugin-dialog";
import { invoke } from "@tauri-apps/api/core";
import { appConfig, fileSystem } from "../config/constants";
import { buildAssetManifest } from "../utils/manifestBuilder";
import { TimelineData, TimelineManifest, ManifestClip, RenderSettings, ExportManifestPayload, RecentProjects } from "../types";
import { t } from "@lingui/core/macro";

// Haversine distance calculator
function calculateDistance(pos1: [number, number], pos2: [number, number]) {
  const R = 6371e3;
  const dLat = (pos2[0] - pos1[0]) * (Math.PI / 180);
  const dLon = (pos2[1] - pos1[1]) * (Math.PI / 180);
  const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(pos1[0] * (Math.PI / 180)) * Math.cos(pos2[0] * (Math.PI / 180)) *
    Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

export const saveProjectData = async (
  waypoints: any[],
  routeSegments: any[],
  metadata: any,
  settings: any,
  routingCache: Record<string, [number, number][]>,
  overrideName?: string,
  asDuplicate?: boolean,
  safeFolderName?: string,
  thumbnailDataUrl?: string | null,
) => {
  const docsPath = await documentDir();

  let projName = overrideName || metadata.project_name || appConfig.defaultProjectName;

  // Ask for archive destination if this is a new project or "Save As" (asDuplicate)
  let archivePath = metadata.archive_path;

  // If it's a legacy project being upgraded, archivePath is INSIDE directory_path!
  // We must force a new archivePath OUTSIDE the legacy folder so it doesn't zip itself.
  if (archivePath && metadata.directory_path && archivePath.startsWith(metadata.directory_path)) {
    const defaultSaveDir = await join(docsPath, fileSystem.rootFolder, fileSystem.projectsFolder);
    archivePath = await join(defaultSaveDir, `${projName}.${fileSystem.extensions.project}`);
  }

  if (asDuplicate) {
    const defaultSaveDir = await join(docsPath, fileSystem.rootFolder, fileSystem.projectsFolder);
    if (!(await exists(defaultSaveDir))) {
      await mkdir(defaultSaveDir, { recursive: true });
    }
    const res = await dialogSave({
      defaultPath: await join(defaultSaveDir, `${projName}.${fileSystem.extensions.project}`),
      filters: [{ name: `${appConfig.name} Project`, extensions: [fileSystem.extensions.project] }],
    });
    if (!res) throw new Error("Save cancelled by user");
    archivePath = res;
    // Update name based on file name chosen
    projName = await basename(archivePath, `.${fileSystem.extensions.project}`);
  } else if (!archivePath && !metadata.directory_path) {
    // If it's a completely new project and they just hit Save, let's auto-generate a workspace
    // without forcing a .nvv prompt, OR auto-save the .nvv silently.
    // The safest is to just leave archivePath empty and let it be a workspace-only project!
  }

  // Workspaces directory (where the files are actually extracted and worked on)
  const workspaceRoot = await join(docsPath, fileSystem.rootFolder, fileSystem.workspacesFolder);
  if (!(await exists(workspaceRoot))) {
    await mkdir(workspaceRoot, { recursive: true });
  }

  let projId = metadata.project_id || "";
  let projectDir = "";

  if (safeFolderName) {
    projId = safeFolderName;
  }

  if (projId && !asDuplicate && !safeFolderName && metadata.directory_path) {
    projectDir = metadata.directory_path; // Use existing workspace directory!
  } else {
    let safeName = safeFolderName || projName.toLowerCase().replace(/[^a-z0-9]+/g, "_") || `untitled_${new Date().toISOString()}`.toLowerCase().replace(/[^a-z0-9]+/g, "_");
    projId = safeName;
    projectDir = await join(workspaceRoot, projId);

    if (!safeFolderName) {
      let counter = 1;
      const baseProjName = overrideName || metadata.project_name || appConfig.defaultProjectName;
      const baseSafeName = baseProjName.toLowerCase().replace(/[^a-z0-9]+/g, "_");
      while (await exists(projectDir)) {
        counter++;
        projName = `${baseProjName} (${counter})`;
        projId = `${baseSafeName}_${counter}`;
        projectDir = await join(workspaceRoot, projId);
      }
    }
  }

  const assetsDir = await join(projectDir, "assets");
  const imageAssetsDir = await join(assetsDir, "image");
  const gpxPath = await join(projectDir, "raw_track.gpx");
  const nvvPath = await join(projectDir, `${projName}.${fileSystem.extensions.project}`);
  const jsonPath = await join(projectDir, "job_config.json");

  if (!(await exists(projectDir))) await mkdir(projectDir, { recursive: true });
  if (!(await exists(assetsDir))) await mkdir(assetsDir, { recursive: true });
  if (!(await exists(imageAssetsDir))) await mkdir(imageAssetsDir, { recursive: true });

  // Initialize GPX String with GPSBabel expected headers
  const gpxLines: string[] = [];
  gpxLines.push(`<?xml version="1.0" encoding="UTF-8"?>`);
  gpxLines.push(`<gpx version="1.1" creator="${appConfig.name}" xmlns="http://www.topografix.com/GPX/1/1">`);
  gpxLines.push(`  <time>${new Date().toISOString()}</time>`);

  // export waypoints
  waypoints.forEach((wp) => {
    gpxLines.push(` <wpt lat="${wp.lat}" lon="${wp.lng}">`);
    const safeName = (wp.name || "Navivi Stop").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    gpxLines.push(`   <name>${safeName}</name>`);
    gpxLines.push(` </wpt>`);
  });

  // track segments
  gpxLines.push(`  <trk>\n    <name>${projName}</name>\n    <trkseg>`);

  let currentTime = new Date();
  let lastPos: [number, number] | null = null;

  // export tracks
  routeSegments.forEach((segment) => {
    // Rough speed estimates: 15 m/s (~54 km/h) for driving, 1.4 m/s (~5 km/h) for walking
    const speedMs = (segment.mode === "walking" || segment.mode === "direct" || segment.mode === "draw") ? 1.4 : 15.0;

    segment.positions.forEach((pos: [number, number]) => {
      let dist = 0;

      if (lastPos) {
        dist = calculateDistance(lastPos, pos);
      }

      // Calculate time delta based on distance and assumed speed
      const timeDeltaSeconds = lastPos ? dist / speedMs : 0;
      currentTime = new Date(currentTime.getTime() + timeDeltaSeconds * 1000);

      gpxLines.push(`      <trkpt lat="${pos[0]}" lon="${pos[1]}">`);
      gpxLines.push(`        <ele>35.0</ele>`); // Static fake elevation
      gpxLines.push(`        <time>${currentTime.toISOString()}</time>`);
      gpxLines.push(`        <speed>${speedMs.toFixed(6)}</speed>`);
      gpxLines.push(`        <fix>3d</fix>`);
      gpxLines.push(`        <sat>8</sat>`);
      gpxLines.push(`        <hdop>1.0</hdop>`);
      gpxLines.push(`      </trkpt>`);

      lastPos = pos;
    });
  });

  gpxLines.push(`    </trkseg>\n  </trk>\n</gpx>`);
  const gpxStr = gpxLines.join('\n');
  await writeTextFile(gpxPath, gpxStr);

  const processedWaypoints = await Promise.all(
    waypoints.map(async (wp) => {
      const relativeImagePaths: string[] = [];

      if (wp.images && wp.images.length > 0) {
        for (const imgPath of wp.images) {
          const fileName = await basename(imgPath);
          const absoluteDest = await join(imageAssetsDir, fileName);
          if (imgPath !== absoluteDest) {
            await copyFile(imgPath, absoluteDest);
          }
          relativeImagePaths.push("assets/image/" + fileName);
        }
      }
      let finalCustomMarker = "";
      if (wp.customMarker) {
        const markerName = await basename(wp.customMarker);
        const markerDest = await join(imageAssetsDir, markerName);
        if (wp.customMarker !== markerDest) {
          await copyFile(wp.customMarker, markerDest);
        }
        finalCustomMarker = "assets/image/" + markerName;
      }

      return {
        id: wp.id,
        lat: wp.lat,
        lng: wp.lng,
        label: wp.name,
        name: wp.name,
        customMarker: finalCustomMarker || undefined,

        popup_image: relativeImagePaths.length > 0 ? [relativeImagePaths[0]] : [],
        camera_pans: relativeImagePaths.length > 0
          ? relativeImagePaths.map((_, i) => (wp.imagePans && wp.imagePans[i] ? wp.imagePans[i] : "panright"))
          : [],
        image_display: wp.imageDisplay || "pip",

        images: relativeImagePaths,
        imagePans: wp.imagePans || [],
        imageTransitions: wp.imageTransitions || [],
        narration: wp.narration || "",
        arrivingNarration: wp.arrivingNarration || "",
        attractionNarration: wp.attractionNarration || "",

        audioUrl: wp.audioUrl ? "assets/audio/" + await basename(wp.audioUrl) : undefined,
        videoUrl: wp.videoUrl ? "assets/video/" + await basename(wp.videoUrl) : undefined,

        routeMode: wp.routeMode || "driving",
        customRoute: wp.customRoute || [],
        drawStyle: wp.drawStyle || "linear",

        isStopBy: wp.isStopBy || false,
        connectToRoute: wp.connectToRoute || false,
      };
    })
  );

  const firstUploadedImage = processedWaypoints.find(
    (wp) => wp.images && wp.images.length > 0,
  )?.images?.[0];
  let thumbnailPath = firstUploadedImage;
  if (thumbnailDataUrl?.startsWith("data:image/")) {
    const base64 = thumbnailDataUrl.split(",", 2)[1];
    if (base64) {
      thumbnailPath = "thumbnail.png";
      const absThumbPath = await join(projectDir, "thumbnail.png");
      await writeFile(
        absThumbPath,
        Uint8Array.from(atob(base64), (char) => char.charCodeAt(0)),
      );
    }
  }

  const startWp = processedWaypoints[0];
  const endWp = processedWaypoints[processedWaypoints.length - 1];

  const jobConfig = {
    project_id: projId,
    user_id: metadata.user_id,
    project_name: projName,
    created_at: metadata.created_at,
    theme: metadata.theme,
    status: "saved",
    archive_path: archivePath,
    thumbnail_path: thumbnailPath,
    source_files: { gps_route: "raw_track.gpx" },
    settings: settings,
    overview_narration: metadata.overview_narration || "",
    start_point: startWp ? { lat: startWp.lat, lng: startWp.lng, label: startWp.label } : null,
    end_point: endWp ? { lat: endWp.lat, lng: endWp.lng, label: endWp.label } : null,
    waypoints: processedWaypoints,
  };

  const payload = JSON.stringify(jobConfig, null, 2);
  await writeTextFile(nvvPath, payload);
  await writeTextFile(jsonPath, payload);

  const manifest = buildAssetManifest(projId, processedWaypoints as any, settings);
  const manifestPath = await join(projectDir, "asset_manifest.json");
  await writeTextFile(manifestPath, JSON.stringify(manifest, null, 2));

  const activeKeys = new Set<string>();

  const routedWaypoints = waypoints.filter(wp => !wp.isStopBy || wp.connectToRoute);

  for (let i = 0; i < routedWaypoints.length - 1; i++) {
    const wp1 = routedWaypoints[i];
    const wp2 = routedWaypoints[i + 1];
    const mode = wp1.routeMode || "driving";
    const customHash = mode === "draw" ? JSON.stringify(wp1.customRoute || []) : "";
    activeKeys.add(`${wp1.lat.toFixed(5)},${wp1.lng.toFixed(5)}|${wp2.lat.toFixed(5)},${wp2.lng.toFixed(5)}|${mode}|${customHash}`);
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

  // Zip the workspace into the single .nvv archive file
  if (archivePath) {
    await invoke("zip_project", { sourceDir: projectDir, destFile: archivePath });
  }

  return { projectDir, projId, projName, nvvPath: archivePath, thumbnailPath };
};

export const loadProjectData = async (forcePath?: string, isFolder = false) => {
  let selectedPath = forcePath;

  if (!selectedPath) {
    if (isFolder) {
      const res = await dialogOpen({
        multiple: false,
        directory: true,
      });
      if (!res || typeof res !== 'string') return null;
      selectedPath = res;
    } else {
      const res = await dialogOpen({
        multiple: false,
        filters: [{ name: `${appConfig.name} Project`, extensions: [fileSystem.extensions.project, 'zip'] }],
      });
      if (!res || typeof res !== 'string') return null;
      selectedPath = res;
    }
  }

  const docsPath = await documentDir();
  let projectDir = "";
  let fileContent = "";
  let isDirectory = false;

  // 1. Check if selectedPath is a folder (Option B: folder-based project)
  try {
    const entries = await readDir(selectedPath);
    isDirectory = true;
    projectDir = selectedPath;

    // Search for a .nvv file inside the folder
    const nvvEntry = entries.find(e => e.name?.endsWith(`.${fileSystem.extensions.project}`));
    if (nvvEntry && nvvEntry.name) {
      const nvvPath = await join(selectedPath, nvvEntry.name);
      fileContent = await readTextFile(nvvPath);
    } else {
      // Fallback to job_config.json
      const configPath = await join(selectedPath, "job_config.json");
      if (await exists(configPath)) {
        fileContent = await readTextFile(configPath);
      } else {
        throw new Error("No Navivi project file or job_config.json found in the selected folder.");
      }
    }
  } catch (err: any) {
    if (isDirectory) throw err;
    // Not a directory, so proceed to handle as a file
  }

  // 2. If it's a file: handle as ZIP archive or standalone JSON
  if (!isDirectory) {
    try {
      // Attempt to unzip it into a Workspace folder (in case it is a single-file ZIP archive)
      const workspaceId = Date.now().toString();
      const workspaceDir = await join(docsPath, fileSystem.rootFolder, fileSystem.workspacesFolder, workspaceId);

      await invoke("unzip_project", { sourceFile: selectedPath, destDir: workspaceDir });

      // If we reach here, it was a valid ZIP project file!
      projectDir = workspaceDir;

      // Find the .nvv file inside the unzipped workspace
      const projectName = await basename(selectedPath, `.${fileSystem.extensions.project}`);
      const nvvPath = await join(workspaceDir, `${projectName}.${fileSystem.extensions.project}`);

      if (await exists(nvvPath)) {
        fileContent = await readTextFile(nvvPath);
      } else {
        // Find ANY .nvv file if the name changed
        const entries = await readDir(workspaceDir);
        const nvvEntry = entries.find(e => e.name?.endsWith(`.${fileSystem.extensions.project}`));
        if (nvvEntry && nvvEntry.name) {
          fileContent = await readTextFile(await join(workspaceDir, nvvEntry.name));
        } else {
          const configPath = await join(workspaceDir, "job_config.json");
          if (await exists(configPath)) {
            fileContent = await readTextFile(configPath);
          } else {
            throw new Error("No .nvv file or job_config.json found in archive");
          }
        }
      }
    } catch (err) {
      // Unzip failed, so it must be a legacy uncompressed JSON file
      projectDir = await dirname(selectedPath);
      fileContent = await readTextFile(selectedPath);
    }
  }

  const data = JSON.parse(fileContent);
  data.directory_path = projectDir;
  data.archive_path = selectedPath; // Save the path to the .nvv archive or folder

  if (data.thumbnail_path && !data.thumbnail_path.match(/^[a-zA-Z]:\\/) && !data.thumbnail_path.startsWith('/')) {
    data.thumbnail_path = await join(projectDir, data.thumbnail_path);
  }

  if (data.source_files?.gps_route && !data.source_files.gps_route.match(/^[a-zA-Z]:\\/) && !data.source_files.gps_route.startsWith('/')) {
    data.source_files.gps_route = await join(projectDir, data.source_files.gps_route);
  }

  if (data.waypoints) {
    for (const wp of data.waypoints) {
      if (wp.customMarker && !wp.customMarker.match(/^[a-zA-Z]:\\/) && !wp.customMarker.startsWith('/')) {
        wp.customMarker = await join(projectDir, wp.customMarker);
      }
      if (wp.audioUrl && !wp.audioUrl.match(/^[a-zA-Z]:\\/) && !wp.audioUrl.startsWith('/')) {
        wp.audioUrl = await join(projectDir, wp.audioUrl);
      }
      if (wp.videoUrl && !wp.videoUrl.match(/^[a-zA-Z]:\\/) && !wp.videoUrl.startsWith('/')) {
        wp.videoUrl = await join(projectDir, wp.videoUrl);
      }
      if (wp.images) {
        for (let i = 0; i < wp.images.length; i++) {
          if (wp.images[i] && !wp.images[i].match(/^[a-zA-Z]:\\/) && !wp.images[i].startsWith('/')) {
            wp.images[i] = await join(projectDir, wp.images[i]);
          }
        }
      }
      if (wp.popup_image) {
        for (let i = 0; i < wp.popup_image.length; i++) {
          if (wp.popup_image[i] && !wp.popup_image[i].match(/^[a-zA-Z]:\\/) && !wp.popup_image[i].startsWith('/')) {
            wp.popup_image[i] = await join(projectDir, wp.popup_image[i]);
          }
        }
      }
    }
  }

  return { data, selectedPath };
};

export const scanProjectsOnDisk = async (): Promise<RecentProjects[]> => {
  try {
    const docsPath = await documentDir();
    const projectsRoot = await join(docsPath, fileSystem.rootFolder, fileSystem.projectsFolder);
    if (!(await exists(projectsRoot))) return [];

    const entries = await readDir(projectsRoot);
    const discovered: RecentProjects[] = [];

    for (const entry of entries) {
      if (!entry.name) continue;
      const fullPath = await join(projectsRoot, entry.name);

      // Check if folder
      try {
        const subEntries = await readDir(fullPath);
        const nvvFile = subEntries.find(s => s.name?.endsWith(`.${fileSystem.extensions.project}`));
        const hasJobConfig = subEntries.some(s => s.name === "job_config.json");

        if (nvvFile || hasJobConfig) {
          let projName = entry.name;
          let thumbnailPath: string | undefined = undefined;

          // Check for thumbnail
          const thumbEntry = subEntries.find(s => s.name?.toLowerCase().startsWith("thumbnail."));
          if (thumbEntry && thumbEntry.name) {
            thumbnailPath = await join(fullPath, thumbEntry.name);
          }

          try {
            const configPath = await join(fullPath, nvvFile?.name || "job_config.json");
            const content = await readTextFile(configPath);
            const parsed = JSON.parse(content);
            if (parsed.project_name) projName = parsed.project_name;
            if (parsed.thumbnail_path) {
              if (parsed.thumbnail_path.match(/^[a-zA-Z]:\\/) || parsed.thumbnail_path.startsWith('/')) {
                thumbnailPath = parsed.thumbnail_path;
              } else {
                thumbnailPath = await join(fullPath, parsed.thumbnail_path);
              }
            }
          } catch { }

          const projectTarget = nvvFile ? await join(fullPath, nvvFile.name) : fullPath;
          discovered.push({
            name: projName,
            path: projectTarget,
            lastOpened: Date.now(),
            thumbnailPath,
          });
        }
      } catch {
        // Entry is a single file (.nvv or .zip archive)
        if (entry.name.endsWith(`.${fileSystem.extensions.project}`)) {
          const cleanName = entry.name.replace(new RegExp(`\\.${fileSystem.extensions.project}$`), "");
          discovered.push({
            name: cleanName,
            path: fullPath,
            lastOpened: Date.now(),
          });
        }
      }
    }

    return discovered;
  } catch (err) {
    console.warn("Failed to scan projects on disk:", err);
    return [];
  }
};

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

export function normalizePathSeparators(p: string): string {
  return p.replace(/\\/g, "/");
}

export function toRelativeProjectPath(filePath: string | undefined, projectDir: string): string {
  if (!filePath) return "";
  const normFile = normalizePathSeparators(filePath);
  const normProj = normalizePathSeparators(projectDir).replace(/\/+$/, "");

  // If filePath starts with projectDir, strip it
  if (normFile.toLowerCase().startsWith(normProj.toLowerCase() + "/")) {
    return normFile.slice(normProj.length + 1);
  }

  // If it's already a relative path (e.g. "assets/video/..."), return normalized
  if (!/^[a-zA-Z]:\//.test(normFile) && !normFile.startsWith("/")) {
    return normFile;
  }

  return normFile;
}

export async function toAbsoluteProjectPath(filePath: string | undefined, projectDir: string): Promise<string> {
  if (!filePath) return "";
  const normFile = normalizePathSeparators(filePath);
  const isWindowsAbs = /^[a-zA-Z]:\//.test(normFile);
  const isUnixAbs = normFile.startsWith("/");

  if (!isWindowsAbs && !isUnixAbs) {
    return await join(projectDir, filePath.replace(/\//g, "\\"));
  }

  try {
    if (await exists(filePath)) {
      return filePath;
    }
  } catch { }

  const assetsIdx = normFile.indexOf("/assets/");
  if (assetsIdx !== -1) {
    const relAsset = normFile.slice(assetsIdx + 1);
    return await join(projectDir, relAsset.replace(/\//g, "\\"));
  }

  return filePath;
}

export function compileTimelineManifest(
  projectName: string,
  timeline: TimelineData,
  renderSettings?: RenderSettings,
  markers?: TimelineManifest["markers"],
  projectDir?: string,
): TimelineManifest & ExportManifestPayload {
  const toRel = (p: string | undefined): string => {
    if (!p) return "";
    return projectDir ? toRelativeProjectPath(p, projectDir) : p;
  };

  // find master audio track
  const audioTrack = timeline.tracks.find((t) => t.type === "audio");
  const audioClip = audioTrack
    ? timeline.clips.find((c) => c.trackId === audioTrack.id)
    : null;
  // map visual clips
  const videoTracks: ManifestClip[] = [];
  // Sort clips by start time so python receives them in order
  const visualClips = timeline.clips
    .filter((c) => c.trackId !== audioTrack?.id)
    .sort((a, b) => a.startTime - b.startTime);

  for (const clip of visualClips) {
    const track = timeline.tracks.find((t) => t.id === clip.trackId);
    videoTracks.push({
      clip_id: clip.id,
      file_path: toRel(clip.source),
      duration: clip.duration,
      type: track?.name.toLowerCase().includes("popup")
        ? "static_popup"
        : "video",
    });
  }
  // calculate total duration (end of last clip)
  const totalDuration = timeline.clips.reduce(
    (max, clip) => Math.max(max, clip.startTime + clip.duration),
    0,
  );

  const aspectRatio = renderSettings?.aspectRatio || "16:9";
  const resolution = renderSettings?.resolution || {
    width: 1920,
    height: 1080,
  };
  const fps = renderSettings?.fps || 30;
  const bitrateKbps = renderSettings?.bitrateKbps || 10000;
  const nowIso = new Date().toISOString();

  // Convert clips inside ui_state and manifest to relative paths
  const relativeClips = timeline.clips.map((c) => ({
    ...c,
    source: c.source ? toRel(c.source) : c.source,
  }));

  // build final json manifest payload
  const manifest: TimelineManifest & ExportManifestPayload = {
    project_name: projectName,
    total_duration_seconds: totalDuration,
    video_tracks: videoTracks,
    audio_track: audioClip?.source ? toRel(audioClip.source) : undefined,
    ui_state: {
      ...timeline,
      clips: relativeClips,
    },
    render_settings: renderSettings,
    aspect_ratio: aspectRatio,
    resolution: resolution,
    fps: fps,
    bitrate_kbps: bitrateKbps,
    skip_rich_media: renderSettings?.skipRichMedia ?? false,
    tracks: timeline.tracks,
    clips: relativeClips,
    transitions: timeline.transitions || [],
    markers: markers || timeline.markers || [],
    exported_at: nowIso,

    // ExportManifestPayload compliance
    projectName: projectName,
    aspectRatio: aspectRatio,
    bitrateKbps: bitrateKbps,
    totalDuration: totalDuration,
    exportedAt: nowIso,
    renderSettings: renderSettings,
  };

  return manifest;
}

export async function saveTimelineManifest(
  projectDir: string,
  projectName: string,
  timeline: TimelineData,
  renderSettings?: RenderSettings,
  markers?: TimelineManifest["markers"],
): Promise<boolean> {
  /**
   * convert react timeline state into timeline.json manifest
   * and saves it with relative paths for portability
   */
  try {
    const manifestPath = await join(projectDir, "timeline.json");
    if ((!timeline?.clips || timeline.clips.length === 0) && (await exists(manifestPath))) {
      try {
        const existingRaw = await readTextFile(manifestPath);
        const existingData = JSON.parse(existingRaw);
        if (existingData?.video_tracks && existingData.video_tracks.length > 0) {
          console.log("Preserving existing timeline.json because in-memory timeline clips are empty.");
          return true;
        }
      } catch (e) {
        // Fall through
      }
    }
    const manifest = compileTimelineManifest(
      projectName,
      timeline,
      renderSettings,
      markers,
      projectDir,
    );

    // write to disk formatted cleanly
    await writeTextFile(manifestPath, JSON.stringify(manifest, null, 2));
    console.log("✓ timeline.json successfully saved.");
    return true;
  } catch (error) {
    console.error("Failed to save timeline.json:", error);
    return false;
  }
}


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

    if (manifest.video_tracks) {
      for (const track of manifest.video_tracks) {
        if (track.file_path) {
          track.file_path = await toAbsoluteProjectPath(track.file_path, projectDir);
        }
        if (track.audio_path) {
          track.audio_path = await toAbsoluteProjectPath(track.audio_path, projectDir);
        }
        if (track.subtitle_path) {
          track.subtitle_path = await toAbsoluteProjectPath(track.subtitle_path, projectDir);
        }
      }
    }

    if (manifest.audio_track) {
      manifest.audio_track = await toAbsoluteProjectPath(manifest.audio_track, projectDir);
    }

    if (manifest.ui_state?.clips) {
      for (const clip of manifest.ui_state.clips) {
        if (clip.source) {
          clip.source = await toAbsoluteProjectPath(clip.source, projectDir);
        }
      }
    }

    if (manifest.clips) {
      for (const clip of manifest.clips) {
        if (clip.source) {
          clip.source = await toAbsoluteProjectPath(clip.source, projectDir);
        }
      }
    }

    return manifest;
  } catch (error) {
    console.error("Failed to load or parse timeline manifest:", error);
    return null;
  }
};

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