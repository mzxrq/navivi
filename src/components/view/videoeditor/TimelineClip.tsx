import { useState, useEffect } from "react";
import { Rnd } from "react-rnd";
import { convertFileSrc } from "@tauri-apps/api/core";
import { ClipData } from "../../../types";
import { AudioWaveform } from "./elements/AudioWaveform";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useUI } from "../../../hooks/useUI"; // ✨ NEW: For throwing track-error toasts

interface ClipProps {
  clip: ClipData;
  isMainTrack: boolean;
  pixelsPerSecond: number;
  isSelected?: boolean;
  activeTool?: string;
  isRippleMode: boolean;
  currentTime: number;
  isLocked: boolean;
  onSplit?: (id: string, time: number) => void;
  onSelect?: (multi: boolean) => void;
}

export function TimelineClip({
  clip,
  isMainTrack,
  pixelsPerSecond,
  isSelected,
  activeTool = "pointer",
  isRippleMode,
  currentTime,
  isLocked,
  onSplit,
  onSelect,
}: ClipProps) {
  const { timeline, setTimeline } = useWorkspace();
  const { showToast } = useUI();

  // ✨ LINK LAYERS FIX: Real-time visual delta state
  const [dragDeltaX, setDragDeltaX] = useState<number>(0);

  // Listen for sibling clips being dragged
  useEffect(() => {
    if (!clip.groupId) return;
    
    const handleGroupDrag = (e: any) => {
      if (e.detail.groupId === clip.groupId && e.detail.sourceId !== clip.id) {
        setDragDeltaX(e.detail.deltaX);
      }
    };
    
    const handleGroupStop = (e: any) => {
      if (e.detail.groupId === clip.groupId && e.detail.sourceId !== clip.id) {
        setDragDeltaX(0);
      }
    };

    window.addEventListener('group-drag', handleGroupDrag);
    window.addEventListener('group-drag-stop', handleGroupStop);
    return () => {
      window.removeEventListener('group-drag', handleGroupDrag);
      window.removeEventListener('group-drag-stop', handleGroupStop);
    };
  }, [clip.groupId, clip.id]);

  const globalXPos = clip.startTime * pixelsPerSecond;
  const xPos = Math.max(0, globalXPos + dragDeltaX); // Prevent dragging visually past 00:00
  const clipWidth = Math.max(clip.duration * pixelsPerSecond, 10);
  const height = isMainTrack ? 80 : 56;

  const isMedia = clip.type === "video" || clip.type === "audio";
  const maxClipWidth =
    isMedia && clip.sourceDuration
      ? clip.sourceDuration * pixelsPerSecond
      : undefined;

  let colorClass = "bg-[#2D2D2D] border-[#404040] text-zinc-300"; // Video
  if (clip.type === "audio")
    colorClass = "bg-[#233F32] border-[#36604C] text-[#93C9B2]"; // Audio
  if (clip.type === "image")
    colorClass = "bg-[#3F2F23] border-[#604636] text-[#C9AD93]"; // Image
  if (clip.type === "text")
    colorClass = "bg-[#23323F] border-[#364C60] text-[#93B2C9]"; // Text

  const selectedClass = isSelected
    ? "border-white shadow-md z-30 brightness-125"
    : "opacity-100 hover:brightness-110 z-10";

  const safeUrl = clip.source ? convertFileSrc(clip.source) : "";
  const showThumbnail =
    (clip.type === "image" || clip.type === "video") && safeUrl;

  const updateClipDimensions = (
    proposedStart: number,
    proposedDuration: number,
    targetTrackId: string = clip.trackId,
    isResize: boolean = false,
    isLeftResize: boolean = false,
  ) => {
    const SNAP_PIXELS = 15;
    const snapThreshold = SNAP_PIXELS / pixelsPerSecond;

    const snapPoints = new Set<number>([0, currentTime]);
    timeline.clips.forEach((c) => {
      if (c.id !== clip.id && (!clip.groupId || c.groupId !== clip.groupId)) {
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
        const closest = snaps.reduce((a, b) =>
          Math.abs(b - finalStart) < Math.abs(a - finalStart) ? b : a,
        );
        if (Math.abs(closest - finalStart) < snapThreshold) {
          const originalEnd = clip.startTime + clip.duration;
          finalStart = closest;
          finalDuration = originalEnd - finalStart;
        }
      } else {
        const closest = snaps.reduce((a, b) =>
          Math.abs(b - finalEnd) < Math.abs(a - finalEnd) ? b : a,
        );
        if (Math.abs(closest - finalEnd) < snapThreshold) {
          finalEnd = closest;
          finalDuration = finalEnd - finalStart;
        }
      }
    } else {
      const closestStart = snaps.reduce((a, b) =>
        Math.abs(b - finalStart) < Math.abs(a - finalStart) ? b : a,
      );
      const closestEnd = snaps.reduce((a, b) =>
        Math.abs(b - finalEnd) < Math.abs(a - finalEnd) ? b : a,
      );

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

    let newSourceOffset = clip.sourceOffset || 0;
    if (isResize && isLeftResize) {
      newSourceOffset = Math.max(
        0,
        newSourceOffset + (finalStart - clip.startTime),
      );
    }

    const deltaStart = finalStart - clip.startTime;
    const deltaDuration = finalDuration - clip.duration;
    const deltaOffset = newSourceOffset - (clip.sourceOffset || 0);

    if (isResize) {
      const targetNeighbors = timeline.clips.filter(
        (c) => c.trackId === targetTrackId && c.id !== clip.id,
      );
      const leftNeighbors = targetNeighbors.filter(
        (n) => n.startTime < clip.startTime,
      );
      const rightNeighbors = targetNeighbors.filter(
        (n) => n.startTime > clip.startTime,
      );

      const minStart =
        leftNeighbors.length > 0
          ? Math.max(...leftNeighbors.map((n) => n.startTime + n.duration))
          : 0;
      const maxEnd =
        rightNeighbors.length > 0
          ? Math.min(...rightNeighbors.map((n) => n.startTime))
          : Infinity;

      if (finalStart < minStart) {
        finalDuration -= minStart - finalStart;
        finalStart = minStart;
      }
      if (finalStart + finalDuration > maxEnd) {
        finalDuration = maxEnd - finalStart;
      }

      setTimeline({
        ...timeline,
        clips: timeline.clips.map((c) => {
          if (c.id === clip.id) {
            return { ...c, startTime: finalStart, duration: finalDuration, sourceOffset: newSourceOffset };
          }
          if (clip.groupId && c.groupId === clip.groupId) {
            return {
              ...c,
              startTime: Math.max(0, c.startTime + deltaStart),
              duration: Math.max(0.1, c.duration + deltaDuration),
              sourceOffset: Math.max(0, (c.sourceOffset || 0) + deltaOffset),
            };
          }
          return c;
        }),
      });
    } else {
      const targetNeighbors = timeline.clips.filter((c) => c.trackId === targetTrackId && c.id !== clip.id);
      
      const overlapping = targetNeighbors.some(c => {
         return finalStart < c.startTime + c.duration && finalStart + finalDuration > c.startTime;
      });

      if (overlapping) {
         showToast("Cannot move clip here: overlaps with existing clips.", "error");
         return; // Revert
      }

      const newClips = timeline.clips.map((c) => {
        if (c.id === clip.id) {
          return {
            ...c,
            startTime: finalStart,
            duration: finalDuration,
            trackId: targetTrackId,
          };
        }
        if (clip.groupId && c.groupId === clip.groupId) {
          return {
            ...c,
            startTime: Math.max(0, c.startTime + deltaStart),
          };
        }
        return c;
      });

      setTimeline({ ...timeline, clips: newClips });
    }
  };

  const formatTransitionLabel = (type: string) => {
    if (type.includes("crossfade")) return "FADE";
    if (type.includes("black")) return "BLACK";
    if (type.includes("white")) return "WHITE";
    
    if (type.startsWith("glsl-")) {
      return type.replace("glsl-", "").substring(0, 5).toUpperCase();
    }
    return "TRANS";
  };

  return (
    <Rnd
      position={{ x: xPos, y: 0 }}
      size={{ width: clipWidth, height: height }}
      maxWidth={maxClipWidth}
      disableDragging={isLocked}
      // ✨ REMOVED bounds="parent" to allow vertical track crossing
      resizeHandleClasses={{
        left: "hover:bg-white/30 transition-colors z-50",
        right: "hover:bg-white/30 transition-colors z-50",
      }}
      enableResizing={{
        left: !isLocked, right: !isLocked,
        top: false, bottom: false, topLeft: false, topRight: false, bottomLeft: false, bottomRight: false,
      }}
      minWidth={10}
      dragAxis="both"
      onMouseDownCapture={(e: React.MouseEvent) => {
        if (e.button === 2) return;
        if (activeTool === "razor" && onSplit) {
          e.stopPropagation(); e.preventDefault();
          const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
          onSplit(clip.id, clip.startTime + (e.clientX - rect.left) / pixelsPerSecond);
          return;
        }
        if (onSelect) onSelect(e.shiftKey || e.ctrlKey || e.metaKey);
      }}
      onContextMenu={(e: React.MouseEvent) => {
        e.preventDefault(); e.stopPropagation();
        if (!isSelected && onSelect) onSelect(false);
        window.dispatchEvent(
          new CustomEvent("open-context-menu", {
            detail: { x: e.clientX, y: e.clientY, type: "timeline-clip", targetId: clip.id },
          }),
        );
      }}
      onDrag={(_e, data) => {
        const newDeltaX = data.x - globalXPos;
        setDragDeltaX(newDeltaX);
        
        // Broadcast movement to linked siblings instantly
        if (clip.groupId) {
          window.dispatchEvent(new CustomEvent('group-drag', {
             detail: { groupId: clip.groupId, deltaX: newDeltaX, sourceId: clip.id }
          }));
        }
      }}
      onDragStop={(e, data) => {
        setDragDeltaX(0);
        
        // Stop sibling broadcast
        if (clip.groupId) {
          window.dispatchEvent(new CustomEvent('group-drag-stop', { detail: { groupId: clip.groupId, sourceId: clip.id } }));
        }

        let targetTrackId = clip.trackId;

        // ✨ CROSS-TRACK DETECTION
        const clientX = 'clientX' in e ? (e as MouseEvent).clientX : ('touches' in e ? (e as TouchEvent).touches[0].clientX : 0);
        const clientY = 'clientY' in e ? (e as MouseEvent).clientY : ('touches' in e ? (e as TouchEvent).touches[0].clientY : 0);

        if (clientX && clientY) {
          // Find whatever HTML element the mouse was dropped on top of
          const elements = document.elementsFromPoint(clientX, clientY);
          const trackEl = elements.find(el => el.getAttribute('data-track-id'));

          if (trackEl) {
            const hoverTrackId = trackEl.getAttribute('data-track-id');
            const hoverTrackType = trackEl.getAttribute('data-track-type');

            if (clip.type === 'audio' && hoverTrackType !== 'audio') {
              showToast("Audio clips must stay in audio tracks.", "error");
            } else if (clip.type !== 'audio' && hoverTrackType === 'audio') {
              showToast("Cannot place video/text in audio tracks.", "error");
            } else {
              targetTrackId = hoverTrackId!;
            }
          }
        }

        const newStartTime = Math.max(0, data.x / pixelsPerSecond);
        updateClipDimensions(newStartTime, clip.duration, targetTrackId, false);
      }}
      onResizeStop={(_e, dir, ref, _delta, position) => {
        const newDuration = parseFloat(ref.style.width) / pixelsPerSecond;
        const newStartTime = Math.max(0, position.x / pixelsPerSecond);
        const isLeftResize = dir === "left" || dir === "topLeft" || dir === "bottomLeft";
        updateClipDimensions(newStartTime, newDuration, clip.trackId, true, isLeftResize);
      }}
      className={`absolute top-0 bottom-0 rounded border overflow-hidden flex flex-col justify-center px-2 transition-[filter,box-shadow,opacity] group ${isLocked ? "" : "hover:z-20 cursor-pointer"} ${colorClass} ${selectedClass} ${isLocked ? "opacity-50 grayscale" : ""}`}
    >
      {showThumbnail && (
        <div
          className="absolute inset-0 z-0 opacity-30 mix-blend-luminosity pointer-events-none"
          style={{
            backgroundImage: `url(${safeUrl})`,
            backgroundSize: "auto 100%",
            backgroundRepeat: "repeat-x",
            backgroundPosition: "left center",
          }}
        />
      )}

      {(clip.type === "audio" || clip.type === "video") && safeUrl && (
        <AudioWaveform src={safeUrl} width={clipWidth} height={height} />
      )}

      <span className="text-[10px] font-bold tracking-wide truncate pointer-events-none select-none relative z-20 drop-shadow-md">
        {clip.label}
      </span>

      {clip.fadeIn && clip.fadeIn > 0 && (
        <div
          className="absolute left-0 top-0 bottom-0 pointer-events-none z-20 group-hover:opacity-100 transition-opacity"
          style={{ width: clip.fadeIn * pixelsPerSecond }}
        >
          <svg
            className="w-full h-full"
            preserveAspectRatio="none"
            viewBox="0 0 100 100"
          >
            <polygon points="0,0 100,100 0,100" fill="rgba(255,255,255,0.15)" />
            <polyline
              points="0,100 100,0"
              fill="none"
              stroke="rgba(255,255,255,0.5)"
              strokeWidth="2"
            />
          </svg>
          {clip.transitionIn && clip.transitionIn !== "none" && (
            <span className="absolute bottom-1 left-1 text-[8px] font-black text-white/80 tracking-widest truncate w-full">
              {formatTransitionLabel(clip.transitionIn)}
            </span>
          )}
        </div>
      )}

      {clip.fadeOut && clip.fadeOut > 0 && (
        <div
          className="absolute right-0 top-0 bottom-0 pointer-events-none z-20 group-hover:opacity-100 transition-opacity"
          style={{ width: clip.fadeOut * pixelsPerSecond }}
        >
          <svg
            className="w-full h-full"
            preserveAspectRatio="none"
            viewBox="0 0 100 100"
          >
            <polygon
              points="100,0 100,100 0,100"
              fill="rgba(255,255,255,0.15)"
            />
            <polyline
              points="0,0 100,100"
              fill="none"
              stroke="rgba(255,255,255,0.5)"
              strokeWidth="2"
            />
          </svg>
          {clip.transitionOut && clip.transitionOut !== "none" && (
            <span className="absolute bottom-1 right-1 text-[8px] font-black text-white/80 tracking-widest text-right truncate w-full">
              {formatTransitionLabel(clip.transitionOut)}
            </span>
          )}
        </div>
      )}

      {!isLocked && (
        <>
          <div
            className="absolute left-0 top-0 w-3 h-3 bg-white/80 border border-black/50 cursor-crosshair z-40 rounded-br shadow-sm hover:bg-white transition-colors opacity-0 group-hover:opacity-100"
            style={{ transform: `translateX(${(clip.fadeIn || 0) * pixelsPerSecond}px)` }}
            onMouseDown={(e) => {
              e.stopPropagation();
              const startX = e.clientX;
              const initialFadeIn = clip.fadeIn || 0;

              const onMouseMove = (moveEvent: MouseEvent) => {
                const deltaX = moveEvent.clientX - startX;
                let newFadeIn = initialFadeIn + deltaX / pixelsPerSecond;
                newFadeIn = Math.max(0, Math.min(newFadeIn, clip.duration));

                setTimeline({
                  ...timeline,
                  clips: timeline.clips.map((c) =>
                    c.id === clip.id || (clip.groupId && c.groupId === clip.groupId)
                      ? { ...c, fadeIn: newFadeIn } : c,
                  ),
                });
              };
              const onMouseUp = () => {
                window.removeEventListener("mousemove", onMouseMove);
                window.removeEventListener("mouseup", onMouseUp);
              };
              window.addEventListener("mousemove", onMouseMove);
              window.addEventListener("mouseup", onMouseUp);
            }}
          />
          <div
            className="absolute right-0 top-0 w-3 h-3 bg-white/80 border border-black/50 cursor-crosshair z-40 rounded-bl shadow-sm hover:bg-white transition-colors opacity-0 group-hover:opacity-100"
            style={{ transform: `translateX(-${(clip.fadeOut || 0) * pixelsPerSecond}px)` }}
            onMouseDown={(e) => {
              e.stopPropagation();
              const startX = e.clientX;
              const initialFadeOut = clip.fadeOut || 0;

              const onMouseMove = (moveEvent: MouseEvent) => {
                const deltaX = moveEvent.clientX - startX;
                let newFadeOut = initialFadeOut - deltaX / pixelsPerSecond;
                newFadeOut = Math.max(0, Math.min(newFadeOut, clip.duration));

                setTimeline({
                  ...timeline,
                  clips: timeline.clips.map((c) =>
                    c.id === clip.id || (clip.groupId && c.groupId === clip.groupId)
                      ? { ...c, fadeOut: newFadeOut } : c,
                  ),
                });
              };
              const onMouseUp = () => {
                window.removeEventListener("mousemove", onMouseMove);
                window.removeEventListener("mouseup", onMouseUp);
              };
              window.addEventListener("mousemove", onMouseMove);
              window.addEventListener("mouseup", onMouseUp);
            }}
          />
        </>
      )}
    </Rnd>
  );
}