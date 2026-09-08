import React, { useEffect, useRef, useState } from "react";

interface AudioWaveformProps {
  src: string;
  width: number;
  height: number;
}

export function AudioWaveform({ src, width, height }: AudioWaveformProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!src || !width || !height) return;

    let isMounted = true;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const drawWaveform = async () => {
      try {
        setIsLoading(true);
        const response = await fetch(src);
        const arrayBuffer = await response.arrayBuffer();

        const audioCtx = new (
          window.AudioContext || (window as any).webkitAudioContext
        )();
        const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);

        if (!isMounted) return;

        const channelData = audioBuffer.getChannelData(0);
        const samplesPerPixel = Math.floor(channelData.length / width);
        const peaks = [];

        for (let i = 0; i < width; i++) {
          let min = 1.0;
          let max = -1.0;
          for (let j = 0; j < samplesPerPixel; j++) {
            const datum = channelData[i * samplesPerPixel + j];
            if (datum < min) min = datum;
            if (datum > max) max = datum;
          }
          peaks.push(Math.max(Math.abs(min), Math.abs(max)));
        }

        ctx.clearRect(0, 0, width, height);
        ctx.fillStyle = "rgba(255,255,255,0.4)";
        const midHeight = height / 2;
        peaks.forEach((peak, index) => {
          const peakHeight = Math.max(1, peak * (height * 0.8));

          ctx.fillRect(index, midHeight - peakHeight / 2, 1, peakHeight);
        });
      } catch (error) {
        console.error("Failed to render waveform:", error);
      } finally {
        if (isMounted) setIsLoading(false);
      }
    };

    drawWaveform();

    return () => {
      isMounted = false;
    };
  }, [src, width, height]);

  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden z-10">
      <canvas
        ref={canvasRef}
        width={width}
        height={height}
        className={`w-full h-full transition-opacity duration-500 ${isLoading ? "opacity-0" : "opacity-100"}`}
      />
    </div>
  );
}
