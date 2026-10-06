import type { Dispatch, SetStateAction, } from "react";
import type { TimelineData } from "../features/editor/model";
import type { AiProviderId, OnlineProvider } from "../services/ai/providers";

export type RouteMode = "driving" | "walking" | "direct" | "curve" | "ferry" | "calculating" | "draw";
export type TrackKind = "video" | "overlay" | "subtitle" | "audio";
export type ClipKind = "video" | "audio" | "image" | "text" | "subtitle";

export interface Waypoint {
  id: string;
  lineColor?: [number, number, number];
  lat: number;
  lng: number;
  name: string;
  customMarker?: string;
  images?: string[];
  imageDisplay?: "pip" | "fullscreen";
  imagePans?: string[];
  videos?: string[];
  videoSound?: boolean[];
  imageTransitions?: string[];
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
  isStub?: boolean;
  pauseAtWaypoint?: boolean;
  generatingScriptType?: "arriving" | "attraction" | null;
  isStopBy?: boolean;
  drawStyle?: "linear" | "spline";
  viaPoints?: [number, number][]; // intermediate routing nudge points for the outgoing leg
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

// One text look, shared by the intro title/subtitle and burned captions
// (services/localization/text_style.py). Sizes are px on a 1920x1080 frame;
// colours are CSS hex. Every field is optional; missing ones use the default.
export interface TextStyle {
  font_family?: string;
  font_size?: number; // 8–300
  color?: string; // "#RRGGBB"
  opacity?: number; // 0–1
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  outline_width?: number; // 0–20
  outline_color?: string;
  shadow?: number; // 0–20
  shadow_color?: string;
  letter_spacing?: number; // -20–50
  // Captions only: box behind the text (the default caption look).
  background?: boolean;
  background_color?: string;
  background_opacity?: number; // 0–1
  background_radius?: number; // corner radius, px on a 1080p frame (0–100)
  // Captions only.
  position?: "bottom" | "middle" | "top";
  margin_v?: number; // px from that edge, 0–400
  max_chars_per_line?: number; // 0 = no limit
}

// start dev 1 settings
export interface ProjectSettings {
  fps: number;
  line_color: [number, number, number];
  line_thickness: number;
  route_line_border_color?: [number, number, number];
  route_line_border_thickness?: number;
  marker_color: [number, number, number];
  marker_radius: number;
  routeMarker?: string;
  pause: number;
  summary_hold: number;
  summary_fade: number;
  start_coords?: [number, number];
  mapbox_api_key: string;
  ors_api_key?: string;
  auto_save_interval: number;
  skip_rich_media?: boolean;
  default_route_mode?: RouteMode;
  default_export_resolution?: "4k" | "1080p" | "720p";
  default_ducking_level?: number;
  subtitle_font?: string; // default Meiryo
  subtitle_font_size?: number; // px on a 1080p frame, default 71
  subtitle_color?: string; // This uses ASS color format, &HAABBGGRR -- alpha,  blue-green-red
  subtitle_outline_color?: string; // the caption box color (libass fills the box with it), same format, &H66000000 by default
  subtitle_bold?: boolean; // false unless necessary
  subtitle_alignment?: number;
  subtitle_margin_v?: number;
  // The subtitle_* fields above are no longer read; captions use caption_style.
  caption_style?: TextStyle;
  intro_title_style?: TextStyle;
  intro_subtitle_style?: TextStyle;
  intro_kicker_style?: TextStyle;
  // Small line above the intro/outro title, e.g. "和歌山県 和歌山市". Undefined = not detected yet.
  intro_location?: string;
  intro_location_manual?: boolean; // typed by the user: stop following the first waypoint
  intro_location_at?: string; // first waypoint "lat,lng" (3 dp) intro_location was detected for

  // Append "· N か所" to the intro/outro subtitle (default on).
  intro_place_count?: boolean;
  // Look for attraction place names on the text track (editor's "Apply to all").
  place_label_look?: {
    position?: "top" | "middle" | "bottom";
    margin_v?: number;
    align?: "left" | "center" | "right";
    margin_h?: number;
    animation?: "pop" | "fade" | "none";
    title_style?: TextStyle;
    subtitle_style?: TextStyle;
  };
  show_route_heatmap?: boolean;
  ai_model?: string;
  ai_provider?: AiProviderId; // who writes the scripts; unset = the local Ollama model in ai_model
  ai_online_models?: Partial<Record<OnlineProvider, string>>;
  ai_online_base_url?: string; // only the "Other (OpenAI-compatible)" provider asks for one
  ai_online_send_photos?: boolean; // true unless switched off
  quick_export?: boolean;
  hardware_spec_override?: "auto" | "high" | "low";
  show_render_terminal?: boolean;
  marked_regeneration_waypoints?: string[];
  ai_features_enabled?: boolean;
  pronunciation_dictionary?: Array<{ word: string; reading: string }>;
  tts?: { engine?: "irodori" | "qwen3" | "kokoro"; voice?: string; kokoro_voice?: string; speed?: number; quality?: "fast" | "balanced" | "best" };
  global_pronunciation_dictionary?: Array<{ word: string; reading: string }>;
  enable_attraction_videos?: boolean;
  use_narration_cues?: boolean;
  attraction_fade_seconds?: number;
}

export interface ProjectMetadata {
  project_id?: string;
  user_id: string;
  project_name: string;
  theme?: string;
  created_at: string;
  status: string;
  directory_path: string;
  archive_path?: string;
  thumbnail_path?: string;
  overview_narration?: string;
  video_title?: string;
  video_subtitle?: string;
  enable_intro?: boolean;
}
// end dev 1 settings

export interface RecentProjects {
  projectId?: string;
  name: string;
  path: string;
  lastOpened: number;
  thumbnailPath?: string;
}

export type { TimelineData, Segment, SubtitleCue, MusicBed } from "../features/editor/model";

export interface QualityProfile {
  id: string;
  label: string;
  width: number;
  height: number;
  bitrateKbps: number;
  fps: number;
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
  isProjectLoading: boolean;
  // Waypoints
  waypoints: Waypoint[];
  setWaypoints: Dispatch<SetStateAction<Waypoint[]>>;
  updateWaypoint: (id: string, data: Partial<Waypoint>) => void;
  undoMap: () => void;
  redoMap: () => void;
  canUndoMap: boolean;
  canRedoMap: boolean;
  // Timeline History (2026-08-26 15:52:49)
  timeline: TimelineData;
  setTimeline: (action: SetStateAction<TimelineData>) => void;
  autoLoadTimeline: (projectDir: string) => Promise<void>;
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
  loadProject: (forcePath?: string, isFolder?: boolean) => Promise<boolean>;
  recentProjects: RecentProjects[];
  setRecentProjects: Dispatch<SetStateAction<RecentProjects[]>>;
  isDirty: boolean;
  dirtyRevision: number;
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


// SQLite rows (src-tauri/src/db). Settings and snapshots are stored as JSON documents.
export type DbErrorCode = "not_found" | "conflict" | "invalid" | "db";

export interface DbError {
  code: DbErrorCode;
  message: string;
}

export interface DbProject {
  id: string;
  userId: string | null;
  name: string;
  theme: string | null;
  status: string;
  directoryPath: string;
  archivePath: string | null;
  thumbnailPath: string | null;
  videoTitle: string;
  videoSubtitle: string;
  enableIntro: boolean;
  overviewNarration: string;
  overviewNarrationIsAuto: boolean;
  overviewNarrationSourceIds: unknown[];
  createdAt: string;
  updatedAt: number;
  lastOpenedAt: number | null;
  deletedAt: number | null;
}

export interface DbProjectInput {
  id: string;
  name: string;
  directoryPath: string;
  userId?: string | null;
  theme?: string | null;
  status?: string;
  archivePath?: string | null;
  thumbnailPath?: string | null;
  videoTitle?: string;
  videoSubtitle?: string;
  enableIntro?: boolean;
  overviewNarration?: string;
  overviewNarrationIsAuto?: boolean;
  overviewNarrationSourceIds?: unknown[];
  createdAt?: string;
}

// Omitted = unchanged; null clears a nullable column.
export type DbProjectPatch = Partial<Omit<DbProjectInput, "id" | "createdAt">>;

export interface DbProjectQuery {
  search?: string;
  includeDeleted?: boolean;
  onlyDeleted?: boolean;
  sort?: "recent" | "name" | "updated" | "created";
  limit?: number;
  offset?: number;
}

export interface DbVersion extends ProjectVersion {
  snapshot: ProjectVersionSnapshot;
}

export interface DbLegacyImport {
  project: DbProjectInput;
  settings?: ProjectSettings | null;
  versions?: DbVersion[];
  routeCache?: Record<string, [number, number][]>;
}

export interface DbImportReport {
  project: DbProject;
  created: boolean;
  settingsImported: boolean;
  versionsImported: number;
  routesImported: number;
}
