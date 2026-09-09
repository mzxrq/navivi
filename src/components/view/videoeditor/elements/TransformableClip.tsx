import { useEffect, useRef, useState } from "react";
import Konva from "konva";
import {
  Image as KonvaImage,
  Text as KonvaText,
  Transformer,
} from "react-konva";
import { convertFileSrc } from "@tauri-apps/api/core";
import { useGLTransition } from "../../../../hooks/useTransition";

interface TransformableClipProps {
  clip: any;
  isSelected: boolean;
  isPlaying: boolean;
  currentTime: number;
  onSelect: () => void;
  onChange: (newAttrs: any) => void;
}

export function TransformableClip({
  clip,
  isSelected,
  isPlaying,
  currentTime,
  onSelect,
  onChange,
}: TransformableClipProps) {
  const shapeRef = useRef<any>(null);
  const trRef = useRef<any>(null);

  const [videoSize, setVideoSize] = useState({ width: 1920, height: 1080 });

  // <Main> Media Elements
  const [videoElement] = useState(() => {
    if (clip.type === "video") {
      const vid = document.createElement("video");
      vid.playsInline = true;
      vid.crossOrigin = "anonymous";
      return vid;
    }
    if (clip.type === "audio") {
      return new window.Audio();
    }
    return null;
  });

  // previous media for transitions
  const [prevVideoElement] = useState(() => {
    if (clip.prevClip?.source && clip.prevClip?.type === "video") {
      const vid = document.createElement("video");
      vid.playsInline = true;
      vid.crossOrigin = "anonymous";
      vid.src = convertFileSrc(clip.prevClip.source);
      vid.load();
      return vid;
    }
    return null;
  });

  const [imageElement] = useState(() => {
    if (clip.type === "image") return new window.Image();
    return null;
  });

  // ミュートstate
  useEffect(() => {
    if (videoElement) videoElement.muted = clip.isMuted || false;
    if (prevVideoElement) prevVideoElement.muted = true;
  }, [clip.isMuted, videoElement, prevVideoElement]);

  useEffect(() => {
    return () => {
      if (videoElement) {
        videoElement.pause();
        videoElement.removeAttribute("src");
        videoElement.load();
      }
      if (prevVideoElement) {
        prevVideoElement.pause();
        prevVideoElement.removeAttribute("src");
        prevVideoElement.load();
      }
    };
  }, [videoElement, prevVideoElement]);

  // Load sources
  useEffect(() => {
    if (!clip.source) return;
    const safeUrl = convertFileSrc(clip.source);

    if (clip.type === "image" && imageElement) {
      imageElement.onload = () => shapeRef.current?.getLayer()?.batchDraw();
      imageElement.src = safeUrl;
    } else if (
      clip.type === "video" &&
      videoElement instanceof HTMLVideoElement
    ) {
      const handleMetadata = () => {
        setVideoSize({
          width: videoElement.videoWidth,
          height: videoElement.videoHeight,
        });
        shapeRef.current?.getLayer()?.batchDraw();
      };
      videoElement.addEventListener("loadedmetadata", handleMetadata);
      videoElement.src = safeUrl;
      videoElement.load();
      return () =>
        videoElement.removeEventListener("loadedmetadata", handleMetadata);
    }
  }, [clip.source, clip.type, videoElement, imageElement]);

  // Animation Loop
  useEffect(() => {
    if (clip.type !== "video" || !shapeRef.current) return;
    const layer = shapeRef.current.getLayer();
    if (!layer) return;

    const anim = new Konva.Animation(() => {}, layer);
    anim.start();

    return () => {
      anim.stop();
    };
  }, [clip.type]);

  const { glCanvas, drawGL } = useGLTransition(
    videoSize.width,
    videoSize.height,
    clip.trasitionIn,
  );

  // Playhead
  useEffect(() => {
    if (clip.type !== "video" || !videoElement) return;

    const localTime = currentTime - clip.startTime + (clip.sourceOffset || 0);

    if (isPlaying) {
      if (videoElement.paused) videoElement.play().catch(() => {});
      if (Math.abs(videoElement.currentTime - localTime) > 0.25) {
        videoElement.currentTime = Math.max(0, localTime);
      }
    } else {
      if (!videoElement.paused) videoElement.pause();
      if (Math.abs(videoElement.currentTime - localTime) > 0.05) {
        videoElement.currentTime = Math.max(0, localTime);
        shapeRef.current?.getLayer()?.batchDraw();
      }
    }

    if (clip.prevClip && prevVideoElement) {
      const prevLocalTime =
        currentTime -
        clip.prevClip.startTime +
        (clip.prevClip.sourceOffset || 0);
      if (isPlaying) {
        if (prevVideoElement.paused) prevVideoElement.play().catch(() => {});
        if (Math.abs(prevVideoElement.currentTime - prevLocalTime) > 0.25)
          prevVideoElement.currentTime = Math.max(0, prevLocalTime);
      } else {
        if (!prevVideoElement.paused) prevVideoElement.pause();
        if (Math.abs(prevVideoElement.currentTime - prevLocalTime) > 0.05)
          prevVideoElement.currentTime = Math.max(0, prevLocalTime);
      }
    }
  }, [
    currentTime,
    isPlaying,
    clip.startTime,
    clip.sourceOffset,
    clip.type,
    videoElement,
  ]);

  // ✨ RENDER LOOP: Calculate Progress & Draw WebGL
  let transitionProgress = 0;
  const clipTime = currentTime - clip.startTime;
  if (
    clip.transitionIn?.startsWith("glsl-") &&
    clip.fadeIn &&
    clipTime >= 0 &&
    clipTime <= clip.fadeIn
  ) {
    transitionProgress = clipTime / clip.fadeIn;
  }
  transitionProgress = Math.max(0, Math.min(1, transitionProgress));
  const isTransitioning = transitionProgress > 0 && transitionProgress < 1;

  useEffect(() => {
    if (isTransitioning && prevVideoElement && videoElement && glCanvas) {
      drawGL(prevVideoElement, videoElement, transitionProgress);
      shapeRef.current?.getLayer()?.batchDraw(); // Force Konva to update its image node
    }
  }, [
    currentTime,
    isTransitioning,
    transitionProgress,
    prevVideoElement,
    videoElement,
    glCanvas,
    drawGL,
  ]);

  useEffect(() => {
    if (isSelected && trRef.current && shapeRef.current) {
      trRef.current.nodes([shapeRef.current]);
      trRef.current.getLayer()?.batchDraw();
    }
  }, [isSelected]);

  const x = clip.x || 0;
  const y = clip.y || 0;
  const scaleX = clip.scaleX || 1;
  const scaleY = clip.scaleY || 1;
  const rotation = clip.rotation || 0;

  let currentOpacity = 1;
  if (
    !clip.transitionIn?.startsWith("glsl-") &&
    clip.fadeIn &&
    clipTime < clip.fadeIn
  ) {
    currentOpacity = clipTime / clip.fadeIn;
  } else if (clip.fadeOut && clipTime > clip.duration - clip.fadeOut) {
    currentOpacity = (clip.duration - clipTime) / clip.fadeOut;
  }
  currentOpacity = Math.max(0, Math.min(1, currentOpacity));

  if (clip.type === "audio") {
    return null;
  }
  const activeMedia =
    isTransitioning && glCanvas
      ? glCanvas
      : clip.type === "video" && videoElement instanceof HTMLVideoElement
        ? videoElement
        : imageElement || undefined;

  return (
    <>
      {clip.type === "text" || clip.type === "subtitle" ? (
        <KonvaText
          ref={shapeRef}
          text={clip.text || "New Text"}
          x={x}
          y={y}
          opacity={currentOpacity}
          fontSize={clip.fontSize || 48}
          fill={clip.color || "#ffffff"}
          scaleX={scaleX}
          scaleY={scaleY}
          rotation={rotation}
          draggable={isSelected}
          onClick={onSelect}
          onTap={onSelect}
          onDragEnd={(e) => onChange({ x: e.target.x(), y: e.target.y() })}
          onTransformEnd={() => {
            const node = shapeRef.current;
            onChange({
              x: node.x(),
              y: node.y(),
              scaleX: node.scaleX(),
              scaleY: node.scaleY(),
              rotation: node.rotation(),
            });
          }}
        />
      ) : (
        <KonvaImage
          ref={shapeRef}
          image={activeMedia}
          x={x}
          y={y}
          opacity={currentOpacity}
          width={clip.type === "video" ? videoSize.width : undefined}
          height={clip.type === "video" ? videoSize.height : undefined}
          scaleX={scaleX}
          scaleY={scaleY}
          rotation={rotation}
          draggable={isSelected}
          onClick={onSelect}
          onTap={onSelect}
          onDragEnd={(e) => onChange({ x: e.target.x(), y: e.target.y() })}
          onTransformEnd={() => {
            const node = shapeRef.current;
            onChange({
              x: node.x(),
              y: node.y(),
              scaleX: node.scaleX(),
              scaleY: node.scaleY(),
              rotation: node.rotation(),
            });
          }}
        />
      )}

      {isSelected && (
        <Transformer
          ref={trRef}
          boundBoxFunc={(oldBox, newBox) =>
            newBox.width < 5 || newBox.height < 5 ? oldBox : newBox
          }
        />
      )}
    </>
  );
}
