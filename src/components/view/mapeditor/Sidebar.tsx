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
  RefreshCw,
  Play // Added for UI completeness
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
  const {
    showToast,
    isRendering,
    setIsRendering,
  } = useUI();
  const {
    waypoints,
    setWaypoints,
    saveProject,
    activeWaypointId,
    setActiveWaypointId,
    forceReroute,
  } = useWorkspace();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [isListEditMode, setIsListEditMode] = useState(false);
  const [showClearConfirm, setShowClearConfirm] = useState(false);

  const [showGenerateConfirm, setShowGenerateConfirm] = useState(false);
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
      if (e.key === "Escape" && showGenerateConfirm) {
        setShowGenerateConfirm(false);
      }
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [showGenerateConfirm]);

  const handleGenerateClick = async () => {
    if (waypoints.length === 0) {
      showToast("Cannot generate: Please add at least one waypoint.", "error");
      return;
    }
    setShowGenerateConfirm(true);
  };
  
  const executeGenerate = async () => {
    setShowGenerateConfirm(false);
    await saveProject();
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

  if (editingId) {
    return <WaypointEditor wpId={editingId} onClose={handleCloseEditor} />;
  }

  return (
    <aside
      ref={sidebarRef}
      className="w-85 shrink-0 bg-white dark:bg-navidark-800 border-r border-zinc-200 dark:border-white/8 flex flex-col h-full select-none z-100 relative shadow-xl transition-colors"
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

      {/* --- ✨ REDESIGNED FOOTER / ACTION AREA --- */}
      <div className="shrink-0 p-4 flex flex-col gap-3 bg-white dark:bg-navidark-800 border-t border-zinc-200 dark:border-white/5 z-30 shadow-[0_-10px_30px_-15px_rgba(0,0,0,0.1)] dark:shadow-[0_-10px_30px_-15px_rgba(0,0,0,0.5)]">
        
        {waypoints.length > 0 && (
          <div className="flex items-center justify-between w-full">
            {/* List Tools Group */}
            <div className="flex items-center bg-zinc-100 dark:bg-zinc-900/50 rounded-lg p-1 border border-zinc-200/50 dark:border-white/5">
              <button
                onClick={() => {
                  setIsListEditMode(!isListEditMode);
                  setShowClearConfirm(false);
                }}
                disabled={waypoints.length === 0 || isRendering || isPreviewing}
                className={`px-3 py-1.5 text-[11px] font-bold rounded-md transition-colors ${
                  isListEditMode
                    ? "bg-navi-100 text-navi-700 dark:bg-navi-500/20 dark:text-navi-300 shadow-sm"
                    : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-200 hover:bg-white dark:hover:bg-zinc-800"
                }`}
              >
                <span className="flex items-center gap-1.5">
                  <Edit className="w-3 h-3" /> {isListEditMode ? "Done" : "Edit List"}
                </span>
              </button>
              <div className="w-px h-4 bg-zinc-300 dark:bg-zinc-700 mx-1" />
              <button 
                onClick={forceReroute} 
                title="Refresh Map Routing"
                className="p-1.5 text-zinc-500 hover:text-navi-500 dark:text-zinc-400 dark:hover:text-navi-400 rounded-md hover:bg-white dark:hover:bg-zinc-800 transition-colors"
              >
                <RefreshCw className="w-3.5 h-3.5" />
              </button>
            </div>
            
            <span className="text-[10px] font-bold text-zinc-400 uppercase tracking-widest px-2">
              {waypoints.length} Stop{waypoints.length !== 1 ? 's' : ''}
            </span>
          </div>
        )}

        {/* Generate Primary Action */}
        <button
          onClick={handleGenerateClick}
          disabled={waypoints.length === 0 || isListEditMode || isRendering || isPreviewing}
          className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-navi-500 hover:bg-navi-600 text-white font-bold text-xs transition-all disabled:opacity-40 disabled:pointer-events-none shadow-md hover:shadow-lg focus:ring-2 focus:ring-navi-500/50 focus:outline-none"
        >
          {isRendering ? (
            <>
              <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Building Assets...
            </>
          ) : (
            <>
              <Play className="w-3.5 h-3.5 fill-current" /> Build Video Timeline
            </>
          )}
        </button>
      </div>

      {showGenerateConfirm && createPortal(
        <div className="fixed inset-0 z-99999 bg-zinc-950/40 backdrop-blur-[2px] flex items-center justify-center p-4 animate-in fade-in duration-200">
          <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 rounded-2xl shadow-2xl w-full max-w-sm overflow-hidden animate-in zoom-in-95 duration-200">
            <div className="p-5">
              <h3 className="text-base font-bold text-zinc-900 dark:text-white mb-2">Ready to Generate?</h3>
              <p className="text-xs text-zinc-500 dark:text-zinc-400 leading-relaxed">
                This will save your project, synthesize AI voiceovers, and render map videos before opening the Timeline.
              </p>
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
                className="px-4 py-2 bg-navi-500 hover:bg-navi-600 text-white text-xs font-bold rounded-lg shadow-md transition-colors"
              >
                Generate Assets
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </aside>
  );
}