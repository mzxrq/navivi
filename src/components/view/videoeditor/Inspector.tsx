import { useWorkspace } from "../../../hooks/useWorkspace";
import { Trash2, Type, Settings2, Sparkles, ImageIcon, CopyPlus } from "../../ui/icons";

interface InspectorProps {
  selectedClipIds: string[]; // ✨ CHANGED: Now an array!
  onClearSelection: () => void;
}

export function Inspector({ selectedClipIds, onClearSelection }: InspectorProps) {
  const { timeline, setTimeline } = useWorkspace();

  if (selectedClipIds.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-zinc-400 p-6 text-center">
        <Settings2 className="w-8 h-8 mb-3 opacity-20" />
        <p className="text-xs">Select a clip on the timeline to edit its properties.</p>
      </div>
    );
  }

  if (selectedClipIds.length > 1) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-zinc-400 p-6 text-center animate-in fade-in zoom-in-95">
        <CopyPlus className="w-8 h-8 mb-3 text-navi-500/50" />
        <p className="text-sm font-bold text-zinc-800 dark:text-zinc-200">{selectedClipIds.length} Clips Selected</p>
        <p className="text-[10px] mt-2 leading-relaxed">You can drag these clips together on the timeline, copy/paste them, or press Delete to remove them.</p>
        <button onClick={() => {
            setTimeline({ ...timeline, clips: timeline.clips.filter(c => !selectedClipIds.includes(c.id)) });
            onClearSelection();
        }} className="mt-6 px-4 py-2 bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400 text-xs font-bold rounded-lg hover:bg-red-100 transition-colors flex items-center gap-2">
            <Trash2 className="w-3.5 h-3.5" /> Delete Selected
        </button>
      </div>
    );
  }

  const selectedClip = timeline.clips.find(c => c.id === selectedClipIds[0]);
  if (!selectedClip) return null;

  const updateClip = (updates: Partial<typeof selectedClip>) => {
    setTimeline({
      ...timeline,
      clips: timeline.clips.map(c => c.id === selectedClip.id ? { ...c, ...updates } : c)
    });
  };

  return (
    <div className="flex-1 flex flex-col gap-4 animate-in fade-in duration-200">
      <div className="flex items-center justify-between pb-3 border-b border-zinc-200 dark:border-navidark-400">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-navi-500" />
          <h4 className="text-sm font-bold text-zinc-800 dark:text-zinc-100 truncate w-40">
            {selectedClip.label}
          </h4>
        </div>
        <button onClick={() => {
            setTimeline({ ...timeline, clips: timeline.clips.filter(c => c.id !== selectedClip.id) });
            onClearSelection();
        }} className="p-1.5 text-zinc-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10 rounded-md transition-colors" title="Delete Clip">
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      <div className="space-y-4">
        {/* Label Edit */}
        <div className="space-y-1.5">
          <label className="flex items-center gap-2 text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
            <Type className="w-3 h-3" /> Clip Label
          </label>
          <input type="text" value={selectedClip.label} onChange={(e) => updateClip({ label: e.target.value })} className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-2 text-xs text-zinc-800 dark:text-zinc-200 focus:outline-none focus:border-navi" />
        </div>

        {/* Text/Subtitle Controls */}
        {(selectedClip.type === 'text' || selectedClip.type === 'subtitle') && (
           <div className="space-y-3 pt-3 border-t border-zinc-200 dark:border-navidark-400">
             <h5 className="text-[10px] font-bold text-zinc-500 uppercase tracking-wider">Text Properties</h5>
             <textarea value={selectedClip.text || ''} onChange={(e) => updateClip({ text: e.target.value })} className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-2 text-xs text-zinc-800 dark:text-zinc-200 h-20 custom-scrollbar" placeholder="Enter subtitle text..." />
             <div className="grid grid-cols-2 gap-2">
                <input type="number" placeholder="Font Size" value={selectedClip.fontSize || 48} onChange={(e) => updateClip({ fontSize: parseInt(e.target.value) })} className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-2 text-xs" />
                <input type="color" value={selectedClip.color || '#ffffff'} onChange={(e) => updateClip({ color: e.target.value })} className="w-full h-8 rounded cursor-pointer" />
             </div>
           </div>
        )}

        {/* Visual Transitions */}
        {selectedClip.type !== 'audio' && selectedClip.type !== 'text' && (
          <div className="space-y-3 pt-3 border-t border-zinc-200 dark:border-navidark-400">
            <h5 className="flex items-center gap-2 text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
              <Sparkles className="w-3 h-3" /> Transitions
            </h5>
            <select value={selectedClip.transitionIn || 'none'} onChange={(e) => updateClip({ transitionIn: e.target.value })} className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-2 text-xs text-zinc-800 dark:text-zinc-200 cursor-pointer">
              <option value="none">No In-Transition</option>
              <option value="crossfade">Crossfade In</option>
              <option value="fade-black">Fade from Black</option>
            </select>
            <select value={selectedClip.transitionOut || 'none'} onChange={(e) => updateClip({ transitionOut: e.target.value })} className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-2 text-xs text-zinc-800 dark:text-zinc-200 cursor-pointer">
              <option value="none">No Out-Transition</option>
              <option value="crossfade">Crossfade Out</option>
              <option value="fade-black">Fade to Black</option>
            </select>
          </div>
        )}

        {/* Transform Edits */}
        <div className="space-y-3 pt-3 border-t border-zinc-200 dark:border-navidark-400">
          <h5 className="flex items-center gap-2 text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
            <ImageIcon className="w-3 h-3" /> Transform
          </h5>
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