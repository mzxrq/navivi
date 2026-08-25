import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useState, useEffect, useRef } from "react";
import { ChevronRight, Trash2, Car, Footprints, FileVideo, Map as MapIcon, Route, Ruler, Plane, Play, Square, Mic, Sparkles, Settings2, } from "lucide-react";
import {
  DragDropContext,
  Droppable,
  Draggable,
  DropResult,
} from "@hello-pangea/dnd";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useUI } from "../../../hooks/useUI";
import { WaypointItem } from "./WaypointItem";
import { WaypointEditor } from "./WaypointEditor";
import { LocationSearch } from "../../ui/LocationSearch";

export function Sidebar() {
  const { showToast } = useUI();
  const { waypoints, setWaypoints, metadata, updateMetadata, saveProject, settings, isDirty, setIsDirty } = useWorkspace();

  const [editingId, setEditingId] = useState<string | null>(null);
  const [isListEditMode, setIsListEditMode] = useState(false);
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [isRendering, setIsRendering] = useState(false);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isGeneratingOverview, setIsGeneratingOverview] = useState(false);
  const [overviewEngine, setOverviewEngine] = useState("ollama");
  const sidebarRef = useRef<HTMLElement>(null);

  // Listen for the preview finishing to reset the button state
  useEffect(() => {
    const handlePreviewFinish = () => setIsPreviewing(false);
    window.addEventListener("preview-finished", handlePreviewFinish);
    return () => window.removeEventListener("preview-finished", handlePreviewFinish);
  }, [])

  const togglePreview = () => {
    if (isPreviewing) {
      window.dispatchEvent(new Event("stop-preview"));
      setIsPreviewing(false);
    } else {
      window.dispatchEvent(new Event("start-preview"));
      setIsPreviewing(true);
    }
  }

  // --- Calculations ---
  const totalDuration = waypoints.reduce((acc, wp) => acc + (wp.duration || settings?.duration_seconds || 3), 0);
  const estimatedTime = totalDuration.toFixed(1);

  // handleClickOutside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        sidebarRef.current &&
        !sidebarRef.current.contains(event.target as Node)
      ) {
        setIsListEditMode(false);
        setShowClearConfirm(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // setupListeners
  useEffect(() => {
    const setupListeners = async () => {
      const unlistenLog = await listen<string>("render-log", (event) => {
        setLogs((prev) => [...prev, event.payload]);
        console.log("Python Log:", event.payload);
      });

      const unlistenError = await listen<string>("render-error", (event) => {
        setLogs((prev) => [...prev, `Error: ${event.payload}`]);
        console.error("Python Error:", event.payload);
      });

      const unlistenFinish = await listen<string>("render-finish", (event) => {
        setIsRendering(false);
        alert(`Render process finished with status: ${event.payload}`);
      });

      return () => {
        unlistenLog();
        unlistenError();
        unlistenFinish();
      };
    };

    const cleanupPromise = setupListeners();
    return () => {
      cleanupPromise.then((cleanup) => cleanup());
    };
  }, []);

  // handleRenderVideo
  const handleRenderVideo = async () => {
    if (waypoints.length === 0) {
      showToast("Cannot render: Please add at least one waypoint.", "error");
      return;
    }

    const invalidWps = waypoints.filter(
      (wp) => !wp.narration.trim() || !wp.images || wp.images.length === 0,
    );
    if (invalidWps.length > 0) {
      const names = invalidWps.map((w) => w.name).join(", ");
      showToast(
        `Validation Failed: Missing image or script in [${names}]`,
        "error",
      );
      return;
    }

    if (
      !confirm(
        "Ready to render? This will generate the configuration for the backend.",
      )
    )
      return;

    await saveProject();

    try {
      setIsRendering(true);
      setLogs([]);

      const configPath = `${metadata.directory_path}/job_config.json`;

      const response = await invoke("start_render", {
        configPath: configPath,
      });

      showToast(response as string, "info");
    } catch (error) {
      setIsRendering(false);
      showToast(`Error from Rust: ${error}`, "error");
    }
  };

  const handleDragEnd = (result: DropResult) => {
    if (!result.destination) return;
    if (result.source.index === result.destination.index) return;

    const newWaypoints = Array.from(waypoints);
    const [reorderedItem] = newWaypoints.splice(result.source.index, 1);
    newWaypoints.splice(result.destination.index, 0, reorderedItem);

    setWaypoints(newWaypoints);
  };

  if (editingId) {
    return (
      <WaypointEditor wpId={editingId} onClose={() => setEditingId(null)} />
    );
  }

  const handleGenerateOverview = async () => {
    // Extract and filter valid location names
    const waypointNames = waypoints
      .map((wp) => wp.name)
      .filter((name) => name && name !== "Locating...");

    if (waypointNames.length === 0) {
      return showToast("Please add some waypoints to the route first!", "info");
    }

    setIsGeneratingOverview(true);
    showToast("Synthesizing route overview...", "info");

    try {
      const payload = JSON.stringify({
        waypoints: waypointNames,
        engine: overviewEngine,
      });

      const pythonResponse = await invoke<string>("run_python_blueprint", {
        action: "generate_overview",
        payload: payload,
      });

      const parsed = JSON.parse(pythonResponse);
      if (parsed.success) {
        updateMetadata({ overview_narration: parsed.script });
        setIsDirty(true);
        showToast("✨ Overview script compiled!", "success");
      } else {
        throw new Error(parsed.error);
      }
    } catch (error) {
      showToast(`Overview generation failed: ${error}`, "error");
    } finally {
      setIsGeneratingOverview(false);
    }
  };

  return (
    <aside
      ref={sidebarRef}
      // Removed p-6 so the sticky header can hit the edges; padding moved to inner containers
      className="w-85 shrink-0 bg-white dark:bg-zinc-950 border-r border-zinc-200 dark:border-white/8 flex flex-col h-full select-none z-10 relative shadow-xl transition-colors"
    >
      {/* --- STICKY HEADER --- */}
      <div className="sticky top-0 z-30 bg-white/95 dark:bg-zinc-950/95 backdrop-blur-md border-b border-zinc-200 dark:border-white/5 p-5 shrink-0 flex flex-col gap-4">
        <LocationSearch />

        <div className="flex flex-col gap-2">
          {/* Header Label & Stats */}
          <div className="flex items-center justify-between">
            <label className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest flex items-center gap-1.5">
              <Mic className="w-3 h-3 text-emerald-500" /> Intro Voice-over
            </label>
            <div className="flex items-center gap-2 text-[9px] font-medium text-zinc-400">
              <span className="flex items-center gap-1"><MapIcon className="w-2.5 h-2.5" /> {waypoints.length}</span>
              <span className="flex items-center gap-1"><FileVideo className="w-2.5 h-2.5" /> ~{estimatedTime}s</span>
            </div>
          </div>

          {/* Intro Script Textarea */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-emerald-500" /> Route Intro Script
              </label>

              <div className="flex items-center gap-2">
                <div className="relative flex items-center">
                  <Settings2 className="w-3 h-3 text-zinc-400 absolute left-1.5 pointer-events-none" />
                  <select
                    value={overviewEngine || "ollama"}
                    onChange={(e) => setOverviewEngine(e.target.value)}
                    disabled={isGeneratingOverview}
                    className="pl-5 pr-1 py-1 text-[10px] bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 rounded-md outline-none cursor-pointer disabled:opacity-50"
                  >
                    <option value="ollama">Ollama</option>
                    <option value="gemini">Gemini</option>
                    <option value="groq">Groq</option>
                  </select>
                </div>

                <button
                  onClick={handleGenerateOverview}
                  disabled={isGeneratingOverview || waypoints.length === 0}
                  className="flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-bold transition-all disabled:opacity-50 disabled:cursor-not-allowed bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-100 dark:hover:bg-emerald-500/20 border border-emerald-200 dark:border-emerald-500/20 shadow-sm"
                >
                  <Sparkles className={`w-3 h-3 ${isGeneratingOverview ? 'animate-pulse' : ''}`} />
                  {isGeneratingOverview ? 'Summarizing...' : 'Magic Write'}
                </button>
              </div>
            </div>
          </div>

          {/* Textarea Container with Glass Loading Overlay */}
          <div className="relative w-full h-24 rounded-xl overflow-hidden shadow-sm border border-zinc-200 dark:border-white/10 group focus-within:border-emerald-500 dark:focus-within:border-emerald-500/50 transition-colors">
            <textarea
              value={metadata.overview_narration || ""}
              onChange={(e) => updateMetadata({ overview_narration: e.target.value })}
              disabled={isGeneratingOverview}
              placeholder="e.g., Welcome to our road trip! Today we'll explore..."
              className="w-full h-full resize-none p-3 text-xs custom-scrollbar bg-zinc-50 dark:bg-zinc-900/50 text-zinc-900 dark:text-zinc-100 focus:outline-none"
            />

            {/* Background Processing Indicator */}
            {isGeneratingOverview && (
              <div className="absolute inset-0 bg-white/70 dark:bg-zinc-950/70 backdrop-blur-[2px] flex flex-col items-center justify-center z-10">
                <div className="flex flex-col items-center gap-2">
                  <Sparkles className="w-5 h-5 text-emerald-500 animate-bounce" />
                  <div className="text-[10px] font-bold text-emerald-600 dark:text-emerald-400 tracking-wide uppercase">
                    Gemma is summarizing route...
                  </div>
                  <div className="w-20 h-1 bg-emerald-100 dark:bg-emerald-900/50 rounded-full overflow-hidden">
                    <div className="h-full bg-emerald-500 rounded-full w-full animate-[pulse_1s_ease-in-out_infinite]"></div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {waypoints.length > 0 && (
            <div className="w-full">
              <button
                onClick={() => {
                  setIsListEditMode(!isListEditMode);
                  setShowClearConfirm(false);
                }}
                className={`w-full py-1.5 text-xs font-bold rounded-lg transition-colors shadow-sm ${isListEditMode
                  ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-500/30"
                  : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800 border border-transparent"
                  }`}
              >
                {isListEditMode ? "Done Editing" : "Edit List"}
              </button>
            </div>
          )}
        </div>
      </div>
      {/* --- SCROLLABLE TIMELINE --- */}
      <div className="flex-1 flex flex-col min-h-0">
        {waypoints.length === 0 ? (
          <div className="p-8 mt-10 mx-5 rounded-2xl border border-dashed border-zinc-300 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/20 text-center shrink-0 transition-colors animate-in fade-in">
            <Route className="w-10 h-10 mb-3 mx-auto opacity-20 text-zinc-500" />
            <p className="text-xs font-semibold text-zinc-500">
              No stops added yet.
            </p>
            <p className="text-[10px] text-zinc-400 mt-1.5">
              Click the map or drop a GPS file to start building your route.
            </p>
          </div>
        ) : (
          <DragDropContext onDragEnd={handleDragEnd}>
            <Droppable droppableId="waypoints-list">
              {(provided) => (
                <div
                  className="flex-1 overflow-y-auto px-4 pt-4 custom-scrollbar flex flex-col pb-4"
                  {...provided.droppableProps}
                  ref={provided.innerRef}
                >
                  {/* Clear All & Confirm UI (Only visible in Edit Mode) */}
                  {isListEditMode && (
                    <div className="relative mb-4 shrink-0 z-20">
                      {!showClearConfirm ? (
                        <button
                          onClick={() => setShowClearConfirm(true)}
                          className="w-full py-2.5 rounded-xl border border-red-200 dark:border-red-500/20 bg-red-50 dark:bg-red-500/5 text-red-600 dark:text-red-400 text-xs font-bold hover:bg-red-100 dark:hover:bg-red-500/10 transition-colors flex items-center justify-center shadow-sm"
                        >
                          <Trash2 className="w-3.5 h-3.5 mr-2" /> Clear All Waypoints
                        </button>
                      ) : (
                        <div className="w-full py-2 px-3 rounded-xl border border-red-300 dark:border-red-500/40 bg-white dark:bg-zinc-900 shadow-sm flex items-center justify-between animate-in fade-in zoom-in-95 duration-200">
                          <span className="text-[11px] font-semibold text-zinc-800 dark:text-zinc-300">
                            Are you sure?
                          </span>
                          <div className="flex items-center">
                            <button
                              onClick={() => setShowClearConfirm(false)}
                              className="text-[10px] font-medium text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-300 px-2 py-1"
                            >
                              Cancel
                            </button>
                            <button
                              onClick={() => {
                                setWaypoints([]);
                                setIsListEditMode(false);
                                setShowClearConfirm(false);
                              }}
                              className="text-[10px] font-bold text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-500/10 px-2.5 py-1 rounded-md hover:bg-red-100 dark:hover:bg-red-500/20 transition-colors"
                            >
                              Confirm
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {waypoints.map((wp, i) => {
                    const isLast = i === waypoints.length - 1;

                    return (
                      <Draggable
                        key={wp.id}
                        draggableId={wp.id}
                        index={i}
                        isDragDisabled={isListEditMode}
                      >
                        {(provided, snapshot) => (
                          <div
                            ref={provided.innerRef}
                            {...provided.draggableProps}
                            {...provided.dragHandleProps}
                            className={`
                              transition-shadow duration-200
                              ${snapshot.isDragging ? "z-50 rounded-xl bg-blend-color-burn dark:bg-blend-color-burn" : "z-10"}
                            `}
                            style={provided.draggableProps.style}
                          >
                            <WaypointItem
                              wp={wp}
                              index={i}
                              isListEditMode={isListEditMode}
                              isFirst={i === 0}
                              isLast={isLast}
                              onEdit={() => setEditingId(wp.id)}
                              onDelete={() =>
                                setWaypoints(
                                  waypoints.filter((w) => w.id !== wp.id),
                                )
                              }
                            />

                            {/* --- TRANSPORT MODE CONNECTOR --- */}
                            {!isLast && !isListEditMode && (
                              <div className="relative h-0 z-20 w-full pointer-events-none">
                                {/* left-[28px] centers over the WaypointItem's timeline bar */}
                                <div className="absolute -top-3 left-7 -translate-x-1/2">
                                  <div className="w-5 h-5 bg-zinc-100 dark:bg-zinc-800 border-2 border-white dark:border-zinc-950 rounded-full flex items-center justify-center text-zinc-500 dark:text-zinc-400 shadow-sm transition-colors">
                                    {wp.routeMode === 'walking' ? (
                                      <Footprints className="w-2.5 h-2.5" />
                                    ) : wp.routeMode === 'driving' ? (
                                      <Car className="w-2.5 h-2.5" />
                                    ) : wp.routeMode === 'curve' ? (
                                      <Plane className="w-2.5 h-2.5" />
                                    ) : (
                                      <Ruler className="w-2.5 h-2.5" />
                                    )}
                                  </div>
                                </div>
                              </div>
                            )}

                          </div>
                        )}
                      </Draggable>
                    );
                  })}
                  {provided.placeholder}
                </div>
              )}
            </Droppable>
          </DragDropContext>
        )}
      </div>

      {/* --- FOOTER / ACTION AREA --- */}
      <div className="shrink-0 px-4 py-3 flex items-center justify-between bg-white dark:bg-zinc-950 border-t border-zinc-100 dark:border-white/5 z-30">

        {/* Left: Preview Animation Button */}
        <button
          onClick={togglePreview}
          disabled={waypoints.length === 0 || isListEditMode || isRendering}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md font-bold text-[10px] transition-all disabled:opacity-40 disabled:pointer-events-none ${isPreviewing
            ? "bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-400"
            : "text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            }`}
        >
          {isPreviewing ? (
            <><Square className="w-3 h-3 fill-current" /> Stop Preview</>
          ) : (
            <><Play className="w-3 h-3 fill-current" /> Preview</>
          )}
        </button>

        {/* Right: Render Video Button */}
        <button
          onClick={handleRenderVideo}
          disabled={waypoints.length === 0 || isListEditMode || isRendering || isPreviewing}
          className="flex items-center justify-center py-1.5 px-3 rounded-md bg-zinc-900 dark:bg-zinc-100 hover:bg-zinc-800 dark:hover:bg-white text-white dark:text-zinc-900 font-bold text-[10px] transition-all disabled:opacity-40 disabled:pointer-events-none shadow-sm"
        >
          {isRendering ? (
            <span className="flex items-center gap-1.5">
              <div className="w-3 h-3 border-[1.5px] border-zinc-500 border-t-zinc-200 dark:border-zinc-400 dark:border-t-zinc-800 rounded-full animate-spin" />
              Rendering...
            </span>
          ) : (
            <>Render Video <ChevronRight className="w-3 h-3 opacity-60 ml-0.5" /></>
          )}
        </button>
      </div>
    </aside>
  );
}