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

export function WaypointItem({ wp, index, isListEditMode, onEdit, onDelete, }: WaypointItemProps) {
  return (
    <div className="flex items-center gap-2 group shrink-0">
      
      {/* Delete Button (Edit Mode Only) */}
      {isListEditMode && (
        <button
          onClick={onDelete}
          className="shrink-0 p-1.5 text-red-500 dark:text-red-400/70 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10 rounded-lg transition-all animate-in slide-in-from-left-2"
        >
          <X className="w-4 h-4" />
        </button>
      )}

      {/* Main Card */}
      <div className="flex-1 flex items-center justify-between bg-zinc-50 dark:bg-zinc-900/30 border border-zinc-200 dark:border-white/5 p-2.5 rounded-xl hover:bg-zinc-100 dark:hover:bg-zinc-900/80 transition-colors overflow-hidden shadow-sm dark:shadow-none">
        
        <div className="flex items-center gap-2.5 overflow-hidden">
          
          {/* Drag Grip Indicator (Normal Mode Only) */}
          {!isListEditMode && (
            <div className="shrink-0 text-zinc-300 dark:text-zinc-700 group-hover:text-zinc-500 transition-colors">
              <GripVertical className="w-4 h-4" />
            </div>
          )}

          {/* Number Badge */}
          <div className="w-6 h-6 rounded-md bg-zinc-200 dark:bg-zinc-800/50 text-zinc-600 dark:text-zinc-500 flex items-center justify-center text-xs font-bold shrink-0 transition-colors">
            {index + 1}
          </div>
          
          {/* Info Section */}
          <div className="flex flex-col overflow-hidden">
            <span className="text-xs font-medium text-zinc-800 dark:text-zinc-300 truncate" title={wp.name}>
              {wp.name}
            </span>
            <div className="flex gap-1.5 mt-0.5">
              {wp.images && wp.images.length > 0 && (
                <div className="flex items-center gap-1 text-zinc-400 dark:text-zinc-500">
                  <ImageIcon className="w-3 h-3" />
                  <span className="text-[9px] font-bold">{wp.images.length}</span>
                </div>
              )}
              {wp.narration && <Mic className="w-3 h-3 text-zinc-400 dark:text-zinc-500" />}
            </div>
          </div>
        </div>

        {/* Hover Actions */}
        {!isListEditMode && (
          <div className="opacity-0 group-hover:opacity-100 flex items-center gap-1 transition-all shrink-0">
            <button onClick={onEdit} className="p-1.5 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded-md text-zinc-500">
              <Edit2 className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}