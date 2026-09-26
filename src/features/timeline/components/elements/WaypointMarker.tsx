import React, { memo } from "react";
import { MapPin } from "lucide-react";
import { WaypointTimelineMarker } from "../../../../types/index";
import { t } from "@lingui/core/macro"; import { Trans } from "@lingui/react/macro";

export interface WaypointMarkerProps {
  marker: WaypointTimelineMarker;
  pixelsPerSecond: number;
  isActive?: boolean;
  onSeek: (time: number) => void;
  onHover?: (marker: WaypointTimelineMarker | null, rect?: DOMRect) => void;
}

/**
 * Formats time in seconds into standard NLE timecode MM:SS.mmm
 */
export function formatMarkerTime(timeInSeconds: number): string {
  const safeTime = Math.max(0, isFinite(timeInSeconds) ? timeInSeconds : 0);
  const totalMilliseconds = Math.round(safeTime * 1000);
  const minutes = Math.floor(totalMilliseconds / 60000);
  const seconds = Math.floor((totalMilliseconds % 60000) / 1000);
  const milliseconds = totalMilliseconds % 1000;

  const mm = minutes.toString().padStart(2, "0");
  const ss = seconds.toString().padStart(2, "0");
  const mmm = milliseconds.toString().padStart(3, "0");

  return `${mm}:${ss}.${mmm}`;
}

export const WaypointMarker = memo(function WaypointMarker({
  marker,
  pixelsPerSecond,
  isActive = false,
  onSeek,
  onHover,
}: WaypointMarkerProps) {
  const xPosition = marker.time * pixelsPerSecond;
  const formattedTime = formatMarkerTime(marker.time);

  const handleTriggerSeek = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    onSeek(marker.time);
  };

  return (
    <div
      className="absolute top-0.5 -translate-x-1/2 group cursor-pointer z-30 select-none flex flex-col items-center"
      style={{ left: `${xPosition}px` }}
      onClick={handleTriggerSeek}
      onMouseDown={handleTriggerSeek}
      onMouseEnter={(e) => {
        onHover?.(marker, e.currentTarget.getBoundingClientRect());
      }}
      onMouseLeave={() => {
        onHover?.(null);
      }}
      title={t`Waypoint #${marker.index}: ${marker.name} (${formattedTime}) - Click to jump playhead`}
      role="button"
      tabIndex={0}
      aria-label={t`Waypoint ${marker.index}: ${marker.name} at ${formattedTime}`}
    >
      {/* Pin Badge */}
      <div
        className={`flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-[9px] font-bold tracking-tight shadow-sm transition-all duration-150 ${
          isActive
            ? "bg-amber-400 text-amber-950 ring-2 ring-white dark:ring-amber-200 shadow-md shadow-amber-500/50 scale-105"
            : "bg-amber-500 hover:bg-amber-400 text-amber-950 dark:bg-amber-500 dark:hover:bg-amber-400 dark:text-zinc-950 ring-1 ring-amber-400/60 hover:scale-105"
        }`}
      >
        <MapPin className="w-2.5 h-2.5 shrink-0 stroke-[2.5]" />
        <span className="font-extrabold leading-none">{marker.index}</span>
      </div>

      {/* Pin Needle Tip pointing to the ruler timestamp */}
      <div className="w-0 h-0 border-l-[3px] border-l-transparent border-r-[3px] border-r-transparent border-t-[3.5px] border-t-amber-500 group-hover:border-t-amber-400 mt-[-0.5px]" />

      {/* Embedded Hover Tooltip */}
      <div className="pointer-events-none opacity-0 group-hover:opacity-100 transition-all duration-150 delay-75 absolute top-full mt-1 z-50 flex flex-col items-center whitespace-nowrap shadow-xl">
        <div className="w-0 h-0 border-l-4 border-l-transparent border-r-4 border-r-transparent border-b-4 border-b-zinc-900/95 dark:border-b-zinc-800/95" />
        <div className="bg-zinc-900/95 dark:bg-zinc-800/95 backdrop-blur-sm text-white text-xs rounded-md border border-zinc-700/80 px-2 py-1 flex flex-col items-center gap-0.5">
          <div className="flex items-center gap-1 font-semibold text-amber-400 text-[11px]">
            <MapPin className="w-2.5 h-2.5 shrink-0" />
            <span>#{marker.index} {marker.name}</span>
          </div>
          <span className="font-mono text-[10px] text-zinc-300 tracking-wider">
            {formattedTime}
          </span>
          <span className="text-[8px] text-zinc-400">
            <Trans>Click to jump playhead</Trans>
          </span>
        </div>
      </div>
    </div>
  );
});

export interface WaypointGuideLineProps {
  marker: WaypointTimelineMarker;
  pixelsPerSecond: number;
}

export const WaypointGuideLine = memo(function WaypointGuideLine({
  marker,
  pixelsPerSecond,
}: WaypointGuideLineProps) {
  const xPosition = marker.time * pixelsPerSecond;

  return (
    <div
      key={`guide-${marker.id}`}
      className="absolute top-0 bottom-0 border-l border-dashed border-amber-500/40 pointer-events-none z-10"
      style={{ left: `${xPosition}px` }}
      title={t`Waypoint #${marker.index}: ${marker.name}`}
    />
  );
});
