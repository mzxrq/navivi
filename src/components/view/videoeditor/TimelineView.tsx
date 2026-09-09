import { listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";
import React, { useState, useEffect, useRef, useMemo } from "react";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useUI } from "../../../hooks/useUI";
import { MediaPool } from "./MediaPool";
import { TimelineTrack } from "./TimelineTrack";
import { ClipData } from "../../../types";
import { Inspector } from "./Inspector";
import { ExportPanel } from "./ExportPanel";
import { saveTimelineManifest } from "../../../services/fileSystem";
import {
  ZoomIn,
  ZoomOut,
  Play,
  Pause,
  SkipBack,
  SkipForward,
  MousePointer2,
  Scissors,
  Sparkles,
  Magnet,
  Eye,
  EyeOff,
  Volume2,
  VolumeX,
  Lock,
  Unlock,
  Type,
} from "../../ui/icons";
import { PreviewMonitor } from "./PreviewMonitor";

export function TimelineView() {
  const { timeline, setTimeline, autoLoadTimeline, metadata } = useWorkspace();
  const { showToast } = useUI();

  const [selectedClipIds, setSelectedClipIds] = useState<string[]>([]);
  const [copiedClips, setCopiedClips] = useState<ClipData[]>([]);

  const [activeTool, setActiveTool] = useState<"pointer" | "razor" | "magic">("pointer");
  const [rightPanelTab, setRightPanelTab] = useState<"inspector" | "export">("inspector");
  const [isRippleMode, setIsRippleMode] = useState(true);

  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [isScrubbing, setIsScrubbing] = useState(false);

  const timelineRef = useRef<HTMLDivElement>(null);
  const headerRef = useRef<HTMLDivElement>(null);
  const rulerRef = useRef<HTMLDivElement>(null);

  const [editingTrackId, setEditingTrackId] = useState<string | null>(null);

  const [marquee, setMarquee] = useState<{
    x1: number;
    y1: number;
    x2: number;
    y2: number;
  } | null>(null);

  const pixelsPerSecond = 20 * timeline.zoomMultiplier;

  // ✨ SORT TRACKS BY ORDER INDEX
  const sortedTracks = useMemo(() => {
    return [...timeline.tracks].sort((a, b) => (a.orderIndex ?? 0) - (b.orderIndex ?? 0));
  }, [timeline.tracks]);

  // ✨ Calculate track bounds using the SORTED tracks
  const trackBounds = useMemo(() => {
    let y = 0;
    return sortedTracks.map((t) => {
      const h = t.type === "video" || t.name.toLowerCase().includes("video") ? 80 : 56;
      const bounds = { id: t.id, top: y, bottom: y + h };
      y += h;
      return bounds;
    });
  }, [sortedTracks]);

  useEffect(() => {
    if (!marquee) return;
    const handleMouseMove = (e: MouseEvent) => {
      if (!timelineRef.current) return;
      const rect = timelineRef.current.getBoundingClientRect();
      const x = e.clientX - rect.left + timelineRef.current.scrollLeft;
      const y = e.clientY - rect.top + timelineRef.current.scrollTop;
      setMarquee((prev) => (prev ? { ...prev, x2: x, y2: y } : null));
    };

    const handleMouseUp = () => {
      if (marquee) {
        const mLeft = Math.min(marquee.x1, marquee.x2);
        const mRight = Math.max(marquee.x1, marquee.x2);
        const mTop = Math.min(marquee.y1, marquee.y2);
        const mBottom = Math.max(marquee.y1, marquee.y2);

        if (mRight - mLeft > 5 || mBottom - mTop > 5) {
          const selected = timeline.clips.filter((clip) => {
            const cLeft = clip.startTime * pixelsPerSecond;
            const cRight = (clip.startTime + clip.duration) * pixelsPerSecond;
            const tb = trackBounds.find((t) => t.id === clip.trackId);
            if (!tb) return false;

            return !(
              cRight < mLeft ||
              cLeft > mRight ||
              tb.bottom < mTop ||
              tb.top > mBottom
            );
          });
          if (selected.length > 0)
            setSelectedClipIds(selected.map((c) => c.id));
        }
        setMarquee(null);
      }
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [marquee, pixelsPerSecond, trackBounds, timeline.clips]);

  const handleZoom = (newZoom: number) =>
    setTimeline({ ...timeline, zoomMultiplier: newZoom });

  const handleSplitClip = (clipId: string, splitTime: number) => {
    const clip = timeline.clips.find((c) => c.id === clipId);
    const track = timeline.tracks.find((t) => t.id === clip?.trackId);
    if (
      !clip ||
      track?.isLocked ||
      splitTime <= clip.startTime ||
      splitTime >= clip.startTime + clip.duration
    )
      return;

    const clip1 = { ...clip, duration: splitTime - clip.startTime };
    const clip2 = {
      ...clip,
      id: crypto.randomUUID(),
      startTime: splitTime,
      duration: clip.duration - clip1.duration,
      sourceOffset: (clip.sourceOffset || 0) + clip1.duration,
    };
    setTimeline({
      ...timeline,
      clips: [...timeline.clips.filter((c) => c.id !== clipId), clip1, clip2],
    });
  };

  const handleSelectClip = (id: string | null, multi: boolean = false) => {
    if (!id) {
      setSelectedClipIds([]);
      return;
    }
    if (multi) {
      setSelectedClipIds((prev) =>
        prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
      );
    } else {
      setSelectedClipIds([id]);
    }
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const activeEl = document.activeElement as HTMLElement | null;
      const activeTag = activeEl?.tagName.toLowerCase();
      if (
        activeTag === "input" ||
        activeTag === "textarea" ||
        activeEl?.isContentEditable
      )
        return;

      const isCtrl = e.ctrlKey || e.metaKey;

      switch (e.key.toLowerCase()) {
        case " ":
          e.preventDefault();
          setIsPlaying((prev) => !prev);
          break;

        case "v":
          if (isCtrl) {
            e.preventDefault();
            if (copiedClips.length === 0) return;

            const minStart = Math.min(...copiedClips.map((c) => c.startTime));
            let newTracks = [...timeline.tracks];
            let newClips = [...timeline.clips];
            const pastedClipIds: string[] = [];

            const clipsByTrack = copiedClips.reduce(
              (acc, clip) => {
                if (!acc[clip.trackId]) acc[clip.trackId] = [];
                acc[clip.trackId].push(clip);
                return acc;
              },
              {} as Record<string, typeof copiedClips>,
            );

            Object.entries(clipsByTrack).forEach(([originalTrackId, clips]) => {
              const originalTrack = timeline.tracks.find(
                (t) => t.id === originalTrackId,
              );
              if (!originalTrack) return;

              const hasCollision = clips.some((pastedClip) => {
                const newStart =
                  currentTime + (pastedClip.startTime - minStart);
                const newEnd = newStart + pastedClip.duration;

                return timeline.clips.some((existing) => {
                  if (existing.trackId !== originalTrackId) return false;
                  const existEnd = existing.startTime + existing.duration;
                  return newStart < existEnd && newEnd > existing.startTime;
                });
              });

              let targetTrackId = originalTrackId;

              if (hasCollision) {
                targetTrackId = crypto.randomUUID();
                const isVideo = originalTrack.type !== "audio";
                const prefix = isVideo ? "VIDEO" : "AUDIO";
                const existingCount = newTracks.filter((t) =>
                  t.name.toUpperCase().includes(prefix),
                ).length;

                newTracks.push({
                  id: targetTrackId,
                  name: `${prefix} ${existingCount + 1}`,
                  type: originalTrack.type,
                  orderIndex: originalTrack.orderIndex + 0.1, // Insert right below
                  isLocked: false,
                  isHidden: false,
                  isMuted: false,
                });
              }

              clips.forEach((c) => {
                const newId = crypto.randomUUID();
                pastedClipIds.push(newId);
                newClips.push({
                  ...c,
                  id: newId,
                  trackId: targetTrackId,
                  startTime: currentTime + (c.startTime - minStart),
                });
              });
            });

            setTimeline({ ...timeline, tracks: newTracks, clips: newClips });
            setSelectedClipIds(pastedClipIds);
            showToast(`Pasted ${pastedClipIds.length} clip(s)`, "success");
          } else {
            setActiveTool("pointer");
          }
          break;

        case "c":
          if (isCtrl) {
            e.preventDefault();
            const toCopy = timeline.clips.filter((c) =>
              selectedClipIds.includes(c.id),
            );
            if (toCopy.length > 0) {
              setCopiedClips(toCopy);
              showToast(`Copied ${toCopy.length} clip(s)`, "success");
            }
          } else setActiveTool("razor");
          break;

        case "x":
          if (isCtrl) {
            e.preventDefault();
            const toCopy = timeline.clips.filter((c) =>
              selectedClipIds.includes(c.id),
            );
            if (toCopy.length > 0) {
              setCopiedClips(toCopy);

              const lockedTracks = timeline.tracks
                .filter((t) => t.isLocked)
                .map((t) => t.id);
              const toDelete = selectedClipIds.filter((id) => {
                const clip = timeline.clips.find((c: any) => c.id === id);
                return clip && !lockedTracks.includes(clip.trackId);
              });

              setTimeline({
                ...timeline,
                clips: timeline.clips.filter(
                  (c: any) => !toDelete.includes(c.id),
                ),
              });
              setSelectedClipIds([]);
              showToast(`Cut ${toCopy.length} clip(s)`, "success");
            }
          }
          break;

        case "a":
          if (isCtrl) {
            e.preventDefault();
            setSelectedClipIds(timeline.clips.map((c) => c.id));
          }
          break;

        case "l":
          if (isCtrl) {
            e.preventDefault();
            if (e.shiftKey) {
              setTimeline({
                ...timeline,
                clips: timeline.clips.map((c) =>
                  selectedClipIds.includes(c.id)
                    ? { ...c, groupId: undefined }
                    : c,
                ),
              });
              showToast("Clips unlinked", "success");
            } else {
              if (selectedClipIds.length < 2) {
                showToast("Select at least 2 clips to link", "warning");
                return;
              }
              const newGroupId = crypto.randomUUID();
              setTimeline({
                ...timeline,
                clips: timeline.clips.map((c) =>
                  selectedClipIds.includes(c.id)
                    ? { ...c, groupId: newGroupId }
                    : c,
                ),
              });
              showToast("Clips linked", "success");
            }
          }
          break;

        case "s":
          if (selectedClipIds.length > 0)
            selectedClipIds.forEach((id) => handleSplitClip(id, currentTime));
          break;

        case "escape":
          e.preventDefault();
          setSelectedClipIds([]);
          break;

        case "backspace":
        case "delete":
          if (selectedClipIds.length > 0) {
            const lockedTracks = timeline.tracks
              .filter((t) => t.isLocked)
              .map((t) => t.id);
            const toDelete = selectedClipIds.filter((id) => {
              const clip = timeline.clips.find((c: any) => c.id === id);
              return clip && !lockedTracks.includes(clip.trackId);
            });
            setTimeline({
              ...timeline,
              clips: timeline.clips.filter(
                (c: any) => !toDelete.includes(c.id),
              ),
            });
            setSelectedClipIds([]);
          }
          break;

        case "home":
          e.preventDefault();
          setCurrentTime(0);
          break;
        case "end":
          e.preventDefault();
          const dur = timeline.clips.reduce(
            (max, clip) => Math.max(max, clip.startTime + clip.duration),
            0,
          );
          setCurrentTime(dur);
          break;
        case "pageup":
          e.preventDefault();
          const edgesPrev = [
            0,
            ...timeline.clips.flatMap((c) => [
              c.startTime,
              c.startTime + c.duration,
            ]),
          ];
          const prevEdge =
            Math.max(...edgesPrev.filter((t) => t < currentTime - 0.01)) || 0;
          setCurrentTime(prevEdge);
          break;
        case "pagedown":
          e.preventDefault();
          const edgesNext = [
            ...timeline.clips.flatMap((c) => [
              c.startTime,
              c.startTime + c.duration,
            ]),
          ];
          const nextEdge = Math.min(
            ...edgesNext.filter((t) => t > currentTime + 0.01),
          );
          if (nextEdge !== Infinity) setCurrentTime(nextEdge);
          break;
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isPlaying, selectedClipIds, currentTime, timeline, copiedClips]);

  useEffect(() => {
    let animationFrameId: number;
    let lastTime = performance.now();
    const playLoop = (time: number) => {
      if (isPlaying) {
        const deltaTime = (time - lastTime) / 1000;
        setCurrentTime((prevTime) => {
          const totalDur = timeline.clips.reduce(
            (max, clip) => Math.max(max, clip.startTime + clip.duration),
            0,
          );
          const nextTime = prevTime + deltaTime;
          if (nextTime >= totalDur && totalDur > 0) {
            setIsPlaying(false);
            return totalDur;
          }
          return nextTime;
        });
      }
      lastTime = time;
      if (isPlaying) animationFrameId = requestAnimationFrame(playLoop);
    };
    if (isPlaying) animationFrameId = requestAnimationFrame(playLoop);
    return () => cancelAnimationFrame(animationFrameId);
  }, [isPlaying, timeline.clips]);

  const handleScrub = (clientX: number) => {
    if (!timelineRef.current) return;
    const rect = timelineRef.current.getBoundingClientRect();
    const scrollLeft = timelineRef.current.scrollLeft;
    const pixelsFromZero = clientX - rect.left + scrollLeft;
    setCurrentTime(Math.max(0, pixelsFromZero / pixelsPerSecond));
  };

  useEffect(() => {
    if (!isScrubbing) return;
    const onMouseMove = (e: MouseEvent) => {
      e.preventDefault();
      handleScrub(e.clientX);
    };
    const onMouseUp = () => setIsScrubbing(false);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [isScrubbing, timeline.zoomMultiplier]);

  useEffect(() => {
    const handleRenameEvent = (e: CustomEvent<{ trackId: string }>) =>
      setEditingTrackId(e.detail.trackId);
    window.addEventListener("start-rename-track" as any, handleRenameEvent);
    return () =>
      window.removeEventListener(
        "start-rename-track" as any,
        handleRenameEvent,
      );
  }, []);

  const handleUpdateTrackName = (trackId: string, newName: string) => {
    setEditingTrackId(null);
    if (!newName.trim()) return;
    setTimeline({
      ...timeline,
      tracks: timeline.tracks.map((t) =>
        t.id === trackId ? { ...t, name: newName.trim() } : t,
      ),
    });
  };

  const handleToggleTrackProp = (
    trackId: string,
    prop: "isHidden" | "isMuted" | "isLocked",
  ) => {
    setTimeline({
      ...timeline,
      tracks: timeline.tracks.map((t) =>
        t.id === trackId ? { ...t, [prop]: !t[prop] } : t,
      ),
    });
  };

  const handleUpdateClip = (id: string, updates: any) => {
    setTimeline({
      ...timeline,
      clips: timeline.clips.map((c) =>
        c.id === id ? { ...c, ...updates } : c,
      ),
    });
  };

  const PRELOAD_SECONDS = 0.5;
  const activeClipsToRender = timeline.clips.filter((clip) => {
    const track = timeline.tracks.find((t) => t.id === clip.trackId);
    if (!track || track.isHidden || track.isMuted) return false;

    return (
      currentTime >= clip.startTime - PRELOAD_SECONDS &&
      currentTime <= clip.startTime + clip.duration
    );
  });

  useEffect(() => {
    const unlisten = listen("render-complete", async (_event) => {
      if (metadata?.directory_path)
        await autoLoadTimeline(metadata.directory_path);
    });
    return () => {
      unlisten.then((f) => f());
    };
  }, [metadata]);

  const handleExportVideo = async () => {
    if (!metadata?.directory_path) return;
    const success = await saveTimelineManifest(
      metadata.directory_path,
      metadata.project_name || "Project",
      timeline,
    );
    if (success)
      invoke("export_video", { projectDir: metadata.directory_path }).catch(
        console.error,
      );
  };

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    if (headerRef.current)
      headerRef.current.scrollTop = e.currentTarget.scrollTop;
    if (rulerRef.current)
      rulerRef.current.scrollLeft = e.currentTarget.scrollLeft;
  };

  const handleUnlink = () => {
    setTimeline({
      ...timeline,
      clips: timeline.clips.map((c) =>
        selectedClipIds.includes(c.id) ? { ...c, groupId: undefined } : c,
      ),
    });
    showToast("Clips unlinked", "success");
  };

  const handleLink = () => {
    if (selectedClipIds.length < 2) return;
    const newGroupId = crypto.randomUUID();
    setTimeline({
      ...timeline,
      clips: timeline.clips.map((c) =>
        selectedClipIds.includes(c.id) ? { ...c, groupId: newGroupId } : c,
      ),
    });
    showToast("Clips linked", "success");
  };

  useEffect(() => {
    const onLink = () => handleLink();
    const onUnlink = () => handleUnlink();

    window.addEventListener("trigger-link-clips", onLink);
    window.addEventListener("trigger-unlink-clips", onUnlink);

    return () => {
      window.removeEventListener("trigger-link-clips", onLink);
      window.removeEventListener("trigger-unlink-clips", onUnlink);
    };
  }, [timeline, selectedClipIds]);

  const maxClipEnd = timeline.clips.reduce(
    (max, clip) => Math.max(max, clip.startTime + clip.duration),
    0,
  );
  const rulerDuration = Math.max(600, maxClipEnd + 120);
  const timelinePixelWidth = rulerDuration * pixelsPerSecond;

  let majorStep = 10,
    minorStep = 2;
  if (timeline.zoomMultiplier < 0.5) {
    majorStep = 30;
    minorStep = 10;
  } else if (timeline.zoomMultiplier > 2.5) {
    majorStep = 2;
    minorStep = 0.5;
  } else if (timeline.zoomMultiplier > 1.2) {
    majorStep = 5;
    minorStep = 1;
  }

  return (
    <div className="flex flex-col flex-1 h-full bg-white dark:bg-[#09090b] overflow-hidden select-none">
      <div className="flex-1 flex min-h-0 border-b border-zinc-200 dark:border-white/5">
        <div className="w-64 shrink-0 flex flex-col border-r border-zinc-200 dark:border-navidark-400">
          <MediaPool />
        </div>

        <div className="w-72 bg-white dark:bg-navidark-800 border-r border-zinc-200 dark:border-navidark-400 flex flex-col shrink-0">
          <div className="flex border-b border-zinc-200 dark:border-navidark-700 bg-zinc-50 dark:bg-navidark-900/50">
            <button
              onClick={() => setRightPanelTab("inspector")}
              className={`flex-1 py-3 text-xs font-bold uppercase tracking-wider transition-colors ${rightPanelTab === "inspector" ? "border-b-2 border-navi text-navi" : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"}`}
            >
              Inspector
            </button>
            <button
              onClick={() => setRightPanelTab("export")}
              className={`flex-1 py-3 text-xs font-bold uppercase tracking-wider transition-colors ${rightPanelTab === "export" ? "border-b-2 border-navi text-navi" : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"}`}
            >
              Export
            </button>
          </div>
          <div className="flex-1 overflow-y-auto custom-scrollbar p-4">
            {rightPanelTab === "inspector" ? (
              <Inspector
                selectedClipIds={selectedClipIds}
                onClearSelection={() => setSelectedClipIds([])}
              />
            ) : (
              <ExportPanel onExport={handleExportVideo} />
            )}
          </div>
        </div>

        <div className="flex-1 p-4 md:p-6 flex flex-col items-center justify-center bg-zinc-50/50 dark:bg-navidark-800 min-w-0 min-h-0 relative overflow-hidden">
          <div className="w-full max-w-5xl aspect-video bg-black border border-zinc-800 relative overflow-hidden group shadow-xl">
            {activeClipsToRender.length > 0 ? (
              <PreviewMonitor
                activeClips={activeClipsToRender}
                currentTime={currentTime}
                isPlaying={isPlaying}
                selectedClipId={
                  selectedClipIds.length === 1 ? selectedClipIds[0] : null
                }
                onSelectClip={(id) => handleSelectClip(id, false)}
                onUpdateClip={handleUpdateClip}
              />
            ) : (
              <div className="flex items-center justify-center h-full"></div>
            )}
          </div>
        </div>
      </div>

      <div className="h-80 shrink-0 flex flex-col bg-zinc-100 dark:bg-navidark-900 relative border-t border-zinc-300 dark:border-black shadow-[0_-4px_20px_rgba(0,0,0,0.1)] min-h-0">
        <div className="h-11 bg-white dark:bg-navidark-800 border-b border-zinc-200 dark:border-navidark-400 flex items-center justify-between px-4 shrink-0 z-30">
          {/* LEFT: Tools */}
          <div className="flex items-center gap-1 bg-zinc-100 dark:bg-navidark-900 p-1 rounded-md border border-zinc-200 dark:border-navidark-700">
            <button onClick={() => setActiveTool("pointer")} className={`p-1.5 rounded transition-colors ${activeTool === "pointer" ? "bg-white dark:bg-navidark-700 text-navi shadow-sm" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200"}`} title="Selection Tool (V)"><MousePointer2 className="w-4 h-4" /></button>
            <button onClick={() => setActiveTool("razor")} className={`p-1.5 rounded transition-colors ${activeTool === "razor" ? "bg-white dark:bg-navidark-700 text-navi shadow-sm" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200"}`} title="Razor Tool (C)"><Scissors className="w-4 h-4" /></button>
            
            <button 
              onClick={() => {
                const popupTrack = sortedTracks.find(t => t.type === "video" || t.type === "overlay");
                if (!popupTrack) return;
                
                const newTextClip: ClipData = {
                  id: crypto.randomUUID(),
                  trackId: popupTrack.id,
                  type: "text",
                  label: "Custom Text",
                  text: "Enter text here...",
                  startTime: currentTime,
                  duration: 5,
                  x: 960,
                  y: 540,
                  fontSize: 64,
                  color: "#ffffff"
                };
                setTimeline({ ...timeline, clips: [...timeline.clips, newTextClip] });
                showToast("Text added to timeline", "success");
              }} 
              className="p-1.5 rounded transition-colors text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200" 
              title="Add Custom Text"
            >
              <Type className="w-4 h-4" />
            </button>

            <div className="w-px h-4 bg-zinc-300 dark:bg-navidark-400 mx-1" />
            <button onClick={() => setIsRippleMode(!isRippleMode)} className={`p-1.5 rounded transition-colors ${isRippleMode ? "bg-navi text-white shadow-sm" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200"}`} title="Ripple Insert Mode"><Magnet className="w-4 h-4" /></button>
            <button onClick={() => setActiveTool("magic")} className={`p-1.5 rounded transition-colors ${activeTool === "magic" ? "bg-white dark:bg-navidark-700 text-navi shadow-sm" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200"}`} title="Auto-Transitions"><Sparkles className="w-4 h-4" /></button>
          </div>

          {/* CENTER: Playback Controls */}
          <div className="flex items-center gap-1 bg-zinc-100 dark:bg-navidark-900 p-1 rounded-md border border-zinc-200 dark:border-navidark-700">
            <button onClick={() => setCurrentTime(0)} className="p-1.5 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 transition-colors rounded hover:bg-zinc-200 dark:hover:bg-navidark-700" title="Home"><SkipBack className="w-4 h-4" /></button>
            <button onClick={() => setIsPlaying(!isPlaying)} className="p-1.5 text-zinc-500 hover:text-navi transition-colors rounded hover:bg-zinc-200 dark:hover:bg-navidark-700" title="Play/Pause (Space)">
              {isPlaying ? <Pause className="w-4 h-4" fill="currentColor" /> : <Play className="w-4 h-4" fill="currentColor" />}
            </button>
            <button onClick={() => setCurrentTime(timeline.clips.reduce((max, c) => Math.max(max, c.startTime + c.duration), 0))} className="p-1.5 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 transition-colors rounded hover:bg-zinc-200 dark:hover:bg-navidark-700" title="End"><SkipForward className="w-4 h-4" /></button>
            <div className="w-px h-4 bg-zinc-300 dark:bg-navidark-400 mx-2" />
            <div className="text-xs font-mono font-medium text-zinc-600 dark:text-zinc-300 px-2 py-0.5 pointer-events-none">
              {new Date(currentTime * 1000).toISOString().substring(11, 23).replace(".", ":")}
            </div>
          </div>

          {/* RIGHT: Zoom Controls */}
          <div className="flex items-center gap-2">
            <ZoomOut className="w-3.5 h-3.5 text-zinc-400" />
            <input type="range" min="0.2" max="5" step="0.1" value={timeline.zoomMultiplier} onChange={(e) => handleZoom(parseFloat(e.target.value))} className="w-24 accent-navi cursor-ew-resize" />
            <ZoomIn className="w-3.5 h-3.5 text-zinc-400" />
          </div>
        </div>

        <div className="flex-1 flex flex-row min-h-0 overflow-hidden">
          <div className="w-40 flex flex-col shrink-0 border-r border-zinc-300 dark:border-navidark-400 bg-zinc-50 dark:bg-navidark-800 z-40">
            <div className="h-8 w-full border-b border-zinc-300 dark:border-navidark-400 shrink-0 flex items-center px-3 bg-zinc-200/90 dark:bg-navidark-800/90">
              <span className="text-[9px] font-bold text-zinc-400 dark:text-zinc-500 tracking-widest">
                TRACKS
              </span>
            </div>
            <div
              ref={headerRef}
              className="flex-1 overflow-hidden"
              onContextMenu={(e) => {
                e.preventDefault();
                window.dispatchEvent(
                  new CustomEvent("open-context-menu", {
                    detail: { x: e.clientX, y: e.clientY, type: "empty-track" },
                  }),
                );
              }}
            >
              <div className="pb-32">
                {/* ✨ MAPPING OVER SORTED TRACKS */}
                {sortedTracks.map((track) => {
                  const isMainTrack = track.type === "video" || track.name.toLowerCase().includes("video");
                  const isAudioTrack = track.type === "audio";
                  const trackHeight = isMainTrack ? "h-20" : "h-14";
                  return (
                    <div
                      key={track.id}
                      onContextMenu={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        window.dispatchEvent(
                          new CustomEvent("open-context-menu", {
                            detail: {
                              x: e.clientX,
                              y: e.clientY,
                              type: "track-header",
                              targetId: track.id,
                            },
                          }),
                        );
                      }}
                      onDoubleClick={() => setEditingTrackId(track.id)}
                      className={`w-full border-b border-zinc-200 dark:border-navidark-400 flex flex-col justify-center px-3 ${editingTrackId === track.id ? "" : "cursor-context-menu"} ${trackHeight}`}
                    >
                      {editingTrackId === track.id ? (
                        <input
                          type="text"
                          autoFocus
                          defaultValue={track.name}
                          onBlur={(e) =>
                            handleUpdateTrackName(track.id, e.target.value)
                          }
                          onKeyDown={(e) => {
                            if (e.key === "Enter")
                              handleUpdateTrackName(track.id, e.currentTarget.value);
                            if (e.key === "Escape") setEditingTrackId(null);
                          }}
                          className="w-full bg-white dark:bg-navidark-900 text-[10px] font-bold text-zinc-900 dark:text-zinc-100 px-1.5 py-1 rounded outline-none border-2 border-navi"
                        />
                      ) : (
                        <span className="text-[10px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-wider truncate mb-1">
                          {track.name}
                        </span>
                      )}
                      <div className="flex items-center gap-2">
                        {!isAudioTrack ? (
                          <button
                            onClick={() => handleToggleTrackProp(track.id, "isHidden")}
                            className={`p-1 rounded transition-colors ${track.isHidden ? "text-red-500 bg-red-50 dark:bg-red-500/10" : "text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200"}`}
                          >
                            {track.isHidden ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                          </button>
                        ) : (
                          <button
                            onClick={() => handleToggleTrackProp(track.id, "isMuted")}
                            className={`p-1 rounded transition-colors ${track.isMuted ? "text-red-500 bg-red-50 dark:bg-red-500/10" : "text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200"}`}
                          >
                            {track.isMuted ? <VolumeX className="w-3.5 h-3.5" /> : <Volume2 className="w-3.5 h-3.5" />}
                          </button>
                        )}
                        <button
                          onClick={() => handleToggleTrackProp(track.id, "isLocked")}
                          className={`p-1 rounded transition-colors ${track.isLocked ? "text-red-500 bg-red-50 dark:bg-red-500/10" : "text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200"}`}
                        >
                          {track.isLocked ? <Lock className="w-3 h-3" /> : <Unlock className="w-3 h-3" />}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="flex-1 flex flex-col min-w-0 relative bg-zinc-50 dark:bg-navidark-800/50">
            <div
              ref={rulerRef}
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
                      <div className={`w-px bg-zinc-400 dark:bg-zinc-600 ${isMajor ? "h-2.5" : "h-1.5"}`} />
                      {isMajor && (
                        <span className="absolute bottom-3 -translate-x-1/2 text-[9px] text-zinc-500 dark:text-zinc-400 font-mono select-none pointer-events-none">
                          {Math.floor(time / 60).toString().padStart(2, "0")}:{Math.floor(time % 60).toString().padStart(2, "0")}
                        </span>
                      )}
                    </div>
                  );
                })}
                <div
                  className="absolute bottom-0 -translate-x-1/2 w-3 h-3 bg-red-500 [clip-path:polygon(50%_100%,0_0,100%_0)] z-50 pointer-events-none"
                  style={{ left: `${currentTime * pixelsPerSecond}px` }}
                />
              </div>
            </div>

            <div
              ref={timelineRef}
              onScroll={handleScroll}
              className="flex-1 overflow-auto custom-scrollbar relative"
              onMouseDown={(e) => {
                if (e.button === 2) return;
                if ((e.target as HTMLElement).closest(".react-draggable")) return;
                const rect = e.currentTarget.getBoundingClientRect();
                const x = e.clientX - rect.left + e.currentTarget.scrollLeft;
                const y = e.clientY - rect.top + e.currentTarget.scrollTop;
                setMarquee({ x1: x, y1: y, x2: x, y2: y });

                if (!e.shiftKey && !e.ctrlKey && !e.metaKey) {
                  setSelectedClipIds([]);
                }
              }}
            >
              <div
                className="relative min-w-max pb-24"
                style={{ width: `${timelinePixelWidth}px` }}
              >
                <div
                  className="absolute top-0 bottom-0 w-[1.5px] bg-red-500 z-35 pointer-events-none shadow-[0_0_10px_rgba(239,68,68,0.5)]"
                  style={{ left: `${currentTime * pixelsPerSecond}px` }}
                />

                {marquee && (
                  <div
                    className="absolute bg-navi-500/20 border border-navi-500 z-50 pointer-events-none"
                    style={{
                      left: Math.min(marquee.x1, marquee.x2),
                      top: Math.min(marquee.y1, marquee.y2),
                      width: Math.abs(marquee.x2 - marquee.x1),
                      height: Math.abs(marquee.y2 - marquee.y1),
                    }}
                  />
                )}

                {/* ✨ MAPPING OVER SORTED TRACKS */}
                {sortedTracks.map((track) => (
                  <TimelineTrack
                    key={track.id}
                    track={track}
                    selectedClipIds={selectedClipIds}
                    onSelectClip={handleSelectClip}
                    activeTool={activeTool}
                    onSplit={handleSplitClip}
                    isRippleMode={isRippleMode}
                    trackWidth={timelinePixelWidth}
                    currentTime={currentTime}
                    isLocked={track.isLocked || false}
                  />
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}