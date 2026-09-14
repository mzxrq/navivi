import { useMemo, useState } from "react";
import { useWorkspace } from "../../../hooks/useWorkspace";

export function ElevationProfile() {
  const { routePoints } = useWorkspace();
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const elevationData = useMemo(() => {
    if (!routePoints || routePoints.length === 0) return null;
    const hasElevation = routePoints.some((pt) => pt.length > 2 && pt[2] !== undefined);
    if (!hasElevation) return null;

    let totalDist = 0;
    const data = [{ dist: 0, ele: routePoints[0][2] || 0, pt: routePoints[0], index: 0 }];
    const R = 6371; // km

    let minEle = routePoints[0][2] || 0;
    let maxEle = routePoints[0][2] || 0;

    for (let i = 1; i < routePoints.length; i++) {
      const [lat1, lon1] = routePoints[i - 1];
      const [lat2, lon2, ele = 0] = routePoints[i];
      
      const dLat = (lat2 - lat1) * (Math.PI / 180);
      const dLon = (lon2 - lon1) * (Math.PI / 180);
      const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
        Math.cos(lat1 * (Math.PI / 180)) * Math.cos(lat2 * (Math.PI / 180)) *
        Math.sin(dLon / 2) * Math.sin(dLon / 2);
      const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
      totalDist += R * c;

      if (ele < minEle) minEle = ele;
      if (ele > maxEle) maxEle = ele;

      data.push({ dist: totalDist, ele, pt: routePoints[i], index: i });
    }

    return { data, totalDist, minEle, maxEle };
  }, [routePoints]);

  if (!elevationData || elevationData.data.length < 2) return null;

  const { data, totalDist, minEle, maxEle } = elevationData;
  const range = Math.max(maxEle - minEle, 10); // avoid div by 0

  return (
    <div className="absolute bottom-4 left-1/2 -translate-x-1/2 w-1/2 h-32 bg-white/90 dark:bg-zinc-900/90 backdrop-blur-md rounded-xl p-4 shadow-xl z-10 flex flex-col pointer-events-auto">
      <div className="text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-2 flex justify-between">
        <span>Elevation Profile</span>
        <span>{totalDist.toFixed(1)} km</span>
      </div>
      <div className="relative flex-1 w-full h-full group"
           onMouseLeave={() => {
             setHoverIndex(null);
             window.dispatchEvent(new CustomEvent('elevation-hover', { detail: null }));
           }}>
        <svg width="100%" height="100%" preserveAspectRatio="none">
          <defs>
            <linearGradient id="ele-grad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#296cf2" stopOpacity="0.4" />
              <stop offset="100%" stopColor="#296cf2" stopOpacity="0.0" />
            </linearGradient>
          </defs>
          <polyline
            points={data.map((d) => `${(d.dist / totalDist) * 100},${100 - ((d.ele - minEle) / range) * 100}`).join(" ")}
            fill="none"
            stroke="#296cf2"
            strokeWidth="2"
            vectorEffect="non-scaling-stroke"
          />
          <polygon
            points={`0,100 ${data.map((d) => `${(d.dist / totalDist) * 100},${100 - ((d.ele - minEle) / range) * 100}`).join(" ")} 100,100`}
            fill="url(#ele-grad)"
          />
        </svg>
        <div
          className="absolute inset-0 cursor-crosshair"
          onMouseMove={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const pct = x / rect.width;
            const dist = pct * totalDist;
            // find closest point
            let closest = data[0];
            let minDiff = Infinity;
            for (const d of data) {
              const diff = Math.abs(d.dist - dist);
              if (diff < minDiff) {
                minDiff = diff;
                closest = d;
              }
            }
            setHoverIndex(closest.index);
            window.dispatchEvent(new CustomEvent('elevation-hover', { detail: closest.pt }));
          }}
        />
        {hoverIndex !== null && (
          <div
            className="absolute top-0 bottom-0 border-l border-dashed border-navi-500 pointer-events-none flex flex-col justify-between"
            style={{ left: `${(data[hoverIndex].dist / totalDist) * 100}%` }}
          >
            <div className="bg-navi-500 text-white text-[10px] px-1 rounded -translate-x-1/2 whitespace-nowrap -mt-4">
              {data[hoverIndex].ele.toFixed(0)}m
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
