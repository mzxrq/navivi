import { useEffect, useRef, useState } from "react";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { ColorSwatches, RGB, rgbToHex } from "../../../components/ui/ColorSwatches";
import type { Waypoint } from "../../../types";

export function LegColorButton({ wp }: { wp: Waypoint }) {
  const { settings, updateWaypoint, setIsDirty } = useWorkspace();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const closeOnEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    window.addEventListener("keydown", closeOnEsc, true);
    return () => {
      document.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", closeOnEsc, true);
    };
  }, [open]);

  const setColor = (lineColor: RGB | undefined) => {
    updateWaypoint(wp.id, { lineColor });
    setIsDirty(true);
  };

  const shown = rgbToHex(wp.lineColor ?? settings.line_color);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen(!open);
        }}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={wp.lineColor ? t`Line color` : t`Line color: route color`}
        aria-label={t`Line color`}
        className={`flex items-center justify-center w-6 h-6 rounded-md transition-colors ${
          open ? "bg-zinc-200/80 dark:bg-white/10" : "hover:bg-zinc-100 dark:hover:bg-white/5"
        }`}
      >
        <span
          className={`w-2.5 h-2.5 rounded-full ring-1 ring-inset ring-black/15 dark:ring-white/20 ${
            wp.lineColor ? "" : "opacity-50"
          }`}
          style={{ backgroundColor: shown }}
        />
      </button>

      {open && (
        <div
          role="dialog"
          onClick={(e) => e.stopPropagation()}
          className="absolute left-0 top-full mt-1 z-50 p-3 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 shadow-lg animate-in fade-in zoom-in-95 duration-100"
        >
          <div className="flex items-center justify-between gap-4 mb-2.5">
            <span className="text-[12px] font-medium text-zinc-700 dark:text-zinc-300 whitespace-nowrap">
              <Trans>Line color</Trans>
            </span>
            {wp.lineColor && (
              <button
                type="button"
                onClick={() => setColor(undefined)}
                className="text-[11px] text-zinc-500 hover:text-navi whitespace-nowrap transition-colors"
              >
                <Trans>Use route color</Trans>
              </button>
            )}
          </div>
          <ColorSwatches color={wp.lineColor ?? null} onChange={setColor} />
        </div>
      )}
    </div>
  );
}
