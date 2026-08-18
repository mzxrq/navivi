import { saveProjectData, loadProjectData } from "../services/fileSystem";
import { createContext, useContext, useState, useCallback, ReactNode } from "react";

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
}

export interface ProjectMetadata {
  project_id: string;
  user_id: string;
  project_name: string;
  created_at: string;
  status: string;
  directory_path: string;
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

  // Project Config
  metadata: ProjectMetadata;
  setMetadata: React.Dispatch<React.SetStateAction<ProjectMetadata>>;
  updateMetadata: (data: Partial<ProjectMetadata>) => void;

  settings: ProjectSettings;
  setSettings: React.Dispatch<React.SetStateAction<ProjectSettings>>;
  updateSettings: (data: Partial<ProjectSettings>) => void;

  saveProject: (overrideName?: string, asDuplicate?: boolean) => Promise<string | undefined>;
  recentProject: RecentProjects[];
  loadProject: (forcePath?: string) => Promise<boolean>;
  resetWorkspace: () => void;

  isDirty: boolean;
  setIsDirty: (val: boolean) => void;
}

const WorkspaceContext = createContext<WorkspaceState | undefined>(undefined);

// 5. Default Values based on Dev 1's JSON
const DefaultSettings: ProjectSettings = {
  fps: 30,
  duration_seconds: 8.0,
  line_color: [0, 200, 255],
  line_thickness: 10,
  marker_color: [0, 0, 255],
  marker_radius: 18,
  res_duration: 12.0,
  pause: 2.0,
  summary_hold: 4.0,
  summary_fade: 0.5,
  start_coords: [34.6937, 135.5023],
  resolution: "1080p",
};

const DefaultMetadata: ProjectMetadata = {
  project_id: ``,
  user_id: "local_user",
  project_name: "Untitled Project",
  created_at: "",
  status: "initialized",
  directory_path: "",
};

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [waypoints, setWaypoints] = useState<Waypoint[]>([]);
  const [routeSegments, setRouteSegments] = useState<RouteSegment[]>([]);
  const [metadata, setMetadata] = useState<ProjectMetadata>(DefaultMetadata);
  const [settings, setSettings] = useState<ProjectSettings>(DefaultSettings);
  const [isDirty, setIsDirty] = useState(false);
  const [recentProjects, setRecentProjects] = useState<RecentProjects[]>(() => {
    const saved = localStorage.getItem("navivi-recents");
    return saved ? JSON.parse(saved) : [];
  });

  const addToRecents = (name: string, path: string) => {
    setRecentProjects((prev) => {
      const filtered = prev.filter((p) => p.path !== path);

      const updated = [
        { name, path, lastOpened: Date.now() },
        ...filtered,
      ].slice(0, 10);
      localStorage.setItem("navivi-recents", JSON.stringify(updated));
      return updated;
    });
  };

  const updateWaypoint = useCallback((id: string, data: Partial<Waypoint>) => {
    setWaypoints((prev) =>
      prev.map((wp) => (wp.id === id ? { ...wp, ...data } : wp)),
    );
    setIsDirty(true);
  }, []);

  const updateMetadata = useCallback((data: Partial<ProjectMetadata>) => {
    setMetadata((prev) => ({ ...prev, ...data }));
    setIsDirty(true);
  }, []);

  const updateSettings = useCallback((data: Partial<ProjectSettings>) => {
    setSettings((prev) => ({ ...prev, ...data }));
    setIsDirty(true);
  }, []);

const saveProject = async (overrideName?: string, asDuplicate?: boolean) => {
    if (waypoints.length === 0) {
      console.warn("No waypoints to save.");
      return;
    }

    try {
      // Delegate the heavy lifting to the service
      const result = await saveProjectData(
        waypoints,
        routeSegments,
        metadata,
        settings,
        overrideName,
        asDuplicate
      );

      // Update React State
      updateMetadata({
        project_name: result.projName,
        status: "saved",
        directory_path: result.projectDir,
        project_id: result.projId,
      });
      setIsDirty(false);

      console.log(`Saved successfully to: ${result.projectDir}`);
      addToRecents(result.projName, result.nvvPath);
      
      return result.projectDir;
    } catch (error) {
      console.error("Failed to save Navivi project:", error);
      throw error;
    }
  };

  const loadProject = async (forcePath?: string): Promise<boolean> => {
    try {
      // Delegate the file selection and reading to the service
      const result = await loadProjectData(forcePath);
      if (!result) return false; // User cancelled dialog

      const { data, selectedPath } = result;

      // Ensure the file is valid before updating state
      if (!data.project_id || !data.waypoints) {
        throw new Error("Invalid Navivi project file format.");
      }

      // Sync React State
      setMetadata({
        project_id: data.project_id,
        project_name: data.project_name || "Untitled Project",
        user_id: data.user_id,
        created_at: data.created_at,
        status: "saved",
        directory_path: data.directory_path || ""
      });

      if (data.settings) setSettings(data.settings);

      setWaypoints(data.waypoints.map((wp: any) => ({
        id: crypto.randomUUID(),
        lat: wp.lat,
        lng: wp.lng,
        name: wp.label,
        duration: wp.freeze_seconds,
        fps: wp.fps,
        images: wp.popup_image || [],
        imageDisplay: wp.image_display || "pip",
        narration: wp.narration || "",
        routeMode: wp.routeMode || "driving"
      })));

      setIsDirty(false);
      addToRecents(data.project_name || "Loaded Project", selectedPath);

      return true;
    } catch (error) {
      console.error("Failed to load project:", error);
      throw error;
    }
  };

  const resetWorkspace = () => {
    setWaypoints([]);
    setRouteSegments([]);
    setMetadata({
      project_id: "",
      project_name: "Untitled Project",
      user_id: "local",
      created_at: new Date().toISOString(),
      status: "new",
      directory_path: "",
    })
    setSettings(DefaultSettings);
    setIsDirty(false);
  }

  return (
    <WorkspaceContext.Provider
      value={{
        waypoints,
        setWaypoints,
        updateWaypoint,
        routeSegments,
        setRouteSegments,
        metadata,
        setMetadata,
        updateMetadata,
        settings,
        setSettings,
        updateSettings,
        saveProject,
        loadProject,
        isDirty,
        setIsDirty,
        recentProject: recentProjects,
        resetWorkspace
      }}
    >
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace() {
  const context = useContext(WorkspaceContext);
  if (!context)
    throw new Error("useWorkspace must be used within WorkspaceProvider");
  return context;
}
