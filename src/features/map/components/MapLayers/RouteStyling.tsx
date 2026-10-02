import { useEffect, useRef, useState } from "react";
import { useWorkspace } from "../../../../hooks/useWorkspace";
import { Palette, X } from "../../../../components/ui/icons";
import { Slider } from "../../../../components/ui/Slider";
import { Switch } from "../../../../components/ui/Switch";
import { ColorSwatches, RGB, rgbToHex } from "../../../../components/ui/ColorSwatches";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";

function ColorRow({
  label,
  color,
  onChange,
}: {
  label: string;
  color: RGB;
  onChange: (c: RGB) => void;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[12px] text-zinc-700 dark:text-zinc-300">{label}</span>
        <span className="text-[10px] tabular-nums text-zinc-400">{rgbToHex(color).toUpperCase()}</span>
      </div>
      <ColorSwatches color={color} onChange={onChange} />
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
      <Slider label={label} min={min} max={max} value={value} onChange={onChange} format={(v) => `${v}px`} />
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
            ? "bg-navi text-white shadow-sm"
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
