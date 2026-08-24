import { useState } from "react";
import { useWorkspace } from "../../hooks/useWorkspace";
import {
  Settings2,
  X,
  Palette,
  Mic,
  Repeat,
  Car,
  Footprints,
  Ruler,
  Plane,
} from "lucide-react";

export function MapSettings() {
  const [isOpen, setIsOpen] = useState(false);
  const { settings, updateSettings, metadata, updateMetadata } = useWorkspace();

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
        className="absolute top-6 right-6 z-400 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 p-2.5 rounded-xl shadow-sm hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100"
        title="Map Appearance"
      >
        <Settings2 className="w-18px h-18px" />
      </button>
    );
  }

  return (
    <div className="absolute top-4 right-4 w-80 bg-white/90 dark:bg-zinc-900/90 backdrop-blur-xl border border-zinc-200 dark:border-white/10 rounded-2xl shadow-2xl p-5 z-40 animate-in fade-in zoom-in-95">
      <h3 className="text-sm font-bold text-zinc-800 dark:text-zinc-200 mb-4 flex items-center gap-2">
        Project Configuration
      </h3>

      <div className="space-y-6">
        {/* --- 1. OVERVIEW NARRATION BLOCK --- */}
        <div className="space-y-2">
          <label className="text-[10px] font-extrabold text-zinc-500 uppercase tracking-wider flex items-center gap-1.5">
            <Mic className="w-3 h-3" />
            Overview Narration
          </label>
          <textarea
            value={metadata.overview_narration || ""}
            onChange={(e) =>
              updateMetadata({ overview_narration: e.target.value })
            }
            placeholder="E.g., Welcome to our weekend getaway! Today we are starting in Osaka..."
            className="w-full h-20 resize-none text-xs bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-white/10 rounded-lg p-2.5 text-zinc-800 dark:text-zinc-200 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 transition-all custom-scrollbar"
          />
        </div>

        <div className="h-px bg-zinc-200 dark:bg-white/10" />

        {/* --- 2. ROUND TRIP BLOCK --- */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <label className="text-[10px] font-extrabold text-zinc-500 uppercase tracking-wider flex items-center gap-1.5">
              <Repeat className="w-3 h-3" />
              Round Trip
            </label>

            {/* Toggle Switch */}
            <button
              onClick={() =>
                updateSettings({ is_round_trip: !settings.is_round_trip })
              }
              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                settings.is_round_trip
                  ? "bg-emerald-500"
                  : "bg-zinc-300 dark:bg-zinc-700"
              }`}
            >
              <span
                className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                  settings.is_round_trip ? "translate-x-4.5" : "translate-x-1"
                }`}
              />
            </button>
          </div>

          {/* Return Mode Selector (Only visible if Round Trip is true) */}
          {settings.is_round_trip && (
            <div className="animate-in slide-in-from-top-1 fade-in duration-200">
              <label className="text-[10px] font-semibold text-zinc-400 mb-1.5 block">
                Return Travel Mode:
              </label>
              <div className="flex items-center gap-1 bg-zinc-100 dark:bg-zinc-950 p-1 rounded-lg border border-zinc-200 dark:border-white/5">
                {[
                  { id: "driving", icon: Car, title: "Driving" },
                  { id: "walking", icon: Footprints, title: "Walking" },
                  { id: "direct", icon: Ruler, title: "Direct" },
                  { id: "curve", icon: Plane, title: "Fly/Ship" },
                ].map((mode) => {
                  const Icon = mode.icon;
                  const isActive =
                    (settings.return_route_mode || "curve") === mode.id;

                  return (
                    <button
                      key={mode.id}
                      onClick={() =>
                        updateSettings({ return_route_mode: mode.id as any })
                      }
                      className={`flex-1 flex justify-center p-1.5 rounded-md transition-all ${
                        isActive
                          ? "bg-white dark:bg-zinc-800 shadow-sm text-emerald-600 dark:text-emerald-400 ring-1 ring-zinc-200 dark:ring-white/10"
                          : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-300 hover:bg-zinc-200/50 dark:hover:bg-white/5"
                      }`}
                      title={mode.title}
                    >
                      <Icon className="w-4 h-4" />
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>
       
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
