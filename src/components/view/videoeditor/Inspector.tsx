import { useWorkspace } from "../../../hooks/useWorkspace";
import { Trash2, Clock, Type, Settings2 } from "../../ui/icons"

interface InspectorProps {
    selectedClipId: string | null;
    onClearSelection: () => void;
}

export function Inspector({ selectedClipId, onClearSelection }: InspectorProps) {
    const { timeline, setTimeline } = useWorkspace();

    // Find the actual clip object based on the ID
    const selectedClip = timeline.clips.find(c => c.id === selectedClipId);

    if (!selectedClip) {
        return (
            <div className="flex-1 flex flex-col items-center justify-center text-zinc-400 p-6 text-center">
                <Settings2 className="w-8 h-8 mb-3 opacity-20" />
                <p className="text-xs">Select a clip on the timeline to edit its properties.</p>
            </div>
        );
    }
    // Helper to safely update just this clip
    const updateClip = (updates: Partial<typeof selectedClip>) => {
        setTimeline({
            ...timeline,
            clips: timeline.clips.map(c =>
                c.id === selectedClip.id ? { ...c, ...updates } : c
            )
        });
    };

    const handleDelete = () => {
        setTimeline({
            ...timeline,
            clips: timeline.clips.filter(c => c.id !== selectedClip.id)
        });
        onClearSelection();
    };

    return (
        <div className="flex-1 flex flex-col gap-4 animate-in fade-in duration-200">
      
      {/* Header */}
      <div className="flex items-center justify-between pb-3 border-b border-zinc-200 dark:border-navidark-400">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-navi-500" />
          <h4 className="text-sm font-bold text-zinc-800 dark:text-zinc-100 truncate w-40">
            {selectedClip.label}
          </h4>
        </div>
        <button 
          onClick={handleDelete}
          className="p-1.5 text-zinc-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10 rounded-md transition-colors"
          title="Delete Clip"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      {/* Form Fields */}
      <div className="space-y-4">
        
        {/* Label Edit */}
        <div className="space-y-1.5">
          <label className="flex items-center gap-2 text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
            <Type className="w-3 h-3" /> Clip Label
          </label>
          <input
            type="text"
            value={selectedClip.label}
            onChange={(e) => updateClip({ label: e.target.value })}
            className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-2 text-xs text-zinc-800 dark:text-zinc-200 focus:outline-none focus:border-navi focus:ring-1 focus:ring-navi"
          />
        </div>

        {/* Timing Edits */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label className="flex items-center gap-2 text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
              <Clock className="w-3 h-3" /> Start (sec)
            </label>
            <input
              type="number"
              step="0.1"
              min="0"
              value={selectedClip.startTime.toFixed(2)}
              onChange={(e) => updateClip({ startTime: parseFloat(e.target.value) || 0 })}
              className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-2 text-xs font-mono text-zinc-800 dark:text-zinc-200 focus:outline-none focus:border-navi"
            />
          </div>
          
          <div className="space-y-1.5">
            <label className="flex items-center gap-2 text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
              <Clock className="w-3 h-3" /> Duration
            </label>
            <input
              type="number"
              step="0.1"
              min="0.1"
              value={selectedClip.duration.toFixed(2)}
              onChange={(e) => updateClip({ duration: parseFloat(e.target.value) || 1 })}
              className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-2 text-xs font-mono text-zinc-800 dark:text-zinc-200 focus:outline-none focus:border-navi"
            />
          </div>
        </div>

        {/* Transform Edits for the Konva Canvas */}
        <div className="space-y-3 pt-3 border-t border-zinc-200 dark:border-navidark-400">
          <h5 className="text-[10px] font-bold text-zinc-500 uppercase tracking-wider">Transform</h5>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex items-center gap-2">
              <span className="text-xs text-zinc-400 w-3">X</span>
              <input type="number" value={Math.round(selectedClip.x || 0)} onChange={(e) => updateClip({ x: parseInt(e.target.value) || 0 })} className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-1.5 text-xs font-mono focus:border-navi" />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-zinc-400 w-3">Y</span>
              <input type="number" value={Math.round(selectedClip.y || 0)} onChange={(e) => updateClip({ y: parseInt(e.target.value) || 0 })} className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-1.5 text-xs font-mono focus:border-navi" />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-zinc-400 w-4">Scl</span>
              <input type="number" step="0.1" value={(selectedClip.scaleX || 1).toFixed(2)} onChange={(e) => updateClip({ scaleX: parseFloat(e.target.value) || 1, scaleY: parseFloat(e.target.value) || 1 })} className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-1.5 text-xs font-mono focus:border-navi" />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-zinc-400 w-4">Rot</span>
              <input type="number" value={Math.round(selectedClip.rotation || 0)} onChange={(e) => updateClip({ rotation: parseInt(e.target.value) || 0 })} className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-1.5 text-xs font-mono focus:border-navi" />
            </div>
          </div>
        </div>
      </div>
    </div>
    );
}