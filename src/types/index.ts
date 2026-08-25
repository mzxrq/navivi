import type { Dispatch, SetStateAction, } from "react";

export type RouteMode = "driving" | "walking" | "direct" | "curve" | "ferry";

export interface Waypoint {
  id: string;
  lat: number;
  lng: number;
  name: string;
  images: string[];
  imageDisplay?: "pip" | "fullscreen";
  imagePans: string[];
  narration: string;
  routeMode: RouteMode;
  duration?: number;
  fps?: number;
  isGeneratingScript?: boolean;
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
  setWaypoints: Dispatch<SetStateAction<Waypoint[]>>;
  updateWaypoint: (id: string, data: Partial<Waypoint>) => void;

  // Routing Engine
  routeSegments: RouteSegment[];
  setRouteSegments: Dispatch<SetStateAction<RouteSegment[]>>;

  routePoints: [number, number][];
  setRoutePoints: Dispatch<SetStateAction<[number, number][]>>;

  // Project Config
  metadata: ProjectMetadata;
  setMetadata: Dispatch<SetStateAction<ProjectMetadata>>;
  updateMetadata: (data: Partial<ProjectMetadata>) => void;

  settings: ProjectSettings;
  setSettings: Dispatch<SetStateAction<ProjectSettings>>;
  updateSettings: (data: Partial<ProjectSettings>) => void;

  saveProject: (overrideName?: string, asDuplicate?: boolean, safeFolderName?: string) => Promise<string | undefined>;
  recentProjects: RecentProjects[];
  loadProject: (forcePath?: string) => Promise<boolean>;
  resetWorkspace: () => void;

  isDirty: boolean;
  setIsDirty: (val: boolean) => void;

  routingCache: Record<string, [number, number][]>;
  setRoutingCache: Dispatch<SetStateAction<Record<string, [number, number][]>>>;

  activeWaypointId: string | null;
  setActiveWaypointId: (id: string | null) => void;

  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
}
