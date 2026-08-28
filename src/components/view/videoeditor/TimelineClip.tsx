import { useState } from "react";
import { Rnd } from "react-rnd";
import { TimelineClipData } from "../../../types";
import { useWorkspace } from "../../../hooks/useWorkspace";

interface ClipProps {
  clip: TimelineClipData;
  isMainTrack: boolean;
  pixelsPerSecond: number;
  isSelected?: boolean;
  onSelect?: () => void;
}

export function TimelineClip({
  clip,
  isMainTrack,
  pixelsPerSecond,
  isSelected,
  onSelect,
}: ClipProps) {
  const { timeline, setTimeline } = useWorkspace();
  const [_contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
  } | null>(null);

  const xPos = clip.startTime * pixelsPerSecond;
  const clipWidth = clip.duration * pixelsPerSecond;
  const height = isMainTrack ? 64 : 32;
  const topPadding = isMainTrack ? 8 : 8;

  const colorClass = isMainTrack
    ? "bg-zinc-900 border-zinc-700 text-white"
    : "bg-cyan-200 dark:bg-cyan-900 border-cyan-300 dark:border-cyan-700 text-cyan-900 dark:text-cyan-100";

  const selectedClass = isSelected
    ? "ring-2 ring-navi shadow-[0_0_15px_rgba(var(--navi-rgb),0.5)] z-30 brightness-110"
    : "opacity-95 hover:opacity-100 z-10";

  const updateClipDimensions = (proposedStart: number, proposedDuration: number, targetTrackId: string = clip.trackId) => {
    let finalStart = proposedStart;
    let finalDuration = proposedDuration;
    const proposedEnd = proposedStart + proposedDuration;

    // Check neighbors on the TARGET track (works for same track or new track)
    const targetNeighbors = timeline.clips.filter(
      (c) => c.trackId === targetTrackId && c.id !== clip.id
    );

    const overlappingClip = targetNeighbors.find((neighbor) => {
      const neighborEnd = neighbor.startTime + neighbor.duration;
      return (
        (proposedStart >= neighbor.startTime && proposedStart < neighborEnd) ||
        (proposedEnd > neighbor.startTime && proposedEnd <= neighborEnd) ||
        (proposedStart <= neighbor.startTime && proposedEnd >= neighborEnd)
      );
    });

    if (overlappingClip) {
      const neighborEnd = overlappingClip.startTime + overlappingClip.duration;
      if (proposedStart > clip.startTime || (proposedStart === clip.startTime && proposedDuration > clip.duration)) {
        if (proposedStart !== clip.startTime) finalStart = overlappingClip.startTime - proposedDuration; 
        else finalDuration = overlappingClip.startTime - proposedStart; 
      } else {
        if (proposedStart !== clip.startTime) finalStart = neighborEnd; 
        else {
          finalStart = neighborEnd; 
          finalDuration = proposedEnd - finalStart;
        }
      }
      if (finalStart < 0) finalStart = 0;
    }

    setTimeline({
      ...timeline,
      clips: timeline.clips.map((c) =>
        c.id === clip.id ? { ...c, startTime: finalStart, duration: finalDuration, trackId: targetTrackId } : c
      ),
    });
  };

  return (
<>
      <Rnd
        position={{ x: xPos, y: topPadding }}
        size={{ width: clipWidth, height: height }}
        enableResizing={{ left: true, right: true, top: false, bottom: false, topLeft: false, topRight: false, bottomLeft: false, bottomRight: false }}
        
        onMouseDownCapture={() => {
          if (onSelect) onSelect();
          setContextMenu(null);
        }}
        
        onContextMenu={(e: React.MouseEvent) => {
          e.preventDefault();
          e.stopPropagation();
          if (onSelect) onSelect();
          window.dispatchEvent(
            new CustomEvent("open-context-menu", {
              detail: { x: e.clientX, y: e.clientY, type: "timeline-clip", targetId: clip.id },
            })
          );
        }}
        
        onDragStop={(e, data) => {
          const clientX = 'clientX' in e ? e.clientX : (e as any).touches?.[0]?.clientX || 0;
          const clientY = 'clientY' in e ? e.clientY : (e as any).touches?.[0]?.clientY || 0;
          const elements = document.elementsFromPoint(clientX, clientY);
          const targetTrack = elements.find(el => el.hasAttribute('data-track-id'));

          let newTrackId = clip.trackId;
          
          if (targetTrack) {
            const hoveredTrackId = targetTrack.getAttribute('data-track-id');
            const hoveredTrackType = targetTrack.getAttribute('data-track-type');
            const currentTrack = timeline.tracks.find(t => t.id === clip.trackId);

            // Only allow it to switch if the track types match (e.g. video to video)
            if (hoveredTrackId && hoveredTrackType === currentTrack?.type) {
              newTrackId = hoveredTrackId;
            }
          }

          const newStartTime = Math.max(0, data.x / pixelsPerSecond);
          updateClipDimensions(newStartTime, clip.duration, newTrackId);
        }}
        
        onResizeStop={(_e, _direction, ref, _delta, position) => {
          const newDuration = parseInt(ref.style.width, 10) / pixelsPerSecond;
          const newStartTime = Math.max(0, position.x / pixelsPerSecond);
          updateClipDimensions(newStartTime, newDuration);
        }}
        className={`absolute ${isMainTrack ? "rounded-xl" : "rounded-full"} ${colorClass} border flex items-center px-3 cursor-pointer transition-[filter,box-shadow,opacity] group hover:z-20 ${selectedClass}`}
      >
        <span className="text-[10px] font-bold tracking-wide truncate pointer-events-none select-none">
          {clip.label}
        </span>

        <div className="absolute left-0 top-0 bottom-0 w-3 cursor-ew-resize group-hover:bg-white/20 rounded-l-full transition-colors" />
        <div className="absolute right-0 top-0 bottom-0 w-3 cursor-ew-resize group-hover:bg-white/20 rounded-r-full transition-colors" />
      </Rnd>
    </>
  );
}
