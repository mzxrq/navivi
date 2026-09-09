import { useEffect, useRef, useState } from "react";

interface AudioWaveformProps {
  src: string;
  width: number;
  height: number;
}

export function AudioWaveform({ src, width, height }: AudioWaveformProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [audioData, setAudioData] = useState<Float32Array | null>(null);

  // ✨ 1. Fetch and decode the audio ONLY when the source changes
  useEffect(() => {
    if (!src) return;
    let isMounted = true;

    const fetchAudio = async () => {
      try {
        setIsLoading(true);
        const response = await fetch(src);
        const arrayBuffer = await response.arrayBuffer();

        const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
        const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);

        if (isMounted) {
          setAudioData(audioBuffer.getChannelData(0));
        }
      } catch (error) {
        console.error("Failed to render waveform:", error);
      }
    };

    fetchAudio();

    return () => {
      isMounted = false;
    };
  }, [src]);

  // ✨ 2. Instantly redraw the canvas whenever the width (Zoom) changes
  useEffect(() => {
    if (!audioData || !width || !height) return;
    
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const samplesPerPixel = Math.floor(audioData.length / width);
    const peaks = [];

    for (let i = 0; i < width; i++) {
      let min = 1.0;
      let max = -1.0;
      for (let j = 0; j < samplesPerPixel; j++) {
        const datum = audioData[i * samplesPerPixel + j];
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

    setIsLoading(false);
  }, [audioData, width, height]);

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