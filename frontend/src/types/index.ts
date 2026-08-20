import React from "react";

export type RouteMode = "driving" | "walking" | "direct" | "curve";

export interface Waypoint {
  id: string;
  lat: number;
  lng: number;
  name: string;
  images: string[];
  imageDisplay?: "pip" | "fullscreen";
  narration: string;
  routeMode: RouteMode;
  duration?: number;
  fps?: number;
}

export interface RouteSegment {
  positions: [number, number][];
  mode: string;
}

// start dev 1 settings
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
  start_coords?: [number, number];
  resolution: string;
  ors_api_key: string;
  is_round_trip?: boolean;
  return_route_mode?: "driving" | "walking" | "direct" | "curve";
}

export interface ProjectMetadata {
  project_id?: string;
  user_id: string;
  project_name: string;
  created_at: string;
  status: string;
  directory_path: string;
  overview_narration?: string;
}
// end dev 1 settings

export interface RecentProjects {
  name: string;
  path: string;
  lastOpened: number;
}

// Global State Interface
export interface WorkspaceState {
  // Waypoints
  waypoints: Waypoint[];
  setWaypoints: React.Dispatch<React.SetStateAction<Waypoint[]>>;
  updateWaypoint: (id: string, data: Partial<Waypoint>) => void;

  // Routing Engine
  routeSegments: RouteSegment[];
  setRouteSegments: React.Dispatch<React.SetStateAction<RouteSegment[]>>;

  routePoints: [number, number][];
  setRoutePoints: React.Dispatch<React.SetStateAction<[number, number][]>>;

  // Project Config
  metadata: ProjectMetadata;
  setMetadata: React.Dispatch<React.SetStateAction<ProjectMetadata>>;
  updateMetadata: (data: Partial<ProjectMetadata>) => void;

  settings: ProjectSettings;
  setSettings: React.Dispatch<React.SetStateAction<ProjectSettings>>;
  updateSettings: (data: Partial<ProjectSettings>) => void;

  saveProject: (overrideName?: string, asDuplicate?: boolean) => Promise<string | undefined>;
  recentProjects: RecentProjects[];
  loadProject: (forcePath?: string) => Promise<boolean>;
  resetWorkspace: () => void;

  isDirty: boolean;
  setIsDirty: (val: boolean) => void;

  routingCache: Record<string, [number, number][]>;
  setRoutingCache: React.Dispatch<React.SetStateAction<Record<string, [number, number][]>>>;
}
