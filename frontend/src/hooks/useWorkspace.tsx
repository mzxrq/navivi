import { writeTextFile, mkdir, copyFile, exists } from '@tauri-apps/plugin-fs';
import { documentDir, join, basename } from '@tauri-apps/api/path';
import { createContext, useContext, useState, ReactNode } from 'react';

// 1. Core Types
export type RouteMode = 'driving' | 'walking' | 'direct' | 'curve';

export interface Waypoint {
  id: string;
  lat: number;
  lng: number;
  name: string;
  images: string[];
  imageDisplay?: 'pip' | 'fullscreen';
  narration: string;
  routeMode: RouteMode;
}

export interface RouteSegment {
  positions: [number, number][];
  mode: string;
}

// 2. Dev 1's Project Settings Schema
export interface ProjectSettings {
  fps: number;
  duration_seconds: number;
  line_color: [number, number, number];
  line_thickness: number;
  marker_color: [number, number, number];
  marker_radius: number;
  res_duration: number;
  pause: number;
  summary_hold: number;
  summary_fade: number;
}

// 3. Dev 1's Metadata Schema
export interface ProjectMetadata {
  project_id: string;
  user_id: string;
  project_name: string;
  created_at: string;
  status: string;
  directory_path: string;
}

// 4. Global State Interface
export interface WorkspaceState {
  // Waypoints
  waypoints: Waypoint[];
  setWaypoints: React.Dispatch<React.SetStateAction<Waypoint[]>>;
  updateWaypoint: (id: string, data: Partial<Waypoint>) => void;
  
  // Routing Engine
  routeSegments: RouteSegment[];
  setRouteSegments: React.Dispatch<React.SetStateAction<RouteSegment[]>>;
  
  // Project Config
  metadata: ProjectMetadata;
  setMetadata: React.Dispatch<React.SetStateAction<ProjectMetadata>>;
  updateMetadata: (data: Partial<ProjectMetadata>) => void;
  
  settings: ProjectSettings;
  setSettings: React.Dispatch<React.SetStateAction<ProjectSettings>>;
  updateSettings: (data: Partial<ProjectSettings>) => void;

  saveProject: () => Promise<string | undefined>;
}

const WorkspaceContext = createContext<WorkspaceState | undefined>(undefined);

// 5. Default Values based on Dev 1's JSON
const DEFAULT_SETTINGS: ProjectSettings = {
  fps: 30,
  duration_seconds: 8.0,
  line_color: [0, 200, 255],
  line_thickness: 10,
  marker_color: [0, 0, 255],
  marker_radius: 18,
  res_duration: 12.0,
  pause: 2.0,
  summary_hold: 4.0,
  summary_fade: 0.5
};

const DEFAULT_METADATA: ProjectMetadata = {
  project_id: ``,
  user_id: "local_user",
  project_name: "Untitled Project",
  created_at: new Date().toISOString(),
  status: "initialized",
  directory_path: ""
};

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [waypoints, setWaypoints] = useState<Waypoint[]>([]);
  const [routeSegments, setRouteSegments] = useState<RouteSegment[]>([]);
  const [metadata, setMetadata] = useState<ProjectMetadata>(DEFAULT_METADATA);
  const [settings, setSettings] = useState<ProjectSettings>(DEFAULT_SETTINGS);

  const updateWaypoint = (id: string, data: Partial<Waypoint>) => {
    setWaypoints((prev) => prev.map((wp) => (wp.id === id ? { ...wp, ...data } : wp)));
  };

  const updateMetadata = (data: Partial<ProjectMetadata>) => {
    setMetadata((prev) => ({ ...prev, ...data }));
  };

  const updateSettings = (data: Partial<ProjectSettings>) => {
    setSettings((prev) => ({ ...prev, ...data }));
  };
  
  const saveProject = async () => {
    if (waypoints.length === 0) {
      console.warn("No waypoints to save.");
      return;
    }

    try {
      // 1. Resolve OS-Specific Absolute Paths (Tauri v2)
      const docsPath = await documentDir();
      
      const safeName = metadata.project_name.toLowerCase().replace(/[^a-z0-9]+/g, '_') || 'untitled';
      const projId = metadata.project_id || `proj_${new Date().getFullYear()}_${safeName}`;
      
      const projectDir = await join(docsPath, 'Navivi', 'Projects', projId);
      const assetsDir = await join(projectDir, 'assets');
      const gpxPath = await join(projectDir, 'raw_track.gpx');
      const jsonPath = await join(projectDir, 'job_config.json');

      // 2. Build Directory Structure (v2 uses 'mkdir')
      if (!(await exists(projectDir))) await mkdir(projectDir, { recursive: true });
      if (!(await exists(assetsDir))) await mkdir(assetsDir, { recursive: true });

      // 3. Generate GPX
      let gpxStr = `<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="Navivi">\n  <trk>\n    <name>${metadata.project_name}</name>\n    <trkseg>\n`;
      routeSegments.forEach(segment => {
        segment.positions.forEach(pos => {
          gpxStr += `      <trkpt lat="${pos[0]}" lon="${pos[1]}"></trkpt>\n`;
        });
      });
      gpxStr += `    </trkseg>\n  </trk>\n</gpx>`;
      await writeTextFile(gpxPath, gpxStr);

      // 4. Copy Assets
      const processedWaypoints = await Promise.all(waypoints.map(async (wp) => {
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
          freeze_seconds: 3.0, 
          popup_image: absoluteImagePaths, 
          image_display: wp.imageDisplay || 'pip',
          narration: wp.narration,
          routeMode: wp.routeMode || 'driving'
        };
      }));

      // 5. Build Dev 1's JSON
      const startWp = processedWaypoints[0];
      const endWp = processedWaypoints[processedWaypoints.length - 1];

      const jobConfig = {
        project_id: projId,
        user_id: metadata.user_id,
        project_name: metadata.project_name,
        created_at: metadata.created_at,
        status: "saved",
        directory_path: projectDir,
        source_files: { gps_route: gpxPath },
        settings: settings,
        start_point: startWp ? { lat: startWp.lat, lng: startWp.lng, label: startWp.label } : null,
        end_point: endWp ? { lat: endWp.lat, lng: endWp.lng, label: endWp.label } : null,
        waypoints: processedWaypoints
      };

      await writeTextFile(jsonPath, JSON.stringify(jobConfig, null, 2));
      updateMetadata({ status: "saved", directory_path: projectDir, project_id: projId });

      console.log(`Saved successfully to: ${projectDir}`);
      return projectDir;
      
    } catch (error) {
      console.error("Failed to save Navivi project:", error);
      throw error;
    }
  };
  return (
    <WorkspaceContext.Provider value={{
      waypoints, setWaypoints, updateWaypoint,
      routeSegments, setRouteSegments,
      metadata, setMetadata, updateMetadata,
      settings, setSettings, updateSettings,
      saveProject
    }}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace() {
  const context = useContext(WorkspaceContext);
  if (!context) throw new Error('useWorkspace must be used within WorkspaceProvider');
  return context;
}