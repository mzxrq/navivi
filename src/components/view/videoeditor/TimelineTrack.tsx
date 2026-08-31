import React, { useState, useRef } from "react";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useUI } from "../../../hooks/useUI";
import { TimelineTrack as TrackType } from "../../../types";
import { TimelineClip } from "./TimelineClip";

interface TrackProps {
  track: TrackType;
  selectedClipId?: string | null;
  activeTool: string;
  onSplit: (id: string, time: number) => void;
  onSelectClip?: (id: string | null) => void;
  trackWidth: number; // 🛠️ Added new prop for dynamic infinite width
}

const pxPs = 20;

export function TimelineTrack({
  track,
  selectedClipId,
  activeTool,
  onSelectClip,
  onSplit,
  trackWidth, // 🛠️ Added to destructuring
}: TrackProps) {
  const { timeline, setTimeline } = useWorkspace();
  const { showToast } = useUI();

  const [isDragOver, setIsDragOver] = useState(false);
  const dragCounter = useRef(0);

  const trackClips = timeline.clips.filter((clip) => clip.trackId === track.id);
  const isMainTrack = track.name.toLowerCase().includes("video");
  const trackHeight = isMainTrack ? "h-20" : "h-14";

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    dragCounter.current += 1;
    if (dragCounter.current === 1) setIsDragOver(true);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    dragCounter.current -= 1;
    if (dragCounter.current === 0) setIsDragOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    dragCounter.current = 0;
    setIsDragOver(false);

    const assetData = e.dataTransfer.getData("text");
    if (!assetData) return;

    const asset = JSON.parse(assetData);
    const trackName = track.name.toLowerCase();

    // --- STRICT TRACK RULES ---
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
    
    // Parse duration
    const durationParts = asset.duration
      ? asset.duration.split(":")
      : ["00", "05"];
    const durationSeconds =
      parseInt(durationParts[0]) * 60 + parseInt(durationParts[1]);

    // 🛠️ THE COLLISION AVOIDANCE ENGINE
    let finalStart = Math.max(0, dropX / zoomRatio);
    let hasOverlap = true;

    while (hasOverlap) {
      const overlappingClip = trackClips.find((neighbor) => {
        const neighborEnd = neighbor.startTime + neighbor.duration;
        const currentEnd = finalStart + durationSeconds;
        // The 0.01 epsilon prevents false overlaps from floating-point math
        return (
          (finalStart >= neighbor.startTime && finalStart < neighborEnd - 0.01) ||
          (currentEnd > neighbor.startTime + 0.01 && currentEnd <= neighborEnd) ||
          (finalStart <= neighbor.startTime && currentEnd >= neighborEnd)
        );
      });

      if (overlappingClip) {
        // Slide it exactly to the end of the clip it hit, and check loop again!
        finalStart = overlappingClip.startTime + overlappingClip.duration;
      } else {
        hasOverlap = false; // It fits! Break the loop.
      }
    }

    const newClip = {
      id: crypto.randomUUID(),
      trackId: track.id,
      label: asset.name,
      source: asset.source || asset.id, 
      type: asset.type, 
      startTime: finalStart,
      duration: durationSeconds,
    };

    setTimeline({
      ...timeline,
      clips: [...timeline.clips, newClip],
    });

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
      style={{ width: `${trackWidth}px` }} // 🛠️ Applied the dynamic width!
      className={`relative border-b border-zinc-200 dark:border-navidark-400 transition-colors ${
        isDragOver
          ? "bg-navi-50/50 dark:bg-navi-900/30 border-navi/50"
          : "bg-white dark:bg-navidark-800 hover:bg-zinc-50 dark:hover:bg-navidark-700"
      } ${trackHeight} shrink-0`}
    >
      <div
        className={`w-full h-full ${isDragOver ? "pointer-events-none" : ""}`}
      >
        {trackClips.map((clip) => (
          <TimelineClip
            key={clip.id}
            clip={clip}
            activeTool={activeTool}
            onSplit={onSplit}
            isMainTrack={isMainTrack}
            pixelsPerSecond={pxPs * timeline.zoomMultiplier}
            isSelected={selectedClipId === clip.id}
            onSelect={() => onSelectClip && onSelectClip(clip.id)}
          />
        ))}
      </div>
    </div>
  );
}