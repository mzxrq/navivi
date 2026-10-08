import { documentDir, join, basename, dirname } from "@tauri-apps/api/path";
import { writeTextFile, writeFile, mkdir, exists, copyFile, readTextFile, readDir, BaseDirectory, open as fsOpen } from "@tauri-apps/plugin-fs";
import { open as dialogOpen } from "@tauri-apps/plugin-dialog";
import { invoke, convertFileSrc } from "@tauri-apps/api/core";
import { appConfig, fileSystem, GLOBAL_DICTIONARY_KEY } from "../config/constants";
import { buildAssetManifest } from "../utils/manifestBuilder";
import { TimelineData, RecentProjects, TextStyle, ProjectMetadata } from "../types";
import { routeCacheKey } from "../utils/routeCacheKey";
import { stripApiKeys } from "../utils/apiKeys";
import { mapboxTileLoader, segmentElevations } from "../utils/terrainElevation";
import { planFileNames } from "../utils/fileNames";
import { renameCredits } from "../utils/photoCredits";
import { emptyTimeline, type ExportOptions, timelineFromEditorState, timelineFromPipeline, toManifest } from "../features/editor/model";
import { i18n } from "@lingui/core";
import { db } from "./db";

// A slug id already used by a different project folder in the DB.
async function isProjectIdTaken(id: string, directoryPath: string): Promise<boolean> {
  try {
    const row = await db.projects.get(id);
    return Boolean(row && row.directoryPath !== directoryPath);
  } catch {
    return false;
  }
}

const xmlText = (text: string) => text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

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

// A path that is already absolute (a drive letter or a leading slash) is left alone when a project is opened.
const isAbsolutePath = (p: string) => /^[a-zA-Z]:/.test(p) || p.startsWith("/") || p.startsWith(String.fromCharCode(92));

// A blank overview narration is left to the pipeline (it restores or writes one); a filled one is kept with its
// auto flag, so a script the user wrote is never replaced and an auto one stays replaceable.
export function overviewNarrationFields(metadata: ProjectMetadata) {
  const text = metadata.overview_narration || "";
  if (!text.trim()) return { overview_narration: "" };
  return {
    overview_narration: text,
    overview_narration_is_auto: metadata.overview_narration_is_auto === true,
    ...(metadata.overview_narration_source_ids !== undefined
      ? { overview_narration_source_ids: metadata.overview_narration_source_ids }
      : {}),
  };
}

// The automatic overview script a render wrote: job_config.json, else the pipeline's own copy in .navivi.
export async function readRenderedOverviewNarration(dir: string): Promise<Partial<ProjectMetadata> | null> {
  const read = async (...parts: string[]) => {
    try {
      return JSON.parse(await readTextFile(await join(dir, ...parts)));
    } catch {
      return null;
    }
  };
  const config = await read(fileSystem.configFile);
  if (config?.overview_narration_is_auto === true && (config.overview_narration || "").trim()) {
    return {
      overview_narration: config.overview_narration,
      overview_narration_is_auto: true,
      overview_narration_source_ids: config.overview_narration_source_ids,
    };
  }
  const saved = await read(fileSystem.metaFolder, "overview_narration.json");
  if ((saved?.script || "").trim()) {
    return { overview_narration: saved.script, overview_narration_is_auto: true, overview_narration_source_ids: saved.source_ids };
  }
  return null;
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
      while ((await exists(projectDir)) || (await isProjectIdTaken(projId, projectDir))) {
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
  const jsonPath = await join(projectDir, "job_config.json");

  if (!(await exists(projectDir))) await mkdir(projectDir, { recursive: true });
  if (!(await exists(assetsDir))) await mkdir(assetsDir, { recursive: true });
  if (!(await exists(imageAssetsDir))) await mkdir(imageAssetsDir, { recursive: true });
  const userVideoDir = await join(assetsDir, "video", "user");
  if (!(await exists(userVideoDir))) await mkdir(userVideoDir, { recursive: true });

  // Initialize GPX String with GPSBabel expected headers
  const gpxLines: string[] = [];
  gpxLines.push(`<?xml version="1.0" encoding="UTF-8"?>`);
  gpxLines.push(`<gpx version="1.1" creator="${appConfig.name}" xmlns="http://www.topografix.com/GPX/1/1">`);
  gpxLines.push(`  <time>${new Date().toISOString()}</time>`);

  // export waypoints
  waypoints.forEach((wp) => {
    gpxLines.push(` <wpt lat="${wp.lat}" lon="${wp.lng}">`);
    const safeName = xmlText(wp.name || "Navivi Stop");
    gpxLines.push(`   <name>${safeName}</name>`);
    gpxLines.push(` </wpt>`);
  });

  // The video colors the route by steepness from these <ele> values (Python reads them back from raw_track.gpx).
  // Without the switch, a token or a network they stay the old constant, which Python ignores as "no elevation".
  let legEle: (number[] | null)[] = [];
  const mapboxToken = settings?.mapbox_api_key || import.meta.env.VITE_MAPBOX_TOKEN;
  if (settings?.show_route_heatmap && mapboxToken) {
    try {
      legEle = await segmentElevations(routeSegments, waypoints, mapboxTileLoader(mapboxToken));
    } catch {
      legEle = [];
    }
  }

  // track segments
  gpxLines.push(`  <trk>\n    <name>${xmlText(projName)}</name>\n    <trkseg>`);

  let currentTime = new Date();
  let lastPos: [number, number] | null = null;

  // export tracks
  routeSegments.forEach((segment, segIndex) => {
    // Rough speed estimates: 15 m/s (~54 km/h) for driving, 1.4 m/s (~5 km/h) for walking
    const speedMs = (segment.mode === "walking" || segment.mode === "direct" || segment.mode === "draw") ? 1.4 : 15.0;

    segment.positions.forEach((pos: [number, number], posIndex: number) => {
      let dist = 0;

      if (lastPos) {
        dist = calculateDistance(lastPos, pos);
      }

      // Calculate time delta based on distance and assumed speed
      const timeDeltaSeconds = lastPos ? dist / speedMs : 0;
      currentTime = new Date(currentTime.getTime() + timeDeltaSeconds * 1000);

      gpxLines.push(`      <trkpt lat="${pos[0]}" lon="${pos[1]}">`);
      gpxLines.push(`        <ele>${(legEle[segIndex]?.[posIndex] ?? 35).toFixed(1)}</ele>`); // 35 = no elevation known
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

  const imageNames = await planFileNames(imageAssetsDir, waypoints.flatMap((wp) => [...(wp.images ?? []), ...(wp.customMarker ? [wp.customMarker] : [])]));
  const videoNames = await planFileNames(userVideoDir, waypoints.flatMap((wp) => wp.videos ?? []));

  const processedWaypoints = await Promise.all(
    waypoints.map(async (wp) => {
      const relativeImagePaths: string[] = [];
      // A credit belongs to its photo, so it moves to the photo's new name when the file is copied into the project.
      const renamed = new Map<string, string>();

      if (wp.images && wp.images.length > 0) {
        for (const imgPath of wp.images) {
          const fileName = imageNames.get(imgPath) ?? (await basename(imgPath));
          const absoluteDest = await join(imageAssetsDir, fileName);
          if (imgPath !== absoluteDest) {
            await copyFile(imgPath, absoluteDest);
          }
          relativeImagePaths.push("assets/image/" + fileName);
          renamed.set(imgPath, "assets/image/" + fileName);
        }
      }
      const relativeVideoPaths: string[] = [];
      for (const videoPath of wp.videos ?? []) {
        const fileName = videoNames.get(videoPath) ?? (await basename(videoPath));
        const absoluteDest = await join(userVideoDir, fileName);
        if (videoPath !== absoluteDest && !(await exists(absoluteDest))) {
          await copyFile(videoPath, absoluteDest);
        }
        relativeVideoPaths.push("assets/video/user/" + fileName);
      }
      let finalCustomMarker = "";
      if (wp.customMarker) {
        const markerName = imageNames.get(wp.customMarker) ?? (await basename(wp.customMarker));
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
        image_display: wp.imageDisplay || "pip",
        overviewHighlight: wp.overviewHighlight,

        images: relativeImagePaths,
        videos: relativeVideoPaths,
        videoSound: relativeVideoPaths.map((_, i) => wp.videoSound?.[i] ?? false),
        imagePans: wp.imagePans || [],
        imageCredits: renameCredits(wp.imageCredits, renamed),
        narration: wp.narration || "",
        arrivingNarration: wp.arrivingNarration || "",
        attractionNarration: wp.attractionNarration || "",

        audioUrl: wp.audioUrl ? "assets/audio/" + await basename(wp.audioUrl) : undefined,
        videoUrl: wp.videoUrl ? "assets/video/" + await basename(wp.videoUrl) : undefined,

        routeMode: wp.routeMode || "driving",
        customRoute: wp.customRoute || [],
        customRouteEle: wp.customRouteEle?.length ? wp.customRouteEle : undefined,
        drawStyle: wp.drawStyle || "linear",
        lineColor: wp.lineColor || undefined,
        viaPoints: wp.viaPoints?.length ? wp.viaPoints : undefined,
        curveOffset: wp.curveOffset ?? undefined,
        timestamp: wp.timestamp || undefined,

        isStopBy: wp.isStopBy || false,
        connectToRoute: wp.connectToRoute || false,
        skipAssetGeneration: wp.skipAssetGeneration ?? undefined,
        pauseAtWaypoint: wp.pauseAtWaypoint ?? undefined,
      };
    })
  );

  let thumbnailPath = metadata.thumbnail_path;
  
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
  } else if (!thumbnailPath) {
    const firstUploadedImage = processedWaypoints.find(
      (wp) => wp.images && wp.images.length > 0,
    )?.images?.[0];
    thumbnailPath = firstUploadedImage;
  }

  const startWp = processedWaypoints[0];
  const endWp = processedWaypoints[processedWaypoints.length - 1];

  // SQLite is the source of truth; job_config.json / .nvv are exported from it for Python.
  const row = await db.projects.upsert({
    id: projId,
    name: projName,
    directoryPath: projectDir,
    userId: metadata.user_id ?? null,
    theme: metadata.theme ?? null,
    status: "saved",
    archivePath: null, // projects open from their folder; a .nvv is only made by "Export for sharing"
    thumbnailPath: thumbnailPath || null,
    videoTitle: metadata.video_title || "",
    videoSubtitle: metadata.video_subtitle || "",
    enableIntro: metadata.enable_intro ?? true,
    overviewNarration: metadata.overview_narration || "",
    overviewNarrationIsAuto: metadata.overview_narration_is_auto === true,
    createdAt: metadata.created_at || undefined,
  });
  // The map keys are app-wide; neither the database row nor job_config.json (and so no shared archive) gets them.
  const savedSettings = stripApiKeys(await db.settings.put(row.id, stripApiKeys(settings)));

  const jobConfig = {
    project_id: row.id,
    user_id: row.userId ?? metadata.user_id,
    project_name: row.name,
    created_at: row.createdAt,
    updated_at: row.updatedAt,
    theme: row.theme ?? undefined,
    status: row.status,
    thumbnail_path: thumbnailPath,
    source_files: { gps_route: "raw_track.gpx" },
    settings: { ...savedSettings, global_pronunciation_dictionary: (await db.appSettings.get(GLOBAL_DICTIONARY_KEY)) ?? [] },
    map_language: i18n.locale || "en",
    ...overviewNarrationFields(metadata),
    video_title: row.videoTitle,
    video_subtitle: row.videoSubtitle,
    enable_intro: row.enableIntro,
    start_point: startWp ? { lat: startWp.lat, lng: startWp.lng, label: startWp.label } : null,
    end_point: endWp ? { lat: endWp.lat, lng: endWp.lng, label: endWp.label } : null,
    waypoints: processedWaypoints,
  };

  const payload = JSON.stringify(jobConfig, null, 2);
  await writeTextFile(jsonPath, payload);

  const manifest = buildAssetManifest(projId, processedWaypoints as any, settings);
  const metaDir = await join(projectDir, fileSystem.metaFolder);
  if (!(await exists(metaDir))) await mkdir(metaDir, { recursive: true });
  const manifestPath = await join(metaDir, "asset_manifest.json");
  await writeTextFile(manifestPath, JSON.stringify(manifest, null, 2));

  const activeKeys = new Set<string>();

  const routedWaypoints = waypoints.filter(wp => !wp.isStopBy || wp.connectToRoute);

  for (let i = 0; i < routedWaypoints.length - 1; i++) {
    const wp1 = routedWaypoints[i];
    const wp2 = routedWaypoints[i + 1];
    activeKeys.add(routeCacheKey(wp1, wp2));
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
  await db.routeCache.replace(row.id, cleanCache);
  // Python reads the exported file (narration_step.py).
  const routeCachePath = await join(metaDir, "routecache.json");
  await writeTextFile(routeCachePath, JSON.stringify(cleanCache));

  return { projectDir, projId, projName, nvvPath: null as string | null, thumbnailPath };
};

// One-time cleanup of a folder made by an older version (duplicate project file, generated files into .navivi,
// map tiles to the shared cache). Run after the project is in the database, since it removes `.history/`.
export async function tidyProjectFolder(projectDir: string): Promise<void> {
  try {
    const sharedTileCache = await join(await documentDir(), fileSystem.rootFolder, fileSystem.cacheFolder, "tiles");
    const report = await invoke<{ moved: string[]; removed: string[]; kept: string[] }>("tidy_project_folder", {
      projectDir,
      sharedTileCache,
      removeHistory: true,
    });
    if (report.moved.length || report.removed.length || report.kept.length) console.log("Tidied project folder:", report);
  } catch (error) {
    console.warn("Could not tidy the project folder:", error);
  }
}

// job_config.json is the project file. Folders from older versions may only have `<name>.nvv`, a JSON copy of it.
async function readProjectFile(dir: string, names: string[]): Promise<string> {
  if (names.includes(fileSystem.configFile)) return readTextFile(await join(dir, fileSystem.configFile));
  for (const name of names.filter((n) => n.endsWith(`.${fileSystem.extensions.project}`))) {
    const text = await readTextFile(await join(dir, name)).catch(() => "");
    if (text.trimStart().startsWith("{")) return text;
  }
  throw new Error("No Navivi project file or job_config.json found in the selected folder.");
}

// A shared archive is unpacked into its own folder, named after the project and never over an existing one.
async function freeWorkspaceDir(docsPath: string, projectName: string): Promise<string> {
  const root = await join(docsPath, fileSystem.rootFolder, fileSystem.workspacesFolder);
  const slug = projectName.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "project";
  let candidate = await join(root, slug);
  for (let n = 2; await exists(candidate); n++) candidate = await join(root, `${slug}_${n}`);
  return candidate;
}

// A copy of a project folder under a new name, with its own project id so it is a separate project in the database.
export async function duplicateProjectFolder(sourceDir: string, name: string): Promise<string> {
  const destDir = await freeWorkspaceDir(await documentDir(), name);
  const config = JSON.parse(await readProjectFile(sourceDir, (await readDir(sourceDir)).map((e) => e.name ?? "")));
  await invoke("duplicate_project_folder", { sourceDir, destDir });
  let id = await basename(destDir);
  if (await isProjectIdTaken(id, destDir)) id = `${id}_${Date.now()}`;
  config.project_id = id;
  config.project_name = name;
  if (config.settings) config.settings = stripApiKeys(config.settings);
  await writeTextFile(await join(destDir, fileSystem.configFile), JSON.stringify(config, null, 2));
  return destDir;
}

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

    fileContent = await readProjectFile(selectedPath, entries.map((e) => e.name ?? ""));
  } catch (err: any) {
    if (isDirectory) throw err;
    // Not a directory, so proceed to handle as a file
  }

  // 2. If it's a file: handle as ZIP archive or standalone JSON
  if (!isDirectory) {
    try {
      // Attempt to unzip it into a Workspace folder (in case it is a single-file ZIP archive)
      const workspaceDir = await freeWorkspaceDir(docsPath, await basename(selectedPath, `.${fileSystem.extensions.project}`));

      await invoke("unzip_project", { sourceFile: selectedPath, destDir: workspaceDir });

      // If we reach here, it was a valid ZIP project file!
      projectDir = workspaceDir;

      fileContent = await readProjectFile(workspaceDir, (await readDir(workspaceDir)).map((e) => e.name ?? ""));
    } catch (err) {
      // Unzip failed, so it must be a legacy uncompressed JSON file
      projectDir = await dirname(selectedPath);
      fileContent = await readTextFile(selectedPath);
    }
  }

  const data = JSON.parse(fileContent);
  data.directory_path = projectDir;
  data.archive_path = null;

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
      if (wp.imageCredits) {
        const absolute = new Map<string, string>();
        for (const rel of Object.keys(wp.imageCredits)) absolute.set(rel, isAbsolutePath(rel) ? rel : await join(projectDir, rel));
        wp.imageCredits = renameCredits(wp.imageCredits, absolute);
      }
      if (wp.videos) {
        for (let i = 0; i < wp.videos.length; i++) {
          if (wp.videos[i] && !wp.videos[i].match(/^[a-zA-Z]:\\/) && !wp.videos[i].startsWith('/')) {
            wp.videos[i] = await join(projectDir, wp.videos[i]);
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

          let fileTime = Date.now();
          try {
            const configPath = await join(fullPath, hasJobConfig ? "job_config.json" : (nvvFile?.name ?? "job_config.json"));
            const content = await readTextFile(configPath);
            const parsed = JSON.parse(content);
            if (parsed.project_name) projName = parsed.project_name;
            if (parsed.updated_at) fileTime = parsed.updated_at;
            else if (parsed.created_at) fileTime = new Date(parsed.created_at).getTime();
            if (parsed.thumbnail_path) {
              if (parsed.thumbnail_path.match(/^[a-zA-Z]:\\/) || parsed.thumbnail_path.startsWith('/')) {
                thumbnailPath = parsed.thumbnail_path;
              } else {
                thumbnailPath = await join(fullPath, parsed.thumbnail_path);
              }
            }
          } catch { }

          const projectTarget = fullPath;
          discovered.push({
            name: projName,
            path: projectTarget,
            lastOpened: fileTime,
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

export async function saveTimelineManifest(
  projectDir: string,
  projectName: string,
  timeline: TimelineData,
  captionStyle?: TextStyle,
  exportOptions?: ExportOptions,
): Promise<boolean> {
  try {
    const manifestPath = await join(projectDir, "timeline.json");
    // An empty timeline (editor never opened) must not wipe what the pipeline wrote.
    if (timeline.segments.length === 0 && (await exists(manifestPath))) return true;
    await writeTextFile(manifestPath, JSON.stringify(toManifest(projectName, timeline, captionStyle, exportOptions), null, 2));
    return true;
  } catch (error) {
    console.error("Failed to save timeline.json:", error);
    return false;
  }
}

export function probeDuration(url: string, kind: "video" | "audio", fallback: number): Promise<number> {
  return new Promise((resolve) => {
    const media = document.createElement(kind);
    const done = (value: number) => {
      media.removeAttribute("src");
      media.load();
      resolve(Number.isFinite(value) && value > 0 ? value : fallback);
    };
    const timer = setTimeout(() => done(fallback), 8000);
    media.preload = "metadata";
    media.onloadedmetadata = () => {
      clearTimeout(timer);
      done(media.duration);
    };
    media.onerror = () => {
      clearTimeout(timer);
      done(fallback);
    };
    media.src = url;
  });
}

// The editor's own state if timeline.json has one, otherwise built from what the pipeline wrote.
export async function loadTimelineData(projectDir: string): Promise<TimelineData> {
  const manifestPath = await join(projectDir, "timeline.json");
  if (!(await exists(manifestPath))) return emptyTimeline();
  const raw = JSON.parse(await readTextFile(manifestPath));
  const saved = timelineFromEditorState(raw);
  if (saved) return saved;

  const rel = (p: string) => toRelativeProjectPath(p, projectDir);
  for (const track of raw.video_tracks ?? []) {
    if (track.file_path) track.file_path = rel(track.file_path);
    if (track.audio_path) track.audio_path = rel(track.audio_path);
    if (track.subtitle_path) track.subtitle_path = rel(track.subtitle_path);
    if (track.extra_audio_path) track.extra_audio_path = rel(track.extra_audio_path);
  }
  for (const clip of raw.ui_state?.clips ?? []) if (clip.source) clip.source = rel(clip.source);

  const durations = new Map<string, number>();
  return timelineFromPipeline(raw, async (relPath, kind) => {
    const key = `${kind}:${relPath}`;
    if (!durations.has(key)) {
      const abs = await toAbsoluteProjectPath(relPath, projectDir);
      durations.set(key, await probeDuration(convertFileSrc(abs), kind, kind === "video" ? 5 : 0));
    }
    return durations.get(key) ?? 0;
  });
}

export async function loadTimelineManifest(projectDir: string): Promise<any | null> {
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
    const manifest = JSON.parse(fileContents);

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
    // .navivi/routecache.json, or the root file an older version wrote
    for (const path of [
      await join(projectDir, fileSystem.metaFolder, "routecache.json"),
      await join(projectDir, ".routecache.json"),
    ]) {
      if (await exists(path)) return JSON.parse(await readTextFile(path));
    }
  } catch (error) {
    console.error("Failed to load route cache:", error);
  }
  return {};
}

export async function saveRouteCache(projectDir: string, cacheData: Record<string, [number, number][]>): Promise<boolean> {
  try {
    const metaDir = await join(projectDir, fileSystem.metaFolder);
    if (!(await exists(metaDir))) await mkdir(metaDir, { recursive: true });
    await writeTextFile(await join(metaDir, "routecache.json"), JSON.stringify(cacheData));
    return true;
  } catch (error) {
    console.error("Failed to save route cache:", error);
    return false;
  }
};
