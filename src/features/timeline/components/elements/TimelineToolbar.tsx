import React from "react";
import {
  MousePointer2,
  Scissors,
  Type,
  Magnet,
  MapPinPlus,
  MapPin,
  Check,
  Unlink as UnlinkIcon,
  SkipBack,
  Play,
  Pause,
  SkipForward,
  ZoomOut,
  ZoomIn,
  Maximize,
  RefreshCw,
  Download,
} from "lucide-react";
import { ClipData, TimelineData } from "../../../../types/index";
import { useWorkspace } from "../../../../hooks/useWorkspace";
import { useUI } from "../../../../hooks/useUI";

interface TimelineToolbarProps {
  activeTool: "pointer" | "razor" | "magic";
  setActiveTool: (tool: "pointer" | "razor" | "magic") => void;
  isRippleMode: boolean;
  setIsRippleMode: (ripple: boolean) => void;
  isPlaying: boolean;
  setIsPlaying: (playing: boolean) => void;
  currentTime: number;
  setCurrentTime: (time: number) => void;
  timeline: TimelineData;
  setTimeline: (data: TimelineData) => void;
  handleZoom: (zoom: number) => void;
  fitTimeline: () => void;
  setIsExportModalOpen: (open: boolean) => void;
  selectedClipIds: string[];
  setSelectedClipIds: (ids: string[]) => void;
  handleUnlink: () => void;
  handleAddMarker: () => void;
  setRightPanelTab: (tab: "media" | "objects" | "markers" | null) => void;
  metadata: any;
  sortedTracks: any[];
}

export function TimelineToolbar({
  activeTool,
  setActiveTool,
  isRippleMode,
  setIsRippleMode,
  isPlaying,
  setIsPlaying,
  currentTime,
  setCurrentTime,
  timeline,
  setTimeline,
  handleZoom,
  fitTimeline,
  setIsExportModalOpen,
  selectedClipIds,
  setSelectedClipIds,
  handleUnlink,
  handleAddMarker,
  setRightPanelTab,
  metadata,
  sortedTracks,
}: TimelineToolbarProps) {
  const { autoLoadTimeline } = useWorkspace();
  const { showToast } = useUI();

  return (
    <div className="h-11 bg-white dark:bg-navidark-800 border-b border-zinc-200 dark:border-navidark-400 flex items-center justify-between px-4 shrink-0 z-30">
      {/* LEFT: Tools */}
      <div className="flex items-center gap-1 bg-zinc-100 dark:bg-navidark-900 p-1 rounded-md border border-zinc-200 dark:border-navidark-700">
        <button
          onClick={() => setActiveTool("pointer")}
          className={`p-1.5 rounded transition-colors ${activeTool === "pointer" ? "bg-white dark:bg-navidark-700 text-navi shadow-sm" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200"}`}
          title="Selection Tool (V)"
        >
          <MousePointer2 className="w-4 h-4" />
        </button>
        <button
          onClick={() => setActiveTool("razor")}
          className={`p-1.5 rounded transition-colors ${activeTool === "razor" ? "bg-white dark:bg-navidark-700 text-navi shadow-sm" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200"}`}
          title="Razor Tool (C)"
        >
          <Scissors className="w-4 h-4" />
        </button>

        <button
          onClick={() => {
            const popupTrack = sortedTracks.find(
              (t) => t.type === "video" || t.type === "overlay",
            );
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
              color: "#ffffff",
            };
            setTimeline({
              ...timeline,
              clips: [...timeline.clips, newTextClip],
            });
            showToast("Text added to timeline", "success");
          }}
          className="p-1.5 rounded transition-colors text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200"
          title="Add Custom Text"
        >
          <Type className="w-4 h-4" />
        </button>

        <div className="w-px h-4 bg-zinc-300 dark:bg-navidark-400 mx-1" />
        <button
          onClick={() => setIsRippleMode(!isRippleMode)}
          className={`p-1.5 rounded transition-colors ${isRippleMode ? "bg-navi text-white shadow-sm" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200"}`}
          title="Ripple Insert Mode"
        >
          <Magnet className="w-4 h-4" />
        </button>
        <button
          onClick={handleAddMarker}
          className="p-1.5 rounded text-zinc-500 hover:text-navi"
          title="Add marker at playhead"
        >
          <MapPinPlus className="w-4 h-4" />
        </button>
        <button
          onClick={() => setRightPanelTab("markers")}
          className="p-1.5 rounded text-zinc-500 hover:text-navi"
          title="Manage timeline markers"
        >
          <MapPin className="w-4 h-4" />
        </button>
        <button
          onClick={() =>
            setSelectedClipIds(timeline.clips.map((clip) => clip.id))
          }
          className="p-1.5 rounded text-zinc-500 hover:text-navi"
          title="Select all clips (Ctrl/Cmd+A)"
        >
          <Check className="w-4 h-4" />
        </button>
        <button
          onClick={handleUnlink}
          disabled={selectedClipIds.length === 0}
          className="p-1.5 rounded text-zinc-500 hover:text-navi disabled:opacity-30"
          title="Unlink selected clips"
        >
          <UnlinkIcon className="w-4 h-4" />
        </button>
      </div>

      {/* CENTER: Playback Controls */}
      <div className="flex items-center gap-1 bg-zinc-100 dark:bg-navidark-900 p-1 rounded-md border border-zinc-200 dark:border-navidark-700">
        <button
          onClick={() => setCurrentTime(0)}
          className="p-1.5 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 transition-colors rounded hover:bg-zinc-200 dark:hover:bg-navidark-700"
          title="Home"
        >
          <SkipBack className="w-4 h-4" />
        </button>
        <button
          onClick={() => setIsPlaying(!isPlaying)}
          className="p-1.5 text-zinc-500 hover:text-navi transition-colors rounded hover:bg-zinc-200 dark:hover:bg-navidark-700"
          title="Play/Pause (Space)"
        >
          {isPlaying ? (
            <Pause className="w-4 h-4" fill="currentColor" />
          ) : (
            <Play className="w-4 h-4" fill="currentColor" />
          )}
        </button>
        <button
          onClick={() =>
            setCurrentTime(
              timeline.clips.reduce(
                (max, c) => Math.max(max, c.startTime + c.duration),
                0,
              ),
            )
          }
          className="p-1.5 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 transition-colors rounded hover:bg-zinc-200 dark:hover:bg-navidark-700"
          title="End"
        >
          <SkipForward className="w-4 h-4" />
        </button>
        <div className="w-px h-4 bg-zinc-300 dark:bg-navidark-400 mx-2" />
        <div className="text-xs font-medium tracking-wide text-zinc-600 dark:text-zinc-300 px-2 py-0.5 pointer-events-none">
          {new Date(currentTime * 1000)
            .toISOString()
            .substring(11, 23)
            .replace(".", ":")}
        </div>
      </div>

      {/* RIGHT: Zoom & Export Controls */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <ZoomOut className="w-3.5 h-3.5 text-zinc-400" />
          <input
            type="range"
            min="0.2"
            max="5"
            step="0.1"
            value={timeline.zoomMultiplier}
            onChange={(e) => handleZoom(parseFloat(e.target.value))}
            className="w-24 accent-navi cursor-ew-resize"
          />
          <ZoomIn className="w-3.5 h-3.5 text-zinc-400" />
        </div>

        <div className="w-px h-4 bg-zinc-300 dark:bg-navidark-400" />

        <button
          onClick={fitTimeline}
          className="p-1.5 text-zinc-500 hover:text-navi"
          title="Fit timeline to content"
        >
          <Maximize className="w-4 h-4" />
        </button>
        <button
          onClick={async () => {
            if (!metadata.directory_path) return;
            await autoLoadTimeline(metadata.directory_path);
            showToast("Timeline reloaded", "success");
          }}
          className="p-1.5 text-zinc-500 hover:text-navi"
          title="Reload saved timeline"
        >
          <RefreshCw className="w-4 h-4" />
        </button>

        <button
          onClick={() => setIsExportModalOpen(true)}
          className="flex items-center gap-1.5 px-3 py-1 bg-navi hover:bg-navi-600 text-white rounded-md text-xs font-bold shadow-sm hover:shadow transition-all cursor-pointer"
          title="Export & Render Video"
        >
          <Download className="w-3.5 h-3.5" />
          <span>Export</span>
        </button>
      </div>
    </div>
  );
}
