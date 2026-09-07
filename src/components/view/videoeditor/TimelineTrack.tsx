import React, { useState, useRef } from "react";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useUI } from "../../../hooks/useUI";
import { TimelineTrack as TrackType } from "../../../types";
import { TimelineClip } from "./TimelineClip";

interface TrackProps {
  track: TrackType;
  onSplit: (id: string, time: number) => void;
  selectedClipIds?: string[];
  onSelectClip?: (id: string | null, multi?: boolean) => void;
  activeTool: string;
  trackWidth: number;
  isRippleMode: boolean;
  currentTime: number;
  isLocked?: boolean;
}

const pxPs = 20;

export function TimelineTrack({
  track,
  selectedClipIds,
  activeTool,
  onSelectClip,
  onSplit,
  trackWidth,
  isRippleMode,
  currentTime,
  isLocked,
}: TrackProps) {
  const { timeline, setTimeline } = useWorkspace();
  const { showToast } = useUI();

  const [isDragOver, setIsDragOver] = useState(false);
  const dragCounter = useRef(0);

  const trackClips = timeline.clips.filter((clip) => clip.trackId === track.id);
  const isMainTrack = track.name.toLowerCase().includes("video");
  const trackHeight = isMainTrack ? "h-20" : "h-14";

  const handleDragEnter = (e: React.DragEvent) => {
    if (isLocked) return;
    e.preventDefault();
    dragCounter.current += 1;
    if (dragCounter.current === 1) setIsDragOver(true);
  };

  const handleDragOver = (e: React.DragEvent) => {
    if (isLocked) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  };

  const handleDragLeave = (e: React.DragEvent) => {
    if (isLocked) return;
    e.preventDefault();
    dragCounter.current -= 1;
    if (dragCounter.current === 0) setIsDragOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    if (isLocked) return;
    e.preventDefault();
    dragCounter.current = 0;
    setIsDragOver(false);

    const assetData = e.dataTransfer.getData("text");
    if (!assetData) return;

    const asset = JSON.parse(assetData);
    const trackName = track.name.toLowerCase();

    if (trackName.includes("video") && asset.type === "audio") {
      showToast("Cannot place Audio on the Video track.", "error");
      return;
    }
    if (trackName.includes("voiceover") && asset.type !== "audio") {
      showToast("The Voiceover track only accepts Audio files.", "error");
      return;
    }
    if (trackName.includes("subtitle")) {
      showToast("Subtitles are generated automatically.", "warning");
      return;
    }
    if (trackName.includes("popup") && asset.type === "audio") {
      showToast("Popup track is for Images and Videos only.", "error");
      return;
    }

    const trackRect = e.currentTarget.getBoundingClientRect();
    const dropX = e.clientX - trackRect.left;
    const zoomRatio = pxPs * timeline.zoomMultiplier;

    const durationParts = asset.duration
      ? asset.duration.split(":")
      : ["00", "05"];
    const durationSeconds =
      parseInt(durationParts[0]) * 60 + parseInt(durationParts[1]);

    const finalStart = Math.max(0, dropX / zoomRatio);
    const finalEnd = finalStart + durationSeconds;

    const newClip = {
      id: crypto.randomUUID(),
      trackId: track.id,
      label: asset.name,
      source: asset.source || asset.id,
      type: asset.type,
      startTime: finalStart,
      duration: durationSeconds,
      sourceDuration: durationSeconds,
      sourceOffset: 0,
    };

    let newClips = [...timeline.clips];

    if (isRippleMode) {
      newClips = newClips.flatMap((c) => {
        if (c.trackId !== track.id) return [c];
        if (c.startTime >= finalStart)
          return [{ ...c, startTime: c.startTime + durationSeconds }];

        const cEnd = c.startTime + c.duration;
        if (c.startTime < finalStart && cEnd > finalStart) {
          return [
            { ...c, duration: finalStart - c.startTime },
            {
              ...c,
              id: crypto.randomUUID(),
              startTime: finalEnd,
              duration: cEnd - finalStart,
              sourceOffset: (c.sourceOffset || 0) + (finalStart - c.startTime),
            },
          ];
        }
        return [c];
      });
    } else {
      newClips = newClips.flatMap((c) => {
        if (c.trackId !== track.id) return [c];

        const cEnd = c.startTime + c.duration;
        if (c.startTime >= finalStart && cEnd <= finalEnd) return [];
        if (c.startTime < finalStart && cEnd > finalEnd) {
          return [
            { ...c, duration: finalStart - c.startTime },
            {
              ...c,
              id: crypto.randomUUID(),
              startTime: finalEnd,
              duration: cEnd - finalEnd,
              sourceOffset: (c.sourceOffset || 0) + (finalEnd - c.startTime),
            },
          ];
        }
        if (c.startTime < finalStart && cEnd > finalStart && cEnd <= finalEnd) {
          return [{ ...c, duration: finalStart - c.startTime }];
        }
        if (
          c.startTime >= finalStart &&
          c.startTime < finalEnd &&
          cEnd > finalEnd
        ) {
          return [
            {
              ...c,
              startTime: finalEnd,
              duration: cEnd - finalEnd,
              sourceOffset: (c.sourceOffset || 0) + (finalEnd - c.startTime),
            },
          ];
        }
        return [c];
      });
    }

    newClips.push(newClip);
    setTimeline({ ...timeline, clips: newClips });
    if (onSelectClip) onSelectClip(newClip.id);
  };

  return (
    <div
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      data-track-id={track.id}
      data-track-type={track.type}
      style={{ width: `${trackWidth}px` }}
      className={`relative border-b border-zinc-200 dark:border-navidark-400 transition-colors ${
        isDragOver
          ? "bg-navi-50/50 dark:bg-navi-900/30 border-navi/50"
          : "hover:bg-zinc-100/50 dark:hover:bg-navidark-700/50"
      } ${trackHeight} shrink-0`}
    >
      {isLocked && (
        <div className="absolute inset-0 bg-[repeating-linear-gradient(45deg,transparent,transparent_10px,rgba(0,0,0,0.03)_10px,rgba(0,0,0,0.03)_20px)] dark:bg-[repeating-linear-gradient(45deg,transparent,transparent_10px,rgba(255,255,255,0.02)_10px,rgba(255,255,255,0.02)_20px)] pointer-events-none z-10" />
      )}

      <div
        className={`w-full h-full ${isDragOver ? "pointer-events-none" : ""}`}
        onContextMenu={(e) => {
          e.preventDefault();
          window.dispatchEvent(
            new CustomEvent("open-context-menu", {
              detail: {
                x: e.clientX,
                y: e.clientY,
                type: "empty-track",
                targetId: track.id,
              },
            }),
          );
        }}
      >
        {trackClips.map((clip) => (
          <TimelineClip
            key={clip.id}
            clip={clip}
            activeTool={activeTool}
            onSplit={onSplit}
            isMainTrack={isMainTrack}
            isRippleMode={isRippleMode}
            pixelsPerSecond={pxPs * timeline.zoomMultiplier}
            isSelected={selectedClipIds?.includes(clip.id)}
            onSelect={(multi) => onSelectClip && onSelectClip(clip.id, multi)}
            currentTime={currentTime}
            isLocked={isLocked ?? false}
          />
        ))}
      </div>
    </div>
  );
}
