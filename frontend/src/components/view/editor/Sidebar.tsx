import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useState, useEffect, useRef } from "react";
import { Layers, ChevronRight, Trash2 } from "lucide-react";
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
  const { waypoints, setWaypoints, metadata, saveProject } = useWorkspace();

  const [editingId, setEditingId] = useState<string | null>(null);
  const [isListEditMode, setIsListEditMode] = useState(false);
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [isRendering, setIsRendering] = useState(false);
  const sidebarRef = useRef<HTMLElement>(null);

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
    if (!result.destination) return; // Dropped outside the list
    if (result.source.index === result.destination.index) return; // Didn't change position

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

  // If normal, render List UI
  return (
    <aside
      ref={sidebarRef}
      className="w-85 shrink-0 bg-white dark:bg-zinc-950 border-r border-zinc-200 dark:border-white/8 flex flex-col p-6 h-full select-none z-10 relative shadow-xl transition-colors gap-6"
    >
      <div className="flex-1 flex flex-col min-h-0 space-y-3">
        {/* Header Block (Keep as is) */}
        <LocationSearch />

        <div className="flex justify-between items-center px-1 shrink-0">
          <h2 className="text-[11px] font-bold text-zinc-500 uppercase tracking-widest flex items-center gap-2">
            <Layers className="w-3.5 h-3.5" /> Waypoints ({waypoints.length})
          </h2>
          {waypoints.length > 0 && (
            <button
              onClick={() => {
                setIsListEditMode(!isListEditMode);
                setShowClearConfirm(false);
              }}
              className={`text-[10px] font-semibold transition-colors px-2 py-0.5 rounded-md ${isListEditMode ? "bg-zinc-200 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-200" : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-300"}`}
            >
              {isListEditMode ? "Done" : "Edit"}
            </button>
          )}
        </div>

        {waypoints.length === 0 ? (
          <div className="group rounded-2xl border border-dashed border-zinc-300 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/20 p-8 text-center shrink-0 transition-colors">
            <p className="text-sm font-medium text-zinc-500">
              Click the map to drop markers
            </p>
          </div>
        ) : (
          <DragDropContext onDragEnd={handleDragEnd}>
            <Droppable droppableId="waypoints-list">
              {(provided) => (
                <div
                  className="flex-1 overflow-y-auto pr-2 custom-scrollbar space-y-2 pb-4"
                  {...provided.droppableProps}
                  ref={provided.innerRef}
                >
                  {isListEditMode && (
                    <div className="relative mb-3 shrink-0">
                      {!showClearConfirm ? (
                        <button
                          onClick={() => setShowClearConfirm(true)}
                          className="w-full py-2.5 rounded-xl border border-red-200 dark:border-red-500/20 bg-red-50 dark:bg-red-500/5 text-red-600 dark:text-red-400 text-xs font-bold hover:bg-red-100 dark:hover:bg-red-500/10 transition-colors flex items-center justify-center gap-2"
                        >
                          <Trash2 className="w-3.5 h-3.5" /> Clear All
                        </button>
                      ) : (
                        <div className="w-full py-2 px-3 rounded-xl border border-red-300 dark:border-red-500/40 bg-white dark:bg-zinc-900 shadow-sm flex items-center justify-between animate-in fade-in zoom-in-95 duration-200">
                          <span className="text-[11px] font-semibold text-zinc-800 dark:text-zinc-300">
                            Are you sure?
                          </span>
                          <div className="flex items-center gap-2">
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

                  {waypoints.map((wp, i) => (
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
                            ${snapshot.isDragging ? "shadow-2xl z-50 opacity-90 scale-[1.02]" : "shadow-none"}
                          `}
                          style={provided.draggableProps.style}
                        >
                          <WaypointItem
                            wp={wp}
                            index={i}
                            isListEditMode={isListEditMode}
                            isFirst={i === 0}
                            isLast={i === waypoints.length - 1}
                            onEdit={() => setEditingId(wp.id)}
                            onDelete={() =>
                              setWaypoints(
                                waypoints.filter((w) => w.id !== wp.id),
                              )
                            }
                          />
                        </div>
                      )}
                    </Draggable>
                  ))}
                  {provided.placeholder}
                </div>
              )}
            </Droppable>
          </DragDropContext>
        )}
      </div>

      <div className="shrink-0 pt-2 flex flex-col gap-2">
        <button
          onClick={handleRenderVideo}
          disabled={waypoints.length === 0 || isListEditMode}
          className="w-full flex items-center justify-center gap-2 py-3 px-4 rounded-xl bg-zinc-900 dark:bg-zinc-900 hover:bg-zinc-800 text-zinc-100 dark:text-zinc-400 dark:hover:text-zinc-200 border border-transparent dark:border-white/5 dark:hover:border-white/10 font-medium text-sm transition-all disabled:opacity-40 disabled:pointer-events-none shadow-md dark:shadow-none"
        >
          Render Video <ChevronRight className="w-4 h-4 opacity-50" />
        </button>
      </div>
    </aside>
  );
}
