import { useEffect, useRef, useState } from "react";
import {
  Car,
  ChevronRight,
  Edit2,
  Footprints,
  GripVertical,
  ImageIcon,
  Mic,
  Pencil,
  Plane,
  Ruler,
  Ship,
  X,
  Navigation,
  Route,
} from "../../../components/ui/icons";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useUI } from "../../../hooks/useUI";
import { RouteMode, Waypoint } from "../../../types/index";

interface WaypointItemProps {
  wp: Waypoint;
  index: number;
  isListEditMode: boolean;
  isFirst: boolean;
  isLast: boolean;
  onEdit: () => void;
  onDelete: () => void;
}

export function WaypointItem({
  wp,
  index,
  isListEditMode,
  isFirst,
  isLast,
  onEdit,
  onDelete,
}: WaypointItemProps) {
  const { activeWaypointId, setActiveWaypointId, updateWaypoint, waypoints } = useWorkspace();
  const { isRendering } = useUI();
  const itemRef = useRef<HTMLDivElement>(null);
  const [isExpanded, setIsExpanded] = useState(false);
  const [isModeExpanded, setIsModeExpanded] = useState(false);
  const isActive = activeWaypointId === wp.id;

  useEffect(() => {
    if (isActive && itemRef.current) {
      itemRef.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [isActive]);

  const handleSelect = () => {
    setActiveWaypointId(wp.id);
    onEdit();
  };

  let displayLabel = "";
  const isStart = index === 0;
  const isEnd = index === waypoints.length - 1 && waypoints.length > 1;

  if (isStart) {
    displayLabel = "S";
  } else if (isEnd) {
    displayLabel = "E";
  } else if (wp.isStopBy) {
    let stopByIndex = 0;
    for (let i = index; i >= 0; i--) {
      if (waypoints[i].isStopBy) stopByIndex++;
      else break;
    }
    displayLabel = `+${stopByIndex}`;
  } else {
    let normalIndex = 1;
    for (let i = 1; i < index; i++) {
      if (!waypoints[i].isStopBy) normalIndex++;
    }
    displayLabel = normalIndex.toString();
  }

  const hasScript = !!(
    wp.arrivingNarration ||
    wp.attractionNarration
  );
  const scriptPreview =
    wp.arrivingNarration || wp.attractionNarration || "";

  return (
    <div
      ref={itemRef}
      onClick={() => {
        if (!isListEditMode) {
          handleSelect();
        }
      }}
      onContextMenu={(e) => {
        e.preventDefault();
        e.stopPropagation();
        if (isListEditMode) return;
        window.dispatchEvent(
          new CustomEvent("open-context-menu", {
            detail: {
              x: e.clientX,
              y: e.clientY,
              type: "waypoint-marker",
              targetId: wp.id,
            },
          }),
        );
      }}
      className={`relative flex items-stretch group transition-all px-2 py-1.5 rounded-xl border ${
        isListEditMode ? "cursor-default" : "cursor-pointer"
      } ${
        isActive
          ? "bg-white dark:bg-white/5 border-zinc-200 dark:border-white/10 shadow-sm"
          : "border-transparent hover:bg-white/50 dark:hover:bg-white/5"
      }`}
    >
      {/* 1. Delete Action */}
      {isListEditMode && (
        <button disabled={isRendering} onClick={(e) => { e.stopPropagation(); onDelete(); }}
          className="shrink-0 mx-2 flex items-center justify-center text-red-500 dark:text-red-400/70 hover:text-red-800 dark:hover:text-red-400 transition-all animate-in slide-in-from-left-2"
        >
          <div className="w-5 h-5 rounded-full bg-red-100 dark:bg-red-500/10 flex items-center justify-center">
            <X className="w-3.5 h-3.5" />
          </div>
        </button>
      )}

      {/* 2. Timeline Graphics */}
      {!isListEditMode && (
        <div className="relative flex flex-col items-center w-10 shrink-0">
          {!isFirst && (
            <div className="absolute top-0 left-1/2 -translate-x-1/2 w-0.5 h-4.5 bg-navi dark:bg-zinc-800 transition-colors" />
          )}

          {!isLast && (
            <div className="absolute top-4.5 bottom-0 left-1/2 -translate-x-1/2 w-0.5 bg-navi dark:bg-zinc-800 transition-colors" />
          )}

          <div
            className={`relative z-10 w-5 h-5 mt-1.75 rounded-full border-[2.5px] flex items-center justify-center shadow-sm transition-colors ${
              wp.isStopBy
                ? "bg-zinc-800 border-zinc-800 text-white"
                : isActive
                  ? "border-navi bg-navi text-white"
                  : "border-zinc-300 dark:border-zinc-700 bg-white dark:bg-[#09090b] text-zinc-700 dark:text-zinc-300"
            }`}
          >
            <span
              className={wp.isStopBy ? "text-[8px]" : "text-[9px] font-bold"}
            >
              {displayLabel}
            </span>
          </div>
        </div>
      )}

      {/* 3. Content Card */}
      <div className="flex-1 flex items-start justify-between min-w-0 py-1.5 pr-2">
        <div className="flex flex-col min-w-0 flex-1">
          <span
            className={`text-sm font-semibold truncate pr-4 transition-colors ${
              wp.isStopBy
                ? "text-zinc-500 dark:text-zinc-500"
                : "text-zinc-900 dark:text-white"
            }`}
            title={wp.name}
          >
            {wp.name}
          </span>

          {/* Collapsible Tree for Media/Script */}
          {(wp.images?.length || hasScript) && (
            <div className="mt-1.5 flex flex-col">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setIsExpanded(!isExpanded);
                }}
                className="flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-wider text-zinc-500 hover:text-navi-500 transition-colors"
              >
                <span
                  className={`transition-transform duration-200 inline-block ${isExpanded ? "rotate-90" : ""}`}
                >
                  <ChevronRight className="w-3.5 h-3.5" />
                </span>
                Assets & Media
              </button>

              {isExpanded && (
                <div className="pl-3 mt-1.5 ml-1 border-l border-zinc-200 dark:border-white/10 flex flex-col gap-1.5 text-[10px] text-zinc-600 dark:text-zinc-400">
                  {wp.images && wp.images.length > 0 && (
                    <div className="flex items-center gap-1.5">
                      <ImageIcon className="w-3 h-3 text-emerald-500" />
                      {wp.images.length} Image{wp.images.length > 1 ? "s" : ""}
                    </div>
                  )}
                  {hasScript && (
                    <div className="flex flex-col gap-0.5">
                      <div className="flex items-center gap-1.5">
                        <Mic className="w-3 h-3 text-navi-400" /> Voiceover
                        Script
                      </div>
                      <span className="pl-4.5 italic text-zinc-400 dark:text-zinc-500 truncate max-w-50">
                        "{scriptPreview.substring(0, 30)}..."
                      </span>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Minimal Inline Route Mode Selector */}
          {!isLast && (
            <div className="mt-2 flex items-center gap-2 flex-wrap">
              <div
                className="flex items-center bg-zinc-100 dark:bg-black/20 rounded-md p-0.5 border border-zinc-200 dark:border-white/5 cursor-pointer min-h-[22px]"
                onClick={(e) => {
                  e.stopPropagation();
                  setIsModeExpanded(!isModeExpanded);
                }}
                onMouseEnter={() => setIsModeExpanded(true)}
                onMouseLeave={() => setIsModeExpanded(false)}
              >
                {[
                  { id: "walking", icon: Footprints, title: "Walk" },
                  { id: "driving", icon: Car, title: "Drive" },
                  { id: "curve", icon: Plane, title: "Fly" },
                  { id: "direct", icon: Ruler, title: "Direct" },
                  { id: "ferry", icon: Ship, title: "Ferry" },
                  { id: "draw", icon: Pencil, title: "Draw" },
                ].map((mode) => {
                  const isModeActive = (wp.routeMode || "driving") === mode.id;
                  if (!isModeActive && !isModeExpanded) return null;
                  const Icon = mode.icon;
                  return (
                    <button
                      key={mode.id}
                      onClick={(e) => {
                        e.stopPropagation();
                        if (isModeActive && !isModeExpanded) {
                          setIsModeExpanded(true);
                        } else {
                          updateWaypoint(wp.id, {
                            routeMode: mode.id as RouteMode,
                          });
                          setIsModeExpanded(false);
                        }
                      }}
                      className={`p-1 rounded transition-colors ${
                        isModeActive
                          ? "bg-white dark:bg-white/10 text-navi-600 dark:text-white shadow-sm ring-1 ring-black/5 dark:ring-white/10"
                          : "text-zinc-400 dark:text-zinc-500 hover:text-zinc-600 dark:hover:text-zinc-300 hover:bg-black/5 dark:hover:bg-white/5"
                      }`}
                      title={mode.title}
                    >
                      <Icon className="w-3 h-3" />
                    </button>
                  );
                })}
              </div>

              {/* Via point adjust button + badge */}
              {(!wp.routeMode || wp.routeMode === "walking" || wp.routeMode === "driving" || wp.routeMode === "ferry") && (
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      window.dispatchEvent(
                        new CustomEvent("enter-via-mode", { detail: { wpId: wp.id } })
                      );
                    }}
                    className="p-1 rounded text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 dark:hover:text-zinc-200 dark:hover:bg-zinc-800 transition-colors"
                    title="Adjust Route (Add via points to nudge)"
                  >
                    <Route className="w-3.5 h-3.5" />
                  </button>
                  {wp.viaPoints && wp.viaPoints.length > 0 && (
                    <div className="flex items-center gap-1">
                      <span className="text-[9px] bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 px-1.5 py-0.5 rounded-full font-bold">
                        {wp.viaPoints.length} via
                      </span>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          updateWaypoint(wp.id, { viaPoints: [] });
                        }}
                        className="text-[9px] text-zinc-400 hover:text-red-500 transition-colors"
                        title="Clear all via points"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Hover Actions */}
        {!isListEditMode && (
          <div className="opacity-0 group-hover:opacity-100 flex items-center gap-0.5 transition-opacity shrink-0 mt-0.5">
            <button
              onClick={(e) => {
                e.stopPropagation();
                handleSelect();
              }}
              className="p-1.5 hover:bg-navi/60 dark:hover:bg-zinc-800 rounded-md text-zinc-400 hover:text-navi-800 dark:hover:text-navi transition-colors"
              title="Edit Stop"
            >
              <Edit2 className="w-3.5 h-3.5" />
            </button>
            <div
              onClick={(e) => e.stopPropagation()}
              className="p-1.5 text-zinc-300 dark:text-zinc-800 hover:text-zinc-500 cursor-grab active:cursor-grabbing transition-colors"
            >
              <GripVertical className="w-4 h-4" />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
