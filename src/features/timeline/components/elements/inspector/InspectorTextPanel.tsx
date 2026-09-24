import { t } from "@lingui/core/macro";
import { Type, Subtitles, Check } from "lucide-react";

const FONT_FAMILIES = [
  { label: "Inter (Modern Sans)", value: "Inter, sans-serif" },
  { label: "Roboto (Clean Sans)", value: "Roboto, sans-serif" },
  { label: "Noto Sans JP (Japanese)", value: "'Noto Sans JP', sans-serif" },
  { label: "Arial (Standard)", value: "Arial, sans-serif" },
  { label: "Impact (Bold Headline)", value: "Impact, sans-serif" },
  { label: "Georgia (Classic Serif)", value: "Georgia, serif" },
  { label: "Courier New (Monospace)", value: "'Courier New', monospace" },
];

const STYLE_PRESETS = [
  {
    id: "standard",
    name: "Standard Subtitle",
    desc: "Crisp white text with black stroke",
    style: {
      fontFamily: "Inter, sans-serif",
      fontSize: 48,
      color: "#ffffff",
      stroke: "#000000",
      strokeWidth: 3,
      shadowColor: "rgba(0, 0, 0, 0.75)",
      shadowBlur: 4,
      shadowOffsetX: 2,
      shadowOffsetY: 2,
      karaoke: false,
      karaokeHighlightColor: "#f59e0b",
    },
  },
  {
    id: "karaoke",
    name: "Karaoke Glow",
    desc: "Golden dynamic highlight and glow",
    style: {
      fontFamily: "'Noto Sans JP', sans-serif",
      fontSize: 52,
      color: "#ffffff",
      stroke: "#18181b",
      strokeWidth: 4,
      shadowColor: "rgba(245, 158, 11, 0.6)",
      shadowBlur: 10,
      shadowOffsetX: 0,
      shadowOffsetY: 0,
      karaoke: true,
      karaokeHighlightColor: "#ffd700",
    },
  },
  {
    id: "impact",
    name: "Punchy Impact",
    desc: "Heavy yellow headline with thick outline",
    style: {
      fontFamily: "Impact, sans-serif",
      fontSize: 60,
      color: "#facc15",
      stroke: "#000000",
      strokeWidth: 6,
      shadowColor: "#000000",
      shadowBlur: 6,
      shadowOffsetX: 3,
      shadowOffsetY: 3,
      karaoke: false,
      karaokeHighlightColor: "#ef4444",
    },
  },
  {
    id: "minimal",
    name: "Minimalist",
    desc: "Clean modern sans-serif",
    style: {
      fontFamily: "Roboto, sans-serif",
      fontSize: 40,
      color: "#f4f4f5",
      stroke: undefined,
      strokeWidth: 0,
      shadowColor: undefined,
      shadowBlur: 0,
      shadowOffsetX: 0,
      shadowOffsetY: 0,
      karaoke: false,
      karaokeHighlightColor: "#38bdf8",
    },
  },
];
interface InspectorTextPanelProps {
  selectedClip: any;
  updateClip: (updates: any) => void;
  updateTextStyle: (updates: any) => void;
}

export function InspectorTextPanel({
  selectedClip,
  updateClip,
  updateTextStyle,
}: InspectorTextPanelProps) {
  return (
    <div className="space-y-4 pt-3 border-t border-zinc-200 dark:border-navidark-400">
      <div className="flex items-center justify-between">
        <h5 className="flex items-center gap-2 text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
          {selectedClip.type === "subtitle" ? (
            <Subtitles className="w-3.5 h-3.5 text-navi" />
          ) : (
            <Type className="w-3.5 h-3.5 text-navi" />
          )}
          Typography & Subtitles
        </h5>
        <span className="text-[10px] font-semibold text-navi px-1.5 py-0.5 rounded bg-navi/10 dark:bg-navi/20">
          {selectedClip.type === "subtitle" ? "Subtitle" : "Rich Text"}
        </span>
      </div>

      {/* Quick Style Presets */}
      <div className="space-y-1.5">
        <label className="text-[10px] text-zinc-400 block font-medium">
          Style Presets
        </label>
        <div className="grid grid-cols-2 gap-1.5">
          {STYLE_PRESETS.map((preset) => (
            <button
              key={preset.id}
              type="button"
              onClick={() => updateTextStyle(preset.style)}
              className="p-2 text-left rounded bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-700 hover:border-navi hover:bg-zinc-100 dark:hover:bg-navidark-800 transition-colors group"
              title={preset.desc}
            >
              <div className="text-xs font-semibold text-zinc-800 dark:text-zinc-200 group-hover:text-navi">
                {preset.name}
              </div>
              <div className="text-[9px] text-zinc-400 truncate">
                {preset.desc}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Content Textarea */}
      <div className="space-y-1.5">
        <label className="text-[10px] text-zinc-400 block font-medium">
          Content
        </label>
        <textarea
          value={selectedClip.text || ""}
          onChange={(e) => updateClip({ text: e.target.value })}
          className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-2 text-xs text-zinc-800 dark:text-zinc-200 h-20 custom-scrollbar focus:border-navi focus:outline-none"
          placeholder="Enter subtitle or display text..."
        />
      </div>

      {/* Font Family Selector */}
      <div className="space-y-1.5">
        <label className="text-[10px] text-zinc-400 block font-medium">
          Font Family
        </label>
        <select
          value={
            selectedClip.fontFamily ||
            selectedClip.style?.fontFamily ||
            "Inter, sans-serif"
          }
          onChange={(e) => updateTextStyle({ fontFamily: e.target.value })}
          className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-2 text-xs text-zinc-800 dark:text-zinc-200 cursor-pointer focus:border-navi"
        >
          {FONT_FAMILIES.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </select>
      </div>

      {/* Font Size & Primary Color */}
      <div className="space-y-1.5 bg-zinc-50 dark:bg-navidark-900 p-2.5 rounded border border-zinc-200 dark:border-navidark-700">
        <div className="flex justify-between items-center text-xs">
          <span className="font-semibold text-zinc-700 dark:text-zinc-300">
            Font Size
          </span>
          <div className="flex items-center gap-2 font-mono text-[11px]">
            <span className="text-zinc-800 dark:text-zinc-200 font-bold">
              {selectedClip.fontSize || selectedClip.style?.fontSize || 48}px
            </span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <input
            type="range"
            min="12"
            max="144"
            step="1"
            value={selectedClip.fontSize || selectedClip.style?.fontSize || 48}
            onChange={(e) =>
              updateTextStyle({ fontSize: parseInt(e.target.value) || 48 })
            }
            className="w-full accent-navi cursor-pointer h-1.5 bg-zinc-200 dark:bg-zinc-700 rounded-lg"
          />
          <input
            type="number"
            min="12"
            max="144"
            value={selectedClip.fontSize || selectedClip.style?.fontSize || 48}
            onChange={(e) =>
              updateTextStyle({ fontSize: parseInt(e.target.value) || 48 })
            }
            className="w-14 bg-white dark:bg-navidark-800 border border-zinc-300 dark:border-navidark-600 rounded px-1.5 py-0.5 text-xs font-mono text-center text-zinc-800 dark:text-zinc-200"
          />
        </div>

        {/* Text Fill Color */}
        <div className="pt-2 mt-2 border-t border-zinc-200 dark:border-navidark-700 flex items-center justify-between">
          <span className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
            Text Color
          </span>
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-mono text-zinc-400 uppercase">
              {selectedClip.color || selectedClip.style?.color || "#ffffff"}
            </span>
            <input
              type="color"
              value={
                (
                  selectedClip.color ||
                  selectedClip.style?.color ||
                  "#ffffff"
                ).startsWith("#")
                  ? selectedClip.color || selectedClip.style?.color || "#ffffff"
                  : "#ffffff"
              }
              onChange={(e) => updateTextStyle({ color: e.target.value })}
              className="w-8 h-7 rounded cursor-pointer border border-zinc-300 dark:border-navidark-600 bg-transparent"
            />
          </div>
        </div>
      </div>

      {/* Text Outline / Stroke */}
      <div className="space-y-2.5 bg-zinc-50 dark:bg-navidark-900 p-2.5 rounded border border-zinc-200 dark:border-navidark-700">
        <div className="flex items-center justify-between">
          <label className="flex items-center gap-2 cursor-pointer text-xs font-semibold text-zinc-800 dark:text-zinc-200">
            <input
              type="checkbox"
              checked={Boolean(
                (selectedClip.strokeWidth ??
                  selectedClip.style?.strokeWidth ??
                  0) > 0 &&
                (selectedClip.stroke || selectedClip.style?.stroke),
              )}
              onChange={(e) => {
                if (e.target.checked) {
                  const defaultStroke =
                    selectedClip.stroke ||
                    selectedClip.style?.stroke ||
                    "#000000";
                  const defaultWidth =
                    selectedClip.strokeWidth ||
                    selectedClip.style?.strokeWidth ||
                    3;
                  updateTextStyle({
                    stroke: defaultStroke,
                    strokeWidth: defaultWidth,
                  });
                } else {
                  updateTextStyle({ stroke: undefined, strokeWidth: 0 });
                }
              }}
              className="accent-navi rounded"
            />
            <span>Text Outline / Stroke</span>
          </label>
          <span className="text-[10px] uppercase font-bold text-zinc-400">
            {(selectedClip.strokeWidth ??
              selectedClip.style?.strokeWidth ??
              0) > 0
              ? "Active"
              : "Off"}
          </span>
        </div>

        {(selectedClip.strokeWidth ?? selectedClip.style?.strokeWidth ?? 0) >
          0 && (
          <div className="space-y-2 pt-2 border-t border-zinc-200 dark:border-navidark-700">
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-zinc-500 dark:text-zinc-400">
                Outline Color
              </span>
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-mono text-zinc-400 uppercase">
                  {selectedClip.stroke ||
                    selectedClip.style?.stroke ||
                    "#000000"}
                </span>
                <input
                  type="color"
                  value={
                    (
                      selectedClip.stroke ||
                      selectedClip.style?.stroke ||
                      "#000000"
                    ).startsWith("#")
                      ? selectedClip.stroke ||
                        selectedClip.style?.stroke ||
                        "#000000"
                      : "#000000"
                  }
                  onChange={(e) => updateTextStyle({ stroke: e.target.value })}
                  className="w-7 h-6 rounded cursor-pointer border border-zinc-300 dark:border-navidark-600 bg-transparent"
                />
              </div>
            </div>

            <div className="space-y-1">
              <div className="flex justify-between items-center text-[11px] text-zinc-500 dark:text-zinc-400">
                <span>Stroke Width</span>
                <span className="font-mono text-navi font-bold">
                  {selectedClip.strokeWidth ??
                    selectedClip.style?.strokeWidth ??
                    3}
                  px
                </span>
              </div>
              <input
                type="range"
                min="0.5"
                max="12"
                step="0.5"
                value={
                  selectedClip.strokeWidth ??
                  selectedClip.style?.strokeWidth ??
                  3
                }
                onChange={(e) =>
                  updateTextStyle({ strokeWidth: parseFloat(e.target.value) })
                }
                className="w-full accent-navi cursor-pointer h-1.5 bg-zinc-200 dark:bg-zinc-700 rounded-lg"
              />
            </div>
          </div>
        )}
      </div>

      {/* Drop Shadow */}
      <div className="space-y-2.5 bg-zinc-50 dark:bg-navidark-900 p-2.5 rounded border border-zinc-200 dark:border-navidark-700">
        <div className="flex items-center justify-between">
          <label className="flex items-center gap-2 cursor-pointer text-xs font-semibold text-zinc-800 dark:text-zinc-200">
            <input
              type="checkbox"
              checked={Boolean(
                (selectedClip.shadowColor || selectedClip.style?.shadowColor) &&
                (selectedClip.shadowBlur ??
                  selectedClip.style?.shadowBlur ??
                  0) > 0,
              )}
              onChange={(e) => {
                if (e.target.checked) {
                  updateTextStyle({
                    shadowColor:
                      selectedClip.shadowColor ||
                      selectedClip.style?.shadowColor ||
                      "rgba(0, 0, 0, 0.75)",
                    shadowBlur:
                      selectedClip.shadowBlur ||
                      selectedClip.style?.shadowBlur ||
                      6,
                    shadowOffsetX:
                      selectedClip.shadowOffsetX ??
                      selectedClip.style?.shadowOffsetX ??
                      2,
                    shadowOffsetY:
                      selectedClip.shadowOffsetY ??
                      selectedClip.style?.shadowOffsetY ??
                      2,
                  });
                } else {
                  updateTextStyle({
                    shadowColor: undefined,
                    shadowBlur: 0,
                    shadowOffsetX: 0,
                    shadowOffsetY: 0,
                  });
                }
              }}
              className="accent-navi rounded"
            />
            <span>Drop Shadow</span>
          </label>
          <span className="text-[10px] uppercase font-bold text-zinc-400">
            {(selectedClip.shadowBlur ?? selectedClip.style?.shadowBlur ?? 0) >
            0
              ? "Active"
              : "Off"}
          </span>
        </div>

        {Boolean(
          (selectedClip.shadowColor || selectedClip.style?.shadowColor) &&
          (selectedClip.shadowBlur ?? selectedClip.style?.shadowBlur ?? 0) > 0,
        ) && (
          <div className="space-y-2 pt-2 border-t border-zinc-200 dark:border-navidark-700">
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-zinc-500 dark:text-zinc-400">
                Shadow Color
              </span>
              <div className="flex items-center gap-2">
                <input
                  type="color"
                  value={
                    (
                      selectedClip.shadowColor ||
                      selectedClip.style?.shadowColor ||
                      "#000000"
                    ).startsWith("#")
                      ? selectedClip.shadowColor ||
                        selectedClip.style?.shadowColor ||
                        "#000000"
                      : "#000000"
                  }
                  onChange={(e) =>
                    updateTextStyle({ shadowColor: e.target.value })
                  }
                  className="w-7 h-6 rounded cursor-pointer border border-zinc-300 dark:border-navidark-600 bg-transparent"
                />
              </div>
            </div>

            <div className="space-y-1">
              <div className="flex justify-between items-center text-[11px] text-zinc-500 dark:text-zinc-400">
                <span>Shadow Blur</span>
                <span className="font-mono text-navi font-bold">
                  {selectedClip.shadowBlur ??
                    selectedClip.style?.shadowBlur ??
                    6}
                  px
                </span>
              </div>
              <input
                type="range"
                min="0"
                max="30"
                step="1"
                value={
                  selectedClip.shadowBlur ?? selectedClip.style?.shadowBlur ?? 6
                }
                onChange={(e) =>
                  updateTextStyle({ shadowBlur: parseInt(e.target.value) || 0 })
                }
                className="w-full accent-navi cursor-pointer h-1.5 bg-zinc-200 dark:bg-zinc-700 rounded-lg"
              />
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <div className="flex justify-between items-center text-[10px] text-zinc-500 dark:text-zinc-400">
                  <span>Offset X</span>
                  <span className="font-mono text-zinc-700 dark:text-zinc-300">
                    {selectedClip.shadowOffsetX ??
                      selectedClip.style?.shadowOffsetX ??
                      2}
                    px
                  </span>
                </div>
                <input
                  type="range"
                  min="-20"
                  max="20"
                  step="1"
                  value={
                    selectedClip.shadowOffsetX ??
                    selectedClip.style?.shadowOffsetX ??
                    2
                  }
                  onChange={(e) =>
                    updateTextStyle({
                      shadowOffsetX: parseInt(e.target.value) || 0,
                    })
                  }
                  className="w-full accent-navi cursor-pointer h-1.5 bg-zinc-200 dark:bg-zinc-700 rounded-lg"
                />
              </div>
              <div className="space-y-1">
                <div className="flex justify-between items-center text-[10px] text-zinc-500 dark:text-zinc-400">
                  <span>Offset Y</span>
                  <span className="font-mono text-zinc-700 dark:text-zinc-300">
                    {selectedClip.shadowOffsetY ??
                      selectedClip.style?.shadowOffsetY ??
                      2}
                    px
                  </span>
                </div>
                <input
                  type="range"
                  min="-20"
                  max="20"
                  step="1"
                  value={
                    selectedClip.shadowOffsetY ??
                    selectedClip.style?.shadowOffsetY ??
                    2
                  }
                  onChange={(e) =>
                    updateTextStyle({
                      shadowOffsetY: parseInt(e.target.value) || 0,
                    })
                  }
                  className="w-full accent-navi cursor-pointer h-1.5 bg-zinc-200 dark:bg-zinc-700 rounded-lg"
                />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Karaoke Mode */}
      <div className="space-y-2.5 bg-zinc-50 dark:bg-navidark-900 p-2.5 rounded border border-zinc-200 dark:border-navidark-700">
        <div className="flex items-center justify-between">
          <label className="flex items-center gap-2 cursor-pointer text-xs font-semibold text-zinc-800 dark:text-zinc-200">
            <input
              type="checkbox"
              checked={Boolean(
                selectedClip.karaoke ?? selectedClip.style?.karaoke,
              )}
              onChange={(e) => {
                updateTextStyle({
                  karaoke: e.target.checked,
                  karaokeHighlightColor:
                    selectedClip.karaokeHighlightColor ||
                    selectedClip.style?.karaokeHighlightColor ||
                    "#f59e0b",
                });
              }}
              className="accent-amber-500 rounded"
            />
            <span>Karaoke Timing Mode</span>
          </label>
          <span className="text-[10px] uppercase font-bold text-amber-500">
            {(selectedClip.karaoke ?? selectedClip.style?.karaoke)
              ? "Active"
              : "Off"}
          </span>
        </div>
        <p className="text-[10px] text-zinc-400 leading-normal">
          Progressively illuminates text in sync with clip duration during
          playback.
        </p>

        {(selectedClip.karaoke ?? selectedClip.style?.karaoke) && (
          <div className="space-y-2 pt-2 border-t border-zinc-200 dark:border-navidark-700">
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-zinc-500 dark:text-zinc-400">
                Highlight Color
              </span>
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-mono text-amber-500 font-bold uppercase">
                  {selectedClip.karaokeHighlightColor ||
                    selectedClip.style?.karaokeHighlightColor ||
                    "#f59e0b"}
                </span>
                <input
                  type="color"
                  value={
                    (
                      selectedClip.karaokeHighlightColor ||
                      selectedClip.style?.karaokeHighlightColor ||
                      "#f59e0b"
                    ).startsWith("#")
                      ? selectedClip.karaokeHighlightColor ||
                        selectedClip.style?.karaokeHighlightColor ||
                        "#f59e0b"
                      : "#f59e0b"
                  }
                  onChange={(e) =>
                    updateTextStyle({ karaokeHighlightColor: e.target.value })
                  }
                  className="w-7 h-6 rounded cursor-pointer border border-zinc-300 dark:border-navidark-600 bg-transparent"
                />
              </div>
            </div>

            {/* Swatches */}
            <div className="flex items-center gap-1.5 pt-1">
              <span className="text-[9px] text-zinc-400 mr-1">Presets:</span>
              {[
                { name: "Gold", color: "#ffd700" },
                { name: "Amber", color: "#f59e0b" },
                { name: "Sky", color: "#38bdf8" },
                { name: "Pink", color: "#ec4899" },
                { name: "Emerald", color: "#10b981" },
              ].map((swatch) => (
                <button
                  key={swatch.color}
                  type="button"
                  onClick={() =>
                    updateTextStyle({ karaokeHighlightColor: swatch.color })
                  }
                  className="w-5 h-5 rounded-full border border-white/20 shadow-sm transition-transform hover:scale-110"
                  style={{ backgroundColor: swatch.color }}
                  title={swatch.name}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
