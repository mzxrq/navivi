import React from "react";
import { Palette } from "lucide-react";

interface InspectorColorPanelProps {
  selectedClip: any; updateClip: (updates: any) => void;
}

export function InspectorColorPanel({ selectedClip, updateClip }: InspectorColorPanelProps) {
  return (
<div className="space-y-3 pt-3 border-t border-zinc-200 dark:border-navidark-400">
      <div className="flex items-center justify-between">
        <h5 className="flex items-center gap-2 text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
          <Palette className="w-3.5 h-3.5 text-navi" /> Color Adjustments
        </h5>
        <button
          type="button"
          onClick={() =>
            updateClip({
              effects: {
                brightness: 0,
                contrast: 0,
                saturation: 0,
              },
            })
          }
          className="text-[10px] text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 underline"
          title="Reset all color adjustments to 0"
        >
          Reset
        </button>
      </div>

      {/* Brightness Slider */}
      <div className="space-y-1.5 bg-zinc-50 dark:bg-navidark-900 p-2.5 rounded border border-zinc-200 dark:border-navidark-700">
        <div className="flex justify-between items-center text-xs">
          <span className="font-semibold text-zinc-700 dark:text-zinc-300">
            Brightness
          </span>
          <span className="font-mono text-[11px] text-zinc-800 dark:text-zinc-200 font-bold">
            {(selectedClip.effects?.brightness ?? 0) > 0
              ? `+${selectedClip.effects?.brightness ?? 0}`
              : selectedClip.effects?.brightness ?? 0}
          </span>
        </div>
        <input
          type="range"
          min="-100"
          max="100"
          step="1"
          value={selectedClip.effects?.brightness ?? 0}
          onChange={(e) =>
            updateClip({
              effects: {
                ...selectedClip.effects,
                brightness: parseInt(e.target.value),
              },
            })
          }
          className="w-full accent-navi cursor-pointer h-1.5 bg-zinc-200 dark:bg-zinc-700 rounded-lg"
        />
      </div>

      {/* Contrast Slider */}
      <div className="space-y-1.5 bg-zinc-50 dark:bg-navidark-900 p-2.5 rounded border border-zinc-200 dark:border-navidark-700">
        <div className="flex justify-between items-center text-xs">
          <span className="font-semibold text-zinc-700 dark:text-zinc-300">
            Contrast
          </span>
          <span className="font-mono text-[11px] text-zinc-800 dark:text-zinc-200 font-bold">
            {(selectedClip.effects?.contrast ?? 0) > 0
              ? `+${selectedClip.effects?.contrast ?? 0}`
              : selectedClip.effects?.contrast ?? 0}
          </span>
        </div>
        <input
          type="range"
          min="-100"
          max="100"
          step="1"
          value={selectedClip.effects?.contrast ?? 0}
          onChange={(e) =>
            updateClip({
              effects: {
                ...selectedClip.effects,
                contrast: parseInt(e.target.value),
              },
            })
          }
          className="w-full accent-navi cursor-pointer h-1.5 bg-zinc-200 dark:bg-zinc-700 rounded-lg"
        />
      </div>

      {/* Saturation Slider */}
      <div className="space-y-1.5 bg-zinc-50 dark:bg-navidark-900 p-2.5 rounded border border-zinc-200 dark:border-navidark-700">
        <div className="flex justify-between items-center text-xs">
          <span className="font-semibold text-zinc-700 dark:text-zinc-300">
            Saturation
          </span>
          <span className="font-mono text-[11px] text-zinc-800 dark:text-zinc-200 font-bold">
            {(selectedClip.effects?.saturation ?? 0) > 0
              ? `+${selectedClip.effects?.saturation ?? 0}`
              : selectedClip.effects?.saturation ?? 0}
          </span>
        </div>
        <input
          type="range"
          min="-100"
          max="100"
          step="1"
          value={selectedClip.effects?.saturation ?? 0}
          onChange={(e) =>
            updateClip({
              effects: {
                ...selectedClip.effects,
                saturation: parseInt(e.target.value),
              },
            })
          }
          className="w-full accent-navi cursor-pointer h-1.5 bg-zinc-200 dark:bg-zinc-700 rounded-lg"
        />
      </div>
    </div>

  );
}
