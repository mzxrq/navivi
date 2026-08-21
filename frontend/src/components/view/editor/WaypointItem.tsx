import { GripVertical, Edit2, X, Image as ImageIcon, Mic } from "lucide-react";
import { Waypoint } from "../../../types"; 

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
  
  return (
    <div className="relative flex items-stretch group hover:bg-zinc-50/50 dark:hover:bg-zinc-900/20 transition-colors px-2 py-1.5">
      
      {/* 1. Delete Action (Edit Mode) */}
      {isListEditMode && (
        <button
          onClick={onDelete}
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
          {/* Top connecting line (from top of container to center of node) */}
          {!isFirst && (
            <div className="absolute top-0 left-1/2 -translate-x-1/2 w-0.5 h-[18px] bg-zinc-200 dark:bg-zinc-800 transition-colors" />
          )}
          
          {/* Bottom connecting line (from center of node to bottom of container) */}
          {!isLast && (
            <div className="absolute top-[18px] bottom-0 left-1/2 -translate-x-1/2 w-0.5 bg-zinc-200 dark:bg-zinc-800 transition-colors" />
          )}
          
          {/* The Node */}
          <div className="relative z-10 w-5 h-5 mt-2 rounded-full border-[2.5px] border-emerald-500 bg-white dark:bg-zinc-950 flex items-center justify-center shadow-sm">
            <span className="text-[9px] font-bold text-emerald-600 dark:text-emerald-400">
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
          {(wp.images?.length || wp.duration || wp.fps) && (
            <div className="flex flex-wrap gap-1.5 mt-1.5">
              {wp.images && wp.images.length > 0 && (
                <span className="flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-zinc-100 dark:bg-zinc-800 text-[9px] font-medium text-zinc-600 dark:text-zinc-400 transition-colors">
                  <ImageIcon className="w-2.5 h-2.5" /> {wp.images.length}
                </span>
              )}
              {wp.narration && (
                <span className="flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-zinc-100 dark:bg-zinc-800 text-[9px] font-medium text-zinc-600 dark:text-zinc-400 transition-colors">
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
              onClick={onEdit} 
              className="p-1.5 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded-md text-zinc-400 hover:text-emerald-600 dark:hover:text-emerald-400 transition-colors"
              title="Edit Stop"
            >
              <Edit2 className="w-3.5 h-3.5" />
            </button>
            {/* Note: If using @hello-pangea/dnd, apply your dragHandleProps to this div */}
            <div className="p-1.5 text-zinc-300 dark:text-zinc-600 hover:text-zinc-500 cursor-grab active:cursor-grabbing transition-colors">
              <GripVertical className="w-4 h-4" />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}