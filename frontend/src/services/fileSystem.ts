import { documentDir, join, basename } from "@tauri-apps/api/path";
import { writeTextFile, mkdir, exists, copyFile, readTextFile } from "@tauri-apps/plugin-fs";
import { open } from "@tauri-apps/plugin-dialog";
import { appConfig, fileSystem } from "../config/constants";

export const saveProjectData = async (
  waypoints: any[],
  routeSegments: any[],
  metadata: any,
  settings: any,
  routingCache: Record<string, [number, number][]>,
  overrideName?: string,
  asDuplicate?: boolean,
) => {
  const docsPath = await documentDir();
  const projectRoot = await join(docsPath, fileSystem.rootFolder, fileSystem.projectsFolder);

  if (!(await exists(projectRoot))) {
    await mkdir(projectRoot, { recursive: true });
  }

  let projName = overrideName || metadata.projName || appConfig.defaultProjectName;
  let projId = asDuplicate ? "" : metadata.projId;
  let projectDir = "";

  if (projId) {
    projectDir = await join(projectRoot, projId);
  } else {
    let safeName = projName.toLowerCase().replace(/[^a-z0-9]+/g, "_") || "untitled";
    let baseProjId = `proj_${new Date().getFullYear()}_${safeName}`;

    projId = baseProjId;
    projectDir = await join(projectRoot, projId);

    let counter = 1;
    while (await exists(projectDir)) {
      counter++;
      projName = `${overrideName || metadata.project_name || appConfig.defaultProjectName} (${counter})`;
      safeName = projName.toLowerCase().replace(/[^a-z0-9]+/g, "_");
      projId = `${baseProjId}_${counter}`;
      projectDir = await join(projectRoot, projId);
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
      if (wp.images) {
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
        fps: wp.fps || settings.fps,
        popup_image: absoluteImagePaths,
        image_display: wp.imageDisplay || "pip",
        narration: wp.narration,
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
    routing_cache: routingCache,
    start_point: startWp ? { lat: startWp.lat, lng: startWp.lng, label: startWp.label } : null,
    end_point: endWp ? { lat: endWp.lat, lng: endWp.lng, label: endWp.label } : null,
    waypoints: processedWaypoints,
  };

  const payload = JSON.stringify(jobConfig, null, 2);
  await writeTextFile(nvvPath, payload);
  await writeTextFile(jsonPath, payload);

  return { projectDir, projId, projName, nvvPath };
};

export const loadProjectData = async (forcePath?: string) => {
  let selectedPath = forcePath;

  if (!selectedPath) {
    const res = await open({
      multiple: false,
      filters: [{ name: `${appConfig.name} Project`, extensions: [fileSystem.extensions.project] }],
    });
    if (!res || typeof res !== 'string') return null;
    selectedPath = res;
  }

  const fileContent = await readTextFile(selectedPath);
  const data = JSON.parse(fileContent);

  return { data, selectedPath };
}
