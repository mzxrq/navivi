import { useState } from "react";
import { Rnd } from "react-rnd";
import { TimelineClipData } from "../../../types";
import { useWorkspace } from "../../../hooks/useWorkspace";

interface ClipProps {
  clip: TimelineClipData;
  isMainTrack: boolean;
  pixelsPerSecond: number;
  isSelected?: boolean;
  activeTool?: string;
  onSplit?: (id: string, time: number) => void;
  onSelect?: () => void;
}

export function TimelineClip({
  clip,
  isMainTrack,
  pixelsPerSecond,
  isSelected,
  activeTool = "pointer",
  onSplit,
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

  const updateClipDimensions = (
    proposedStart: number,
    proposedDuration: number,
    targetTrackId: string = clip.trackId,
    isResize: boolean = false
  ) => {
    let finalStart = Math.max(0, proposedStart);
    let finalDuration = Math.max(0.1, proposedDuration);
    const finalEnd = finalStart + finalDuration;

    if (isResize) {
      // 🛠️ 1. STRICT BOUNDARIES FOR RESIZING
      const targetNeighbors = timeline.clips.filter(
        (c) => c.trackId === targetTrackId && c.id !== clip.id
      );

      // Find where our neighbors are relative to our ORIGINAL position
      const leftNeighbors = targetNeighbors.filter((n) => n.startTime < clip.startTime);
      const rightNeighbors = targetNeighbors.filter((n) => n.startTime > clip.startTime);

      const minStart = leftNeighbors.length > 0 
          ? Math.max(...leftNeighbors.map((n) => n.startTime + n.duration)) 
          : 0;
          
      const maxEnd = rightNeighbors.length > 0 
          ? Math.min(...rightNeighbors.map((n) => n.startTime)) 
          : Infinity;

      // Hit a wall on the left
      if (finalStart < minStart) {
        const diff = minStart - finalStart;
        finalStart = minStart;
        finalDuration -= diff;
      }

      // Hit a wall on the right
      if (finalStart + finalDuration > maxEnd) {
        finalDuration = maxEnd - finalStart;
      }

      setTimeline({
        ...timeline,
        clips: timeline.clips.map((c) =>
          c.id === clip.id
            ? { ...c, startTime: finalStart, duration: finalDuration }
            : c
        ),
      });
      
    } else {
      // 🛠️ 2. THE OVERWRITE ENGINE FOR DRAGGING
      let newClips = [...timeline.clips];

      // 1. Remove the dragged clip temporarily so we don't calculate against it
      newClips = newClips.filter((c) => c.id !== clip.id);

      // 2. Map through the timeline and dynamically slice anything that got dropped on
      newClips = newClips.flatMap((c) => {
        // Leave clips on other tracks completely alone
        if (c.trackId !== targetTrackId) return [c];

        const cEnd = c.startTime + c.duration;

        // Condition 1: Completely engulfed -> Delete it
        if (c.startTime >= finalStart && cEnd <= finalEnd) return [];

        // Condition 2: Engulfs the drop -> Split it down the middle!
        if (c.startTime < finalStart && cEnd > finalEnd) {
          const leftHalf = { ...c, duration: finalStart - c.startTime };
          const rightHalf = {
            ...c,
            id: crypto.randomUUID(), // Ensure the split half has a unique ID
            startTime: finalEnd,
            duration: cEnd - finalEnd,
          };
          return [leftHalf, rightHalf];
        }

        // Condition 3: Overlaps on the left -> Trim the tail
        if (c.startTime < finalStart && cEnd > finalStart && cEnd <= finalEnd) {
          return [{ ...c, duration: finalStart - c.startTime }];
        }

        // Condition 4: Overlaps on the right -> Trim the head
        if (c.startTime >= finalStart && c.startTime < finalEnd && cEnd > finalEnd) {
          return [{ ...c, startTime: finalEnd, duration: cEnd - finalEnd }];
        }

        // Safe! No overlap.
        return [c];
      });

      // 3. Insert the dragged clip safely into its new kingdom
      newClips.push({
        ...clip,
        startTime: finalStart,
        duration: finalDuration,
        trackId: targetTrackId,
      });

      setTimeline({ ...timeline, clips: newClips });
    }
  };

  return (
    <>
      <Rnd
        position={{ x: xPos, y: topPadding }}
        size={{ width: clipWidth, height: height }}
        enableResizing={{
          left: true,
          right: true,
          top: false,
          bottom: false,
          topLeft: false,
          topRight: false,
          bottomLeft: false,
          bottomRight: false,
        }}
        minWidth={10}
        dragAxis="both"
        bounds="parent" // 🛠️ 3. This physically prevents dragging to the left of 0:00!
        onMouseDownCapture={(e: React.MouseEvent) => {
          if (activeTool === "razor" && onSplit) {
            e.stopPropagation();
            e.preventDefault();
            const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
            const clickX = e.clientX - rect.left;
            const splitTime = clip.startTime + clickX / pixelsPerSecond;
            onSplit(clip.id, splitTime);
            return;
          }

          if (onSelect) onSelect();
          setContextMenu(null);
        }}
        onContextMenu={(e: React.MouseEvent) => {
          e.preventDefault();
          e.stopPropagation();
          if (onSelect) onSelect();
          window.dispatchEvent(
            new CustomEvent("open-context-menu", {
              detail: {
                x: e.clientX,
                y: e.clientY,
                type: "timeline-clip",
                targetId: clip.id,
              },
            })
          );
        }}
        onDragStop={(e, data) => {
          const clientX = "clientX" in e ? e.clientX : (e as any).touches?.[0]?.clientX || 0;
          const clientY = "clientY" in e ? e.clientY : (e as any).touches?.[0]?.clientY || 0;
          
          const elements = document.elementsFromPoint(clientX, clientY);
          const targetTrack = elements.find((el) => el.hasAttribute("data-track-id"));

          let newTrackId = clip.trackId;

          if (targetTrack) {
            const hoveredTrackId = targetTrack.getAttribute("data-track-id");
            const hoveredTrackType = targetTrack.getAttribute("data-track-type");
            const currentTrack = timeline.tracks.find((t) => t.id === clip.trackId);

            if (hoveredTrackId && hoveredTrackType === currentTrack?.type) {
              newTrackId = hoveredTrackId;
            }
          }

          const newStartTime = Math.max(0, data.x / pixelsPerSecond);
          updateClipDimensions(newStartTime, clip.duration, newTrackId, false); // FALSE = Drag/Overwrite Mode
        }}
        onResizeStop={(_e, _direction, ref, _delta, position) => {
          const newDuration = parseInt(ref.style.width, 10) / pixelsPerSecond;
          const newStartTime = Math.max(0, position.x / pixelsPerSecond);
          updateClipDimensions(newStartTime, newDuration, clip.trackId, true); // TRUE = Resize/Wall Mode
        }}
        className={`absolute ${
          isMainTrack ? "rounded-xl" : "rounded-full"
        } ${colorClass} border flex items-center px-3 cursor-pointer transition-[filter,box-shadow,opacity] group hover:z-20 ${selectedClass}`}
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