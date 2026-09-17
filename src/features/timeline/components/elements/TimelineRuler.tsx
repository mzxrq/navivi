import React from "react";
import { WaypointTimelineMarker } from "../../../../types/index";
import { WaypointMarker } from "./WaypointMarker";

interface TimelineRulerProps {
  rulerRef: React.RefObject<HTMLDivElement | null>;
  timelineRef: React.RefObject<HTMLDivElement | null>;
  timelinePixelWidth: number;
  isPlaying: boolean;
  setIsPlaying: (playing: boolean) => void;
  setIsScrubbing: (scrubbing: boolean) => void;
  handleScrub: (clientX: number) => void;
  rulerDuration: number;
  minorStep: number;
  majorStep: number;
  pixelsPerSecond: number;
  waypointMarkers: WaypointTimelineMarker[];
  currentTime: number;
  setCurrentTime: (time: number) => void;
  handleMarkerHover: (
    marker: WaypointTimelineMarker | null,
    rect?: DOMRect,
  ) => void;
}

export function TimelineRuler({
  rulerRef,
  timelineRef,
  timelinePixelWidth,
  isPlaying,
  setIsPlaying,
  setIsScrubbing,
  handleScrub,
  rulerDuration,
  minorStep,
  majorStep,
  pixelsPerSecond,
  waypointMarkers,
  currentTime,
  setCurrentTime,
  handleMarkerHover,
}: TimelineRulerProps) {
  return (
    <div
      ref={rulerRef}
      onScroll={(e) => {
        if (timelineRef.current) {
          timelineRef.current.scrollLeft = e.currentTarget.scrollLeft;
        }
      }}
      className="h-8 w-full border-b border-zinc-300 dark:border-navidark-400 bg-zinc-200/90 dark:bg-navidark-800/90 overflow-hidden shrink-0"
    >
      <div
        className="h-full cursor-ew-resize relative shrink-0"
        style={{ width: `${timelinePixelWidth}px` }}
        onMouseDown={(e) => {
          if (isPlaying) setIsPlaying(false);
          setIsScrubbing(true);
          handleScrub(e.clientX);
        }}
      >
        {Array.from({
          length: Math.ceil(rulerDuration / minorStep),
        }).map((_, i) => {
          const time = i * minorStep;
          const isMajor = time % majorStep === 0;
          return (
            <div
              key={time}
              className="absolute bottom-0"
              style={{ left: `${time * pixelsPerSecond}px` }}
            >
              <div
                className={`w-px bg-zinc-400 dark:bg-zinc-600 ${isMajor ? "h-2.5" : "h-1.5"}`}
              />
              {isMajor && (
                <span className="absolute bottom-3 -translate-x-1/2 text-[9px] text-zinc-500 dark:text-zinc-400 font-semibold tracking-wider select-none pointer-events-none">
                  {Math.floor(time / 60)
                    .toString()
                    .padStart(2, "0")}
                  :
                  {Math.floor(time % 60)
                    .toString()
                    .padStart(2, "0")}
                </span>
              )}
            </div>
          );
        })}
        {/* Waypoint Timeline Ruler Markers (F4.2 & F4.3) */}
        {waypointMarkers.map((marker) => (
          <WaypointMarker
            key={marker.id}
            marker={marker}
            pixelsPerSecond={pixelsPerSecond}
            isActive={Math.abs(currentTime - marker.time) < 0.15}
            onSeek={(time) => {
              if (isPlaying) setIsPlaying(false);
              setCurrentTime(time);
            }}
            onHover={handleMarkerHover}
          />
        ))}

        <div
          className="absolute bottom-0 -translate-x-1/2 w-3 h-3 bg-navi [clip-path:polygon(50%_100%,0_0,100%_0)] z-50 pointer-events-none"
          style={{ left: `${currentTime * pixelsPerSecond}px` }}
        />
      </div>
    </div>
  );
}
