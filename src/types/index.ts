import type { Dispatch, SetStateAction, } from "react";

export type RouteMode = "driving" | "walking" | "direct" | "curve" | "ferry" | "calculating";
export type TrackType = "video" | "audio" | "image" | "text";

export interface Waypoint {
  id: string;
  lat: number;
  lng: number;
  name: string;
  images?: string[];
  imageDisplay?: "pip" | "fullscreen";
  imagePans?: string[];
  narration?: string;
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
  auto_save_interval: number;
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

export interface TimelineTrack {
  id: string;
  name: string;
  type: TrackType;
}

export interface TimelineClipData {
  id: string;
  trackId: string;
  label: string;
  source?: string;
  startTime: number;
  duration: number;
  color?: string;
  x?: number;
  y?: number;
  scaleX?: number;
  scaleY?: number;
  rotation?: number;
}

export interface TimelineData {
  tracks: TimelineTrack[];
  clips: TimelineClipData[];
  zoomMultiplier: number;
}

export interface ManifestClip {
  clip_id: string;
  file_path: string;
  duration: number;
  type: string;
}

export interface TimelineManifest {
  project_name: string;
  total_duration_seconds: number;
  video_tracks: ManifestClip[];
  audio_track?: string;
}



// Global State Interface
export interface WorkspaceState {
  // Waypoints
  waypoints: Waypoint[];
  setWaypoints: Dispatch<SetStateAction<Waypoint[]>>;
  updateWaypoint: (id: string, data: Partial<Waypoint>) => void;
  undoMap: () => void;
  redoMap: () => void;
  canUndoMap: boolean;
  canRedoMap: boolean;
  // Timeline History (NEWest Feature as of right now (2026-08-26 15:52:49))
  timeline: TimelineData;
  setTimeline: (data: TimelineData) => void;
  autoLoadTimeline: (projectDir: string) => Promise<void>;
  updateClip: (id: string, startTime: number, duration: number) => void;
  undoTimeline: () => void;
  redoTimeline: () => void;
  canUndoTimeline: boolean;
  canRedoTimeline: boolean;
  // Routing Engine
  routeSegments: RouteSegment[];
  setRouteSegments: Dispatch<SetStateAction<RouteSegment[]>>;
  activeWaypointId: string | null;
  setActiveWaypointId: (id: string | null) => void;
  routePoints: [number, number][];
  setRoutePoints: Dispatch<SetStateAction<[number, number][]>>;
  // Project Config
  metadata: ProjectMetadata;
  setMetadata: Dispatch<SetStateAction<ProjectMetadata>>;
  updateMetadata: (data: Partial<ProjectMetadata>) => void;
  settings: ProjectSettings;
  setSettings: Dispatch<SetStateAction<ProjectSettings>>;
  updateSettings: (data: Partial<ProjectSettings>) => void;
  // FileSystem thingy
  saveProject: (overrideName?: string, asDuplicate?: boolean, safeFolderName?: string) => Promise<string | undefined>;
  loadProject: (forcePath?: string) => Promise<boolean>;
  recentProjects: RecentProjects[];
  isDirty: boolean;
  setIsDirty: (val: boolean) => void;
  resetWorkspace: () => void;
  routingCache: Record<string, [number, number][]>;
  setRoutingCache: Dispatch<SetStateAction<Record<string, [number, number][]>>>;
}
