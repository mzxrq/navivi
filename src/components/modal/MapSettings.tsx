import { useState } from "react";
import { useWorkspace } from "../../hooks/useWorkspace";
import {
  X,
  Palette,
} from "../ui/icons";

export function MapSettings() {
  const [isOpen, setIsOpen] = useState(false);
  const { settings, updateSettings, } = useWorkspace();

  const rgbToHex = (rgb: [number, number, number]) =>
    "#" + rgb.map((x) => x.toString(16).padStart(2, "0")).join("");

  const hexToRgb = (hex: string): [number, number, number] => {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return [r, g, b];
  };

  if (!isOpen) {
    return (
      <button
        onClick={() => setIsOpen(true)}
        className="absolute top-4 right-4 z-400 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 p-2.5 rounded-xl shadow-2xs hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors text-zinc-600 dark:text-white hover:text-zinc-900 dark:hover:text-zinc-100"
        title="Settings"
      >
        <Palette className="w-12px h-12px" />
      </button>
    );
  }

  return (
    <div className="absolute top-4 right-4 w-80 bg-white/90 dark:bg-zinc-900/90 backdrop-blur-xl border border-zinc-200 dark:border-white/10 rounded-2xl shadow-2xl p-5 z-40 animate-in fade-in zoom-in-95">
          <div className="flex justify-between">
            <h3 className="text-xs font-bold text-zinc-800 dark:text-zinc-200 flex items-center gap-2">
              <Palette className="w-3.5 h-3.5 text-zinc-500" /> Map Appearance
            </h3>
            <button
              onClick={() => setIsOpen(false)}
              className="text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 transition-colors p-1"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Body */}
          <div className="p-4 space-y-5">
            <div className="flex gap-3">
              {/* Line Color Custom Picker */}
              <div className="flex-1 space-y-1.5">
                <label className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">
                  Route Line
                </label>
                <div className="relative group">
                  <input
                    type="color"
                    value={rgbToHex(settings.line_color)}
                    onChange={(e) =>
                      updateSettings({ line_color: hexToRgb(e.target.value) })
                    }
                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10"
                  />
                  <div className="w-full h-8 rounded-lg border border-zinc-200 dark:border-white/10 shadow-sm flex items-center px-2 gap-2 bg-zinc-50 dark:bg-zinc-900/50 group-hover:border-zinc-400 dark:group-hover:border-zinc-600 transition-colors">
                    <div
                      className="w-4 h-4 rounded-full border border-black/10"
                      style={{ backgroundColor: rgbToHex(settings.line_color) }}
                    />
                    <span className="text-xs font-mono text-zinc-600 dark:text-zinc-400 uppercase">
                      {rgbToHex(settings.line_color)}
                    </span>
                  </div>
                </div>
              </div>

              {/* Marker Color Custom Picker */}
              <div className="flex-1 space-y-1.5">
                <label className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">
                  Marker
                </label>
                <div className="relative group">
                  <input
                    type="color"
                    value={rgbToHex(settings.marker_color)}
                    onChange={(e) =>
                      updateSettings({ marker_color: hexToRgb(e.target.value) })
                    }
                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10"
                  />
                  <div className="w-full h-8 rounded-lg border border-zinc-200 dark:border-white/10 shadow-sm flex items-center px-2 gap-2 bg-zinc-50 dark:bg-zinc-900/50 group-hover:border-zinc-400 dark:group-hover:border-zinc-600 transition-colors">
                    <div
                      className="w-4 h-4 rounded-full border border-black/10"
                      style={{
                        backgroundColor: rgbToHex(settings.marker_color),
                      }}
                    />
                    <span className="text-xs font-mono text-zinc-600 dark:text-zinc-400 uppercase">
                      {rgbToHex(settings.marker_color)}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <div className="space-y-2 pt-1">
              <div className="flex justify-between items-end">
                <label className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">
                  Line Thickness
                </label>
                <span className="text-xs font-mono font-medium text-zinc-700 dark:text-zinc-300">
                  {settings.line_thickness}px
                </span>
              </div>
              <input
                type="range"
                min="2"
                max="24"
                value={settings.line_thickness}
                onChange={(e) =>
                  updateSettings({ line_thickness: parseInt(e.target.value) })
                }
                className="w-full h-1.5 bg-zinc-200 dark:bg-zinc-800 rounded-lg appearance-none cursor-pointer accent-zinc-700 dark:accent-zinc-300"
              />
            </div>
          </div>
        </div>
              
  );
}
