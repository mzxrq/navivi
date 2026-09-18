import { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import {
  Trash2,
  Car,
  Footprints,
  Route,
  Ruler,
  Plane,
  Ship,
  Edit,
  Film,
} from "../../../components/ui/icons";
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
import { LocationSearch } from "../../../components/ui/LocationSearch";
import { OverviewPanel } from "./OverviewPanel";

export function Sidebar() {
  const { showToast, isRendering, setIsRendering } = useUI();

  const {
    waypoints,
    setWaypoints,
    saveProject,
    activeWaypointId,
    setActiveWaypointId,
    forceReroute,
    setIsDirty,
    settings,
    updateSettings,
    routeSegments,
  } = useWorkspace();

  const [isListEditMode, setIsListEditMode] = useState(false);
  const [showClearConfirm, setShowClearConfirm] = useState(false);

  const [showGenerateConfirm, setShowGenerateConfirm] = useState(false);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const sidebarRef = useRef<HTMLElement>(null);

  const handleCloseEditor = () => {
    setActiveWaypointId(null);
  };

  useEffect(() => {
    const handlePreviewFinish = () => setIsPreviewing(false);
    window.addEventListener("preview-finished", handlePreviewFinish);
    return () =>
      window.removeEventListener("preview-finished", handlePreviewFinish);
  }, []);

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

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (showGenerateConfirm) {
          setShowGenerateConfirm(false);
        } else if (activeWaypointId) {
          handleCloseEditor();
        }
      }
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [showGenerateConfirm, activeWaypointId]);

  const handleGenerateClick = async () => {
    if (waypoints.length === 0) {
      showToast("Cannot generate: Please add at least one waypoint.", "error");
      return;
    }
    setShowGenerateConfirm(true);
  };

  const executeGenerate = async () => {
    setShowGenerateConfirm(false);
    await saveProject(); // ✨ Settings are already updated by the checkbox below
    setIsRendering(true);
  };

  const handleDragEnd = (result: DropResult) => {
    if (!result.destination) return;
    if (result.source.index === result.destination.index) return;

    const newWaypoints = Array.from(waypoints);
    const [reorderedItem] = newWaypoints.splice(result.source.index, 1);
    newWaypoints.splice(result.destination.index, 0, reorderedItem);

    setWaypoints(newWaypoints);
  };

  const handleReverseRoute = () => {
    if (waypoints.length < 2) return;
    setWaypoints([...waypoints].reverse());
    if (setIsDirty) setIsDirty(true);
    showToast("Route reversed successfully.", "info");
  };

  return (
    <aside
      ref={sidebarRef}
      className="pt-10 w-90 shrink-0 bg-white dark:bg-[#09090b] border-r border-zinc-200 dark:border-white/5 flex flex-col h-full select-none z-100 relative shadow-2xl transition-colors"
    >
      <div className="sticky top-0 z-30 bg-white/80 dark:bg-[#09090b]/80 backdrop-blur-xl border-b border-zinc-100 dark:border-white/5 p-4 shrink-0 flex flex-col gap-4">
        <LocationSearch />
        <OverviewPanel />
      </div>

      {/* --- SCROLLABLE TIMELINE --- */}
      <div className="flex-1 flex flex-col min-h-0">
        {waypoints.length === 0 ? (
          <div className="p-8 mt-10 mx-5 rounded-2xl border border-dashed border-zinc-300 dark:border-white/10 bg-black/5 dark:bg-white/5 text-center shrink-0 transition-colors animate-in fade-in">
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

      {/* --- FOOTER TOOLBAR --- */}
      <div className="shrink-0 px-4 py-3 flex items-center justify-between gap-3 bg-white/90 dark:bg-[#09090b]/90 backdrop-blur-xl border-t border-zinc-100 dark:border-white/5 z-30">
        {waypoints.length > 0 && (
          <div className="flex items-center bg-black/5 dark:bg-white/5 rounded-full p-1 border border-black/5 dark:border-white/5 transition-all shrink-0">
            <button
              onClick={() => {
                setIsListEditMode(!isListEditMode);
                setShowClearConfirm(false);
              }}
              disabled={waypoints.length === 0 || isRendering || isPreviewing}
              title={isListEditMode ? "Done Editing" : "Edit List"}
              className={`w-7 h-7 rounded-full flex items-center justify-center transition-colors ${
                isListEditMode
                  ? "bg-navi text-white shadow-md"
                  : "text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-200 hover:bg-white dark:hover:bg-zinc-800"
              }`}
            >
              <Edit className="w-3.5 h-3.5" />
            </button>

            <div className="w-px h-4 bg-black/10 dark:bg-white/10 mx-1" />

            <div
              className={`flex items-center overflow-hidden transition-all duration-300 ease-out ${showClearConfirm ? "max-w-32 opacity-100" : "max-w-10"}`}
            >
              {!showClearConfirm ? (
                <button
                  onClick={() => setShowClearConfirm(true)}
                  disabled={
                    waypoints.length === 0 || isRendering || isPreviewing
                  }
                  title="Clear Entire Route"
                  className="w-7 h-7 text-zinc-500 hover:text-red-500 dark:text-zinc-400 dark:hover:text-red-400 rounded-full hover:bg-white dark:hover:bg-zinc-800 transition-colors flex items-center justify-center shrink-0"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              ) : (
                <div className="flex items-center gap-1.5 px-1.5 h-7 animate-in fade-in slide-in-from-right-2">
                  <button
                    onClick={() => setShowClearConfirm(false)}
                    className="px-2 h-full text-[10px] font-bold text-zinc-500 hover:bg-black/5 dark:hover:bg-white/10 rounded-full transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => {
                      setWaypoints([]);
                      setIsListEditMode(false);
                      setShowClearConfirm(false);
                    }}
                    className="px-2 h-full text-[10px] font-bold text-white bg-red-500 hover:bg-red-600 rounded-full transition-colors shadow-sm"
                  >
                    Clear
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Generate Primary Action */}
        <button
          onClick={handleGenerateClick}
          disabled={
            waypoints.length === 0 ||
            isListEditMode ||
            isRendering ||
            isPreviewing
          }
          className="flex items-center justify-center gap-2 py-1.5 px-4 rounded-full bg-navi hover:bg-navi-600 text-white font-bold text-[11px] transition-all disabled:opacity-30 disabled:pointer-events-none shadow-md shadow-navi/20"
        >
          {isRendering ? (
            <>
              <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Generating...
            </>
          ) : (
            <>
              <Film className="w-3.5 h-3.5 fill-current" /> Generate Assets
            </>
          )}
        </button>
      </div>

      {showGenerateConfirm &&
        createPortal(
          <div className="fixed inset-0 z-99999 bg-zinc-950/40 backdrop-blur-[2px] flex items-center justify-center p-4 animate-in fade-in duration-200">
            <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 rounded-2xl shadow-2xl w-full max-w-sm overflow-hidden animate-in zoom-in-95 duration-200">
              <div className="p-5">
                <h3 className="text-base font-bold text-zinc-900 dark:text-white mb-2">
                  Ready to Generate?
                </h3>
                <p className="text-xs text-zinc-500 dark:text-zinc-400 leading-relaxed">
                  This will save your project, synthesize AI voiceovers, and
                  render map videos before opening the Timeline.
                </p>

                {/* ✨ NEW: Skip Rich Media Toggle */}
                <label className="flex items-start gap-2.5 mt-5 cursor-pointer group">
                  <input
                    type="checkbox"
                    className="mt-0.5 w-4 h-4 rounded border-zinc-300 text-navi focus:ring-navi bg-white dark:bg-zinc-800 dark:border-zinc-700 transition-colors cursor-pointer"
                    checked={settings.skip_rich_media || false}
                    onChange={(e) => {
                      updateSettings({ skip_rich_media: e.target.checked });
                      if (setIsDirty) setIsDirty(true);
                    }}
                  />
                  <div className="flex flex-col gap-0.5">
                    <span className="text-sm font-bold text-zinc-800 dark:text-zinc-200 group-hover:text-navi transition-colors">
                      Skip Rich Media (Fast Render)
                    </span>
                    <span className="text-[10px] text-zinc-500 dark:text-zinc-400 leading-tight">
                      Generates the map route only. Ignores all pop-up images
                      and AI voice synthesis to save time.
                    </span>
                  </div>
                </label>
              </div>

              <div className="p-4 bg-zinc-50 dark:bg-black/20 border-t border-zinc-100 dark:border-white/5 flex items-center justify-end gap-3">
                <button
                  onClick={() => setShowGenerateConfirm(false)}
                  className="px-4 py-2 text-xs font-bold text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={executeGenerate}
                  className="px-4 py-2 bg-navi hover:bg-navi-600 text-white text-xs font-bold rounded-lg shadow-md transition-colors"
                >
                  Generate Assets
                </button>
              </div>
            </div>
          </div>,
          document.body,
        )}
    </aside>
  );
}
