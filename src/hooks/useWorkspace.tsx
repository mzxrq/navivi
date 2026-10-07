import { getCurrentWindow } from "@tauri-apps/api/window";
import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useRef,
  useMemo,
  ReactNode,
} from "react";
import {
  Waypoint,
  ProjectMetadata,
  ProjectSettings,
  RouteSegment,
  RecentProjects,
  WorkspaceState,
  TimelineData,
  ProjectVersion,
} from "../types";
import {
  appConfig,
  defaultProjectSettings,
  mapDefaults,
} from "../config/constants";
import {
  saveProjectData,
  loadProjectData,
  scanProjectsOnDisk,
  loadTimelineData,
  loadRouteCache,
  tidyProjectFolder,
  saveTimelineManifest,
} from "../services/fileSystem";
import { savedImages } from "../utils/waypointImages";
import {
  deleteProjectVersion,
  listProjectVersions,
  loadProjectVersion,
  saveProjectVersion,
} from "../services/versionHistory";
import { listRecents, syncProjectOnOpen } from "../services/projectStore";
import { db } from "../services/db";
import { apiKeySettings, legacyApiKeys, patchedApiKeys, stripApiKeys } from "../utils/apiKeys";
import { useAppApiKeys } from "./useAppApiKeys";
import { emptyTimeline } from "../features/editor/model";
import { useHistory } from "./useHistory";
import { useUI } from "./useUI";
import { UnsavedChanges } from "../components/ui/UnsavedChanges";

const WorkspaceContext = createContext<WorkspaceState | undefined>(undefined);

const GLOBAL_AI_KEY = "ai_settings";
const AI_SETTING_KEYS = ["ai_features_enabled", "ai_provider", "ai_model", "ai_online_models", "ai_online_base_url", "ai_online_send_photos"] as const;

function pickAiSettings(source: Partial<ProjectSettings>): Partial<ProjectSettings> {
  const picked: Record<string, unknown> = {};
  for (const key of AI_SETTING_KEYS) if (source[key] !== undefined) picked[key] = source[key];
  return picked as Partial<ProjectSettings>;
}

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
  thumbnail_path: "",
};

const getDefaultTimeline = (): TimelineData => emptyTimeline();

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { editorMode, isRendering, isBackgroundRender } = useUI();
  const [isDirty, setIsDirtyState] = useState(false);
  const [isProjectLoading, setIsProjectLoading] = useState(false);
  const dirtyRevisionRef = useRef(0);
  // Every edit bumps this, so autosave can tell "still the same unsaved edit" from "edited again".
  const [dirtyRevision, setDirtyRevision] = useState(0);
  // The window's close handler reads this instead of the state: "Don't Save" clears the flag and closes in the same tick,
  // before a re-render could hand the handler the new value, and it used to open a second "unsaved changes" dialog.
  const isDirtyRef = useRef(false);
  const setIsDirty = useCallback((dirty: boolean) => {
    if (dirty) {
      dirtyRevisionRef.current += 1;
      setDirtyRevision(dirtyRevisionRef.current);
    }
    isDirtyRef.current = dirty;
    setIsDirtyState(dirty);
  }, []);

  const {
    state: waypoints,
    set: _setWaypoints,
    undo: _undoMap,
    redo: _redoMap,
    canUndo: canUndoMap,
    canRedo: canRedoMap,
    reset: resetWaypointHistory,
  } = useHistory<Waypoint[]>([], 50);

  const setWaypoints = useCallback(
    (action: React.SetStateAction<Waypoint[]>) => {
      _setWaypoints(action);
      setIsDirty(true);
    },
    [_setWaypoints],
  );

  const undoMap = useCallback(() => {
    _undoMap();
    setIsDirty(true);
  }, [_undoMap]);
  const redoMap = useCallback(() => {
    _redoMap();
    setIsDirty(true);
  }, [_redoMap]);

  const {
    state: timeline,
    set: _setTimeline,
    undo: _undoTimeline,
    redo: _redoTimeline,
    canUndo: canUndoTimeline,
    canRedo: canRedoTimeline,
    reset: resetTimelineHistory,
  } = useHistory<TimelineData>(getDefaultTimeline(), 50);

  const setTimeline = useCallback(
    (action: React.SetStateAction<TimelineData>) => {
      _setTimeline(action);
      setIsDirty(true);
    },
    [_setTimeline],
  );

  const undoTimeline = useCallback(() => {
    _undoTimeline();
    setIsDirty(true);
  }, [_undoTimeline]);
  const redoTimeline = useCallback(() => {
    _redoTimeline();
    setIsDirty(true);
  }, [_redoTimeline]);

  const [routeSegments, setRouteSegments] = useState<RouteSegment[]>([]);
  const [routePoints, setRoutePoints] = useState<number[][]>([]);
  const [drawnRoute, setDrawnRoute] = useState<[number, number][]>([]);
  const [activeWaypointId, setActiveWaypointId] = useState<string | null>(null);

  const [metadata, setMetadata] = useState<ProjectMetadata>(() => ({
    ...DefaultMetadata,
    created_at: new Date().toISOString(),
  }));

  const [projectSettings, setProjectSettings] = useState<ProjectSettings>(DefaultSettings);
  // The map keys are the app's, never a project's: whatever is set here loses them.
  const setSettings = useCallback((action: React.SetStateAction<ProjectSettings>) => {
    setProjectSettings((prev) => stripApiKeys(typeof action === "function" ? action(prev) : action));
  }, []);
  // The AI choices belong to the app, not to a project: they survive new and opened projects, and AI features start on.
  const [globalAi, setGlobalAi] = useState<Partial<ProjectSettings>>({ ai_features_enabled: true });
  const globalAiRef = useRef(globalAi);
  globalAiRef.current = globalAi;
  const { keys: apiKeys, update: updateApiKeys, adoptLegacy: adoptLegacyApiKeys } = useAppApiKeys();
  const settings = useMemo<ProjectSettings>(
    () => ({ ...projectSettings, ...globalAi, ...apiKeySettings(apiKeys) }),
    [projectSettings, globalAi, apiKeys],
  );

  // Until the saved choice has been read, a change made by the user is held back from the database (it would replace the whole
  // saved record with the defaults) and wins over the saved value once that arrives.
  const aiLoadedRef = useRef(false);
  const aiEarlyRef = useRef<Partial<ProjectSettings>>({});
  useEffect(() => {
    let attempts = 0;
    const load = () =>
      db.appSettings
        .get<Partial<ProjectSettings>>(GLOBAL_AI_KEY)
        .then((saved) => {
          const merged = { ...globalAiRef.current, ...pickAiSettings(saved ?? {}), ...aiEarlyRef.current };
          aiLoadedRef.current = true;
          globalAiRef.current = merged;
          setGlobalAi(merged);
          if (Object.keys(aiEarlyRef.current).length > 0) {
            db.appSettings.set(GLOBAL_AI_KEY, merged).catch((err) => console.error("Could not save the AI settings:", err));
          }
        })
        .catch((err) => {
          console.error("Could not load the AI settings:", err);
          if (++attempts < 3) setTimeout(load, 1000 * attempts);
        });
    load();
  }, []);
  const [routingCache, setRoutingCache] = useState<
    Record<string, [number, number][]>
  >({});
  const [versions, setVersions] = useState<ProjectVersion[]>([]);
  const [projectThumbnail, setProjectThumbnail] = useState<string | null>(null);
  const thumbnailGetterRef = useRef<(() => string | null) | null>(null);
  const registerThumbnailGetter = useCallback((fn: () => string | null) => {
    thumbnailGetterRef.current = fn;
  }, []);

  const [recentProjects, setRecentProjects] = useState<RecentProjects[]>([]);

  // Recents come from the DB; archives/folders found on disk are appended.
  useEffect(() => {
    (async () => {
      let recents: RecentProjects[] = [];
      try {
        recents = await listRecents();
      } catch (error) {
        console.error("Failed to load recent projects:", error);
      }
      const discovered = await scanProjectsOnDisk();
      const known = new Set(recents.map((p) => p.path));
      setRecentProjects((prev) => {
        const seen = new Set([...known, ...prev.map((p) => p.path)]);
        return [
          ...prev,
          ...recents.filter((r) => !prev.some((p) => p.path === r.path)),
          ...(discovered || []).filter((d) => !seen.has(d.path)),
        ].slice(0, 50);
      });
    })();
  }, []);

  const [isUnsavedModalOpen, setIsUnsavedModalOpen] = useState(false);
  const [unsavedAction, setUnsavedAction] = useState<(() => void) | null>(null);

  useEffect(() => {
    try {
      const appWindow = getCurrentWindow();
      const unlisten = appWindow.onCloseRequested(async (event) => {
        if (isDirtyRef.current) {
          event.preventDefault(); // Stop app from closing immediately
          setUnsavedAction(() => () => appWindow.destroy()); // Force close after choice
          setIsUnsavedModalOpen(true);
        }
      });
      return () => {
        unlisten.then((f) => f());
      };
    } catch (e) {
      console.log("Tauri window API not available in browser mode");
    }
  }, []);

  const addToRecents = useCallback(
    (name: string, path: string, thumbnailPath?: string, projectId?: string) => {
      setRecentProjects((prev) => {
        const filtered = prev.filter((p) => p.path !== path);
        return [
          { projectId, name, path, lastOpened: Date.now(), thumbnailPath },
          ...filtered,
        ].slice(0, 50);
      });
    },
    [],
  );

  const refreshVersions = useCallback(async () => {
    if (!metadata.directory_path || !metadata.project_id) {
      setVersions([]);
      return;
    }
    setVersions(
      await listProjectVersions(metadata.directory_path, metadata.project_id),
    );
  }, [metadata.directory_path, metadata.project_id]);

  const createVersion = useCallback(
    async (label = "") => {
      if (!metadata.directory_path || !metadata.project_id) return null;
      const version = await saveProjectVersion({
        projectId: metadata.project_id,
        projectName: metadata.project_name,
        label,
        waypoints,
        routeSegments,
        metadata,
        settings,
        timeline,
        routePoints,
        drawnRoute,
        routingCache,
        activeWaypointId,
      });
      await refreshVersions();
      return version;
    },
    [
      activeWaypointId,
      drawnRoute,
      metadata,
      refreshVersions,
      routePoints,
      routeSegments,
      routingCache,
      settings,
      timeline,
      waypoints,
    ],
  );

  const restoreVersion = useCallback(
    async (versionId: string) => {
      if (!metadata.directory_path || !metadata.project_id) return false;
      const snapshot = await loadProjectVersion(
        metadata.directory_path,
        metadata.project_id,
        versionId,
      );
      if (!snapshot) return false;

      resetWaypointHistory(snapshot.waypoints);
      resetTimelineHistory(snapshot.timeline);
      setRouteSegments(snapshot.routeSegments);
      setRoutePoints(snapshot.routePoints);
      setDrawnRoute(snapshot.drawnRoute);
      setRoutingCache(snapshot.routingCache);
      setActiveWaypointId(snapshot.activeWaypointId);
      setMetadata({
        ...snapshot.metadata,
        project_id: metadata.project_id,
        directory_path: metadata.directory_path,
        status: "restored",
      });
      setSettings(snapshot.settings);
      setIsDirty(true);
      return true;
    },
    [
      metadata.directory_path,
      metadata.project_id,
      resetTimelineHistory,
      resetWaypointHistory,
      metadata.project_id,
      metadata.directory_path,
    ],
  );

  const removeVersion = useCallback(
    async (versionId: string) => {
      if (!metadata.directory_path || !metadata.project_id) return false;
      const deleted = await deleteProjectVersion(
        metadata.directory_path,
        metadata.project_id,
        versionId,
      );
      if (deleted) await refreshVersions();
      return deleted;
    },
    [metadata.directory_path, metadata.project_id, refreshVersions],
  );

  const updateWaypoint = useCallback(
    (id: string, data: Partial<Waypoint>) => {
      setWaypoints((prev) =>
        prev.map((wp) => (wp.id === id ? { ...wp, ...data } : wp)),
      );
    },
    [setWaypoints],
  );

  const updateMetadata = useCallback((data: Partial<ProjectMetadata>) => {
    setMetadata((prev) => ({ ...prev, ...data }));
    setIsDirty(true);
  }, []);

  const updateSettings = useCallback((data: Partial<ProjectSettings>) => {
    const ai = pickAiSettings(data);
    if (Object.keys(ai).length > 0) {
      const next = { ...globalAiRef.current, ...ai };
      globalAiRef.current = next;
      setGlobalAi(next);
      if (aiLoadedRef.current) {
        db.appSettings.set(GLOBAL_AI_KEY, next).catch((err) => console.error("Could not save the AI settings:", err));
      } else {
        aiEarlyRef.current = { ...aiEarlyRef.current, ...ai };
      }
    }
    const keys = patchedApiKeys(data);
    if (Object.keys(keys).length > 0) updateApiKeys(keys);
    const rest = stripApiKeys(data);
    // Changing only a map key is not an edit of the project.
    if (Object.keys(rest).length === 0) return;
    setSettings((prev) => ({ ...prev, ...rest }));
    setIsDirty(true);
  }, []);

  const saveProject = async (
    overrideName?: string,
    asDuplicate?: boolean,
    safeFolderName?: string,
    recordVersion = true,
  ) => {
    // Allowed to save empty project
    if (waypoints.length === 0) {
      console.warn(
        "No waypoints to save, but saving anyway to preserve metadata.",
      );
    }

    const saveRevision = dirtyRevisionRef.current;
    let freshThumbnail = projectThumbnail;
    if (thumbnailGetterRef.current) {
      try {
        const t = thumbnailGetterRef.current();
        if (t) freshThumbnail = t;
      } catch (e) {}
    }
    try {
      const result = await saveProjectData(
        waypoints,
        routeSegments,
        metadata,
        settings,
        routingCache,
        overrideName,
        asDuplicate,
        safeFolderName,
        freshThumbnail,
      );

      await saveTimelineManifest(result.projectDir, result.projName, timeline, settings.caption_style);
      // The assistant keeps its chat in the project folder: a first save or a Save As tells it where the chat now lives.
      window.dispatchEvent(new CustomEvent("project-saved", { detail: { dir: result.projectDir, saveAs: !!asDuplicate } }));

      setMetadata({
        ...metadata,
        project_name: result.projName,
        status: "saved",
        directory_path: result.projectDir,
        project_id: result.projId,
        thumbnail_path: result.thumbnailPath || "",
      });
      if (dirtyRevisionRef.current === saveRevision) {
        isDirtyRef.current = false;
        setIsDirtyState(false);
      }

      const savedMetadata = {
        ...metadata,
        project_name: result.projName,
        status: "saved",
        directory_path: result.projectDir,
        project_id: result.projId,
        thumbnail_path: result.thumbnailPath || "",
      };
      if (recordVersion)
        await saveProjectVersion({
          projectId: result.projId,
          projectName: result.projName,
          label: "Saved version",
          waypoints,
          routeSegments,
          metadata: savedMetadata,
          settings,
          timeline,
          routePoints,
          drawnRoute,
          routingCache,
          activeWaypointId,
        });
      setVersions(await listProjectVersions(result.projectDir, result.projId));

      console.log(`Saved successfully to: ${result.projectDir}`);
      setProjectThumbnail(result.thumbnailPath || null);
      try {
        await db.projects.touchOpened(result.projId);
      } catch (error) {
        console.error("Failed to update recents:", error);
      }
      addToRecents(result.projName, result.nvvPath || result.projectDir, result.thumbnailPath, result.projId);

      return result.projectDir;
    } catch (error) {
      console.error("Failed to save Navivi project:", error);
      throw error;
    }
  };

  const loadProject = async (
    forcePath?: string,
    isFolder = false,
  ): Promise<boolean> => {
    setIsProjectLoading(true);
    try {
      const result = await loadProjectData(forcePath, isFolder);
      if (!result) return false;

      const { selectedPath } = result;
      let data = result.data;
      if (!data.project_id || !data.waypoints) {
        throw new Error("Invalid Navivi project file format.");
      }
      // A project saved by an earlier version carries the map keys; they move to the app below.
      let legacyKeys = legacyApiKeys(data.settings);

      // DB metadata/settings win; if the DB fails, open from the files alone.
      let recoveredCache: Record<string, [number, number][]> = {};
      try {
        const synced = await syncProjectOnOpen(data, selectedPath);
        data = synced.data;
        legacyKeys = { ...legacyKeys, ...synced.legacyApiKeys };
        recoveredCache = synced.routingCache;
        await tidyProjectFolder(data.directory_path);
      } catch (error) {
        console.error("Database sync failed; using project files only:", error);
        if (data.directory_path) recoveredCache = await loadRouteCache(data.directory_path);
      }
      setRoutingCache(recoveredCache);
      setRoutePoints([]); // the previous project's imported track must not leak into this one
      console.log(`Recovered ${Object.keys(recoveredCache).length} routes from cache!`);

      setMetadata({
        project_id: data.project_id,
        project_name: data.project_name || appConfig.defaultProjectName,
        user_id: data.user_id,
        created_at: data.created_at,
        status: "saved",
        directory_path: data.directory_path || "",
        thumbnail_path: data.thumbnail_path || "",
        overview_narration: data.overview_narration || "",
        overview_narration_is_auto: data.overview_narration_is_auto === true,
        overview_narration_source_ids: data.overview_narration_source_ids,
        video_title: data.video_title || "",
        video_subtitle: data.video_subtitle || "",
        enable_intro: data.enable_intro ?? true,
      });

      adoptLegacyApiKeys(legacyKeys);
      if (data.settings) setSettings(data.settings);

      resetWaypointHistory(
        data.waypoints.map((wp: any) => ({
          id: wp.id || crypto.randomUUID(),
          lat: wp.lat,
          lng: wp.lng,
          name: wp.label || wp.name,
          routeMode: wp.routeMode || "walking",
          customRoute: wp.customRoute || [],
          customRouteEle: wp.customRouteEle?.length ? wp.customRouteEle : undefined,
          drawStyle: wp.drawStyle || "linear",
          lineColor: wp.lineColor || undefined,
          viaPoints: wp.viaPoints?.length ? wp.viaPoints : undefined,
          curveOffset: wp.curveOffset ?? undefined,
          timestamp: wp.timestamp || undefined,
          customMarker: wp.customMarker,

          isStopBy: wp.isStopBy || false,
          connectToRoute: wp.connectToRoute || false,
          skipAssetGeneration: wp.skipAssetGeneration ?? undefined,
          pauseAtWaypoint: wp.pauseAtWaypoint ?? undefined,
          images: savedImages(wp),
          videos: wp.videos || [],
          videoSound: wp.videoSound || [],
          imagePans: wp.imagePans || wp.camera_pans || [],
          imageDisplay: wp.image_display || "pip",
          narration: wp.narration || "",
          arrivingNarration: wp.arrivingNarration || "",
          attractionNarration: wp.attractionNarration || "",
          audioUrl: wp.audioUrl,
          videoUrl: wp.videoUrl,
        })),
      );
      resetTimelineHistory(getDefaultTimeline());
      await autoLoadTimeline(data.directory_path);

      setVersions(
        await listProjectVersions(data.directory_path || "", data.project_id),
      );

      setIsDirty(false);
      setProjectThumbnail(data.thumbnail_path || null);
      addToRecents(
        data.project_name || appConfig.defaultProjectName,
        selectedPath,
        data.thumbnail_path,
        data.project_id,
      );

      return true;
    } catch (error) {
      console.error("Failed to load project:", error);
      throw error;
    } finally {
      setIsProjectLoading(false);
    }
  };

  const resetWorkspace = () => {
    setActiveWaypointId(null);
    resetWaypointHistory([]);
    resetTimelineHistory(getDefaultTimeline());
    setRouteSegments([]);
    setRoutePoints([]);
    setMetadata({
      ...DefaultMetadata,
      created_at: new Date().toISOString(),
    });
    setSettings(DefaultSettings);
    setRoutingCache({});
    setProjectThumbnail(null);
    setVersions([]);
    setIsDirty(false);
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
        if (isRendering && !(isBackgroundRender && editorMode === "timeline")) return;
      const activeEl = document.activeElement;
      const isTyping =
        activeEl?.tagName === "INPUT" ||
        activeEl?.tagName === "TEXTAREA" ||
        activeEl?.getAttribute("contenteditable") === "true";

      if (isTyping) return;

      const isCmdOrCtrl = e.metaKey || e.ctrlKey;

      if (isCmdOrCtrl && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) {
          editorMode === "map" ? redoMap() : redoTimeline();
        } else {
          editorMode === "map" ? undoMap() : undoTimeline();
        }
      } else if (isCmdOrCtrl && e.key.toLowerCase() === "y") {
        e.preventDefault();
        editorMode === "map" ? redoMap() : redoTimeline();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [editorMode, undoMap, redoMap, undoTimeline, redoTimeline, isRendering, isBackgroundRender]);

  const autoLoadTimeline = async (projectDir: string) => {
    try {
      resetTimelineHistory(await loadTimelineData(projectDir));
    } catch (error) {
      console.error("Failed to load timeline:", error);
      resetTimelineHistory(getDefaultTimeline());
    }
  };

  const forceReroute = () => {
    setRoutingCache({});
  };

  return (
    <WorkspaceContext.Provider
      value={{
        waypoints,
        setWaypoints,
        undoMap,
        redoMap,
        canUndoMap,
        canRedoMap,
        timeline,
        setTimeline,
        autoLoadTimeline,
        undoTimeline,
        redoTimeline,
        canUndoTimeline,
        canRedoTimeline,
        updateWaypoint,
        routeSegments,
        setRouteSegments,
        activeWaypointId,
        setActiveWaypointId,
        routePoints,
        setRoutePoints,
        metadata,
        setMetadata,
        updateMetadata,
        settings,
        setSettings,
        updateSettings,
        saveProject,
        loadProject,
        isDirty,
        dirtyRevision,
        setIsDirty,
        recentProjects,
        setRecentProjects,
        projectThumbnail,
        setProjectThumbnail,
        registerThumbnailGetter,
        resetWorkspace,
        routingCache,
        setRoutingCache,
        forceReroute,
        drawnRoute,
        setDrawnRoute,
        versions,
        refreshVersions,
        createVersion,
        restoreVersion,
        deleteVersion: removeVersion,
        isProjectLoading,
      }}
    >
      {children}

      <UnsavedChanges
        isOpen={isUnsavedModalOpen}
        projectName={metadata.project_name || "Untitled Project"}
        onCancel={() => {
          setIsUnsavedModalOpen(false);
          setUnsavedAction(null);
        }}
        onDiscard={() => {
          setIsUnsavedModalOpen(false);
          if (unsavedAction) unsavedAction();
          setUnsavedAction(null);
        }}
        onSave={async () => {
          await saveProject();
          setIsUnsavedModalOpen(false);
          if (unsavedAction) unsavedAction();
          setUnsavedAction(null);
        }}
      />
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace() {
  const context = useContext(WorkspaceContext);
  if (!context)
    throw new Error("useWorkspace must be used within WorkspaceProvider");
  return context;
}
