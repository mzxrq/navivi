import { useEffect } from "react";
import { t } from "@lingui/core/macro"; import { Trans } from "@lingui/react/macro";
import {
  MousePointer2,
  Scissors,
  Type,
  Magnet,
  MapPinPlus,
  MapPin,
  Check,
  UnlinkIcon,
  SkipBack,
  Play,
  Pause,
  SkipForward,
  ZoomOut,
  ZoomIn,
  Maximize,
  RefreshCw,
  Download,
  Music,
} from "../../../../components/ui/icons";
import { open } from "@tauri-apps/plugin-dialog";
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

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't trigger if user is typing in an input or textarea
      const activeEl = document.activeElement;
      if (
        activeEl?.tagName.toLowerCase() === "input" ||
        activeEl?.tagName.toLowerCase() === "textarea"
      ) {
        return;
      }

      // Handle Ctrl/Cmd+A for Select All
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") {
        e.preventDefault();
        setSelectedClipIds(timeline.clips.map((clip) => clip.id));
        return;
      }

      // Ignore other modifier combinations
      if (e.ctrlKey || e.metaKey || e.altKey) {
        return;
      }

      switch (e.key.toLowerCase()) {
        case "v":
          e.preventDefault();
          setActiveTool("pointer");
          break;
        case "c":
          e.preventDefault();
          setActiveTool("razor");
          break;
        case " ": // Space
          e.preventDefault();
          setIsPlaying(!isPlaying);
          break;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isPlaying, setIsPlaying, setActiveTool, setSelectedClipIds, timeline.clips]);

  return (
    <div className="h-11 bg-white dark:bg-navidark-800 border-b border-zinc-200 dark:border-navidark-400 flex items-center justify-between px-4 shrink-0 z-30">
      {/* LEFT: Tools */}
      <div className="flex items-center gap-1 bg-zinc-100 dark:bg-navidark-900 p-1 rounded-md border border-zinc-200 dark:border-navidark-700">
        <button
          onClick={() => setActiveTool("pointer")}
          className={`p-1.5 rounded transition-colors ${activeTool === "pointer" ? "bg-white dark:bg-navidark-700 text-navi shadow-sm" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200"}`}
          title={t`Selection Tool (V)`}
        >
          <MousePointer2 className="w-4 h-4" />
        </button>
        <button
          onClick={() => setActiveTool("razor")}
          className={`p-1.5 rounded transition-colors ${activeTool === "razor" ? "bg-white dark:bg-navidark-700 text-navi shadow-sm" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200"}`}
          title={t`Razor Tool (C)`}
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
              label: t`Custom Text`,
              text: t`Lorem ipsum`,
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
          }}
          className="p-1.5 rounded transition-colors text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200"
          title={t`Add Custom Text`}
        >
          <Type className="w-4 h-4" />
        </button>
        
        <button
          onClick={async () => {
            const selected = await open({
              multiple: false,
              filters: [
                {
                  name: "Audio",
                  extensions: ["mp3", "wav", "ogg"],
                },
              ],
            });
            if (selected && typeof selected === "string") {
              const filename = selected.split(/[/\\]/).pop() || "Audio";
              const audioTrack = sortedTracks.find((t) => t.id === "track-audio-2") || sortedTracks.find((t) => t.type === "audio");
              if (!audioTrack) {
                showToast(t`No audio track found`, "error");
                return;
              }
              const newClip: ClipData = {
                id: crypto.randomUUID(),
                trackId: audioTrack.id,
                type: "audio",
                label: filename,
                source: selected,
                startTime: currentTime,
                duration: 10, // Default duration, will ideally be updated after loading
                volume: 1.0,
                fadeIn: 1.0,
                fadeOut: 1.0,
                ducking: true, // Background music should duck during voiceovers
              };
              setTimeline({
                ...timeline,
                clips: [...timeline.clips, newClip],
              });
              showToast(t`Background music added to A2: Music track`, "success");
            }
          }}
          className="p-1.5 rounded transition-colors text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200"
          title={t`Add Background Music`}
        >
          <Music className="w-4 h-4" />
        </button>

        <div className="w-px h-4 bg-zinc-300 dark:bg-navidark-400 mx-1" />
        <button
          onClick={() => setIsRippleMode(!isRippleMode)}
          className={`p-1.5 rounded transition-colors ${isRippleMode ? "bg-navi text-white shadow-sm" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200"}`}
          title={t`Ripple Insert Mode`}
        >
          <Magnet className="w-4 h-4" />
        </button>
        <button
          onClick={handleAddMarker}
          className="p-1.5 rounded text-zinc-500 hover:text-navi"
          title={t`Add marker at playhead`}
        >
          <MapPinPlus className="w-4 h-4" />
        </button>
        <button
          onClick={() => setRightPanelTab("markers")}
          className="p-1.5 rounded text-zinc-500 hover:text-navi"
          title={t`Manage timeline markers`}
        >
          <MapPin className="w-4 h-4" />
        </button>
        <button
          onClick={() =>
            setSelectedClipIds(timeline.clips.map((clip) => clip.id))
          }
          className="p-1.5 rounded text-zinc-500 hover:text-navi"
          title={t`Select all clips`}
        >
          <Check className="w-4 h-4" />
        </button>
        <button
          onClick={handleUnlink}
          disabled={selectedClipIds.length === 0}
          className="p-1.5 rounded text-zinc-500 hover:text-navi disabled:opacity-30"
          title={t`Unlink selected clips`}
        >
          <UnlinkIcon className="w-4 h-4" />
        </button>
      </div>

      {/* CENTER: Playback Controls */}
      <div className="flex items-center gap-1 bg-zinc-100 dark:bg-navidark-900 p-1 rounded-md border border-zinc-200 dark:border-navidark-700">
        <button
          onClick={() => setCurrentTime(0)}
          className="p-1.5 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 transition-colors rounded hover:bg-zinc-200 dark:hover:bg-navidark-700"
          title={t`Home`}
        >
          <SkipBack className="w-4 h-4" />
        </button>
        <button
          onClick={() => setIsPlaying(!isPlaying)}
          className="p-1.5 text-zinc-500 hover:text-navi transition-colors rounded hover:bg-zinc-200 dark:hover:bg-navidark-700"
          title={t`Play/Pause (Space)`}
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
          title={t`End`}
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
        <button
            onClick={() => handleZoom(Math.max(0.2, timeline.zoomMultiplier - 0.2))}
            className="p-1 rounded hover:bg-zinc-200 dark:hover:bg-navidark-700 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 transition-colors"
            title={t`Zoom Out`}
          >
            <ZoomOut className="w-3.5 h-3.5" />
          </button>
          <input
            type="range"
            min="0.2"
            max="5"
            step="0.1"
            value={timeline.zoomMultiplier}
            onChange={(e) => handleZoom(parseFloat(e.target.value))}
            className="w-24 accent-navi cursor-ew-resize mx-1"
          />
          <button
            onClick={() => handleZoom(Math.min(5, timeline.zoomMultiplier + 0.2))}
            className="p-1 rounded hover:bg-zinc-200 dark:hover:bg-navidark-700 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 transition-colors"
            title={t`Zoom In`}
          >
            <ZoomIn className="w-3.5 h-3.5" />
          </button>
        </div>

        <div className="w-px h-4 bg-zinc-300 dark:bg-navidark-400" />

        <button
          onClick={fitTimeline}
          className="p-1.5 text-zinc-500 hover:text-navi"
          title={t`Fit timeline to content`}
        >
          <Maximize className="w-4 h-4" />
        </button>
        <button
          onClick={async () => {
            if (!metadata.directory_path) return;
            await autoLoadTimeline(metadata.directory_path);
            showToast(t`Timeline reloaded`, "success");
          }}
          className="p-1.5 text-zinc-500 hover:text-navi"
          title={t`Reload saved timeline`}
        >
          <RefreshCw className="w-4 h-4" />
        </button>

        <button
          onClick={() => setIsExportModalOpen(true)}
          className="flex items-center gap-1.5 px-3 py-1 bg-navi hover:bg-navi-600 text-white rounded-md text-xs font-bold shadow-sm hover:shadow transition-all cursor-pointer"
          title={t`Export & Render Video`}
        >
          <Download className="w-3.5 h-3.5" />
          <span><Trans>Export</Trans></span>
        </button>
      </div>
    </div>
  );
}
