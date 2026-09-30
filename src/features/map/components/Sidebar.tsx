import { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { Route, Film, Trash2 } from "../../../components/ui/icons";
import {
  DragDropContext,
  Droppable,
  Draggable,
  DropResult,
} from "@hello-pangea/dnd";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useUI } from "../../../hooks/useUI";
import { WaypointItem } from "./WaypointItem";
import { LocationSearch } from "../../../components/ui/LocationSearch";
import { OverviewPanel } from "./OverviewPanel";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";

export function Sidebar() {
  const {
    showToast,
    isRendering,
    setIsRendering,
    isRenderCollapsed,
    setIsRenderCollapsed,
  } = useUI();

  const {
    waypoints,
    setWaypoints,
    saveProject,
    activeWaypointId,
    setActiveWaypointId,
    setIsDirty,
    settings,
    updateSettings,
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
    if (isRenderCollapsed) {
      setIsRenderCollapsed(false);
      await saveProject();
      setIsRendering(true);
      return;
    }
    if (waypoints.length === 0) {
      showToast(t`Cannot generate: Please add at least one waypoint.`, "error");
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

  const exitEditMode = () => {
    setIsListEditMode(false);
    setShowClearConfirm(false);
  };

  const stopCount = waypoints.filter((w) => !w.isStopBy).length;
  const stopByCount = waypoints.length - stopCount;
  const canEditList = waypoints.length > 0 && !isRendering && !isPreviewing;

  return (
    <aside
      ref={sidebarRef}
      className="pt-10 w-90 shrink-0 bg-zinc-50 dark:bg-[#09090b] border-r border-zinc-200 dark:border-white/5 flex flex-col h-full select-none z-100 relative transition-colors"
    >
      {isRendering && <div className="absolute inset-0 z-60 cursor-not-allowed" />}

      <div className="px-3 pt-3 pb-2 shrink-0">
        <LocationSearch />
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar px-3 pb-3">
        <div className="pt-1 pb-3">
          <OverviewPanel />
        </div>

        <div className="sticky top-0 z-30 -mx-3 px-4 py-2 bg-zinc-50/90 dark:bg-[#09090b]/90 backdrop-blur-md flex items-center gap-2">
          <h2 className="text-[12px] font-semibold text-zinc-900 dark:text-zinc-100">
            <Trans>Route</Trans>
          </h2>
          {waypoints.length > 0 && (
            <span className="text-[11px] text-zinc-500 tabular-nums">
              {stopByCount > 0 ? (
                <Trans>
                  {stopCount} stops · {stopByCount} stop-by
                </Trans>
              ) : (
                <Trans>{stopCount} stops</Trans>
              )}
            </span>
          )}
          {waypoints.length > 0 && !isListEditMode && (
            <button
              type="button"
              onClick={() => setIsListEditMode(true)}
              disabled={!canEditList}
              className="ml-auto h-6 px-2 rounded-md text-[11px] font-medium text-zinc-500 hover:text-zinc-900 hover:bg-zinc-200/60 dark:hover:text-zinc-100 dark:hover:bg-white/5 transition-colors disabled:opacity-40 disabled:pointer-events-none"
            >
              <Trans>Edit</Trans>
            </button>
          )}
        </div>

        {waypoints.length === 0 ? (
          <div className="mt-2 px-6 py-10 rounded-lg border border-dashed border-zinc-300 dark:border-white/10 text-center animate-in fade-in">
            <Route className="w-6 h-6 mb-3 mx-auto text-zinc-400" />
            <p className="text-[13px] font-medium text-zinc-700 dark:text-zinc-300">
              <Trans>No stops added yet</Trans>
            </p>
            <p className="text-[11px] text-zinc-500 mt-1 leading-relaxed">
              <Trans>Click the map or drop a GPS file to start building your route</Trans>
            </p>
          </div>
        ) : (
          <DragDropContext onDragEnd={handleDragEnd}>
            <Droppable droppableId="waypoints-list">
              {(provided) => (
                <div
                  className="flex flex-col"
                  {...provided.droppableProps}
                  ref={provided.innerRef}
                >
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
                          className={`rounded-lg ${
                            snapshot.isDragging
                              ? "z-50 bg-white dark:bg-zinc-900 shadow-lg ring-1 ring-black/5 dark:ring-white/10"
                              : ""
                          }`}
                          style={provided.draggableProps.style}
                        >
                          <WaypointItem
                            wp={wp}
                            index={i}
                            isListEditMode={isListEditMode}
                            isFirst={i === 0}
                            isLast={i === waypoints.length - 1}
                            onEdit={() => setActiveWaypointId(wp.id)}
                            onDelete={() =>
                              setWaypoints(waypoints.filter((w) => w.id !== wp.id))
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

      <div className="shrink-0 px-3 py-3 border-t border-zinc-200 dark:border-white/5 bg-zinc-50 dark:bg-[#09090b]">
        {isListEditMode ? (
          showClearConfirm ? (
            <div className="flex items-center gap-2 animate-in fade-in duration-150">
              <span className="flex-1 text-[12px] text-zinc-600 dark:text-zinc-400 truncate">
                <Trans>Remove all {waypoints.length} stops?</Trans>
              </span>
              <button
                type="button"
                onClick={() => setShowClearConfirm(false)}
                className="h-8 px-3 rounded-md text-[12px] font-medium text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200/70 dark:hover:bg-white/5 transition-colors"
              >
                <Trans>Cancel</Trans>
              </button>
              <button
                type="button"
                onClick={() => {
                  setWaypoints([]);
                  exitEditMode();
                }}
                className="h-8 px-3 rounded-md text-[12px] font-semibold text-white bg-red-500 hover:bg-red-600 transition-colors"
              >
                <Trans>Clear</Trans>
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setShowClearConfirm(true)}
                disabled={!canEditList}
                className="h-8 px-2.5 rounded-md text-[12px] font-medium text-red-500 hover:bg-red-500/10 transition-colors flex items-center gap-1.5 disabled:opacity-40"
              >
                <Trash2 className="w-3.5 h-3.5" />
                <Trans>Clear route</Trans>
              </button>
              <button
                type="button"
                onClick={exitEditMode}
                className="ml-auto h-8 px-4 rounded-md text-[12px] font-semibold bg-zinc-900 text-white hover:bg-zinc-800 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white transition-colors"
              >
                <Trans>Done</Trans>
              </button>
            </div>
          )
        ) : (
          <button
            type="button"
            onClick={handleGenerateClick}
            disabled={
              waypoints.length === 0 ||
              (isRendering && !isRenderCollapsed) ||
              isPreviewing
            }
            className={`w-full h-9 rounded-lg flex items-center justify-center gap-2 text-[13px] font-semibold text-white transition-colors disabled:opacity-40 disabled:pointer-events-none ${
              isRenderCollapsed
                ? "bg-amber-500 hover:bg-amber-600"
                : "bg-navi hover:brightness-110"
            }`}
          >
            {isRenderCollapsed ? (
              <>
                <Film className="w-4 h-4" /> <Trans>Resume Generation</Trans>
              </>
            ) : isRendering ? (
              <>
                <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                <Trans>Generating...</Trans>
              </>
            ) : (
              <>
                <Film className="w-4 h-4" /> <Trans>Generate Assets</Trans>
              </>
            )}
          </button>
        )}
      </div>

      {showGenerateConfirm &&
        createPortal(
          <div className="fixed inset-0 z-99999 bg-zinc-950/40 backdrop-blur-[2px] flex items-center justify-center p-4 animate-in fade-in duration-200">
            <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 rounded-xl shadow-2xl w-full max-w-sm overflow-hidden animate-in zoom-in-95 duration-200">
              <div className="p-5">
                <h3 className="text-[15px] font-semibold text-zinc-900 dark:text-white mb-1.5">
                  <Trans>Ready to Generate?</Trans>
                </h3>
                <p className="text-[12px] text-zinc-500 dark:text-zinc-400 leading-relaxed">
                  <Trans>This will save your project, synthesize AI voiceovers, and render map videos before opening the Timeline.</Trans>
                </p>

                <div className="mt-4 space-y-1">
                  <label className="flex items-start gap-2.5 p-2 -mx-2 rounded-lg cursor-pointer hover:bg-zinc-50 dark:hover:bg-white/5 transition-colors">
                    <input
                      type="checkbox"
                      className="mt-0.5 w-4 h-4 rounded border-zinc-300 accent-navi cursor-pointer"
                      checked={settings.skip_rich_media || false}
                      onChange={(e) => {
                        updateSettings({ skip_rich_media: e.target.checked });
                        if (setIsDirty) setIsDirty(true);
                      }}
                    />
                    <span className="flex flex-col gap-0.5">
                      <span className="text-[13px] font-medium text-zinc-800 dark:text-zinc-200">
                        <Trans>Skip Rich Media (Fast Render)</Trans>
                      </span>
                      <span className="text-[11px] text-zinc-500 dark:text-zinc-400 leading-snug">
                        <Trans>Generates the map route only. Ignores all pop-up images and AI voice synthesis to save time.</Trans>
                      </span>
                    </span>
                  </label>

                  <label className="flex items-start gap-2.5 p-2 -mx-2 rounded-lg cursor-pointer hover:bg-zinc-50 dark:hover:bg-white/5 transition-colors">
                    <input
                      type="checkbox"
                      className="mt-0.5 w-4 h-4 rounded border-zinc-300 accent-navi cursor-pointer"
                      checked={settings.quick_export || false}
                      onChange={(e) => {
                        updateSettings({ quick_export: e.target.checked });
                        if (setIsDirty) setIsDirty(true);
                      }}
                    />
                    <span className="flex flex-col gap-0.5">
                      <span className="text-[13px] font-medium text-zinc-800 dark:text-zinc-200">
                        <Trans>Quick Export (Auto-stitch & Export)</Trans>
                      </span>
                      <span className="text-[11px] text-zinc-500 dark:text-zinc-400 leading-snug">
                        <Trans>Automatically stitch all video segments and export upon completion without pausing for asset review</Trans>
                      </span>
                    </span>
                  </label>
                </div>
              </div>

              <div className="px-5 py-3 bg-zinc-50 dark:bg-black/20 border-t border-zinc-100 dark:border-white/5 flex items-center justify-end gap-2">
                <button
                  onClick={() => setShowGenerateConfirm(false)}
                  className="h-8 px-3 text-[12px] font-medium text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200/70 dark:hover:bg-white/5 rounded-md transition-colors"
                >
                  <Trans>Cancel</Trans>
                </button>
                <button
                  onClick={executeGenerate}
                  className="h-8 px-4 bg-navi hover:brightness-110 text-white text-[12px] font-semibold rounded-md transition-colors"
                >
                  <Trans>Generate Assets</Trans>
                </button>
              </div>
            </div>
          </div>,
          document.body,
        )}
    </aside>
  );
}
