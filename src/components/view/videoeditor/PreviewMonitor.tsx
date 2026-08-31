import { useState, useRef, useEffect } from 'react';
import { Stage, Layer, Rect } from 'react-konva';
import { TransformableClip } from './TransformableClip';

interface PreviewMonitorProps {
  activeClips: any[];
  currentTime: number;
  isPlaying: boolean;
  selectedClipId: string | null;
  onSelectClip: (id: string | null) => void;
  onUpdateClip: (id: string, updates: any) => void;
}

export function PreviewMonitor({ activeClips, currentTime, isPlaying, selectedClipId, onSelectClip, onUpdateClip }: PreviewMonitorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [stageScale, setStageScale] = useState(1);
  const LOGICAL_WIDTH = 1920;
  const LOGICAL_HEIGHT = 1080;

  useEffect(() => {
    const handleResize = () => {
      if (containerRef.current) {
        setStageScale(containerRef.current.offsetWidth / LOGICAL_WIDTH);
      }
    };
    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  return (
    <div ref={containerRef} className="w-full aspect-video bg-black rounded-lg overflow-hidden shadow-2xl border border-zinc-800">
      <Stage
        width={LOGICAL_WIDTH * stageScale}
        height={LOGICAL_HEIGHT * stageScale}
        scaleX={stageScale}
        scaleY={stageScale}
        onMouseDown={(e) => {
          if (e.target === e.target.getStage()) onSelectClip(null);
        }}
      >
        <Layer>
          <Rect width={LOGICAL_WIDTH} height={LOGICAL_HEIGHT} fill="#000000" />
          {activeClips.map((clip) => (
            <TransformableClip
              key={clip.id}
              clip={clip}
              isSelected={clip.id === selectedClipId}
              isPlaying={isPlaying}
              currentTime={currentTime}
              onSelect={() => onSelectClip(clip.id)}
              onChange={(newAttrs) => onUpdateClip(clip.id, newAttrs)}
            />
          ))}
        </Layer>
      </Stage>
    </div>
  );
}