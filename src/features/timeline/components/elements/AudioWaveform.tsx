import { useEffect, useRef, useState } from "react";
import { AudioWaveformProps } from "../../../../types/index";
interface DecodedAudio {
  channelData: Float32Array;
  sampleRate: number;
  duration: number;
}

const audioBufferCache = new Map<string, Promise<DecodedAudio>>();

function getDecodedAudio(src: string): Promise<DecodedAudio> {
  if (audioBufferCache.has(src)) {
    return audioBufferCache.get(src)!;
  }

  const decodePromise = (async () => {
    const response = await fetch(src);
    if (!response.ok) {
      throw new Error(`Failed to fetch audio source: ${response.statusText}`);
    }
    const arrayBuffer = await response.arrayBuffer();
    const OfflineCtx =
      window.OfflineAudioContext || (window as any).webkitOfflineAudioContext;
    const audioCtx = OfflineCtx
      ? new OfflineCtx(1, 2, 44100)
      : new (window.AudioContext || (window as any).webkitAudioContext)();

    try {
      const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
      return {
        channelData: audioBuffer.getChannelData(0),
        sampleRate: audioBuffer.sampleRate,
        duration: audioBuffer.duration,
      };
    } finally {
      if (audioCtx && typeof (audioCtx as any).close === "function") {
        await (audioCtx as any).close().catch(() => {});
      }
    }
  })();

  decodePromise.catch(() => {
    audioBufferCache.delete(src);
  });

  audioBufferCache.set(src, decodePromise);
  return decodePromise;
}

export function AudioWaveform({
  src,
  width,
  height,
  duration,
  sourceOffset = 0,
  volume = 1.0,
  color = "rgba(255, 255, 255, 0.45)",
}: AudioWaveformProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [decodedAudio, setDecodedAudio] = useState<DecodedAudio | null>(null);

  useEffect(() => {
    if (!src) {
      setIsLoading(false);
      setDecodedAudio(null);
      return;
    }

    let isMounted = true;
    setIsLoading(true);

    getDecodedAudio(src)
      .then((data) => {
        if (isMounted) {
          setDecodedAudio(data);
          setIsLoading(false);
        }
      })
      .catch((err) => {
        console.error("Failed to render audio waveform for:", src, err);
        if (isMounted) {
          setIsLoading(false);
          setDecodedAudio(null);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [src]);

  useEffect(() => {
    if (!decodedAudio || !width || !height || width <= 0 || height <= 0) return;

    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const pixelWidth = Math.max(1, Math.floor(width));
    const pixelHeight = Math.max(1, Math.floor(height));

    canvas.width = Math.floor(pixelWidth * dpr);
    canvas.height = Math.floor(pixelHeight * dpr);

    ctx.save();
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, pixelWidth, pixelHeight);

    const { channelData, sampleRate, duration: totalDuration } = decodedAudio;
    const totalSamples = channelData.length;

    const validOffset = Math.max(0, sourceOffset);
    const startSample = Math.min(
      totalSamples,
      Math.floor(validOffset * sampleRate),
    );

    const effectiveDuration =
      duration !== undefined && duration > 0 ? duration : totalDuration;
    const endSample = Math.min(
      totalSamples,
      Math.max(
        startSample + 1,
        Math.floor((validOffset + effectiveDuration) * sampleRate),
      ),
    );

    const windowSamples = endSample - startSample;
    const samplesPerPixel = windowSamples / pixelWidth;
    const stride = Math.max(1, Math.floor(samplesPerPixel / 32));
    const effectiveVol = Math.max(0, volume);
    const midHeight = pixelHeight / 2;

    ctx.fillStyle = color;

    for (let i = 0; i < pixelWidth; i++) {
      const segStart = startSample + Math.floor(i * samplesPerPixel);
      const segEnd = Math.min(
        endSample,
        startSample + Math.floor((i + 1) * samplesPerPixel),
      );

      let min = 1.0;
      let max = -1.0;

      if (segStart < totalSamples) {
        for (let j = segStart; j < segEnd; j += stride) {
          const val = channelData[j];
          if (val < min) min = val;
          if (val > max) max = val;
        }
      }

      if (min > max) {
        min = 0;
        max = 0;
      }

      const peak = Math.max(Math.abs(min), Math.abs(max)) * effectiveVol;
      const peakHeight = Math.max(1, peak * (pixelHeight * 0.82));

      ctx.fillRect(i, midHeight - peakHeight / 2, 1, peakHeight);
    }

    ctx.restore();
    setIsLoading(false);
  }, [decodedAudio, width, height, duration, sourceOffset, volume, color]);

  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden z-10">
      <canvas
        ref={canvasRef}
        style={{ width: "100%", height: "100%" }}
        className={`transition-opacity duration-300 ${
          isLoading ? "opacity-0" : "opacity-100"
        }`}
      />
    </div>
  );
}
