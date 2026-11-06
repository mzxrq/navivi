import { useMemo } from "react";
import { t } from "@lingui/core/macro";
import { useWorkspace } from "../../../hooks/useWorkspace";
import type { Waypoint } from "../../../types/index";
import { legFacts } from "../../../utils/legEstimate";
import { legEnds } from "../../../utils/courses";
import { useSegmentElevation } from "../hooks/useSegmentElevations";

const formatKm = (km: number) => (km < 1 ? t`${Math.round(km * 1000)} m` : t`${km.toFixed(1)} km`);

function formatMinutes(minutes: number) {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return t`${m} min`;
  return m === 0 ? t`${h} h` : t`${h} h ${m} min`;
}

// Distance and time of the leg that leaves `wp`, for the sidebar's leg row (utils/courses.ts legEnds, as useMapRouting).
export function LegStats({ wp }: { wp: Waypoint }) {
  const { waypoints, routeSegments } = useWorkspace();
  const legs = useMemo(() => legEnds(waypoints), [waypoints]);
  const r = legs.findIndex(([from]) => from.id === wp.id);
  const terrain = useSegmentElevation(r);

  const stats = useMemo(() => {
    const seg = routeSegments[r];
    if (r < 0) return null;
    if (!seg || seg.mode === "calculating" || seg.positions.length < 2) return "pending" as const;
    return legFacts(legs[r][0], legs[r][1], seg, terrain);
  }, [legs, r, routeSegments, terrain]);

  if (!stats) return null;
  if (stats === "pending") return <span className="text-[11px] text-zinc-400" aria-hidden>…</span>;

  const title = [
    t`Distance along the path: ${stats.km.toFixed(2)} km`,
    stats.slopeKm !== null ? t`With height change: ${stats.slopeKm.toFixed(2)} km` : null,
    stats.ascentM !== null
      ? stats.source === "terrain"
        ? t`Climb: ${Math.round(stats.ascentM)} m (estimated from map terrain)`
        : t`Climb: ${Math.round(stats.ascentM)} m`
      : t`Time ignores climb: no elevation available for this leg`,
  ]
    .filter(Boolean)
    .join("\n");

  return (
    <span title={title} className="text-[11px] text-zinc-500 tabular-nums whitespace-nowrap">
      {formatKm(stats.km)}
      {stats.ascentM !== null && stats.ascentM >= 1 && <> · ↑{Math.round(stats.ascentM)} m</>}
      {" · "}
      {formatMinutes(stats.minutes)}
      {stats.ascentM !== null && <> ({t`flat ${formatMinutes(stats.flatMinutes)}`})</>}
    </span>
  );
}
