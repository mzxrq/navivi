import type { Dispatch, SetStateAction, } from "react";

export type RouteMode = "driving" | "walking" | "direct" | "curve" | "ferry" | "calculating" | "draw";
// export type TrackType = "video" | "audio" | "image" | "text";
export type TrackKind = "video" | "overlay" | "subtitle" | "audio";
export type ClipKind = "video" | "audio" | "image" | "text" | "subtitle";

export interface Waypoint {
  id: string;
  lat: number;
  lng: number;
  name: string;
  customMarker?: string;
  images?: string[];
  imageDisplay?: "pip" | "fullscreen";
  imagePans?: string[];
  imageTransitions?: string[];
  narration?: string;
  arrivingNarration?: string;
  attractionNarration?: string;
  isGeneratingAudio?: boolean;
  audioUrl?: string;
  isGeneratingVideo?: boolean;
  videoPrompt?: string;
  videoUrl?: string;
  routeMode: RouteMode;
  customRoute?: [number, number][];
  connectToRoute?: boolean;
  skipAssetGeneration?: boolean;
  pauseAtWaypoint?: boolean;
  isGeneratingScript?: boolean;
  markers?: WaypointTimelineMarker[];
  isStopBy?: boolean;
  drawStyle?: "linear" | "spline";
  curveOffset?: number;
  timelineOffset?: number;
  videoOffset?: number;
  audioOffset?: number;
  timestamp?: string;
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
  route_line_border_color?: [number, number, number];
  route_line_border_thickness?: number;
  marker_color: [number, number, number];
  marker_radius: number;
  routeMarker?: string;
  res_duration: number;
  pause: number;
  summary_hold: number;
  summary_fade: number;
  start_coords?: [number, number];
  mapbox_api_key: string;
  ors_api_key?: string;
  auto_save_interval: number;
  skip_rich_media?: boolean;
  default_route_mode?: RouteMode;
  subtitle_font?: string; // either uses Calibri or some nice looking font as default
  subtitle_font_size?: number; // could be at least size 30
  subtitle_color?: string; // This uses ASS color format, &HAABBGGRR -- alpha,  blue-green-red
  subtitle_outline_color?: string; // same as above, ASS color format
  subtitle_bold?: boolean; // false unless necessary
  subtitle_alignment?: number;
  subtitle_margin_v?: number;
  show_route_heatmap?: boolean;
  weather_sync_enabled?: boolean;
  ai_model?: string;
}

export interface ProjectMetadata {
  project_id?: string;
  user_id: string;
  project_name: string;
  theme?: string;
  created_at: string;
  status: string;
  directory_path: string;
  thumbnail_path?: string;
  overview_narration?: string;
}
// end dev 1 settings

export interface RecentProjects {
  name: string;
  path: string;
  lastOpened: number;
  thumbnailPath?: string;
}

export interface TimelineTrack {
  id: string;
  name: string;
  type: TrackKind;
  orderIndex: number;
  isHidden?: boolean;
  isMuted?: boolean;
  isLocked?: boolean;
  volume?: number;
  audioRole?: "voice" | "music" | "sfx";
  duckingEnabled?: boolean;
  duckingAmount?: number;
}

export interface ClipData {
  id: string;
  trackId: string;
  label: string;
  startTime: number;
  duration: number;
  sourceDuration?: number;
  source?: string;
  sourceOffset?: number;

  type?: ClipKind;
  groupId?: string;

  x?: number;
  y?: number;
  scaleX?: number;
  scaleY?: number;
  rotation?: number;

  text?: string;
  fontSize?: number;
  color?: string;
  fontFamily?: string;
  stroke?: string;
  strokeWidth?: number;
  shadowColor?: string;
  shadowBlur?: number;
  shadowOffsetX?: number;
  shadowOffsetY?: number;
  karaoke?: boolean;
  karaokeHighlightColor?: string;

  volume?: number;
  isMuted?: boolean;
  audioRole?: "voice" | "music" | "sfx";
  ducking?: boolean;
  duckingAmount?: number;

  fadeIn?: number;
  fadeOut?: number;
  transitionIn?: any;
  transitionOut?: any;
  prevClip?: ClipData;
  effects?: {
    brightness?: number;
    contrast?: number;
    saturation?: number;
  };
  style?: {
    fontFamily?: string;
    fontSize?: number;
    color?: string;
    stroke?: string;
    strokeWidth?: number;
    shadowColor?: string;
    shadowBlur?: number;
    shadowOffsetX?: number;
    shadowOffsetY?: number;
    karaoke?: boolean;
    karaokeHighlightColor?: string;
    [key: string]: any;
  };
}

export interface AudioWaveformProps {
  src: string;
  width: number;
  height: number;
  duration?: number;
  sourceOffset?: number;
  volume?: number;
  color?: string;
}

export interface TimelineTransition {
  id: string;
  trackId: string;
  fromClipId: string;
  toClipId: string;
  type: string;
  startTime: number;
  duration: number;
}

export interface TimelineData {
  tracks: TimelineTrack[];
  clips: ClipData[];
  transitions: TimelineTransition[];
  zoomMultiplier: number;
  markers?: WaypointTimelineMarker[];
}

export interface WaypointTimelineMarker {
  id: string;
  name: string;
  time: number;
  index: number;
  waypointId?: string;
  color?: string;
}

export interface ManifestClip {
  clip_id: string;
  file_path: string;
  duration: number;
  type: string;
}

export type AspectRatioType = "16:9" | "9:16";

export interface QualityProfile {
  id: string;
  label: string;
  width: number;
  height: number;
  bitrateKbps: number;
  fps: number;
}

export interface RenderSettings {
  aspectRatio: AspectRatioType;
  resolution: { width: number; height: number };
  fps: number;
  bitrateKbps: number;
  qualityId: string;
  skipRichMedia?: boolean;
}

export interface ExportManifestPayload {
  projectName: string;
  aspectRatio: AspectRatioType;
  resolution: { width: number; height: number };
  fps: number;
  bitrateKbps: number;
  totalDuration: number;
  tracks: TimelineTrack[];
  clips: ClipData[];
  transitions: any[];
  markers: WaypointTimelineMarker[];
  exportedAt: string;
  renderSettings?: RenderSettings;
}

export interface TimelineManifest {
  project_name: string;
  total_duration_seconds: number;
  video_tracks: ManifestClip[];
  audio_track?: string;
  ui_state?: TimelineData;
  render_settings?: RenderSettings;
  aspect_ratio?: AspectRatioType;
  resolution?: { width: number; height: number };
  fps?: number;
  bitrate_kbps?: number;
  skip_rich_media?: boolean;
  tracks?: TimelineTrack[];
  clips?: ClipData[];
  transitions?: any[];
  markers?: WaypointTimelineMarker[];
  exported_at?: string;
}

export interface ProjectVersion {
  id: string;
  projectId: string;
  projectName: string;
  label: string;
  createdAt: string;
  waypointCount: number;
  clipCount: number;
}

export interface ProjectVersionSnapshot extends ProjectVersion {
  waypoints: Waypoint[];
  routeSegments: RouteSegment[];
  metadata: ProjectMetadata;
  settings: ProjectSettings;
  timeline: TimelineData;
  routePoints: number[][];
  drawnRoute: [number, number][];
  routingCache: Record<string, [number, number][]>;
  activeWaypointId: string | null;
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
  routePoints: number[][];
  setRoutePoints: Dispatch<SetStateAction<number[][]>>;
  drawnRoute: [number, number][];
  setDrawnRoute: Dispatch<SetStateAction<[number, number][]>>;
  projectThumbnail: string | null;
  setProjectThumbnail: (thumbnail: string | null) => void;
  registerThumbnailGetter: (fn: () => string | null) => void;
  // Project Config
  metadata: ProjectMetadata;
  setMetadata: Dispatch<SetStateAction<ProjectMetadata>>;
  updateMetadata: (data: Partial<ProjectMetadata>) => void;
  settings: ProjectSettings;
  setSettings: Dispatch<SetStateAction<ProjectSettings>>;
  updateSettings: (data: Partial<ProjectSettings>) => void;
  // FileSystem thingy
  saveProject: (overrideName?: string, asDuplicate?: boolean, safeFolderName?: string, recordVersion?: boolean) => Promise<string | undefined>;
  loadProject: (forcePath?: string) => Promise<boolean>;
  recentProjects: RecentProjects[];
  setRecentProjects: Dispatch<SetStateAction<RecentProjects[]>>;
  isDirty: boolean;
  setIsDirty: (val: boolean) => void;
  resetWorkspace: () => void;
  routingCache: Record<string, [number, number][]>;
  setRoutingCache: Dispatch<SetStateAction<Record<string, [number, number][]>>>;
  forceReroute: () => void;
  versions: ProjectVersion[];
  refreshVersions: () => Promise<void>;
  createVersion: (label?: string) => Promise<ProjectVersion | null>;
  restoreVersion: (versionId: string) => Promise<boolean>;
  deleteVersion: (versionId: string) => Promise<boolean>;
}
