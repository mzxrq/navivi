import { useMemo, useState } from "react";
import { Trans } from "@lingui/react/macro";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { gradientColor, routeProfile, segmentGradients, type LegElevation } from "../../../utils/elevation";

const MAX_POINTS = 300;

export function ElevationProfile({ legs }: { legs: LegElevation[] }) {
  const { routePoints, settings } = useWorkspace();
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

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

  return (
    <div className="absolute bottom-4 left-1/2 -translate-x-1/2 w-1/2 h-32 bg-white/90 dark:bg-zinc-900/90 backdrop-blur-md rounded-xl p-4 shadow-xl z-10 flex flex-col pointer-events-auto">
      <div className="text-xs text-zinc-700 dark:text-zinc-300 mb-2 flex justify-between">
        <span><Trans>Elevation profile</Trans></span>
        <span>
          {(totalMeters / 1000).toFixed(1)} km · +{gain.toFixed(0)} m · −{loss.toFixed(0)} m
        </span>
      </div>
      <div
        className="relative flex-1 w-full h-full group"
        onMouseLeave={() => {
          setHoverIndex(null);
          window.dispatchEvent(new CustomEvent("elevation-hover", { detail: null }));
        }}
      >
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
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
