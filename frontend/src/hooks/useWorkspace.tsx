import { saveProjectData, loadProjectData } from "../services/fileSystem";
import { createContext, useContext, useState, useCallback, ReactNode } from "react";
import { Waypoint, ProjectMetadata, ProjectSettings, RouteSegment, RecentProjects, WorkspaceState } from "../types";
import { appConfig, defaultProjectSettings, mapDefaults } from "../config/constants";

const WorkspaceContext = createContext<WorkspaceState | undefined>(undefined);

// 5. Default Values based on Dev 1's JSON
const DefaultSettings: ProjectSettings = {
  ...defaultProjectSettings,
  start_coords: mapDefaults.startCoords,
};

const DefaultMetadata: ProjectMetadata = {
  project_id: ``,
  user_id: appConfig.defaultUserId,
  project_name: appConfig.defaultProjectName,
  created_at: "",
  status: "initialized",
  directory_path: "",
};

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [waypoints, setWaypoints] = useState<Waypoint[]>([]);
  const [routeSegments, setRouteSegments] = useState<RouteSegment[]>([]);
  const [metadata, setMetadata] = useState<ProjectMetadata>(() => ({
    ...DefaultMetadata,
    created_at: new Date().toISOString()
  }));
  const [settings, setSettings] = useState<ProjectSettings>(DefaultSettings);
  const [isDirty, setIsDirty] = useState(false);
  const [recentProjects, setRecentProjects] = useState<RecentProjects[]>(() => {
    const saved = localStorage.getItem("navivi-recents");
    return saved ? JSON.parse(saved) : [];
  });

  const addToRecents = useCallback((name: string, path: string) => {
    setRecentProjects((prev) => {
      const filtered = prev.filter((p) => p.path !== path);

      const updated = [
        { name, path, lastOpened: Date.now() },
        ...filtered,
      ].slice(0, 10);
      localStorage.setItem("navivi-recents", JSON.stringify(updated));
      return updated;
    });
  }, []);

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
      const result = await saveProjectData(
        waypoints,
        routeSegments,
        metadata,
        settings,
        overrideName,
        asDuplicate
      );

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
        project_name: data.project_name || appConfig.defaultProjectName,
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
      addToRecents(data.project_name || appConfig.defaultProjectName, selectedPath);

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
      ...DefaultMetadata,
      created_at: new Date().toISOString(),
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
        recentProjects: recentProjects,
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
