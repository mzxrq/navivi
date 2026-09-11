import { useState, useEffect, useRef } from "react";
import { Stage, Layer, Rect, Text, Group } from "react-konva";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useTheme } from "../../../hooks/useTheme";
import { Film } from "../../ui/icons";
import { exportVideo } from "../../../services/exportApi";

export function TimelineEditor() {
  const { waypoints, setWaypoints, settings } = useWorkspace();
  const { theme } = useTheme();
  
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 250 });
  const [isExporting, setIsExporting] = useState(false);
  
  // Base constants
  const PX_PER_SEC = 20;
  const TRACK_HEIGHT = 40;
  const HEADER_HEIGHT = 30;

  useEffect(() => {
    const updateSize = () => {
      if (containerRef.current) {
        setDimensions({
          width: containerRef.current.offsetWidth,
          height: containerRef.current.offsetHeight
        });
      }
    };
    // initial delay for layout
    setTimeout(updateSize, 50);
    window.addEventListener("resize", updateSize);
    return () => window.removeEventListener("resize", updateSize);
  }, []);

  const handleExport = async () => {
    setIsExporting(true);
    try {
      await exportVideo(waypoints, settings);
      alert("Export triggered successfully!");
    } catch (error) {
      console.error(error);
      alert("Failed to export video");
    } finally {
      setIsExporting(false);
    }
  };

  const isDark = theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  const textColor = isDark ? "#a1a1aa" : "#52525b";
  const gridColor = isDark ? "#27272a" : "#e4e4e7";

  let runningTime = 0;
  
  const blocks = waypoints.map((wp) => {
    const duration = 5; // Default 5s
    const startTime = wp.timelineOffset !== undefined ? wp.timelineOffset : runningTime;
    
    // Auto-advance for the next sequence if it hasn't been manually moved too far
    runningTime = Math.max(runningTime, startTime + duration);
    
    return {
      id: wp.id,
      name: wp.name || "Waypoint",
      startTime,
      duration,
      trackIndex: 0,
      wp
    };
  });

  const allClips: any[] = [];
  
  blocks.forEach(b => {
    // Flight block
    allClips.push({
      ...b,
      label: `Route to ${b.name}`,
      color: "#0284c7",
      type: "flight"
    });
    
    // Video block
    if (b.wp.videoUrl || b.wp.isGeneratingVideo || b.wp.videoPrompt) {
      allClips.push({
        id: b.id + "-video",
        name: "Wan 2.2 Video",
        label: "Video",
        startTime: b.wp.videoOffset !== undefined ? b.wp.videoOffset : b.startTime,
        duration: b.duration,
        trackIndex: 1,
        color: "#16a34a",
        wp: b.wp,
        type: "video"
      });
    }

    // Audio block
    if (b.wp.audioUrl || b.wp.isGeneratingAudio || b.wp.narration || b.wp.arrivingNarration || b.wp.attractionNarration) {
      allClips.push({
        id: b.id + "-audio",
        name: "Irodori Audio",
        label: "Audio",
        startTime: b.wp.audioOffset !== undefined ? b.wp.audioOffset : b.startTime,
        duration: b.duration,
        trackIndex: 2,
        color: "#ea580c",
        wp: b.wp,
        type: "audio"
      });
    }
  });

  const handleDragEnd = (e: any, id: string, type: string) => {
    const x = e.target.x();
    const newStartTime = Math.max(0, x / PX_PER_SEC);
    
    setWaypoints((prev) =>
      prev.map((wp) => {
        if (wp.id === id) {
          if (type === "flight") return { ...wp, timelineOffset: newStartTime };
          if (type === "video") return { ...wp, videoOffset: newStartTime };
          if (type === "audio") return { ...wp, audioOffset: newStartTime };
        }
        return wp;
      })
    );
  };

  const handleDoubleClick = (id: string, type: string) => {
    setWaypoints((prev) =>
      prev.map((wp) => {
        if (wp.id === id) {
          if (type === "flight") return { ...wp, timelineOffset: undefined };
          if (type === "video") return { ...wp, videoOffset: undefined };
          if (type === "audio") return { ...wp, audioOffset: undefined };
        }
        return wp;
      })
    );
  };

  const tracks = ["Map Flight", "Wan 2.2 Video", "Irodori Audio"];
  
  const maxEndTime = allClips.reduce((max, clip) => Math.max(max, clip.startTime + clip.duration), 0);
  const stageWidth = Math.max(dimensions.width - 128, (maxEndTime * PX_PER_SEC) + 1000);

  return (
    <div ref={containerRef} className="w-full h-full bg-zinc-50 dark:bg-navidark-900 overflow-hidden relative border-t border-zinc-200 dark:border-navidark-400 select-none">
      <div className="absolute top-0 left-0 w-32 h-full bg-zinc-100 dark:bg-navidark-800 z-10 border-r border-zinc-200 dark:border-navidark-400 flex flex-col">
        <div className="h-[30px] border-b border-zinc-200 dark:border-navidark-400 flex items-center px-2 shrink-0 bg-white dark:bg-navidark-900">
          <span className="text-[10px] font-bold text-zinc-500 uppercase">Tracks</span>
        </div>
        {tracks.map((t) => (
          <div key={t} className="flex flex-col justify-center px-2 border-b border-zinc-200 dark:border-navidark-400 bg-zinc-50 dark:bg-navidark-800" style={{ height: TRACK_HEIGHT }}>
            <span className="text-[10px] font-bold text-zinc-600 dark:text-zinc-300 uppercase tracking-wider truncate">{t}</span>
          </div>
        ))}
      </div>
      
      <div className="ml-32 h-full overflow-x-auto overflow-y-hidden relative custom-scrollbar bg-white dark:bg-navidark-950">
        <div className="absolute top-0 right-0 h-[30px] z-20 flex items-center px-4 bg-white/80 dark:bg-navidark-900/80 backdrop-blur-sm border-b border-l border-zinc-200 dark:border-navidark-400 rounded-bl-lg">
          <button
            onClick={handleExport}
            disabled={isExporting}
            className="flex items-center gap-1.5 px-3 py-1 rounded-md text-[10px] font-bold transition-all disabled:opacity-50 disabled:cursor-not-allowed bg-blue-50 dark:bg-blue-500/10 text-blue-700 dark:text-blue-300 hover:bg-blue-100 border border-blue-200 shadow-sm"
          >
            <Film className="w-3 h-3" />
            {isExporting ? "Rendering..." : "Render Final Video"}
          </button>
        </div>
        <Stage width={stageWidth} height={Math.max(dimensions.height, 200)}>
          <Layer>
            {/* Grid/Ruler Background */}
            <Rect x={0} y={0} width={stageWidth} height={HEADER_HEIGHT} fill={isDark ? "#18181b" : "#f4f4f5"} />
            
            {/* Ticks and labels */}
            {Array.from({ length: Math.ceil(stageWidth / (PX_PER_SEC * 5)) }).map((_, i) => (
              <Group key={i} x={i * PX_PER_SEC * 5}>
                <Rect x={0} y={0} width={1} height={Math.max(dimensions.height, 200)} fill={gridColor} />
                <Text
                  x={2}
                  y={8}
                  text={`${i * 5}s`}
                  fontSize={10}
                  fill={textColor}
                  fontFamily="monospace"
                />
              </Group>
            ))}
            
            {/* Minor Ticks */}
            {Array.from({ length: Math.ceil(stageWidth / PX_PER_SEC) }).map((_, i) => (
              i % 5 !== 0 && (
                <Rect key={`minor-${i}`} x={i * PX_PER_SEC} y={HEADER_HEIGHT - 6} width={1} height={6} fill={gridColor} />
              )
            ))}

            {/* Clips */}
            {allClips.map((clip) => (
              <Group
                key={clip.id}
                x={clip.startTime * PX_PER_SEC}
                y={HEADER_HEIGHT + clip.trackIndex * TRACK_HEIGHT + 4}
                draggable
                onDragEnd={(e) => handleDragEnd(e, clip.wp.id, clip.type)}
                onDblClick={() => handleDoubleClick(clip.wp.id, clip.type)}
                dragBoundFunc={(pos) => {
                  return {
                    x: Math.max(0, pos.x),
                    y: HEADER_HEIGHT + clip.trackIndex * TRACK_HEIGHT + 4 // lock vertical movement
                  };
                }}
              >
                <Rect
                  width={clip.duration * PX_PER_SEC}
                  height={TRACK_HEIGHT - 8}
                  fill={clip.color}
                  cornerRadius={4}
                  shadowColor="black"
                  shadowBlur={2}
                  shadowOpacity={0.2}
                />
                <Text
                  x={6}
                  y={6}
                  text={clip.label}
                  fontSize={11}
                  fontStyle="bold"
                  fill="#ffffff"
                  width={clip.duration * PX_PER_SEC - 12}
                  wrap="none"
                  ellipsis={true}
                />
              </Group>
            ))}
          </Layer>
        </Stage>
      </div>
    </div>
  );
}
