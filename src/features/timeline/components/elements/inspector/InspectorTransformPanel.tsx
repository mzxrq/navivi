import { t } from "@lingui/core/macro";
import { ImageIcon } from "lucide-react";

interface InspectorTransformPanelProps {
  selectedClip: any; updateClip: (updates: any) => void;
}

export function InspectorTransformPanel({ selectedClip, updateClip }: InspectorTransformPanelProps) {
  return (
<div className="space-y-3 pt-3 border-t border-zinc-200 dark:border-navidark-400">
      <h5 className="flex items-center gap-2 text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
        <ImageIcon className="w-3 h-3" /> Transform
      </h5>
      <div className="grid grid-cols-2 gap-3">
        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-400 w-3">X</span>
          <input
            type="number"
            value={Math.round(selectedClip.x || 0)}
            onChange={(e) =>
              updateClip({ x: parseInt(e.target.value) || 0 })
            }
            className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-1.5 text-xs font-mono focus:border-navi"
          />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-400 w-3">Y</span>
          <input
            type="number"
            value={Math.round(selectedClip.y || 0)}
            onChange={(e) =>
              updateClip({ y: parseInt(e.target.value) || 0 })
            }
            className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-1.5 text-xs font-mono focus:border-navi"
          />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-400 w-4">Scl</span>
          <input
            type="number"
            step="0.1"
            value={(selectedClip.scaleX || 1).toFixed(2)}
            onChange={(e) =>
              updateClip({
                scaleX: parseFloat(e.target.value) || 1,
                scaleY: parseFloat(e.target.value) || 1,
              })
            }
            className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-1.5 text-xs font-mono focus:border-navi"
          />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-400 w-4">Rot</span>
          <input
            type="number"
            value={Math.round(selectedClip.rotation || 0)}
            onChange={(e) =>
              updateClip({ rotation: parseInt(e.target.value) || 0 })
            }
            className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-1.5 text-xs font-mono focus:border-navi"
          />
        </div>
      </div>
    </div>

  );
}
