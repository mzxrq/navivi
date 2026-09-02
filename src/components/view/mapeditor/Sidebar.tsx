import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useState, useEffect, useRef } from "react";
import {
  ChevronRight,
  Trash2,
  Car,
  Footprints,
  Route,
  Ruler,
  Plane,
  Play,
  Square,
  Ship,
  Edit,
  RefreshCw,
} from "../../ui/icons";
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
import { OverviewPanel } from "./OverviewPanel";

export function Sidebar() {
  const { showToast, setEditorMode } = useUI();
  const {
    waypoints,
    setWaypoints,
    metadata,
    saveProject,
    activeWaypointId,
    setActiveWaypointId,
    forceReroute,
  } = useWorkspace();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [isListEditMode, setIsListEditMode] = useState(false);
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [isRendering, setIsRendering] = useState(false);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const sidebarRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (activeWaypointId) {
      setEditingId(activeWaypointId);
    }
  }, [activeWaypointId]);

  const handleCloseEditor = () => {
    setEditingId(null);
    setActiveWaypointId(null);
  };

  useEffect(() => {
    const handlePreviewFinish = () => setIsPreviewing(false);
    window.addEventListener("preview-finished", handlePreviewFinish);
    return () =>
      window.removeEventListener("preview-finished", handlePreviewFinish);
  }, []);

  const togglePreview = () => {
    if (isPreviewing) {
      window.dispatchEvent(new Event("stop-preview"));
      setIsPreviewing(false);
    } else {
      window.dispatchEvent(new Event("start-preview"));
      setIsPreviewing(true);
    }
  };

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
  // Renamed to better reflect its new purpose!
  const handleGenerate = async () => {
    if (waypoints.length === 0) {
      showToast("Cannot generate: Please add at least one waypoint.", "error");
      return;
    }

    if (
      !confirm(
        "Ready to generate assets? This will create your voiceovers and map videos before opening the timeline.",
      )
    ) {
      return;
    }

    await saveProject();

    try {
      setIsRendering(true); // Overlay turns ON

      const configPath = `${metadata.directory_path}/job_config.json`;

      // 1. Set up listeners for the background events BEFORE we start the render
      await new Promise<void>((resolve, reject) => {
        let unlistenFinish: () => void;
        let unlistenLog: () => void;
        let unlistenErr: () => void; // Add this!

        // Listen for standard logs
        listen<string>("render-log", (event) => {
          console.log("[Python]:", event.payload);
        }).then((un) => (unlistenLog = un));

        // 🛠️ ADD THIS: Listen to stderr (This is where tqdm progress bars and errors actually go!)
        listen<string>("render-error", (event) => {
          console.log("[Progress/Error]:", event.payload);
        }).then((un) => (unlistenErr = un));

        // Listen for the actual Finish line
        listen<string>("render-finish", (event) => {
          if (event.payload === "Success") {
            resolve();
          } else {
            reject("Python pipeline failed. Check the console.");
          }

          if (unlistenFinish) unlistenFinish();
          if (unlistenLog) unlistenLog();
          if (unlistenErr) unlistenErr(); // Clean it up
        }).then((un) => (unlistenFinish = un));

        // 2. Start the process
        invoke("start_render", { configPath: configPath }).catch((err) => {
          reject(err);
        });
      });

      // 3. THIS ONLY RUNS WHEN PYTHON IS 100% DONE NOW!
      showToast("Assets generated successfully!", "success");
      setEditorMode("timeline");
    } catch (error) {
      showToast(`Render Error: ${error}`, "error");
    } finally {
      setIsRendering(false); // Overlay turns OFF
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

  // If editingId is set, render the WaypointEditor
  if (editingId) {
    return <WaypointEditor wpId={editingId} onClose={handleCloseEditor} />;
  }

  return (
    <aside
      ref={sidebarRef}
      className="w-85 shrink-0 bg-white dark:bg-navidark-800 border-r border-zinc-200 dark:border-white/8 flex flex-col h-full select-none z-10 relative shadow-xl transition-colors"
    >
      <div className="sticky top-0 z-30 bg-white/95 dark:bg-navidark-800/95 backdrop-blur-md border-b border-zinc-200 dark:border-white/5 p-5 shrink-0 flex flex-col gap-4">
        <LocationSearch />
        <OverviewPanel />
      </div>

      {/* --- SCROLLABLE TIMELINE --- */}
      <div className="flex-1 flex flex-col min-h-0">
        {waypoints.length === 0 ? (
          <div className="p-8 mt-10 mx-5 rounded-2xl border border-dashed border-zinc-300 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-800/20 text-center shrink-0 transition-colors animate-in fade-in">
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
                  {/* Clear All & Confirm UI */}
                  {isListEditMode && (
                    <div className="relative mb-4 shrink-0 z-20">
                      {!showClearConfirm ? (
                        <button
                          onClick={() => setShowClearConfirm(true)}
                          className="w-full py-2.5 rounded-xl border border-red-200 dark:border-red-500/20 bg-red-50 dark:bg-red-500/5 text-red-600 dark:text-red-400 text-xs font-bold hover:bg-red-100 dark:hover:bg-red-500/10 transition-colors flex items-center justify-center shadow-sm"
                        >
                          <Trash2 className="w-3.5 h-3.5 mr-2" /> Clear All
                          Waypoints
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
                              onEdit={() => {
                                setActiveWaypointId(wp.id);
                                setEditingId(wp.id);
                              }}
                              onDelete={() =>
                                setWaypoints(
                                  waypoints.filter((w) => w.id !== wp.id),
                                )
                              }
                            />

                            {/* --- TRANSPORT MODE CONNECTOR --- */}
                            {!isLast && !isListEditMode && (
                              <div className="relative h-0 z-20 w-full pointer-events-none">
                                <div className="absolute -top-3 left-7 -translate-x-1/2">
                                  <div className="w-5 h-5 bg-zinc-100 dark:bg-zinc-800 border-2 border-white dark:border-zinc-950 rounded-full flex items-center justify-center text-zinc-500 dark:text-zinc-400 shadow-sm transition-colors">
                                    {wp.routeMode === "walking" ? (
                                      <Footprints className="w-2.5 h-2.5" />
                                    ) : wp.routeMode === "driving" ? (
                                      <Car className="w-2.5 h-2.5" />
                                    ) : wp.routeMode === "curve" ? (
                                      <Plane className="w-2.5 h-2.5" />
                                    ) : wp.routeMode === "ferry" ? (
                                      <Ship className="w-2.5 h-2.5" />
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
      <div className="shrink-0 px-2.5 py-1.75 flex items-center justify-between bg-white dark:bg-zinc-950 border-t border-zinc-100 dark:border-white/5 z-30">
        {/* Left: Preview Animation Button */}
        {/* <button
          onClick={togglePreview}
          disabled={waypoints.length === 0 || isListEditMode || isRendering}
          className={`flex items-center gap-1 px-2 py-1 rounded-md font-bold text-[10px] transition-all disabled:opacity-40 disabled:pointer-events-none ${
            isPreviewing
              ? "bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-400"
              : "text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800"
          }`}
        >
          {isPreviewing ? (
            <>
              <Square className="w-3 h-3 fill-current" /> Stop Preview
            </>
          ) : (
            <>
              <Play className="w-3 h-3 fill-current" /> Preview
            </>
          )}
        </button> */}
        {waypoints.length > 0 && (
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                setIsListEditMode(!isListEditMode);
                setShowClearConfirm(false);
              }}
              disabled={
                waypoints.length === 0 ||
                isRendering ||
                isPreviewing
              }
              className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-colors shadow-sm ${
                isListEditMode
                  ? "bg-navi-100 text-navi dark:bg-navi/20 dark:text-navi-200 border border-navi-200 dark:border-navi/30"
                  : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800 border border-transparent"
              }`}
            >
              {isListEditMode ? (
                <span className="inline-flex items-center gap-1.5 text-[12px]">
                  <Edit className="w-2.5 h-2.5" /> Done Editing
                </span>
              ) : (
                <span className="inline-flex items-baseline gap-1.5 text-[12px]">
                  <Edit className="w-2.5 h-2.5" /> Edit List
                </span>
              )}
            </button>
            <button onClick={forceReroute} title="Refresh waypoint">
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Right: Render Video Button */}
        <button
          onClick={handleGenerate}
          disabled={
            waypoints.length === 0 ||
            isListEditMode ||
            isRendering ||
            isPreviewing
          }
          className="flex items-center justify-center py-1 px-1.5 rounded-md bg-zinc-900 dark:bg-zinc-100 hover:bg-zinc-800 dark:hover:bg-white text-white dark:text-zinc-900 font-bold text-[10px] transition-all disabled:opacity-40 disabled:pointer-events-none shadow-sm"
        >
          {isRendering ? (
            <span className="flex items-center gap-1.5">
              <div className="w-1.5 h-1.5 border-[1.5px] border-zinc-500 border-t-zinc-200 dark:border-zinc-400 dark:border-t-zinc-800 rounded-sm animate-spin" />
              Rendering...
            </span>
          ) : (
            <>
              Generate <ChevronRight className="w-3 h-3 opacity-60 ml-0.5" />
            </>
          )}
        </button>
      </div>
    </aside>
  );
}
