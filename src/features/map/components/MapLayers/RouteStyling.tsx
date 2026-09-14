import { useState } from "react";
import { useWorkspace } from "../../../../hooks/useWorkspace";
import { X, Palette } from "../../../../components/ui/icons";

const PRESET_COLORS = [
  "#3b82f6", // Blue
  "#ef4444", // Red
  "#10b981", // Green
  "#f59e0b", // Orange
  "#8b5cf6", // Purple
  "#ec4899", // Pink
  "#ffffff", // White
  "#000000", // Black
];

const rgbToHex = (rgb: [number, number, number]) =>
  "#" + rgb.map((x) => Math.round(x).toString(16).padStart(2, "0")).join("");

const hexToRgb = (hex: string): [number, number, number] => {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return [r, g, b];
};

const ColorPicker = ({
  label,
  color,
  onChange,
}: {
  label: string;
  color: [number, number, number];
  onChange: (c: [number, number, number]) => void;
}) => {
  const currentHex = rgbToHex(color);
  return (
    <div className="flex-1 space-y-1.5">
      <label className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">
        {label}
      </label>
      <div className="flex flex-wrap gap-1.5">
        {PRESET_COLORS.map((c) => (
          <button
            key={c}
            onClick={() => onChange(hexToRgb(c))}
            className={`w-5 h-5 rounded-full border-2 ${currentHex === c ? "border-navi scale-110 shadow-sm" : "border-transparent shadow-sm hover:scale-110"} transition-all`}
            style={{ backgroundColor: c }}
            title={c}
          />
        ))}
        {/* Custom fallback picker */}
        <div className="relative w-5 h-5 rounded-full border-2 border-dashed border-zinc-300 dark:border-zinc-600 hover:border-zinc-400 transition-colors overflow-hidden group">
          <input
            type="color"
            value={currentHex}
            onChange={(e) => onChange(hexToRgb(e.target.value))}
            className="absolute -top-2 -left-2 w-10 h-10 opacity-0 cursor-pointer z-10"
            title="Custom Color"
          />
          <div className="absolute inset-0 bg-linear-to-br from-red-500 via-green-500 to-blue-500 opacity-20 group-hover:opacity-50 transition-opacity" />
        </div>
      </div>
    </div>
  );
};

export function RouteStyling() {
  const [isOpen, setIsOpen] = useState(false);
  const { settings, updateSettings } = useWorkspace();

  return (
    <div className="relative flex items-center">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`flex items-center justify-center w-10 h-10 rounded-full transition-all font-bold bg-white dark:bg-zinc-800 text-zinc-700 hover:bg-zinc-200 dark:text-zinc-200 dark:hover:bg-zinc-500 ${
          isOpen
            ? "bg-zinc-400 hover:bg-zinc-600 text-white shadow-zinc-200/25"
            : "bg-white dark:bg-zinc-800 text-zinc-700 hover:bg-zinc-200 dark:text-zinc-200 dark:hover:bg-zinc-500"
        }`}
        title="Route Lines Config"
      >
        <Palette className="w-3.5 h-3.5" />
      </button>

      {/* 🛠️ The Popup renders below it */}
      {isOpen && (
        <div className="absolute top-12 right-0 w-64 bg-white/90 dark:bg-zinc-900/90 backdrop-blur-xl border border-zinc-200 dark:border-white/10 rounded-2xl shadow-2xl p-5 z-40 animate-in fade-in zoom-in-95">
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

          <div className="p-4 space-y-6">
            <div className="flex flex-col gap-4">
              <ColorPicker
                label="Route Line"
                color={settings.line_color || [0, 200, 255]}
                onChange={(c) => updateSettings({ line_color: c })}
              />
              <ColorPicker
                label="Marker"
                color={settings.marker_color || [0, 0, 255]}
                onChange={(c) => updateSettings({ marker_color: c })}
              />
              <ColorPicker
                label="Border"
                color={settings.route_line_border_color || [255, 255, 255]}
                onChange={(c) => updateSettings({ route_line_border_color: c })}
              />
            </div>

            <div className="flex flex-col gap-4">
              <div className="space-y-2 pt-1 flex flex-col justify-end">
                <div className="flex justify-between items-end">
                  <label className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">
                    B-Width
                  </label>
                  <span className="text-xs font-mono font-medium text-zinc-700 dark:text-zinc-300">
                    {settings.route_line_border_thickness || 0}px
                  </span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="12"
                  value={settings.route_line_border_thickness || 0}
                  onChange={(e) =>
                    updateSettings({
                      route_line_border_thickness: parseInt(e.target.value),
                    })
                  }
                  className="w-full h-1.5 bg-zinc-200 dark:bg-zinc-800 rounded-lg appearance-none cursor-pointer accent-zinc-700 dark:accent-zinc-300"
                />
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
      )}
    </div>
  );
}
