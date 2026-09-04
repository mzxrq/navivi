import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
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
} from "../types";
import {
  appConfig,
  defaultProjectSettings,
  mapDefaults,
} from "../config/constants";
import {
  saveProjectData,
  loadProjectData,
  loadTimelineManifest,
  loadRouteCache,
  saveTimelineManifest,
} from "../services/fileSystem";
import { TimelineClipData, TimelineTrack } from "../types";
import { useHistory } from "./useHistory";
import { useUI } from "./useUI";

const WorkspaceContext = createContext<WorkspaceState | undefined>(undefined);

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

const DefaultTimeline: TimelineData = {
  tracks: [
    { id: "t-subtitles", name: "Subtitles", type: "text" },
    { id: "t-popups", name: "Popups", type: "image" },
    { id: "t-mapvideo", name: "Video", type: "video" },
    { id: "t-voiceover", name: "Voiceover", type: "audio" },
  ],
  clips: [],
  zoomMultiplier: 1.0,
};

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { editorMode } = useUI(); // editorMode : Map <-> Timeline

  const {
    state: waypoints,
    set: setWaypoints,
    undo: undoMap,
    redo: redoMap,
    canUndo: canUndoMap,
    canRedo: canRedoMap,
    reset: resetWaypointHistory,
  } = useHistory<Waypoint[]>([], 50); // Waypoint management and undo/redo history for MapEditor

  const {
    state: timeline,
    set: setTimeline,
    undo: undoTimeline,
    redo: redoTimeline,
    canUndo: canUndoTimeline,
    canRedo: canRedoTimeline,
    reset: resetTimelineHistory,
  } = useHistory<TimelineData>(DefaultTimeline, 50); // Timeline management and undo/redo history for VideoEditor

  const [routeSegments, setRouteSegments] = useState<RouteSegment[]>([]); // RouteSegments
  const [routePoints, setRoutePoints] = useState<[number, number][]>([]); // MapPin Route points
  const [drawnRoute, setDrawnRoute] = useState<[number, number][]>([]);
  const [activeWaypointId, setActiveWaypointId] = useState<string | null>(null); // Selected waypoint (for context menu)
  const [metadata, setMetadata] = useState<ProjectMetadata>(() => ({
    ...DefaultMetadata,
    created_at: new Date().toISOString(),
  })); // Project metadata (see ../services/index.ts for more)
  const [settings, setSettings] = useState<ProjectSettings>(DefaultSettings); // Project setting (see ../services/index.ts for more)
  const [routingCache, setRoutingCache] = useState<
    Record<string, [number, number][]>
  >({}); // Read routingCache from project's job_config.json
  const [isDirty, setIsDirty] = useState(false); // check if save or unsaved state
  const [recentProjects, setRecentProjects] = useState<RecentProjects[]>(() => {
    const saved = localStorage.getItem("navivi-recents");
    return saved ? JSON.parse(saved) : [];
  }); // Recent Project for TitleScreen.tsx

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
  }, []); // add recent project to TitleScreen

  const updateWaypoint = useCallback((id: string, data: Partial<Waypoint>) => {
    setWaypoints((prev) =>
      prev.map((wp) => (wp.id === id ? { ...wp, ...data } : wp)),
    );
    setIsDirty(true);
  }, []); // update waypoint when is moved or its information like narration or image were updated

  const updateClip = useCallback(
    (id: string, startTime: number, duration: number) => {
      setTimeline({
        ...timeline,
        clips: timeline.clips.map((clip) =>
          clip.id === id ? { ...clip, startTime, duration } : clip,
        ),
      });
      setIsDirty(true);
    },
    [timeline, setTimeline],
  ); // update clip/timeline track when clip is added or its information were updated

  const updateMetadata = useCallback((data: Partial<ProjectMetadata>) => {
    setMetadata((prev) => ({ ...prev, ...data }));
    setIsDirty(true);
  }, []); // update metadata such as project renaming

  const updateSettings = useCallback((data: Partial<ProjectSettings>) => {
    setSettings((prev) => ({ ...prev, ...data }));
    setIsDirty(true);
  }, []); // update setting (see index.ts for more)

  const saveProject = async (
    overrideName?: string,
    asDuplicate?: boolean,
    safeFolderName?: string,
  ) => {
    if (waypoints.length === 0) {
      console.warn("No waypoints to save.");
      return;
    }

    try {
      // 1. Save all the Map/Route/Settings data
      const result = await saveProjectData(
        waypoints,
        routeSegments,
        metadata,
        settings,
        routingCache,
        overrideName,
        asDuplicate,
        safeFolderName,
      );

      // 🛠️ 2. NEW: Instantly save the Timeline Manifest into that exact same folder!
      await saveTimelineManifest(result.projectDir, result.projName, timeline);

      // 3. Update UI state
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
  }; // see fileSystem.ts for more

  const loadProject = async (forcePath?: string): Promise<boolean> => {
    try {
      // Delegate the file selection and reading to the service
      const result = await loadProjectData(forcePath);
      if (!result) return false; // User cancelled dialog

      const { data, selectedPath } = result;
      if (data.directory_path) {
        const recoveredCache = await loadRouteCache(data.directory_path);
        setRoutingCache(recoveredCache);
        console.log(
          `Recovered ${Object.keys(recoveredCache).length} routes from cache!`,
        );
      } else {
        // Fallback just in case
        setRoutingCache({});
      }

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
        directory_path: data.directory_path || "",
        overview_narration: data.overview_narration || "",
      });

      if (data.settings) setSettings(data.settings);

      resetWaypointHistory(
        data.waypoints.map((wp: any) => ({
          id: wp.id || crypto.randomUUID(),
          lat: wp.lat,
          lng: wp.lng,
          name: wp.label,
          images: wp.popup_image || [],
          imageDisplay: wp.image_display || "pip",
          narration: wp.narration || "",
          routeMode: wp.routeMode || "walking",
          customRoute: wp.customRoute || [],
          drawStyle: wp.drawStyle || "linear",
          isStopBy: wp.isStopBy || false,
        })),
      );
      resetTimelineHistory(DefaultTimeline);

      setIsDirty(false);
      addToRecents(
        data.project_name || appConfig.defaultProjectName,
        selectedPath,
      );

      return true;
    } catch (error) {
      console.error("Failed to load project:", error);
      throw error;
    }
  }; // see fileSystem.ts for more

  const resetWorkspace = () => {
    setActiveWaypointId(null);
    resetWaypointHistory([]);
    resetTimelineHistory(DefaultTimeline);
    setRouteSegments([]);
    setMetadata({
      ...DefaultMetadata,
      created_at: new Date().toISOString(),
    });
    setSettings(DefaultSettings);
    setRoutingCache({});
    setIsDirty(false);
  }; // reset entire workspace

  // undo/redo shortcut
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignore keypresses inside input fields or textareas so typing doesn't trigger undo
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
  }, [editorMode, undoMap, redoMap, undoTimeline, redoTimeline]);

  // auto-loader logic for TimelineManifest
  const autoLoadTimeline = async (projectDir: string) => {
    const manifest = await loadTimelineManifest(projectDir);
    if (!manifest) return; // no manifest -> exit

    // ensure standard base tracks ready
    const videoTrackId = crypto.randomUUID();
    const popupTrackId = crypto.randomUUID();
    const audioTrackId = crypto.randomUUID();

    const defaultTracks: TimelineTrack[] = [
      { id: popupTrackId, name: "Popups", type: "video" },
      { id: videoTrackId, name: "Video", type: "video" },
      { id: audioTrackId, name: "Voiceover", type: "audio" },
    ];

    // convert python manifest clips into ui timeline clips
    let runningTime = 0;
    const generatedClips: TimelineClipData[] = [];

    manifest.video_tracks.forEach((item) => {
      const targetTrackId =
        item.type === "static_popup" ? popupTrackId : videoTrackId;

      generatedClips.push({
        id: item.clip_id,
        trackId: targetTrackId,
        label: item.file_path.split("/").pop() || item.clip_id, //Extract filename for UI
        startTime: runningTime,
        duration: item.duration,
        source: item.file_path,
      });
      // advance running time so next clip starts exactly when this one ends
      runningTime += item.duration;
    });

    // add master audio track if it exists
    if (manifest.audio_track) {
      generatedClips.push({
        id: "master_audio",
        trackId: audioTrackId,
        label: manifest.audio_track.split("/").pop() || "Master Audio",
        startTime: 0,
        duration: manifest.total_duration_seconds,
        source: manifest.audio_track,
      });
    }

    // overwrite the timeline state with generated data
    setTimeline({
      tracks: defaultTracks,
      clips: generatedClips,
      zoomMultiplier: 1,
    });
  };

  const forceReroute = () => {
    setRoutingCache({});
  };

  return (
    <WorkspaceContext.Provider
      value={{
        // map history
        waypoints,
        setWaypoints,
        undoMap,
        redoMap,
        canUndoMap,
        canRedoMap,
        // timeline history
        timeline,
        setTimeline,
        autoLoadTimeline,
        updateClip,
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
        setIsDirty,
        recentProjects,
        resetWorkspace,
        routingCache,
        setRoutingCache,
        forceReroute,
        drawnRoute,
        setDrawnRoute,
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
