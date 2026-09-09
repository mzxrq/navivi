import { readTextFile, exists } from "@tauri-apps/plugin-fs";
import { getCurrentWindow } from "@tauri-apps/api/window"; // ✨ NEW: For App Close intercept
import { parseSRT } from "../utils/srtParser";
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
import { ClipData, TimelineTrack } from "../types";
import { useHistory } from "./useHistory";
import { useUI } from "./useUI";

// ✨ NEW: Import your Modal!
import { UnsavedChanges } from "../components/ui/UnsavedChanges";

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
    { id: "track-video-2", name: "V2: Pop-ups", type: "video", orderIndex: 0 },
    { id: "track-video-1", name: "V1: Main Video", type: "video", orderIndex: 1 },
    { id: "track-subtitles", name: "T1: Subtitles", type: "subtitle", orderIndex: 2 },
    { id: "track-audio-1", name: "A1: Voiceovers", type: "audio", orderIndex: 3 },
    { id: "track-audio-2", name: "A2: Music", type: "audio", orderIndex: 4 },
  ],
  clips: [],
  transitions: [],
  zoomMultiplier: 1.0,
};

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { editorMode } = useUI();
  const [isDirty, setIsDirty] = useState(false);

  // ✨ FIX: Wrap Waypoint History to trigger isDirty
  const {
    state: waypoints,
    set: _setWaypoints,
    undo: _undoMap,
    redo: _redoMap,
    canUndo: canUndoMap,
    canRedo: canRedoMap,
    reset: resetWaypointHistory,
  } = useHistory<Waypoint[]>([], 50);

  const setWaypoints = useCallback((action: React.SetStateAction<Waypoint[]>) => {
    _setWaypoints(action);
    setIsDirty(true);
  }, [_setWaypoints]);

  const undoMap = useCallback(() => { _undoMap(); setIsDirty(true); }, [_undoMap]);
  const redoMap = useCallback(() => { _redoMap(); setIsDirty(true); }, [_redoMap]);

  // ✨ FIX: Wrap Timeline History to trigger isDirty! (Fixes Status Bar)
  const {
    state: timeline,
    set: _setTimeline,
    undo: _undoTimeline,
    redo: _redoTimeline,
    canUndo: canUndoTimeline,
    canRedo: canRedoTimeline,
    reset: resetTimelineHistory,
  } = useHistory<TimelineData>(DefaultTimeline, 50);

  const setTimeline = useCallback((action: React.SetStateAction<TimelineData>) => {
    _setTimeline(action);
    setIsDirty(true);
  }, [_setTimeline]);

  const undoTimeline = useCallback(() => { _undoTimeline(); setIsDirty(true); }, [_undoTimeline]);
  const redoTimeline = useCallback(() => { _redoTimeline(); setIsDirty(true); }, [_redoTimeline]);

  const [routeSegments, setRouteSegments] = useState<RouteSegment[]>([]);
  const [routePoints, setRoutePoints] = useState<[number, number][]>([]);
  const [drawnRoute, setDrawnRoute] = useState<[number, number][]>([]);
  const [activeWaypointId, setActiveWaypointId] = useState<string | null>(null);
  
  const [metadata, setMetadata] = useState<ProjectMetadata>(() => ({
    ...DefaultMetadata,
    created_at: new Date().toISOString(),
  }));
  
  const [settings, setSettings] = useState<ProjectSettings>(DefaultSettings);
  const [routingCache, setRoutingCache] = useState<Record<string, [number, number][]>>({});
  
  const [recentProjects, setRecentProjects] = useState<RecentProjects[]>(() => {
    const saved = localStorage.getItem("navivi-recents");
    return saved ? JSON.parse(saved) : [];
  });

  // ✨ GLOBAL UNSAVED MODAL STATE
  const [isUnsavedModalOpen, setIsUnsavedModalOpen] = useState(false);
  const [unsavedAction, setUnsavedAction] = useState<(() => void) | null>(null);

  // ✨ TAURI APP CLOSE INTERCEPTOR
  useEffect(() => {
    try {
      const appWindow = getCurrentWindow();
      const unlisten = appWindow.onCloseRequested(async (event) => {
        if (isDirty) {
          event.preventDefault(); // Stop app from closing immediately
          setUnsavedAction(() => () => appWindow.destroy()); // Force close after choice
          setIsUnsavedModalOpen(true);
        }
      });
      return () => {
        unlisten.then(f => f());
      };
    } catch (e) {
      console.log("Tauri window API not available in browser mode");
    }
  }, [isDirty]);

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
  }, [setWaypoints]);

  const updateClip = useCallback(
    (id: string, startTime: number, duration: number) => {
      setTimeline({
        ...timeline,
        clips: timeline.clips.map((clip) =>
          clip.id === id ? { ...clip, startTime, duration } : clip,
        ),
      });
    },
    [timeline, setTimeline],
  );

  const updateMetadata = useCallback((data: Partial<ProjectMetadata>) => {
    setMetadata((prev) => ({ ...prev, ...data }));
    setIsDirty(true);
  }, []);

  const updateSettings = useCallback((data: Partial<ProjectSettings>) => {
    setSettings((prev) => ({ ...prev, ...data }));
    setIsDirty(true);
  }, []);

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

      await saveTimelineManifest(result.projectDir, result.projName, timeline);

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
      const result = await loadProjectData(forcePath);
      if (!result) return false;

      const { data, selectedPath } = result;
      if (data.directory_path) {
        const recoveredCache = await loadRouteCache(data.directory_path);
        setRoutingCache(recoveredCache);
        console.log(
          `Recovered ${Object.keys(recoveredCache).length} routes from cache!`,
        );
      } else {
        setRoutingCache({});
      }

      if (!data.project_id || !data.waypoints) {
        throw new Error("Invalid Navivi project file format.");
      }

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
      await autoLoadTimeline(data.directory_path);

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
  };

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
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
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

  const autoLoadTimeline = async (projectDir: string) => {
    const manifest = await loadTimelineManifest(projectDir);
    if (!manifest) {
      resetTimelineHistory(DefaultTimeline);
      return;
    }
    
    if (manifest.ui_state) {
      resetTimelineHistory(manifest.ui_state);
      return;
    }

    const defaultTracks: TimelineTrack[] = [
      { id: "track-video-2", name: "V2: Pop-ups", type: "video", orderIndex: 0 },
      { id: "track-video-1", name: "V1: Main Video", type: "video", orderIndex: 1 },
      { id: "track-subtitles", name: "T1: Subtitles", type: "subtitle", orderIndex: 2 },
      { id: "track-audio-1", name: "A1: Voiceovers", type: "audio", orderIndex: 3 },
      { id: "track-audio-2", name: "A2: Music", type: "audio", orderIndex: 4 },
    ];

    const parseDuration = (val: any): number => {
      if (typeof val === "number") return val;
      if (typeof val === "string") {
        if (val.includes(":")) {
          const parts = val.split(":");
          return parseInt(parts[0]) * 60 + parseFloat(parts[1]);
        }
        return parseFloat(val) || 5.0;
      }
      return 5.0; 
    };

    let runningTime = 0;
    const newClips: ClipData[] = [];

    manifest.video_tracks.forEach((item) => {
      const targetTrackId = item.type === "static_popup" ? "track-video-2" : "track-video-1";
      const safeDuration = parseDuration(item.duration);

      newClips.push({
        id: item.clip_id || crypto.randomUUID(),
        trackId: targetTrackId,
        label: item.file_path.split(/[/\\]/).pop() || "Video Clip", 
        startTime: runningTime,
        duration: safeDuration,
        sourceDuration: safeDuration,
        source: item.file_path,
        type: "video",
      });
      
      runningTime += item.duration;
    });

    if (manifest.audio_track) {
      newClips.push({
        id: crypto.randomUUID(),
        trackId: "track-audio-1",
        label: manifest.audio_track.split(/[/\\]/).pop() || "Master Audio",
        startTime: 0,
        duration: manifest.total_duration_seconds,
        source: manifest.audio_track,
        type: "audio",
      });

      try {
        const srtPath = manifest.audio_track.replace(/\.[^/.]+$/, ".srt"); 
        
        if (await exists(srtPath)) {
          const srtContent = await readTextFile(srtPath);
          const parsedSubtitles = parseSRT(srtContent);
          
          parsedSubtitles.forEach((sub) => {
            newClips.push({
              id: crypto.randomUUID(),
              trackId: "track-subtitles",
              label: `Sub: ${sub.text.substring(0, 15)}...`,
              type: "text",
              text: sub.text,
              startTime: sub.startTime,
              duration: sub.endTime - sub.startTime,
              x: 960,
              y: 900,
              fontSize: 48,
              color: "#ffffff",
              stroke: "#000000",
              strokeWidth: 2,
            });
          });
        }
      } catch (err) {
        console.error("Failed to load or parse subtitles:", err);
      }
    }

    setTimeline({
      tracks: defaultTracks,
      clips: newClips,
      zoomMultiplier: 1,
      transitions: [],
    });
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
        setRecentProjects,
        resetWorkspace,
        routingCache,
        setRoutingCache,
        forceReroute,
        drawnRoute,
        setDrawnRoute,
      }}
    >
      {children}
      
      {/* ✨ GLOBAL UNSAVED PROMPT */}
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