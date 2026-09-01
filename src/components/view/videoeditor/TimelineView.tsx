import { listen } from "@tauri-apps/api/event";
import { convertFileSrc, invoke } from "@tauri-apps/api/core";
import React, { useState, useEffect, useRef } from "react";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { MediaPool } from "./MediaPool";
import { TimelineTrack } from "./TimelineTrack";
import { TimelineTrack as TrackType } from "../../../types";
import { Inspector } from "./Inspector";
import { ExportPanel } from "./ExportPanel"; // 🛠️ Added ExportPanel import
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
} from "../../ui/icons";
import { PreviewMonitor } from "./PreviewMonitor";

export function TimelineView() {
  const { timeline, setTimeline, autoLoadTimeline, metadata } = useWorkspace();
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null);
  const [activeTool, setActiveTool] = useState<"pointer" | "razor" | "magic">(
    "pointer",
  );
  
  // 🛠️ Added new states for Tabs and Ripple Mode
  const [rightPanelTab, setRightPanelTab] = useState<"inspector" | "export">("inspector");
  const [isRippleMode, setIsRippleMode] = useState(true);

  // Playback & Scrubbing
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [isScrubbing, setIsScrubbing] = useState(false);
  const timelineRef = React.useRef<HTMLDivElement>(null);

  // Track Renaming State ---
  const [editingTrackId, setEditingTrackId] = useState<string | null>(null);

  // Timeline Zoom
  const handleZoom = (newZoom: number) => {
    setTimeline({ ...timeline, zoomMultiplier: newZoom });
  };

  const handleSplitClip = (clipId: string, splitTime: number) => {
    const clip = timeline.clips.find(c => c.id === clipId);
    if (!clip || splitTime <= clip.startTime || splitTime >= clip.startTime + clip.duration) return;

    const clip1 = { ...clip, duration: splitTime - clip.startTime };
    const clip2 = { ...clip, id: crypto.randomUUID(), startTime: splitTime, duration: clip.duration - clip1.duration };
    setTimeline({
      ...timeline,
      clips: [...timeline.clips.filter(c => c.id !== clipId), clip1, clip2]
    });
  }

  // Playback Engine
  useEffect(() => {
    let animationFrameId: number;
    let lastTime = performance.now();

    const playLoop = (time: number) => {
      if (isPlaying) {
        const deltaTime = (time - lastTime) / 1000;
        setCurrentTime((prevTime) => {
          const totalDuration = timeline.clips.reduce(
            (max, clip) => Math.max(max, clip.startTime + clip.duration),
            0,
          );
          const nextTime = prevTime + deltaTime;
          if (nextTime >= totalDuration && totalDuration > 0) {
            setIsPlaying(false);
            return totalDuration;
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

  // Scrubbing Engine
  const handleScrub = (clientX: number) => {
    if (!timelineRef.current) return;
    const rect = timelineRef.current.getBoundingClientRect();
    const scrollLeft = timelineRef.current.scrollLeft;
    const zeroPoint = rect.left - scrollLeft + 128; // 132px header offset
    const pixelsFromZero = clientX - zeroPoint;
    const pixelsPerSecond = 20 * timeline.zoomMultiplier;
    setCurrentTime(Math.max(0, pixelsFromZero / pixelsPerSecond));
  };

  // Zoom Check for Scrub
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

  // Track Renaming Handler
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

  const handleUpdateClip = (id: string, updates: any) => {
    setTimeline({
      ...timeline,
      clips: timeline.clips.map((c) =>
        c.id === id ? { ...c, ...updates } : c,
      ),
    });
  };

  // Find Active Visual Clip
  const activeVisualClip = timeline.clips.find((clip) => {
    const track = timeline.tracks.find((t) => t.id === clip.trackId);
    if (!track) return false;
    const isVisual =
      track.name.toLowerCase().includes("video") ||
      track.name.toLowerCase().includes("popup");
    return (
      isVisual &&
      currentTime >= clip.startTime &&
      currentTime < clip.startTime + clip.duration
    );
  });
  const activeVisualClips = activeVisualClip ? [activeVisualClip] : [];

  // Automatic Manifest Loader
  useEffect(() => {
    const unlisten = listen("render-complete", async (_event) => {
      console.log("Python render complete! Loading timeline...");
      if (metadata?.directory_path) {
        await autoLoadTimeline(metadata.directory_path);
      }
    });
    return () => {
      unlisten.then((f) => f());
    };
  }, [metadata]);

  const videoRef = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    if (!videoRef.current || !activeVisualClip) return;
    const video = videoRef.current;
    const expectedTime = currentTime - activeVisualClip.startTime;
    if (Math.abs(video.currentTime - expectedTime) > 0.1) {
      video.currentTime = expectedTime;
    }
    if (isPlaying && video.paused) {
      video.play().catch((e) => console.warn("Browser prevented playback:", e));
    } else if (!isPlaying && !video.paused) {
      video.pause();
    }
  }, [currentTime, isPlaying, activeVisualClip]);

  const handleExportVideo = async () => {
    if (!metadata?.directory_path) return;
    const success = await saveTimelineManifest(
      metadata.directory_path,
      metadata.project_name || "Project",
      timeline,
    );
    if (success) {
      console.log("Triggering Render engine...");
      try {
        await invoke("export_video", { projectDir: metadata.directory_path });
      } catch (error) {
        console.error("Render failed:", error);
      }
    }
  };

  // 🛠️ UPGRADED RULER MATH: Calculate the exact timeline pixel width
  const pixelsPerSecond = 20 * timeline.zoomMultiplier;
  const maxClipEnd = timeline.clips.reduce(
    (max, clip) => Math.max(max, clip.startTime + clip.duration),
    0,
  );
  const rulerDuration = Math.max(600, maxClipEnd + 120);
  const timelinePixelWidth = rulerDuration * pixelsPerSecond;

  let majorStep = 10;
  let minorStep = 2;
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
      {/* TOP HALF: Panels & Preview */}
      <div className="flex-1 flex min-h-0 border-b border-zinc-200 dark:border-white/5">
        <MediaPool />

        {/* 🛠️ UI FIX: Added min-w-0 to constrain the preview container */}
        <div className="flex-1 p-4 md:p-6 flex flex-col items-center justify-center bg-zinc-50/50 dark:bg-navidark-800 min-w-0 min-h-0 relative overflow-hidden">
          {/* 🛠️ Constrain the monitor so it never pushes the inspector */}
          <div className="w-full h-full max-w-4xl max-h-full flex items-center justify-center">
            <div className="w-full aspect-video bg-black rounded-lg shadow-xl border border-zinc-800 relative overflow-hidden group">
              {activeVisualClip ? (
                <div className="absolute inset-0">
                  <PreviewMonitor
                    activeClips={activeVisualClips}
                    currentTime={currentTime}
                    isPlaying={isPlaying}
                    selectedClipId={selectedClipId}
                    onSelectClip={setSelectedClipId}
                    onUpdateClip={handleUpdateClip}
                  />
                  <div className="absolute bottom-8 left-1/2 -translate-x-1/2 flex items-center gap-4 bg-zinc-900/80 backdrop-blur px-6 py-2 rounded-full border border-white/10 text-white z-10">
                    <button onClick={() => setCurrentTime(0)} className="hover:text-navi transition-colors">
                      <SkipBack className="w-4 h-4" />
                    </button>
                    <button onClick={() => setIsPlaying(!isPlaying)} className="w-8 h-8 flex items-center justify-center bg-white text-black rounded-full hover:bg-navi hover:text-white transition-colors">
                      {isPlaying ? <Pause className="w-4 h-4" fill="currentColor" /> : <Play className="w-4 h-4 ml-0.5" fill="currentColor" />}
                    </button>
                    <button className="hover:text-navi transition-colors">
                      <SkipForward className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex items-center justify-center h-full">
                  <span className="text-zinc-600 font-mono text-sm">No visual</span>
                </div>
              )}

              {/* Hover state controls when there is NO visual clip active */}
              {!activeVisualClip && (
                <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-4 bg-zinc-900/80 backdrop-blur px-6 py-2 rounded-full border border-white/10 text-white z-10 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button onClick={() => setCurrentTime(0)} className="hover:text-navi transition-colors"><SkipBack className="w-4 h-4" /></button>
                  <button onClick={() => setIsPlaying(!isPlaying)} className="w-8 h-8 flex items-center justify-center bg-white text-black rounded-full hover:bg-navi hover:text-white transition-colors">
                    {isPlaying ? <Pause className="w-4 h-4" fill="currentColor" /> : <Play className="w-4 h-4 ml-0.5" fill="currentColor" />}
                  </button>
                  <button className="hover:text-navi transition-colors"><SkipForward className="w-4 h-4" /></button>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* 🛠️ THE NEW RIGHT PANEL (Tabs) */}
        <div className="w-80 bg-white dark:bg-navidark-800 border-l border-zinc-200 dark:border-navidark-400 flex flex-col shrink-0">
          {/* Tab Header */}
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

          {/* Tab Content */}
          <div className="flex-1 overflow-y-auto custom-scrollbar p-4">
            {rightPanelTab === "inspector" ? (
              <Inspector selectedClipId={selectedClipId} onClearSelection={() => setSelectedClipId(null)} />
            ) : (
              <ExportPanel onExport={handleExportVideo} />
            )}
          </div>
        </div>
      </div>

      {/* BOTTOM HALF: Timeline */}
      <div className="h-80 shrink-0 flex flex-col bg-zinc-100 dark:bg-navidark-900 relative border-t border-zinc-300 dark:border-black shadow-[0_-4px_20px_rgba(0,0,0,0.1)] min-h-0">
        
        {/* 🛠️ UPGRADED TOOLBAR */}
        <div className="h-11 bg-white dark:bg-navidark-800 border-b border-zinc-200 dark:border-navidark-400 flex items-center justify-between px-4 shrink-0 z-30">
          <div className="flex items-center gap-1 bg-zinc-100 dark:bg-navidark-900 p-1 rounded-md border border-zinc-200 dark:border-navidark-700">
            <button onClick={() => setActiveTool("pointer")} className={`p-1.5 rounded transition-colors ${activeTool === "pointer" ? "bg-white dark:bg-navidark-700 text-navi shadow-sm" : "text-zinc-500 hover:text-zinc-900"}`} title="Selection Tool">
              <MousePointer2 className="w-4 h-4" />
            </button>
            <button onClick={() => setActiveTool("razor")} className={`p-1.5 rounded transition-colors ${activeTool === "razor" ? "bg-white dark:bg-navidark-700 text-navi shadow-sm" : "text-zinc-500 hover:text-zinc-900"}`} title="Razor Tool">
              <Scissors className="w-4 h-4" />
            </button>
            
            {/* The Magnet / Ripple Toggle */}
            <div className="w-px h-4 bg-zinc-300 dark:bg-navidark-400 mx-1" />
            <button onClick={() => setIsRippleMode(!isRippleMode)} className={`p-1.5 rounded transition-colors ${isRippleMode ? "bg-navi text-white shadow-sm" : "text-zinc-500 hover:text-zinc-900"}`} title="Ripple Insert Mode">
              <Magnet className="w-4 h-4" />
            </button>
            <button onClick={() => setActiveTool("magic")} className={`p-1.5 rounded transition-colors ${activeTool === "magic" ? "bg-white dark:bg-navidark-700 text-navi shadow-sm" : "text-zinc-500 hover:text-zinc-900"}`} title="Auto-Transitions">
              <Sparkles className="w-4 h-4" />
            </button>
          </div>
          
          <div className="text-xs font-mono font-medium text-zinc-600 dark:text-zinc-300 bg-zinc-100 dark:bg-navidark-900 px-3 py-1 rounded-md border border-zinc-200 dark:border-navidark-700">
            {new Date(currentTime * 1000).toISOString().substring(11, 23).replace(".", ":")}
          </div>
          <div className="flex items-center gap-2">
            <ZoomOut className="w-3.5 h-3.5 text-zinc-400" />
            <input type="range" min="0.2" max="5" step="0.1" value={timeline.zoomMultiplier} onChange={(e) => handleZoom(parseFloat(e.target.value))} className="w-24 accent-navi cursor-ew-resize" />
            <ZoomIn className="w-3.5 h-3.5 text-zinc-400" />
          </div>
        </div>

        {/* Scrollable Tracks Area */}
        <div ref={timelineRef} className="flex-1 overflow-auto custom-scrollbar relative min-h-0">
          <div className="flex flex-col min-w-max pb-12 relative">
            {/* THE TIME RULER (Sticky Vertical) */}
            <div className="sticky top-0 w-full h-8 bg-zinc-200/90 dark:bg-navidark-800/90 backdrop-blur-md border-b border-zinc-300 dark:border-navidark-400 z-45 flex items-center">
              <div className="sticky left-0 w-32 h-full bg-zinc-100 dark:bg-navidark-800 border-r border-zinc-300 dark:border-navidark-400 shrink-0 z-60 flex items-center px-3 shadow-[2px_0_5px_rgba(0,0,0,0.02)]">
                <span className="text-[9px] font-bold text-zinc-400 dark:text-zinc-500 tracking-widest">TIMELINE</span>
              </div>

              <div
                className="h-full cursor-ew-resize relative overflow-hidden shrink-0"
                style={{ width: `${timelinePixelWidth}px` }}
                onMouseDown={(e) => {
                  if (isPlaying) setIsPlaying(false);
                  setIsScrubbing(true);
                  handleScrub(e.clientX);
                }}
              >
                {Array.from({ length: Math.ceil(rulerDuration / minorStep) }).map((_, i) => {
                  const time = i * minorStep;
                  const isMajor = time % majorStep === 0;
                  return (
                    <div key={time} className="absolute bottom-0" style={{ left: `${time * pixelsPerSecond}px` }}>
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
              className="absolute top-0 bottom-0 w-[1.5px] bg-red-500 z-35 pointer-events-none shadow-[0_0_10px_rgba(239,68,68,0.5)]"
              style={{ left: `${127 + currentTime * pixelsPerSecond}px` }}
            />

            {/* Tracks List */}
            {timeline.tracks.map((track: TrackType) => {
              const isMainTrack = track.name.toLowerCase().includes("video");
              const trackHeight = isMainTrack ? "h-20" : "h-14";

              return (
                <div key={track.id} className="flex w-max group">
                  <div
                    onContextMenu={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      window.dispatchEvent(new CustomEvent("open-context-menu", { detail: { x: e.clientX, y: e.clientY, type: "track-header", targetId: track.id } }));
                    }}
                    onDoubleClick={() => setEditingTrackId(track.id)}
                    className={`sticky left-0 shrink-0 w-32 bg-zinc-50 dark:bg-navidark-700 border-r border-b border-zinc-200 dark:border-navidark-400 flex items-center justify-between px-3 z-40 ${editingTrackId === track.id ? "" : "cursor-context-menu"} ${trackHeight}`}
                  >
                    {editingTrackId === track.id ? (
                      <input
                        type="text"
                        autoFocus
                        defaultValue={track.name}
                        onBlur={(e) => handleUpdateTrackName(track.id, e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") handleUpdateTrackName(track.id, e.currentTarget.value);
                          if (e.key === "Escape") setEditingTrackId(null);
                        }}
                        className="w-full bg-white dark:bg-navidark-900 text-[10px] font-bold text-zinc-900 dark:text-zinc-100 px-1.5 py-1 rounded outline-none border-2 border-navi"
                      />
                    ) : (
                      <span className="text-[10px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-wider truncate">
                        {track.name}
                      </span>
                    )}
                  </div>

                  <TimelineTrack
                    track={track}
                    selectedClipId={selectedClipId}
                    onSelectClip={setSelectedClipId}
                    activeTool={activeTool}
                    onSplit={handleSplitClip}
                    isRippleMode={isRippleMode} // 🛠️ Passed the ripple mode state!
                    trackWidth={timelinePixelWidth}
                  />
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}