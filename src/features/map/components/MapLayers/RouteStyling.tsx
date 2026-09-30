import { useEffect, useRef, useState } from "react";
import { useWorkspace } from "../../../../hooks/useWorkspace";
import { Palette, X } from "../../../../components/ui/icons";
import { Switch } from "../../../../components/ui/Switch";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";

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

const hexToRgb = (hex: string): [number, number, number] => [
  parseInt(hex.slice(1, 3), 16),
  parseInt(hex.slice(3, 5), 16),
  parseInt(hex.slice(5, 7), 16),
];

function ColorRow({
  label,
  color,
  onChange,
}: {
  label: string;
  color: [number, number, number];
  onChange: (c: [number, number, number]) => void;
}) {
  const currentHex = rgbToHex(color);
  const isCustom = !PRESET_COLORS.includes(currentHex);
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[12px] text-zinc-700 dark:text-zinc-300">{label}</span>
        <span className="text-[10px] tabular-nums text-zinc-400">{currentHex.toUpperCase()}</span>
      </div>
      <div className="flex items-center gap-1.5">
        {PRESET_COLORS.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => onChange(hexToRgb(c))}
            aria-label={c}
            aria-pressed={currentHex === c}
            title={c}
            className={`w-5 h-5 rounded-full ring-1 ring-inset ring-black/10 dark:ring-white/15 transition-transform hover:scale-110 ${
              currentHex === c ? "outline-2 outline-offset-2 outline-navi" : ""
            }`}
            style={{ backgroundColor: c }}
          />
        ))}
        <label
          title={t`Custom Color`}
          className={`relative w-5 h-5 rounded-full cursor-pointer overflow-hidden ring-1 ring-inset ring-black/10 dark:ring-white/15 bg-[conic-gradient(#ef4444,#f59e0b,#10b981,#3b82f6,#8b5cf6,#ef4444)] transition-transform hover:scale-110 ${
            isCustom ? "outline-2 outline-offset-2 outline-navi" : ""
          }`}
        >
          <input
            type="color"
            value={currentHex}
            onChange={(e) => onChange(hexToRgb(e.target.value))}
            className="absolute inset-0 opacity-0 cursor-pointer"
          />
        </label>
      </div>
    </div>
  );
}

function SliderRow({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="block space-y-1.5">
      <span className="flex items-center justify-between">
        <span className="text-[12px] text-zinc-700 dark:text-zinc-300">{label}</span>
        <span className="text-[11px] text-zinc-500 tabular-nums">{value}px</span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(parseInt(e.target.value))}
        className="w-full h-1 accent-navi cursor-pointer"
      />
    </label>
  );
}

/** Route line / marker appearance, opened from the map's top-right controls. */
export function RouteStyling() {
  const [isOpen, setIsOpen] = useState(false);
  const { settings, updateSettings } = useWorkspace();
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    const onDown = (e: MouseEvent) => {
      if (!panelRef.current?.contains(e.target as Node)) setIsOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [isOpen]);

  return (
    <div ref={panelRef} className="relative">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        title={t`Route Lines Config`}
        aria-label={t`Route Lines Config`}
        className={`flex items-center justify-center w-7 h-7 rounded-lg transition-colors ${
          isOpen
            ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
            : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-white/5"
        }`}
      >
        <Palette className="w-3.5 h-3.5" />
      </button>

      {isOpen && (
        <div className="absolute top-full right-0 mt-2 w-72 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 shadow-lg z-40 animate-in fade-in zoom-in-95 duration-100">
          <div className="flex items-center justify-between px-3.5 pt-3 pb-2">
            <h3 className="text-[13px] font-semibold text-zinc-900 dark:text-zinc-100">
              <Trans>Map Appearance</Trans>
            </h3>
            <button
              type="button"
              onClick={() => setIsOpen(false)}
              title={t`Close`}
              aria-label={t`Close`}
              className="p-1 -mr-1 rounded-md text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 dark:hover:text-zinc-200 dark:hover:bg-white/5 transition-colors"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="px-3.5 pb-3 space-y-3">
            <ColorRow
              label={t`Route Line`}
              color={settings.line_color || [0, 200, 255]}
              onChange={(c) => updateSettings({ line_color: c })}
            />
            <ColorRow
              label={t`Border`}
              color={settings.route_line_border_color || [255, 255, 255]}
              onChange={(c) => updateSettings({ route_line_border_color: c })}
            />
            <ColorRow
              label={t`Marker`}
              color={settings.marker_color || [0, 0, 255]}
              onChange={(c) => updateSettings({ marker_color: c })}
            />
          </div>

          <div className="px-3.5 py-3 space-y-3 border-t border-zinc-100 dark:border-white/5">
            <SliderRow
              label={t`Line Thickness`}
              value={settings.line_thickness}
              min={2}
              max={24}
              onChange={(v) => updateSettings({ line_thickness: v })}
            />
            <SliderRow
              label={t`Border Width`}
              value={settings.route_line_border_thickness || 0}
              min={0}
              max={12}
              onChange={(v) => updateSettings({ route_line_border_thickness: v })}
            />
          </div>

          <div className="px-3.5 py-3 flex items-center gap-3 border-t border-zinc-100 dark:border-white/5">
            <div className="flex-1 min-w-0">
              <p className="text-[12px] text-zinc-700 dark:text-zinc-300">
                <Trans>Gradient Heatmap</Trans>
              </p>
              <p className="text-[11px] text-zinc-500">
                <Trans>Color route lines by slope gradient</Trans>
              </p>
            </div>
            <Switch
              checked={!!settings.show_route_heatmap}
              onChange={(v) => updateSettings({ show_route_heatmap: v })}
              label={t`Gradient Heatmap`}
            />
          </div>
        </div>
      )}
    </div>
  );
}
