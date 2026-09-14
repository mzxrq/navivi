import { useWorkspace } from "../../../hooks/useWorkspace";
import {
  Trash2,
  Type,
  Settings2,
  Sparkles,
  ImageIcon,
  CopyPlus,
  Volume2,
  VolumeX,
  Mic,
  Palette,
  Subtitles,
} from "../../ui/icons";

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
    desc: "Golden dynamic highlight & glow",
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

interface InspectorProps {
  selectedClipIds: string[];
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
        <p className="text-sm font-bold text-zinc-800 dark:text-zinc-200">
          {selectedClipIds.length} Clips Selected
        </p>
        <p className="text-[10px] mt-2 leading-relaxed">
          You can drag these clips together on the timeline, copy/paste them, or press Delete to remove them.
        </p>
        <button
          onClick={() => {
            setTimeline({
              ...timeline,
              clips: timeline.clips.filter((c) => !selectedClipIds.includes(c.id)),
            });
            onClearSelection();
          }}
          className="mt-6 px-4 py-2 bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400 text-xs font-bold rounded-lg hover:bg-red-100 transition-colors flex items-center gap-2"
        >
          <Trash2 className="w-3.5 h-3.5" /> Delete Selected
        </button>
      </div>
    );
  }

  const selectedClip = timeline.clips.find((c) => c.id === selectedClipIds[0]);
  if (!selectedClip) return null;

  const updateClip = (updates: Partial<typeof selectedClip>) => {
    setTimeline({
      ...timeline,
      clips: timeline.clips.map((c) =>
        c.id === selectedClip.id ? { ...c, ...updates } : c,
      ),
    });
  };

  const currentVol = selectedClip.volume !== undefined ? selectedClip.volume : 1.0;
  const currentVolPercent = Math.round(currentVol * 100);
  const volDb =
    currentVol > 0.001
      ? `${(20 * Math.log10(currentVol)).toFixed(1)} dB`
      : "-∞ dB";

  const isAudioClip = selectedClip.type === "audio";
  const isTextOrSubtitle =
    selectedClip.type === "text" || selectedClip.type === "subtitle";
  const duckingAmount = selectedClip.duckingAmount ?? 0.25;

  const updateTextStyle = (props: Partial<typeof selectedClip>) => {
    updateClip({
      ...props,
      style: {
        ...(selectedClip.style || {}),
        ...props,
      },
    });
  };

  return (
    <div className="flex-1 flex flex-col gap-4 animate-in fade-in duration-200">
      <div className="flex items-center justify-between pb-3 border-b border-zinc-200 dark:border-navidark-400">
        <div className="flex items-center gap-2">
          <div
            className={`w-2 h-2 rounded-full ${
              isAudioClip
                ? "bg-[#93C9B2]"
                : isTextOrSubtitle
                  ? "bg-amber-400"
                  : "bg-navi-500"
            }`}
          />
          <h4 className="text-sm font-bold text-zinc-800 dark:text-zinc-100 truncate w-40">
            {selectedClip.label}
          </h4>
        </div>
        <button
          onClick={() => {
            setTimeline({
              ...timeline,
              clips: timeline.clips.filter((c) => c.id !== selectedClip.id),
            });
            onClearSelection();
          }}
          className="p-1.5 text-zinc-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10 rounded-md transition-colors"
          title="Delete Clip"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

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
            className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-2 text-xs text-zinc-800 dark:text-zinc-200 focus:outline-none focus:border-navi"
          />
        </div>

        {/* Audio & Mixing Panel (for Audio clips) */}
        {isAudioClip && (
          <div className="space-y-4 pt-3 border-t border-zinc-200 dark:border-navidark-400">
            <div className="flex items-center justify-between">
              <h5 className="flex items-center gap-2 text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
                <Volume2 className="w-3.5 h-3.5 text-[#93C9B2]" /> Audio & Mixing
              </h5>
              <button
                type="button"
                onClick={() => updateClip({ isMuted: !selectedClip.isMuted })}
                className={`px-2 py-1 rounded text-xs font-semibold flex items-center gap-1.5 transition-colors ${
                  selectedClip.isMuted
                    ? "bg-red-500/20 text-red-400 border border-red-500/40"
                    : "bg-zinc-100 dark:bg-navidark-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-navidark-600"
                }`}
                title={selectedClip.isMuted ? "Unmute Clip" : "Mute Clip"}
              >
                {selectedClip.isMuted ? (
                  <>
                    <VolumeX className="w-3 h-3 text-red-400" />
                    <span>Muted</span>
                  </>
                ) : (
                  <>
                    <Volume2 className="w-3 h-3 text-emerald-400" />
                    <span>Mute</span>
                  </>
                )}
              </button>
            </div>

            {/* Volume Slider with % and dB readout */}
            <div className="space-y-1.5 bg-zinc-50 dark:bg-navidark-900 p-2.5 rounded border border-zinc-200 dark:border-navidark-700">
              <div className="flex justify-between items-center text-xs">
                <span className="font-semibold text-zinc-700 dark:text-zinc-300">
                  Volume
                </span>
                <div className="flex items-center gap-2 font-mono text-[11px]">
                  <span className="text-zinc-800 dark:text-zinc-200 font-bold">
                    {currentVolPercent}%
                  </span>
                  <span className="text-zinc-400 text-[10px]">({volDb})</span>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min="0"
                  max="150"
                  step="1"
                  value={currentVolPercent}
                  onChange={(e) =>
                    updateClip({ volume: parseFloat(e.target.value) / 100 })
                  }
                  className="w-full accent-[#36604C] dark:accent-[#93C9B2] cursor-pointer h-1.5 bg-zinc-200 dark:bg-zinc-700 rounded-lg"
                />
                <button
                  type="button"
                  onClick={() => updateClip({ volume: 1.0 })}
                  className="text-[10px] text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 underline shrink-0"
                  title="Reset to 100% (0 dB)"
                >
                  Reset
                </button>
              </div>
            </div>

            {/* Audio Role Selection */}
            <div className="space-y-1.5">
              <label className="text-[10px] font-bold text-zinc-500 uppercase tracking-wider flex items-center gap-1.5">
                <Mic className="w-3 h-3" /> Audio Role
              </label>
              <select
                value={selectedClip.audioRole || ""}
                onChange={(e) =>
                  updateClip({
                    audioRole: (e.target.value as any) || undefined,
                  })
                }
                className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-2 text-xs text-zinc-800 dark:text-zinc-200 cursor-pointer"
              >
                <option value="">Auto (Follow Track Name)</option>
                <option value="voice">Voice / Narration (Duck Trigger)</option>
                <option value="music">Music / BGM (Duckable)</option>
                <option value="sfx">Sound Effects (SFX)</option>
              </select>
            </div>

            {/* Fades: Fade In & Fade Out */}
            <div className="space-y-1.5">
              <label className="text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
                Fade Transitions
              </label>
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1 bg-zinc-50 dark:bg-navidark-900 p-2 rounded border border-zinc-200 dark:border-navidark-700">
                  <span className="text-[10px] text-zinc-400">Fade In (s)</span>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    max={selectedClip.duration}
                    value={(selectedClip.fadeIn || 0).toFixed(1)}
                    onChange={(e) =>
                      updateClip({
                        fadeIn: Math.max(0, parseFloat(e.target.value) || 0),
                      })
                    }
                    className="w-full bg-transparent text-xs font-mono text-zinc-800 dark:text-zinc-200 outline-none"
                  />
                </div>
                <div className="space-y-1 bg-zinc-50 dark:bg-navidark-900 p-2 rounded border border-zinc-200 dark:border-navidark-700">
                  <span className="text-[10px] text-zinc-400">Fade Out (s)</span>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    max={selectedClip.duration}
                    value={(selectedClip.fadeOut || 0).toFixed(1)}
                    onChange={(e) =>
                      updateClip({
                        fadeOut: Math.max(0, parseFloat(e.target.value) || 0),
                      })
                    }
                    className="w-full bg-transparent text-xs font-mono text-zinc-800 dark:text-zinc-200 outline-none"
                  />
                </div>
              </div>
            </div>

            {/* Auto-Ducking Configuration */}
            <div className="space-y-2.5 bg-zinc-50 dark:bg-navidark-900 p-2.5 rounded border border-zinc-200 dark:border-navidark-700">
              <div className="flex items-center justify-between">
                <label className="flex items-center gap-2 cursor-pointer text-xs font-semibold text-zinc-800 dark:text-zinc-200">
                  <input
                    type="checkbox"
                    checked={Boolean(selectedClip.ducking)}
                    onChange={(e) => updateClip({ ducking: e.target.checked })}
                    className="accent-amber-500 rounded"
                  />
                  <span>Auto-Duck during voice</span>
                </label>
                <span className="text-[10px] uppercase font-bold text-amber-500">
                  {selectedClip.ducking ? "Active" : "Off"}
                </span>
              </div>

              {selectedClip.ducking && (
                <div className="space-y-1 pt-1 border-t border-zinc-200 dark:border-navidark-700">
                  <div className="flex justify-between items-center text-[11px] text-zinc-500 dark:text-zinc-400">
                    <span>Attenuation</span>
                    <span className="font-mono text-amber-500 font-bold">
                      {Math.round((1 - duckingAmount) * 100)}% reduction (
                      {(20 * Math.log10(duckingAmount)).toFixed(1)} dB)
                    </span>
                  </div>
                  <input
                    type="range"
                    min="0.05"
                    max="0.8"
                    step="0.05"
                    value={duckingAmount}
                    onChange={(e) =>
                      updateClip({ duckingAmount: parseFloat(e.target.value) })
                    }
                    className="w-full accent-amber-500 cursor-pointer h-1.5 bg-zinc-200 dark:bg-zinc-700 rounded-lg"
                  />
                </div>
              )}
            </div>
          </div>
        )}

        {/* Typography & Subtitles Controls */}
        {isTextOrSubtitle && (
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
                      (selectedClip.color || selectedClip.style?.color || "#ffffff").startsWith("#")
                        ? (selectedClip.color || selectedClip.style?.color || "#ffffff")
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
                      (selectedClip.strokeWidth ?? selectedClip.style?.strokeWidth ?? 0) > 0 &&
                      (selectedClip.stroke || selectedClip.style?.stroke)
                    )}
                    onChange={(e) => {
                      if (e.target.checked) {
                        const defaultStroke = selectedClip.stroke || selectedClip.style?.stroke || "#000000";
                        const defaultWidth = (selectedClip.strokeWidth || selectedClip.style?.strokeWidth) || 3;
                        updateTextStyle({ stroke: defaultStroke, strokeWidth: defaultWidth });
                      } else {
                        updateTextStyle({ stroke: undefined, strokeWidth: 0 });
                      }
                    }}
                    className="accent-navi rounded"
                  />
                  <span>Text Outline / Stroke</span>
                </label>
                <span className="text-[10px] uppercase font-bold text-zinc-400">
                  {(selectedClip.strokeWidth ?? selectedClip.style?.strokeWidth ?? 0) > 0 ? "Active" : "Off"}
                </span>
              </div>

              {(selectedClip.strokeWidth ?? selectedClip.style?.strokeWidth ?? 0) > 0 && (
                <div className="space-y-2 pt-2 border-t border-zinc-200 dark:border-navidark-700">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] text-zinc-500 dark:text-zinc-400">
                      Outline Color
                    </span>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-mono text-zinc-400 uppercase">
                        {selectedClip.stroke || selectedClip.style?.stroke || "#000000"}
                      </span>
                      <input
                        type="color"
                        value={
                          (selectedClip.stroke || selectedClip.style?.stroke || "#000000").startsWith("#")
                            ? (selectedClip.stroke || selectedClip.style?.stroke || "#000000")
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
                        {selectedClip.strokeWidth ?? selectedClip.style?.strokeWidth ?? 3}px
                      </span>
                    </div>
                    <input
                      type="range"
                      min="0.5"
                      max="12"
                      step="0.5"
                      value={selectedClip.strokeWidth ?? selectedClip.style?.strokeWidth ?? 3}
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
                      (selectedClip.shadowBlur ?? selectedClip.style?.shadowBlur ?? 0) > 0
                    )}
                    onChange={(e) => {
                      if (e.target.checked) {
                        updateTextStyle({
                          shadowColor: selectedClip.shadowColor || selectedClip.style?.shadowColor || "rgba(0, 0, 0, 0.75)",
                          shadowBlur: (selectedClip.shadowBlur || selectedClip.style?.shadowBlur) || 6,
                          shadowOffsetX: (selectedClip.shadowOffsetX ?? selectedClip.style?.shadowOffsetX) ?? 2,
                          shadowOffsetY: (selectedClip.shadowOffsetY ?? selectedClip.style?.shadowOffsetY) ?? 2,
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
                  {(selectedClip.shadowBlur ?? selectedClip.style?.shadowBlur ?? 0) > 0 ? "Active" : "Off"}
                </span>
              </div>

              {Boolean(
                (selectedClip.shadowColor || selectedClip.style?.shadowColor) &&
                (selectedClip.shadowBlur ?? selectedClip.style?.shadowBlur ?? 0) > 0
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
                          (selectedClip.shadowColor || selectedClip.style?.shadowColor || "#000000").startsWith("#")
                            ? (selectedClip.shadowColor || selectedClip.style?.shadowColor || "#000000")
                            : "#000000"
                        }
                        onChange={(e) => updateTextStyle({ shadowColor: e.target.value })}
                        className="w-7 h-6 rounded cursor-pointer border border-zinc-300 dark:border-navidark-600 bg-transparent"
                      />
                    </div>
                  </div>

                  <div className="space-y-1">
                    <div className="flex justify-between items-center text-[11px] text-zinc-500 dark:text-zinc-400">
                      <span>Shadow Blur</span>
                      <span className="font-mono text-navi font-bold">
                        {selectedClip.shadowBlur ?? selectedClip.style?.shadowBlur ?? 6}px
                      </span>
                    </div>
                    <input
                      type="range"
                      min="0"
                      max="30"
                      step="1"
                      value={selectedClip.shadowBlur ?? selectedClip.style?.shadowBlur ?? 6}
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
                          {selectedClip.shadowOffsetX ?? selectedClip.style?.shadowOffsetX ?? 2}px
                        </span>
                      </div>
                      <input
                        type="range"
                        min="-20"
                        max="20"
                        step="1"
                        value={selectedClip.shadowOffsetX ?? selectedClip.style?.shadowOffsetX ?? 2}
                        onChange={(e) =>
                          updateTextStyle({ shadowOffsetX: parseInt(e.target.value) || 0 })
                        }
                        className="w-full accent-navi cursor-pointer h-1.5 bg-zinc-200 dark:bg-zinc-700 rounded-lg"
                      />
                    </div>
                    <div className="space-y-1">
                      <div className="flex justify-between items-center text-[10px] text-zinc-500 dark:text-zinc-400">
                        <span>Offset Y</span>
                        <span className="font-mono text-zinc-700 dark:text-zinc-300">
                          {selectedClip.shadowOffsetY ?? selectedClip.style?.shadowOffsetY ?? 2}px
                        </span>
                      </div>
                      <input
                        type="range"
                        min="-20"
                        max="20"
                        step="1"
                        value={selectedClip.shadowOffsetY ?? selectedClip.style?.shadowOffsetY ?? 2}
                        onChange={(e) =>
                          updateTextStyle({ shadowOffsetY: parseInt(e.target.value) || 0 })
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
                    checked={Boolean(selectedClip.karaoke ?? selectedClip.style?.karaoke)}
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
                  {(selectedClip.karaoke ?? selectedClip.style?.karaoke) ? "Active" : "Off"}
                </span>
              </div>
              <p className="text-[10px] text-zinc-400 leading-normal">
                Progressively illuminates text in sync with clip duration during playback.
              </p>

              {(selectedClip.karaoke ?? selectedClip.style?.karaoke) && (
                <div className="space-y-2 pt-2 border-t border-zinc-200 dark:border-navidark-700">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] text-zinc-500 dark:text-zinc-400">
                      Highlight Color
                    </span>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-mono text-amber-500 font-bold uppercase">
                        {selectedClip.karaokeHighlightColor || selectedClip.style?.karaokeHighlightColor || "#f59e0b"}
                      </span>
                      <input
                        type="color"
                        value={
                          (selectedClip.karaokeHighlightColor || selectedClip.style?.karaokeHighlightColor || "#f59e0b").startsWith("#")
                            ? (selectedClip.karaokeHighlightColor || selectedClip.style?.karaokeHighlightColor || "#f59e0b")
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
        )}

        {/* Visual Transitions (Hidden for audio, text, and subtitle) */}
        {!isAudioClip && !isTextOrSubtitle && (
          <div className="space-y-3 pt-3 border-t border-zinc-200 dark:border-navidark-400">
            <h5 className="flex items-center gap-2 text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
              <Sparkles className="w-3 h-3" /> Transitions
            </h5>
            <div className="space-y-2">
              <div>
                <label className="text-[10px] text-zinc-400 block mb-1">In-Transition</label>
                <select
                  value={selectedClip.transitionIn || "none"}
                  onChange={(e) => {
                    const val = e.target.value === "none" ? undefined : e.target.value;
                    if (val) {
                      const duration = selectedClip.fadeIn || 1.0;
                      const precedingClip = timeline.clips
                        .filter(
                          (c) =>
                            c.trackId === selectedClip.trackId &&
                            c.id !== selectedClip.id &&
                            c.startTime < selectedClip.startTime,
                        )
                        .sort((a, b) => (b.startTime + b.duration) - (a.startTime + a.duration))[0];

                      const updatedClips = timeline.clips.map((c) => {
                        if (c.id === selectedClip.id) {
                          return {
                            ...c,
                            transitionIn: val,
                            fadeIn: duration,
                            prevClip: precedingClip || undefined,
                          };
                        }
                        if (precedingClip && c.id === precedingClip.id) {
                          return {
                            ...c,
                            transitionOut: val,
                            fadeOut: duration,
                          };
                        }
                        return c;
                      });

                      const filteredTransitions = (timeline.transitions || []).filter(
                        (t) =>
                          !precedingClip ||
                          !(t.fromClipId === precedingClip.id && t.toClipId === selectedClip.id),
                      );

                      const newTransitions = precedingClip
                        ? [
                            ...filteredTransitions,
                            {
                              id: crypto.randomUUID(),
                              trackId: selectedClip.trackId,
                              fromClipId: precedingClip.id,
                              toClipId: selectedClip.id,
                              type: val,
                              duration: duration,
                              startTime:
                                precedingClip.startTime +
                                precedingClip.duration -
                                duration / 2,
                            },
                          ]
                        : filteredTransitions;

                      setTimeline({
                        ...timeline,
                        clips: updatedClips,
                        transitions: newTransitions,
                      });
                    } else {
                      updateClip({ transitionIn: undefined, fadeIn: undefined, prevClip: undefined });
                    }
                  }}
                  className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-2 text-xs text-zinc-800 dark:text-zinc-200 cursor-pointer"
                >
                  <option value="none">None</option>
                  <option value="glsl-crossfade">Crossfade (GLSL)</option>
                  <option value="glsl-wipe">Wipe (GLSL)</option>
                  <option value="glsl-slide">Slide (GLSL)</option>
                  <option value="glsl-dissolve">Dissolve (GLSL)</option>
                  <option value="glsl-dreamy">Dreamy (GLSL)</option>
                  <option value="glsl-directionalwarp">Directional Warp (GLSL)</option>
                  <option value="glsl-pixelize">Pixelize (GLSL)</option>
                  <option value="glsl-multiply_blend">Multiply Blend (GLSL)</option>
                  <option value="glsl-crosswarp">Cross Warp (GLSL)</option>
                  <option value="glsl-burn">Burn (GLSL)</option>
                  <option value="crossfade">Opacity Fade</option>
                  <option value="fade-black">Fade from Black</option>
                </select>
              </div>
              <div>
                <label className="text-[10px] text-zinc-400 block mb-1">Out-Transition</label>
                <select
                  value={selectedClip.transitionOut || "none"}
                  onChange={(e) => {
                    const val = e.target.value === "none" ? undefined : e.target.value;
                    if (val) {
                      const duration = selectedClip.fadeOut || 1.0;
                      const nextClip = timeline.clips
                        .filter(
                          (c) =>
                            c.trackId === selectedClip.trackId &&
                            c.id !== selectedClip.id &&
                            c.startTime > selectedClip.startTime,
                        )
                        .sort((a, b) => a.startTime - b.startTime)[0];

                      const updatedClips = timeline.clips.map((c) => {
                        if (c.id === selectedClip.id) {
                          return {
                            ...c,
                            transitionOut: val,
                            fadeOut: duration,
                          };
                        }
                        if (nextClip && c.id === nextClip.id) {
                          return {
                            ...c,
                            transitionIn: val,
                            fadeIn: duration,
                            prevClip: selectedClip,
                          };
                        }
                        return c;
                      });

                      const filteredTransitions = (timeline.transitions || []).filter(
                        (t) =>
                          !nextClip ||
                          !(t.fromClipId === selectedClip.id && t.toClipId === nextClip.id),
                      );

                      const newTransitions = nextClip
                        ? [
                            ...filteredTransitions,
                            {
                              id: crypto.randomUUID(),
                              trackId: selectedClip.trackId,
                              fromClipId: selectedClip.id,
                              toClipId: nextClip.id,
                              type: val,
                              duration: duration,
                              startTime:
                                selectedClip.startTime +
                                selectedClip.duration -
                                duration / 2,
                            },
                          ]
                        : filteredTransitions;

                      setTimeline({
                        ...timeline,
                        clips: updatedClips,
                        transitions: newTransitions,
                      });
                    } else {
                      updateClip({ transitionOut: undefined, fadeOut: undefined });
                    }
                  }}
                  className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-2 text-xs text-zinc-800 dark:text-zinc-200 cursor-pointer"
                >
                  <option value="none">None</option>
                  <option value="glsl-crossfade">Crossfade (GLSL)</option>
                  <option value="glsl-wipe">Wipe (GLSL)</option>
                  <option value="glsl-slide">Slide (GLSL)</option>
                  <option value="glsl-dissolve">Dissolve (GLSL)</option>
                  <option value="glsl-dreamy">Dreamy (GLSL)</option>
                  <option value="glsl-directionalwarp">Directional Warp (GLSL)</option>
                  <option value="glsl-pixelize">Pixelize (GLSL)</option>
                  <option value="glsl-multiply_blend">Multiply Blend (GLSL)</option>
                  <option value="glsl-crosswarp">Cross Warp (GLSL)</option>
                  <option value="glsl-burn">Burn (GLSL)</option>
                  <option value="crossfade">Opacity Fade</option>
                  <option value="fade-black">Fade to Black</option>
                </select>
              </div>
            </div>
          </div>
        )}

        {/* Color Adjustments (for Video and Image clips) */}
        {(selectedClip.type === "video" || selectedClip.type === "image") && (
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
        )}

        {/* Transform Edits (Hidden for audio clips) */}
        {!isAudioClip && (
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
        )}
      </div>
    </div>
  );
}