import { useState, useRef, useEffect } from "react";
import { Stage, Layer, Rect } from "react-konva";
import { TransformableClip } from "./elements/TransformableClip";

interface PreviewMonitorProps {
  activeClips: any[];
  currentTime: number;
  isPlaying: boolean;
  selectedClipId: string | null;
  onSelectClip: (id: string | null) => void;
  onUpdateClip: (id: string, updates: any) => void;
}

export function PreviewMonitor({
  activeClips,
  currentTime,
  isPlaying,
  selectedClipId,
  onSelectClip,
  onUpdateClip,
}: PreviewMonitorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const LOGICAL_WIDTH = 1920;
  const LOGICAL_HEIGHT = 1080;
  const [dimensions, setDimensions] = useState({
    width: 800,
    height: 450,
    scale: 800 / LOGICAL_WIDTH,
  });

  useEffect(() => {
    const observer = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      if (width === 0 || height === 0) return;

      setDimensions((prev) => {
        const scale = Math.min(width / LOGICAL_WIDTH, height / LOGICAL_HEIGHT);
        const newWidth = LOGICAL_WIDTH * scale;
        const newHeight = LOGICAL_HEIGHT * scale;
        if (Math.abs(prev.width - newWidth) > 1) {
          return { width: newWidth, height: newHeight, scale };
        }
        return prev;
      });
    });

    if (containerRef.current) observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={containerRef}
      className="absolute inset-0 flex items-center justify-center overflow-hidden"
    >
      <Stage
        width={dimensions.width}
        height={dimensions.height}
        scaleX={dimensions.scale}
        scaleY={dimensions.scale}
        onMouseDown={(e) => {
          if (
            e.target === e.target.getStage() ||
            e.target.name() === "background"
          ) {
            onSelectClip(null);
          }
        }}
      >
        <Layer>
          <Rect
            name="background"
            width={LOGICAL_WIDTH}
            height={LOGICAL_HEIGHT}
            fill="#000000"
          />
          {activeClips.map((clip) => {
            const prevClip = activeClips
              .filter(
                (c) =>
                  c.trackId === clip.trackId &&
                  c.id !== clip.id &&
                  c.startTime < clip.startTime,
              )
              .sort(
                (left, right) =>
                  right.startTime +
                  right.duration -
                  (left.startTime + left.duration),
              )[0];

            return (
              <TransformableClip
                key={clip.id}
                clip={{ ...clip, prevClip }}
                isSelected={clip.id === selectedClipId}
                isPlaying={isPlaying}
                currentTime={currentTime}
                onSelect={() => onSelectClip(clip.id)}
                onChange={(newAttrs) => onUpdateClip(clip.id, newAttrs)}
              />
            );
          })}
        </Layer>
      </Stage>
    </div>
  );
}
