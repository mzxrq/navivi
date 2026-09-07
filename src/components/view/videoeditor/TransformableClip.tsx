import { useRef, useEffect, useState } from 'react';
import { Image as KonvaImage, Text as KonvaText, Transformer } from 'react-konva';
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

  const safeUrl = clip.source ? convertFileSrc(clip.source) : '';
  const [image] = useImage((clip.type === 'image' || clip.type === 'static_popup') ? safeUrl : '');
  const [videoElement, setVideoElement] = useState<HTMLVideoElement | null>(null);

  useEffect(() => {
    if (clip.type !== 'video') return;
    const vid = document.createElement('video');
    vid.src = safeUrl;
    vid.crossOrigin = "anonymous";
    vid.muted = true;
    vid.loop = false;
    
    vid.addEventListener('loadeddata', () => {
      setVideoElement(vid);
      shapeRef.current?.getLayer()?.batchDraw();
    });
    vid.load();
    
    return () => { vid.removeAttribute('src'); };
  }, [safeUrl, clip.type]);

  useEffect(() => {
    if (!videoElement) return;
    const isWithinClip = currentTime >= clip.startTime && currentTime <= clip.startTime + clip.duration;
    const expectedTime = Math.max(0, currentTime - clip.startTime);

    if (Math.abs(videoElement.currentTime - expectedTime) > 0.1) {
      videoElement.currentTime = expectedTime;
    }

    if (isPlaying && isWithinClip) {
      videoElement.play().catch(() => {});
      const anim = () => {
        shapeRef.current?.getLayer()?.batchDraw();
        animRef.current = requestAnimationFrame(anim);
      };
      animRef.current = requestAnimationFrame(anim);
    } else {
      videoElement.pause();
      if (animRef.current) cancelAnimationFrame(animRef.current);
      shapeRef.current?.getLayer()?.batchDraw(); 
    }
    return () => { if (animRef.current) cancelAnimationFrame(animRef.current); };
  }, [isPlaying, currentTime, videoElement, clip.startTime, clip.duration]);

  useEffect(() => {
    if (!videoElement) return;
    const handleSeeked = () => shapeRef.current?.getLayer()?.batchDraw();
    videoElement.addEventListener('seeked', handleSeeked);
    return () => videoElement.removeEventListener('seeked', handleSeeked);
  }, [videoElement]);

  const mediaSource = clip.type === 'video' ? videoElement : image;
  const isWithinClip = currentTime >= clip.startTime && currentTime <= clip.startTime + clip.duration; // Add this line!

  useEffect(() => {
    if (isSelected && trRef.current && shapeRef.current) {
      trRef.current.nodes([shapeRef.current]);
      trRef.current.getLayer().batchDraw();
    }
  }, [isSelected, mediaSource, clip.type, clip.text]);

  const handleTransformEnd = () => {
    const node = shapeRef.current;
    onChange({
      ...clip,
      x: node.x(),
      y: node.y(),
      scaleX: node.scaleX(),
      scaleY: node.scaleY(),
      rotation: node.rotation(),
    });
  };

  if (clip.type === 'text' || clip.type === 'subtitle') {
    const isWithinClip = currentTime >= clip.startTime && currentTime <= clip.startTime + clip.duration;
    return (
      <>
        <KonvaText
          visible={isWithinClip}
          text={clip.text || 'Sample Text'}
          x={clip.x || 1920 / 2 - 100}
          y={clip.y || 1080 - 150}
          fontSize={clip.fontSize || 48}
          fill={clip.color || '#ffffff'}
          fontFamily="Arial"
          stroke={clip.stroke || '#000000'}
          strokeWidth={clip.strokeWidth || 2}
          scaleX={clip.scaleX || 1}
          scaleY={clip.scaleY || 1}
          rotation={clip.rotation || 0}
          draggable={isSelected}
          onClick={onSelect}
          onTap={onSelect}
          ref={shapeRef}
          onDragEnd={(e) => onChange({ ...clip, x: e.target.x(), y: e.target.y() })}
          onTransformEnd={handleTransformEnd}
        />
        {isSelected && <Transformer ref={trRef} boundBoxFunc={(oldBox, newBox) => (newBox.width < 10 || newBox.height < 10 ? oldBox : newBox)} />}
      </>
    );
  }

  if (!mediaSource) return null;

  return (
    <>
      <KonvaImage
        visible={isWithinClip}
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
        onDragEnd={(e) => onChange({ ...clip, x: e.target.x(), y: e.target.y() })}
        onTransformEnd={handleTransformEnd}
      />
      {isSelected && <Transformer ref={trRef} boundBoxFunc={(oldBox, newBox) => (newBox.width < 10 || newBox.height < 10 ? oldBox : newBox)} />}
    </>
  );
}