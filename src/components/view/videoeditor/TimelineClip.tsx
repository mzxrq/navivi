
import { Rnd } from "react-rnd";
import { ClipData } from "../../../types";
import { useWorkspace } from "../../../hooks/useWorkspace";

interface ClipProps {
  clip: ClipData;
  isMainTrack: boolean;
  pixelsPerSecond: number;
  isSelected?: boolean;
  activeTool?: string;
  isRippleMode: boolean; // ✨ NEW
  currentTime: number;
  onSplit?: (id: string, time: number) => void;
  onSelect?: (multi: boolean) => void;
  isLocked: boolean;
}

export function TimelineClip({
  clip,
  isMainTrack,
  pixelsPerSecond,
  isSelected,
  activeTool = "pointer",
  isRippleMode, // ✨ NEW
  currentTime,
  onSplit,
  onSelect,
  isLocked,
}: ClipProps) {
  const { timeline, setTimeline } = useWorkspace();

  const xPos = clip.startTime * pixelsPerSecond;
  const clipWidth = Math.max(clip.duration * pixelsPerSecond, 10);
  const height = isMainTrack ? 80 : 56;

  const isMedia = clip.type === "video" || clip.type === "audio";
  const maxClipWidth = isMedia && clip.sourceDuration ? clip.sourceDuration * pixelsPerSecond : undefined;

  let colorClass = "bg-zinc-800 border-zinc-600 text-white";
  if (clip.type === 'audio') colorClass = "bg-purple-900/80 border-purple-700 text-purple-100";
  if (clip.type === 'image' || clip.type === 'static_popup') colorClass = "bg-amber-900/80 border-amber-700 text-amber-100";
  if (clip.type === 'text' || clip.type === 'subtitle') colorClass = "bg-blue-900/80 border-blue-700 text-blue-100";

  const selectedClass = isSelected
    ? "ring-2 ring-white shadow-lg z-30 brightness-110"
    : "opacity-90 hover:opacity-100 z-10";

  const transitionPixelWidth = 1.0 * pixelsPerSecond;

  const updateClipDimensions = (
    proposedStart: number,
    proposedDuration: number,
    targetTrackId: string = clip.trackId,
    isResize: boolean = false,
    isLeftResize: boolean = false
  ) => {
    
    // 🧲 THE MAGNETIC SNAP ENGINE 
    const SNAP_PIXELS = 15;
    const snapThreshold = SNAP_PIXELS / pixelsPerSecond;

    const snapPoints = new Set<number>([0, currentTime]);
    timeline.clips.forEach(c => {
      if (c.id !== clip.id) {
        snapPoints.add(c.startTime);
        snapPoints.add(c.startTime + c.duration);
      }
    });
    const snaps = Array.from(snapPoints);

    let finalStart = proposedStart;
    let finalDuration = proposedDuration;
    let finalEnd = finalStart + finalDuration;

    if (isResize) {
      if (isLeftResize) {
        const closest = snaps.reduce((a, b) => Math.abs(b - finalStart) < Math.abs(a - finalStart) ? b : a);
        if (Math.abs(closest - finalStart) < snapThreshold) {
          const originalEnd = clip.startTime + clip.duration;
          finalStart = closest;
          finalDuration = originalEnd - finalStart;
        }
      } else {
        const closest = snaps.reduce((a, b) => Math.abs(b - finalEnd) < Math.abs(a - finalEnd) ? b : a);
        if (Math.abs(closest - finalEnd) < snapThreshold) {
          finalEnd = closest;
          finalDuration = finalEnd - finalStart;
        }
      }
    } else {
      const closestStart = snaps.reduce((a, b) => Math.abs(b - finalStart) < Math.abs(a - finalStart) ? b : a);
      const closestEnd = snaps.reduce((a, b) => Math.abs(b - finalEnd) < Math.abs(a - finalEnd) ? b : a);

      const distStart = Math.abs(closestStart - finalStart);
      const distEnd = Math.abs(closestEnd - finalEnd);

      if (distStart < snapThreshold && distStart <= distEnd) {
        finalStart = closestStart;
      } else if (distEnd < snapThreshold && distEnd < distStart) {
        finalStart = closestEnd - finalDuration;
      }
    }

    finalStart = Math.max(0, finalStart);
    finalDuration = Math.max(0.1, finalDuration);

    if (isMedia && clip.sourceDuration && finalDuration > clip.sourceDuration) {
      finalDuration = clip.sourceDuration;
    }

    finalEnd = finalStart + finalDuration;

    // --- TIMELINE MATH ENGINE ---
    if (isResize) {
      // Wall Mode: Prevents resizing over other clips
      const targetNeighbors = timeline.clips.filter((c) => c.trackId === targetTrackId && c.id !== clip.id);
      const leftNeighbors = targetNeighbors.filter((n) => n.startTime < clip.startTime);
      const rightNeighbors = targetNeighbors.filter((n) => n.startTime > clip.startTime);

      const minStart = leftNeighbors.length > 0 ? Math.max(...leftNeighbors.map((n) => n.startTime + n.duration)) : 0;
      const maxEnd = rightNeighbors.length > 0 ? Math.min(...rightNeighbors.map((n) => n.startTime)) : Infinity;

      if (finalStart < minStart) {
        finalDuration -= (minStart - finalStart);
        finalStart = minStart;
      }
      if (finalStart + finalDuration > maxEnd) {
        finalDuration = maxEnd - finalStart;
      }

      setTimeline({
        ...timeline,
        clips: timeline.clips.map((c) => c.id === clip.id ? { ...c, startTime: finalStart, duration: finalDuration } : c),
      });
      
    } else {
      let newClips = [...timeline.clips].filter((c) => c.id !== clip.id);

      if (isRippleMode) {
        // ✨ RIPPLE MODE
        // 1. Close the gap on the original track left by lifting the clip
        newClips = newClips.map((c) => {
          if (c.trackId === clip.trackId && c.startTime > clip.startTime) {
            return { ...c, startTime: Math.max(0, c.startTime - clip.duration) };
          }
          return c;
        });

        // Calculate visual drop point (if we dragged on the same track, closing the gap shifts our drop target!)
        let effectiveStart = finalStart;
        if (clip.trackId === targetTrackId && finalStart > clip.startTime) {
           effectiveStart = Math.max(0, finalStart - clip.duration);
        }

        // 2. Open a new gap on the target track
        newClips = newClips.flatMap((c) => {
          if (c.trackId !== targetTrackId) return [c];

          // Push it right
          if (c.startTime >= effectiveStart) {
            return [{ ...c, startTime: c.startTime + finalDuration }];
          }

          // If dropped in the exact middle of a clip, split it and push the right half!
          const cEnd = c.startTime + c.duration;
          if (c.startTime < effectiveStart && cEnd > effectiveStart) {
             return [
               { ...c, duration: effectiveStart - c.startTime },
               { ...c, id: crypto.randomUUID(), startTime: effectiveStart + finalDuration, duration: cEnd - effectiveStart }
             ];
          }

          return [c];
        });

        newClips.push({ ...clip, startTime: effectiveStart, duration: finalDuration, trackId: targetTrackId });
        setTimeline({ ...timeline, clips: newClips });

      } else {
        // 🔥 OVERWRITE MODE
        newClips = newClips.flatMap((c) => {
          if (c.trackId !== targetTrackId) return [c];

          const cEnd = c.startTime + c.duration;
          if (c.startTime >= finalStart && cEnd <= finalEnd) return [];
          if (c.startTime < finalStart && cEnd > finalEnd) {
            return [
              { ...c, duration: finalStart - c.startTime },
              { ...c, id: crypto.randomUUID(), startTime: finalEnd, duration: cEnd - finalEnd }
            ];
          }
          if (c.startTime < finalStart && cEnd > finalStart && cEnd <= finalEnd) {
            return [{ ...c, duration: finalStart - c.startTime }];
          }
          if (c.startTime >= finalStart && c.startTime < finalEnd && cEnd > finalEnd) {
            return [{ ...c, startTime: finalEnd, duration: cEnd - finalEnd }];
          }
          return [c];
        });

        newClips.push({ ...clip, startTime: finalStart, duration: finalDuration, trackId: targetTrackId });
        setTimeline({ ...timeline, clips: newClips });
      }
    }
  };

  const formatTransitionLabel = (type: string) => {
    if (type.includes('crossfade')) return 'FADE';
    if (type.includes('black')) return 'BLACK';
    if (type.includes('white')) return 'WHITE';
    return 'TRANS';
  };

  return (
    <Rnd
      position={{ x: xPos, y: 0 }}
      size={{ width: clipWidth, height: height }}
      maxWidth={maxClipWidth}
      disableDragging={isLocked} 
      enableResizing={{
        left: !isLocked, right: !isLocked,
        top: false, bottom: false,
        topLeft: false, topRight: false, bottomLeft: false, bottomRight: false,
      }}
      resizeHandleClasses={{
        left: "hover:bg-white/30 transition-colors z-50",
        right: "hover:bg-white/30 transition-colors z-50"
      }}
      minWidth={10}
      dragAxis="both"
      bounds="parent"
      onMouseDownCapture={(e: React.MouseEvent) => {
        if (activeTool === "razor" && onSplit) {
          e.stopPropagation(); e.preventDefault();
          const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
          onSplit(clip.id, clip.startTime + (e.clientX - rect.left) / pixelsPerSecond);
          return;
        }
        if (onSelect) onSelect(e.shiftKey || e.ctrlKey || e.metaKey);
      }}
      onContextMenu={(e: React.MouseEvent) => {
        e.stopPropagation(); e.preventDefault();
        if (onSelect) onSelect(e.shiftKey || e.ctrlKey || e.metaKey);
        window.dispatchEvent(new CustomEvent("open-context-menu", { detail: { x: e.clientX, y: e.clientY, type: "timeline-clip", targetId: clip.id } }));
      }}
      onDragStop={(_e, data) => {
        const newStartTime = Math.max(0, data.x / pixelsPerSecond);
        updateClipDimensions(newStartTime, clip.duration, clip.trackId, false);
      }}
      onResizeStop={(_e, dir, ref, _delta, position) => {
        const newDuration = parseFloat(ref.style.width) / pixelsPerSecond;
        const newStartTime = Math.max(0, position.x / pixelsPerSecond);
        const isLeftResize = dir === "left" || dir === "topLeft" || dir === "bottomLeft";
        updateClipDimensions(newStartTime, newDuration, clip.trackId, true, isLeftResize);
      }}
      className={`absolute top-0 bottom-0 rounded-md border-2 overflow-hidden flex flex-col justify-center px-2 transition-[filter,box-shadow,opacity] group ${isLocked ? "" : "hover:z-20 cursor-pointer"} ${colorClass} ${selectedClass} ${isLocked ? "opacity-50 grayscale" : ""}`}
    >
      <span className="text-[10px] font-bold tracking-wide truncate pointer-events-none select-none relative z-20 drop-shadow-md">
        {clip.label}
      </span>
      
      {clip.transitionIn && clip.transitionIn !== "none" && (
         <div className="absolute left-0 top-0 bottom-0 border-r border-white/40 pointer-events-none flex items-center justify-center overflow-hidden bg-[repeating-linear-gradient(45deg,transparent,transparent_4px,rgba(255,255,255,0.15)_4px,rgba(255,255,255,0.15)_8px)]" style={{ width: Math.min(transitionPixelWidth, clipWidth / 2) }}>
           <span className="text-[8px] font-black text-white/80 -rotate-90 tracking-widest">{formatTransitionLabel(clip.transitionIn)}</span>
         </div>
      )}

      {clip.transitionOut && clip.transitionOut !== "none" && (
         <div className="absolute right-0 top-0 bottom-0 border-l border-white/40 pointer-events-none flex items-center justify-center overflow-hidden bg-[repeating-linear-gradient(-45deg,transparent,transparent_4px,rgba(255,255,255,0.15)_4px,rgba(255,255,255,0.15)_8px)]" style={{ width: Math.min(transitionPixelWidth, clipWidth / 2) }}>
           <span className="text-[8px] font-black text-white/80 rotate-90 tracking-widest">{formatTransitionLabel(clip.transitionOut)}</span>
         </div>
      )}
      
      {!isLocked && (
        <>
          <div className="absolute left-0 top-0 bottom-0 w-2 cursor-ew-resize hover:bg-white/30 transition-colors z-30" />
          <div className="absolute right-0 top-0 bottom-0 w-2 cursor-ew-resize hover:bg-white/30 transition-colors z-30" />
        </>
      )}
    </Rnd>
  );
}