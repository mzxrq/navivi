import { useEffect, useRef, useState } from "react";
import Konva from "konva";
import {
  Image as KonvaImage,
  Text as KonvaText,
  Group as KonvaGroup,
  Transformer,
} from "react-konva";
import { convertFileSrc } from "@tauri-apps/api/core";
import { useGLTransition } from "../../../../hooks/useTransition";

let measureCanvasCtx: CanvasRenderingContext2D | null = null;
function getMeasuredTextDimensions(
  text: string,
  fontSize: number,
  fontFamily: string,
) {
  if (typeof document !== "undefined" && !measureCanvasCtx) {
    const c = document.createElement("canvas");
    measureCanvasCtx = c.getContext("2d");
  }
  const lines = (text || "New Text").split("\n");
  if (measureCanvasCtx) {
    measureCanvasCtx.font = `${fontSize}px ${fontFamily}`;
    let maxW = 0;
    for (const l of lines) {
      const metrics = measureCanvasCtx.measureText(l);
      if (metrics.width > maxW) maxW = metrics.width;
    }
    return {
      width: Math.max(10, maxW),
      height: Math.max(10, lines.length * fontSize * 1.25),
    };
  }
  return {
    width: Math.max(10, (text || "New Text").length * fontSize * 0.6),
    height: Math.max(10, lines.length * fontSize * 1.25),
  };
}

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
  const [hasTransitionFrame, setHasTransitionFrame] = useState(false);

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

  const [imageElement] = useState(() => {
    if (clip.type === "image") return new window.Image();
    return null;
  });

  // Dynamic previous media for transitions (supports both video and image)
  const [prevMediaElement, setPrevMediaElement] = useState<
    HTMLVideoElement | HTMLImageElement | null
  >(null);

  useEffect(() => {
    if (!clip.prevClip?.source) {
      setPrevMediaElement(null);
      return;
    }

    const safeUrl = convertFileSrc(clip.prevClip.source);

    if (clip.prevClip.type === "video") {
      const vid = document.createElement("video");
      vid.playsInline = true;
      vid.crossOrigin = "anonymous";
      vid.muted = true;
      vid.src = safeUrl;
      vid.load();
      setPrevMediaElement(vid);

      return () => {
        vid.pause();
        vid.removeAttribute("src");
        vid.load();
      };
    } else if (clip.prevClip.type === "image") {
      const img = new window.Image();
      img.crossOrigin = "anonymous";
      img.onload = () => {
        shapeRef.current?.getLayer()?.batchDraw();
      };
      img.src = safeUrl;
      setPrevMediaElement(img);

      return () => {
        img.onload = null;
      };
    } else {
      setPrevMediaElement(null);
    }
  }, [clip.prevClip?.id, clip.prevClip?.source, clip.prevClip?.type]);

  // ミュートstate
  useEffect(() => {
    if (videoElement instanceof HTMLVideoElement)
      videoElement.muted = clip.isMuted || false;
    if (prevMediaElement instanceof HTMLVideoElement)
      prevMediaElement.muted = true;
  }, [clip.isMuted, videoElement, prevMediaElement]);

  useEffect(() => {
    return () => {
      if (videoElement instanceof HTMLVideoElement) {
        videoElement.pause();
        videoElement.removeAttribute("src");
        videoElement.load();
      }
    };
  }, [videoElement]);

  // Load sources
  useEffect(() => {
    if (!clip.source) return;
    const safeUrl = convertFileSrc(clip.source);

    if (clip.type === "image" && imageElement) {
      imageElement.onload = () => {
        if (imageElement.naturalWidth && imageElement.naturalHeight) {
          setVideoSize({
            width: imageElement.naturalWidth,
            height: imageElement.naturalHeight,
          });
        }
        shapeRef.current?.getLayer()?.batchDraw();
      };
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

  // Trigger layer redraw when color adjustment effects change
  useEffect(() => {
    shapeRef.current?.getLayer()?.batchDraw();
  }, [
    clip.effects?.brightness,
    clip.effects?.contrast,
    clip.effects?.saturation,
  ]);

  // Animation Loop
  useEffect(() => {
    const isPrevVideo = prevMediaElement instanceof HTMLVideoElement;
    if ((clip.type !== "video" && !isPrevVideo) || !shapeRef.current) return;
    const layer = shapeRef.current.getLayer();
    if (!layer) return;

    const anim = new Konva.Animation(() => {}, layer);
    anim.start();

    return () => {
      anim.stop();
    };
  }, [clip.type, prevMediaElement]);

  const { glCanvas, drawGL } = useGLTransition(
    videoSize.width,
    videoSize.height,
    clip.transitionIn,
  );

  useEffect(() => {
    setHasTransitionFrame(false);
  }, [clip.transitionIn, clip.prevClip?.id, clip.source]);

  // Playhead
  useEffect(() => {
    if (clip.type === "video" && videoElement instanceof HTMLVideoElement) {
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
    }

    if (clip.prevClip && prevMediaElement instanceof HTMLVideoElement) {
      const prevLocalTime =
        currentTime -
        clip.prevClip.startTime +
        (clip.prevClip.sourceOffset || 0);
      if (isPlaying) {
        if (prevMediaElement.paused) prevMediaElement.play().catch(() => {});
        if (Math.abs(prevMediaElement.currentTime - prevLocalTime) > 0.25)
          prevMediaElement.currentTime = Math.max(0, prevLocalTime);
      } else {
        if (!prevMediaElement.paused) prevMediaElement.pause();
        if (Math.abs(prevMediaElement.currentTime - prevLocalTime) > 0.05)
          prevMediaElement.currentTime = Math.max(0, prevLocalTime);
      }
    }
  }, [
    currentTime,
    isPlaying,
    clip.startTime,
    clip.sourceOffset,
    clip.type,
    clip.prevClip,
    videoElement,
    prevMediaElement,
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

  const currentMedia =
    clip.type === "video" && videoElement instanceof HTMLVideoElement
      ? videoElement
      : clip.type === "image" && imageElement
        ? imageElement
        : null;

  useEffect(() => {
    if (!isTransitioning || !prevMediaElement || !currentMedia || !glCanvas)
      return;

    let animationFrame: number | null = null;
    const renderTransition = () => {
      const rendered = drawGL(
        prevMediaElement,
        currentMedia,
        transitionProgress,
      );
      if (rendered) {
        setHasTransitionFrame(true);
        shapeRef.current?.getLayer()?.batchDraw();
      } else {
        animationFrame = requestAnimationFrame(renderTransition);
      }
    };
    renderTransition();

    return () => {
      if (animationFrame !== null) cancelAnimationFrame(animationFrame);
    };
  }, [
    currentTime,
    isTransitioning,
    transitionProgress,
    prevMediaElement,
    currentMedia,
    glCanvas,
    drawGL,
  ]);

  const textRef = useRef<any>(null);

  const isTextOrSubtitle = clip.type === "text" || clip.type === "subtitle";
  const textContent = clip.text !== undefined ? clip.text : "New Text";
  const fontFamily =
    clip.fontFamily || clip.style?.fontFamily || "Inter, sans-serif";
  const fontSize = clip.fontSize || clip.style?.fontSize || 48;
  const fillColor = clip.color || clip.style?.color || "#ffffff";
  const strokeColor = clip.stroke || clip.style?.stroke || undefined;
  const strokeWidth = clip.strokeWidth ?? clip.style?.strokeWidth ?? 0;
  const shadowColor = clip.shadowColor || clip.style?.shadowColor || undefined;
  const shadowBlur = clip.shadowBlur ?? clip.style?.shadowBlur ?? 0;
  const shadowOffsetX = clip.shadowOffsetX ?? clip.style?.shadowOffsetX ?? 0;
  const shadowOffsetY = clip.shadowOffsetY ?? clip.style?.shadowOffsetY ?? 0;
  const shadowOpacity = shadowColor ? 0.8 : 0;
  const isKaraoke = Boolean(
    clip.karaoke ??
    clip.style?.karaoke ??
    (clip.trackId === "track-subtitles" && clip.karaoke),
  );
  const karaokeHighlightColor =
    clip.karaokeHighlightColor ||
    clip.style?.karaokeHighlightColor ||
    "#f59e0b";

  const measured = isTextOrSubtitle
    ? getMeasuredTextDimensions(textContent, fontSize, fontFamily)
    : { width: 100, height: 50 };

  const computedTextWidth =
    textRef.current &&
    typeof textRef.current.width === "function" &&
    textRef.current.width() > 0
      ? textRef.current.width()
      : measured.width;
  const computedTextHeight =
    textRef.current &&
    typeof textRef.current.height === "function" &&
    textRef.current.height() > 0
      ? textRef.current.height()
      : measured.height;

  const clipProgress =
    clip.duration > 0
      ? Math.max(0, Math.min(1, (currentTime - clip.startTime) / clip.duration))
      : 0;

  useEffect(() => {
    if (isKaraoke && isTextOrSubtitle && shapeRef.current) {
      shapeRef.current.getLayer()?.batchDraw();
    }
  }, [isKaraoke, isTextOrSubtitle, currentTime]);

  useEffect(() => {
    if (isSelected && trRef.current && shapeRef.current) {
      trRef.current.nodes([shapeRef.current]);
      trRef.current.getLayer()?.batchDraw();
    }
  }, [isSelected, isKaraoke, clip.type]);

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
    isTransitioning && glCanvas && hasTransitionFrame
      ? glCanvas
      : clip.type === "video" && videoElement instanceof HTMLVideoElement
        ? videoElement
        : imageElement || undefined;

  return (
    <>
      {isTextOrSubtitle ? (
        <KonvaGroup
          ref={shapeRef}
          x={x}
          y={y}
          opacity={currentOpacity}
          scaleX={scaleX}
          scaleY={scaleY}
          rotation={rotation}
          draggable={isSelected}
          onClick={onSelect}
          onTap={onSelect}
          onDragEnd={(e) => onChange({ x: e.target.x(), y: e.target.y() })}
          onTransformEnd={() => {
            const node = shapeRef.current;
            if (!node) return;
            onChange({
              x: node.x(),
              y: node.y(),
              scaleX: node.scaleX(),
              scaleY: node.scaleY(),
              rotation: node.rotation(),
            });
          }}
        >
          {/* Layer 1 (Base): Normal KonvaText with default fill color, stroke, and drop shadow */}
          <KonvaText
            ref={textRef}
            text={textContent}
            x={0}
            y={0}
            fontFamily={fontFamily}
            fontSize={fontSize}
            fill={fillColor}
            stroke={strokeColor}
            strokeWidth={strokeWidth}
            fillAfterStrokeEnabled={true}
            shadowColor={shadowColor}
            shadowBlur={shadowBlur}
            shadowOffsetX={shadowOffsetX}
            shadowOffsetY={shadowOffsetY}
            shadowOpacity={shadowOpacity}
          />

          {/* Layer 2 (Highlight): Wrapped inside a Konva Group with horizontal clipping */}
          {isKaraoke && clipProgress > 0 && (
            <KonvaGroup
              clip={{
                x: 0,
                y: 0,
                width: computedTextWidth * clipProgress,
                height: computedTextHeight + 20,
              }}
              clipX={0}
              clipY={0}
              clipWidth={computedTextWidth * clipProgress}
              clipHeight={computedTextHeight + 20}
            >
              <KonvaText
                text={textContent}
                x={0}
                y={0}
                fontFamily={fontFamily}
                fontSize={fontSize}
                fill={karaokeHighlightColor}
                stroke={strokeColor}
                strokeWidth={strokeWidth}
                fillAfterStrokeEnabled={true}
              />
            </KonvaGroup>
          )}
        </KonvaGroup>
      ) : (
        <KonvaImage
          ref={shapeRef}
          image={activeMedia}
          x={x}
          y={y}
          opacity={currentOpacity}
          width={videoSize.width}
          height={videoSize.height}
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
          sceneFunc={(context, shape) => {
            if (!activeMedia) return;
            const ctx = context._context;
            const b = clip.effects?.brightness ?? 0;
            const c = clip.effects?.contrast ?? 0;
            const s = clip.effects?.saturation ?? 0;
            const hasColorFilter = b !== 0 || c !== 0 || s !== 0;

            const prevFilter = ctx.filter;
            if (hasColorFilter) {
              const bVal = Math.max(0, 1 + b / 100);
              const cVal = Math.max(0, 1 + c / 100);
              const sVal = Math.max(0, 1 + s / 100);
              ctx.filter = `brightness(${bVal}) contrast(${cVal}) saturate(${sVal})`;
            }

            const w = shape.width() || videoSize.width;
            const h = shape.height() || videoSize.height;
            context.drawImage(activeMedia, 0, 0, w, h);

            if (hasColorFilter) {
              ctx.filter = prevFilter || "none";
            }
          }}
          hitFunc={(context, shape) => {
            context.beginPath();
            context.rect(
              0,
              0,
              shape.width() || videoSize.width,
              shape.height() || videoSize.height,
            );
            context.closePath();
            context.fillStrokeShape(shape);
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
