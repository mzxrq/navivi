import { GripVertical, Edit2, X, ImageIcon, Mic } from "../../ui/icons";
import { Waypoint } from "../../../types"; 
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
  onDelete 
}: WaypointItemProps) {

  const { activeWaypointId, setActiveWaypointId } = useWorkspace();
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
      onClick={handleSelect}
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
          className="shrink-0 mx-2 flex items-center justify-center text-red-500 dark:text-red-400/70 hover:text-red-600 dark:hover:text-red-400 transition-all animate-in slide-in-from-left-2"
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
          <div className={`relative z-10 w-5 h-5 mt-2 rounded-full border-[2.5px] bg-navi dark:bg-navi flex items-center justify-center shadow-sm transition-colors ${
            isActive ? "border-navi bg-navi dark:bg-navi" : "border-navi"
          }`}>
            <span className={`text-[9px] font-bold ${
              isActive ? "text-white dark:text-white" : "text-white dark:text-white"
            }`}>
              {index + 1}
            </span>
          </div>
        </div>
      )}

      {/* 3. Content Card */}
      <div className="flex-1 flex items-start justify-between min-w-0 py-1.5 pr-2">
        <div className="flex flex-col min-w-0 flex-1">
          {/* Location Name */}
          <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 truncate pr-4 transition-colors" title={wp.name}>
            {wp.name}
          </span>
          
          {/* Narration Preview (Subtext) */}
          {wp.narration && (
            <span className="text-[10px] text-zinc-400 dark:text-zinc-500 italic truncate mt-0.5 transition-colors">
              "{wp.narration}"
            </span>
          )}

          {/* Micro Data Badges */}
          {(wp.images?.length || wp.duration || wp.fps || wp.narration) && (
            <div className="flex flex-wrap gap-1.5 mt-1.5">
              {wp.images && wp.images.length > 0 && (
                <span className="flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-zinc-100 dark:bg-zinc-800/80 text-[9px] font-medium text-zinc-600 dark:text-zinc-400 transition-colors">
                  <ImageIcon className="w-2.5 h-2.5" /> {wp.images.length}
                </span>
              )}
              {wp.narration && (
                <span className="flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-zinc-100 dark:bg-zinc-800/80 text-[9px] font-medium text-zinc-600 dark:text-zinc-400 transition-colors">
                  <Mic className="w-2.5 h-2.5" /> Script
                </span>
              )}
            </div>
          )}
        </div>

        {/* 4. Hover Actions & Drag Grip */}
        {!isListEditMode && (
          <div className="opacity-0 group-hover:opacity-100 flex items-center gap-0.5 transition-opacity shrink-0 mt-0.5">
            <button 
              onClick={(e) => {
                e.stopPropagation();
                handleSelect();
              }} 
              className="p-1.5 hover:bg-navi/60 dark:hover:bg-zinc-800 rounded-md text-zinc-400 hover:text-emerald-600 dark:hover:text-emerald-400 transition-colors"
              title="Edit Stop"
            >
              <Edit2 className="w-3.5 h-3.5" />
            </button>
            <div 
              onClick={(e) => e.stopPropagation()}
              className="p-1.5 text-zinc-300 dark:text-zinc-600 hover:text-zinc-500 cursor-grab active:cursor-grabbing transition-colors"
            >
              <GripVertical className="w-4 h-4" />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}