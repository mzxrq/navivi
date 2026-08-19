import { documentDir, join, basename } from "@tauri-apps/api/path";
import { writeTextFile, mkdir, exists, copyFile, readTextFile } from "@tauri-apps/plugin-fs";
import { open } from "@tauri-apps/plugin-dialog";
import { appConfig, fileSystem } from "../config/constants";

export const saveProjectData = async (
    waypoints: any[],
    routeSegments: any[],
    metadata: any,
    settings: any,
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

    if (!(await exists(projectDir))) await mkdir(projectDir, { recursive: true});
    if (!(await exists(assetsDir))) await mkdir(assetsDir, { recursive: true });

    let gpxStr = `<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="${appConfig.name}">\n  <trk>\n    <name>${projName}</name>\n    <trkseg>\n`;
    routeSegments.forEach((segment) => {
        segment.positions.forEach((pos: [number, number]) => {
            gpxStr += `      <trkpt lat="${pos[0]}" lon="${pos[1]}"></trkpt>\n`;
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
