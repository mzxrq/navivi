import { Trans } from "@lingui/react/macro";
import { panelAlphaStyle, useMapPanelOpacity } from "../../../../hooks/useMapPanelOpacity";
import { GRADIENT_STOPS } from "../../../../utils/elevation";
import type { LegElevationState } from "./useLegElevations";

interface HeatmapLegendProps {
  state: LegElevationState;
  is3D: boolean;
  onEnable3D: () => void;
}

const bar = `linear-gradient(to right, ${GRADIENT_STOPS.map(
  (s, i) => `${s.color} ${(i / (GRADIENT_STOPS.length - 1)) * 100}%`,
).join(", ")})`;

/** Colour key for the elevation heatmap, plus the reason when some legs could not be coloured. */
export function HeatmapLegend({ state, is3D, onEnable3D }: HeatmapLegendProps) {
  const { legs, missing, needsTerrain } = state;
  const opacity = useMapPanelOpacity();
  if (legs.length === 0) return null;
  const anyColored = legs.some((leg) => leg.ele);

  return (
    <div
      style={panelAlphaStyle(opacity)}
      className="absolute top-14 left-3 z-10 w-40 rounded-lg border border-zinc-200 bg-white/(--panel-alpha) p-2 text-[10px] shadow-sm backdrop-blur-md dark:border-white/10 dark:bg-zinc-900/(--panel-alpha)"
    >
      {anyColored && (
        <>
          <div className="mb-1 flex justify-between text-zinc-700 dark:text-zinc-300">
            <span><Trans>Downhill</Trans></span>
            <span><Trans>Uphill</Trans></span>
          </div>
          <div className="h-2 rounded-sm" style={{ background: bar }} />
          <div className="mt-0.5 flex justify-between text-zinc-500">
            <span>{GRADIENT_STOPS[0].pct}%</span>
            <span>0%</span>
            <span>+{GRADIENT_STOPS[GRADIENT_STOPS.length - 1].pct}%</span>
          </div>
        </>
      )}
      {missing > 0 && (
        <p className={`text-zinc-500 ${anyColored ? "mt-2" : ""}`}>
          {needsTerrain ? (
            <Trans>These legs have no recorded elevation. 3D terrain can supply it.</Trans>
          ) : (
            <Trans>Some legs are still waiting for terrain data. Move the map over them.</Trans>
          )}
        </p>
      )}
      {needsTerrain && !is3D && (
        <button
          type="button"
          onClick={onEnable3D}
          className="mt-1.5 rounded-md bg-navi px-2 py-1 text-[11px] text-white hover:brightness-110"
        >
          <Trans>Turn on 3D terrain</Trans>
        </button>
      )}
    </div>
  );
}
