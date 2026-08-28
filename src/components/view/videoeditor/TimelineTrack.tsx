import React, { useState, useRef } from "react";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useUI } from "../../../hooks/useUI";
import { TimelineTrack as TrackType } from "../../../types";
import { TimelineClip } from "./TimelineClip";

interface TrackProps {
  track: TrackType;
  selectedClipId?: string | null;
  onSelectClip?: (id: string | null) => void;
}

const pxPs = 20;

export function TimelineTrack({
  track,
  selectedClipId,
  onSelectClip,
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
    const startTime = Math.max(0, dropX / zoomRatio);

    const durationParts = asset.duration
      ? asset.duration.split(":")
      : ["00", "05"];
    const durationSeconds =
      parseInt(durationParts[0]) * 60 + parseInt(durationParts[1]);

    const newClip = {
      id: crypto.randomUUID(),
      trackId: track.id,
      label: asset.name,
      source: asset.id,
      startTime: startTime,
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
      className={`flex-1 w-full min-w-[2000px] relative border-b border-zinc-200 dark:border-navidark-400 transition-colors ${
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
