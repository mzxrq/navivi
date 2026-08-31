import { useRef, useEffect, useMemo } from 'react';
import { Image as KonvaImage, Transformer } from 'react-konva';
import { convertFileSrc } from '@tauri-apps/api/core';
import useImage from 'use-image';

interface ClipProps {
  clip: any;
  isSelected: boolean;
  isPlaying: boolean;
  currentTime: number;
  onSelect: () => void;
  onChange: (newAttrs: any) => void;
}

export function TransformableClip({ clip, isSelected, isPlaying, currentTime, onSelect, onChange }: ClipProps) {
  const shapeRef = useRef<any>(null);
  const trRef = useRef<any>(null);
  const animRef = useRef<number>(0);

  const safeUrl = convertFileSrc(clip.source);
  
  // Handle Static Images
  const [image] = useImage(clip.type === 'image' ? safeUrl : '');

  // Handle Video Frames
  const videoElement = useMemo(() => {
    if (clip.type !== 'video') return null;
    const vid = document.createElement('video');
    vid.src = safeUrl;
    vid.muted = true;
    return vid;
  }, [safeUrl, clip.type]);

  // Sync Video Playback
  useEffect(() => {
    if (!videoElement) return;
    const expectedTime = currentTime - clip.startTime;
    if (Math.abs(videoElement.currentTime - expectedTime) > 0.1) {
      videoElement.currentTime = expectedTime;
    }
    if (isPlaying) {
      videoElement.play().catch(() => {});
      // Force Konva to redraw the video frame continuously
      const anim = () => {
        shapeRef.current?.getLayer()?.batchDraw();
        animRef.current = requestAnimationFrame(anim);
      };
      animRef.current = requestAnimationFrame(anim);
    } else {
      videoElement.pause();
      if (animRef.current) cancelAnimationFrame(animRef.current);
    }
    return () => { if (animRef.current) cancelAnimationFrame(animRef.current); };
  }, [isPlaying, currentTime, videoElement, clip.startTime]);

  useEffect(() => {
    if (isSelected && trRef.current && shapeRef.current) {
      trRef.current.nodes([shapeRef.current]);
      trRef.current.getLayer().batchDraw();
    }
  }, [isSelected]);

  const mediaSource = clip.type === 'video' ? videoElement : image;
  if (!mediaSource) return null;

  return (
    <>
      <KonvaImage
        image={mediaSource}
        x={clip.x || 0}
        y={clip.y || 0}
        scaleX={clip.scaleX || 1}
        scaleY={clip.scaleY || 1}
        rotation={clip.rotation || 0}
        draggable={isSelected}
        onClick={onSelect}
        onTap={onSelect}
        ref={shapeRef}
        onDragEnd={(e) => {
          onChange({ ...clip, x: e.target.x(), y: e.target.y() });
        }}
        onTransformEnd={(_e) => {
          const node = shapeRef.current;
          onChange({
            ...clip,
            x: node.x(),
            y: node.y(),
            scaleX: node.scaleX(),
            scaleY: node.scaleY(),
            rotation: node.rotation(),
          });
        }}
      />
      {isSelected && (
        <Transformer ref={trRef} boundBoxFunc={(oldBox, newBox) => (newBox.width < 10 || newBox.height < 10 ? oldBox : newBox)} />
      )}
    </>
  );
}