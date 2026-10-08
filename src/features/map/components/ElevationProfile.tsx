import { useMemo, useState } from "react";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { ChevronDown, ChevronUp, Mountain } from "../../../components/ui/icons";
import { panelAlphaStyle, useMapPanelOpacity } from "../../../hooks/useMapPanelOpacity";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { gradientColor, routeProfile, segmentGradients, type LegElevation } from "../../../utils/elevation";

const MAX_POINTS = 300;
const HIDDEN_KEY = "navivi_elevation_hidden";

export function ElevationProfile({ legs }: { legs: LegElevation[] }) {
  const { routePoints, settings } = useWorkspace();
  const opacity = useMapPanelOpacity();
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [hidden, setHiddenState] = useState(() => {
    try {
      return localStorage.getItem(HIDDEN_KEY) === "1";
    } catch {
      return false;
    }
  });
  const setHidden = (next: boolean) => {
    setHiddenState(next);
    if (next) {
      setHoverIndex(null);
      window.dispatchEvent(new CustomEvent("elevation-hover", { detail: null }));
    }
    try {
      localStorage.setItem(HIDDEN_KEY, next ? "1" : "0");
    } catch {}
  };

  // Shown with the heatmap, or right after importing a track that carries elevation.
  const wanted = Boolean(settings.show_route_heatmap) || routePoints.some((p) => Number.isFinite(p[2]));

  const profile = useMemo(() => {
    const full = wanted ? routeProfile(legs) : null;
    if (!full) return null;
    const step = Math.max(1, Math.ceil(full.points.length / MAX_POINTS));
    const keep = full.points.map((_, i) => i).filter((i) => i % step === 0 || i === full.points.length - 1);
    const dist = keep.map((i) => full.dist[i]);
    const ele = keep.map((i) => full.ele[i]);
    return { ...full, dist, ele, points: keep.map((i) => full.points[i]), slopes: segmentGradients(dist, ele) };
  }, [legs, wanted]);

  if (!profile) return null;

  const { dist, ele, points, slopes, totalMeters, min, max, gain, loss } = profile;
  const range = Math.max(max - min, 10);
  const x = (d: number) => (totalMeters > 0 ? (d / totalMeters) * 100 : 0);
  const y = (e: number) => 100 - ((e - min) / range) * 100;
  const line = dist.map((d, i) => `${x(d)},${y(ele[i])}`).join(" ");

  if (hidden) {
    return (
      <button
        type="button"
        onClick={() => setHidden(false)}
        aria-label={t`Show elevation profile`}
        style={panelAlphaStyle(opacity)}
        className="absolute bottom-4 left-3 z-10 pointer-events-auto flex items-center gap-1.5 h-8 px-3 rounded-lg bg-white/(--panel-alpha) dark:bg-zinc-900/(--panel-alpha) backdrop-blur-md shadow-lg text-[12px] font-medium text-zinc-700 dark:text-zinc-300 hover:text-zinc-900 dark:hover:text-white transition-colors"
      >
        <Mountain className="w-3.5 h-3.5" />
        <Trans>Elevation profile</Trans>
        <ChevronUp className="w-3.5 h-3.5" />
      </button>
    );
  }

  return (
    <div
      style={panelAlphaStyle(opacity)}
      className="absolute bottom-4 left-3 w-80 max-w-[calc(100%-1.5rem)] h-28 bg-white/(--panel-alpha) dark:bg-zinc-900/(--panel-alpha) backdrop-blur-md rounded-xl px-3 pt-2 pb-2.5 shadow-xl z-10 flex flex-col pointer-events-auto"
    >
      <div className="text-xs text-zinc-700 dark:text-zinc-300 mb-2 flex items-center justify-between gap-3 shrink-0">
        <span><Trans>Elevation profile</Trans></span>
        <span className="flex items-center gap-2">
          <span className="tabular-nums">
            {(totalMeters / 1000).toFixed(1)} km · +{gain.toFixed(0)} m · −{loss.toFixed(0)} m
          </span>
          <button
            type="button"
            onClick={() => setHidden(true)}
            aria-label={t`Hide elevation profile`}
            title={t`Hide elevation profile`}
            className="w-6 h-6 -mr-1.5 flex items-center justify-center rounded-md text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 dark:hover:text-zinc-200 dark:hover:bg-white/5 transition-colors"
          >
            <ChevronDown className="w-4 h-4" />
          </button>
        </span>
      </div>
      <div
        className="relative flex-1 min-h-0 w-full group"
        onMouseLeave={() => {
          setHoverIndex(null);
          window.dispatchEvent(new CustomEvent("elevation-hover", { detail: null }));
        }}
      >
        <svg className="absolute inset-0 w-full h-full" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polygon points={`0,100 ${line} 100,100`} fill="currentColor" className="text-zinc-400/15" />
          {slopes.map((pct, i) => (
            <line
              key={i}
              x1={x(dist[i])}
              y1={y(ele[i])}
              x2={x(dist[i + 1])}
              y2={y(ele[i + 1])}
              stroke={gradientColor(pct)}
              strokeWidth="2.5"
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </svg>
        <div
          className="absolute inset-0 cursor-crosshair"
          onMouseMove={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const target = ((e.clientX - rect.left) / rect.width) * totalMeters;
            let closest = 0;
            for (let i = 1; i < dist.length; i++) {
              if (Math.abs(dist[i] - target) < Math.abs(dist[closest] - target)) closest = i;
            }
            setHoverIndex(closest);
            window.dispatchEvent(
              new CustomEvent("elevation-hover", { detail: [points[closest][0], points[closest][1], ele[closest]] }),
            );
          }}
        />
        {hoverIndex !== null && dist[hoverIndex] !== undefined && (
          <div
            className="absolute top-0 bottom-0 border-l border-dashed border-navi pointer-events-none flex flex-col justify-between"
            style={{ left: `${x(dist[hoverIndex])}%` }}
          >
            <div className="bg-navi text-white text-[10px] px-1 rounded -translate-x-1/2 whitespace-nowrap -mt-4">
              {ele[hoverIndex].toFixed(0)} m
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
