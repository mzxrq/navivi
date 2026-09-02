import {
  GripVertical,
  Edit2,
  X,
  ImageIcon,
  Mic,
  Car,
  Footprints,
  Ruler,
  Plane,
  Pencil,
} from "../../ui/icons";
import { Waypoint, RouteMode } from "../../../types";
import { useEffect, useRef } from "react";
import { useWorkspace } from "../../../hooks/useWorkspace";

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
  const { activeWaypointId, setActiveWaypointId, updateWaypoint } =
    useWorkspace();
  const itemRef = useRef<HTMLDivElement>(null);
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

  return (
    <div
      ref={itemRef}
      className={`relative flex items-stretch group transition-all px-2 py-1.5 rounded-xl border cursor-pointer ${
        isActive
          ? "bg-navi/60 dark:bg-navi/20 border-navi/50 dark:border-navi/40 ring-1 ring-navi/30"
          : "border-transparent hover:bg-zinc-50/80 dark:hover:bg-zinc-900/30"
      }`}
    >
      {/* 1. Delete Action (Edit Mode) */}
      {isListEditMode && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
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
          {/* Top connecting line */}
          {!isFirst && (
            <div className="absolute top-0 left-1/2 -translate-x-1/2 w-0.5 h-4.5 bg-navi dark:bg-zinc-800 transition-colors" />
          )}

          {/* Bottom connecting line */}
          {!isLast && (
            <div className="absolute top-4.5 bottom-0 left-1/2 -translate-x-1/2 w-0.5 bg-navi dark:bg-zinc-800 transition-colors" />
          )}

          {/* The Node */}
          <div
            className={`relative z-10 w-5 h-5 mt-2 rounded-full border-[2.5px] bg-navi dark:bg-navi flex items-center justify-center shadow-sm transition-colors ${
              isActive ? "border-navi bg-navi dark:bg-navi" : "border-navi"
            }`}
          >
            <span
              className={`text-[9px] font-bold ${
                isActive
                  ? "text-white dark:text-white"
                  : "text-white dark:text-white"
              }`}
            >
              {index + 1}
            </span>
          </div>
        </div>
      )}

      {/* 3. Content Card */}
      <div className="flex-1 flex items-start justify-between min-w-0 py-1.5 pr-2">
        <div className="flex flex-col min-w-0 flex-1">
          {/* Location Name */}
          <span
            className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 truncate pr-4 transition-colors"
            title={wp.name}
          >
            {wp.name}
          </span>

          {/* Micro Data Badges */}
          {(wp.images?.length || wp.narration) && (
            <div className="flex flex-wrap gap-1.5 mt-1.5">
              {wp.images && wp.images.length > 0 && (
                <span className="flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-zinc-100 dark:bg-zinc-800/80 text-[9px] font-medium text-zinc-800 dark:text-zinc-400 transition-colors">
                  <ImageIcon className="w-2.5 h-2.5" /> {wp.images.length} / 3
                </span>
              )}
              {wp.narration && (
                <span className="flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-zinc-100 dark:bg-zinc-800/80 text-[9px] font-medium text-zinc-800 dark:text-zinc-400 transition-colors">
                  <Mic className="w-2.5 h-2.5" />
                </span>
              )}
            </div>
          )}

          {/* Narration Preview (Subtext) */}
          {wp.narration && (
            <span className="text-[10px] text-zinc-400 dark:text-zinc-500 italic truncate mt-0.5 transition-colors">
              {wp.narration.substring(0, 40) + " ..."}
            </span>
          )}

          {/* Routing Mode Controls */}
          {!isListEditMode && !isLast && (
            <div className="flex-col items-center gap-1 mt-2 pt-2 border-t border-zinc-200/60 dark:border-white/10 w-full">
              <div className="font-bold text-[9px] text-zinc-400">
                To the next stop:
              </div>
              <div className="flex gap-2 bg-zinc-100/80 dark:bg-zinc-900 rounded-md p-0.5 border border-zinc-200/50 dark:border-white/5">
                {[
                  {
                    mode: "walking",
                    icon: Footprints,
                    title: "Walk",
                    activeColor: "text-navi-800 dark:text-white",
                  },
                  {
                    mode: "driving",
                    icon: Car,
                    title: "Drive",
                    activeColor: "text-navi-800 dark:text-white",
                  },
                  {
                    mode: "curve",
                    icon: Plane,
                    title: "Fly",
                    activeColor: "text-navi-800 dark:text-white",
                  },
                  {
                    mode: "direct",
                    icon: Ruler,
                    title: "Direct",
                    activeColor: "text-navi-800 dark:text-white",
                  },
                  {
                    mode: "draw",
                    icon: Pencil,
                    title: "Draw",
                    activeColor: "text-navi-800 dark:text-white",
                  },
                ].map(({ mode, icon: Icon, title, activeColor }) => {
                  const isSelected =
                    wp.routeMode === mode ||
                    (!wp.routeMode && mode === "driving");
                  return (
                    <button
                      key={mode}
                      onClick={(e) => {
                        e.stopPropagation();
                        updateWaypoint(wp.id, { routeMode: mode as RouteMode });
                      }}
                      className={`flex items-center justify-center p-1.25 rounded-md transition-all duration-300 ease-out overflow-hidden ${
                        isSelected
                          ? `bg-white dark:bg-zinc-800 shadow-sm ring-1 ring-zinc-200 dark:ring-white/10 ${activeColor}`
                          : "text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-200/50 dark:hover:bg-white/5"
                      }`}
                      title={title}
                    >
                      <Icon
                        size={`${isSelected ? 16 : 14}`}
                        strokeWidth={`${isSelected ? "2.5" : "2"}`}
                      />
                      <span
                        className={`font-bold text-[9px] tracking-wider whitespace-nowrap transition-all duration-300 ease-out ${
                          isSelected
                            ? "max-w-10 ml-1.5 opacity-100"
                            : "max-w-0 ml-0 opacity-0"
                        }`}
                      >
                        {title}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* 5. Hover Actions & Drag Grip */}
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
