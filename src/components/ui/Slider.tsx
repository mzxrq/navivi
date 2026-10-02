import { useEffect, useRef, useState } from "react";

interface SliderProps {
  value: number;
  min: number;
  max: number;
  step?: number;
  label: string;
  onChange?: (value: number) => void;
  // Fires once when a drag or key press ends with a different value, for settings that are costly to apply on every move.
  onCommit?: (value: number) => void;
  format?: (value: number) => string;
  disabled?: boolean;
  className?: string;
}

const THUMB = 4; // px; the invisible native thumb has the same width, so the drawn one lines up with where it really is
const MAX_TICKS = 40;

// A ruler fader: baseline that fills with the accent, tick marks hanging under it (one per step, taller at the ends and the
// middle), a slim bar as the handle. The native range input sits on top, invisible, so keyboard, focus and screen readers behave.
export function Slider({ value, min, max, step = 1, label, onChange, onCommit, format, disabled, className = "w-full" }: SliderProps) {
  const [live, setLive] = useState(value);
  const liveRef = useRef(value);
  useEffect(() => {
    setLive(value);
    liveRef.current = value;
  }, [value]);

  const fraction = max > min ? Math.min(1, Math.max(0, (live - min) / (max - min))) : 0;
  const steps = Math.max(1, Math.round((max - min) / step));
  const intervals = steps <= MAX_TICKS ? steps : 20;
  const x = `calc((100% - ${THUMB}px) * ${fraction} + ${THUMB / 2}px)`;

  const commit = () => {
    if (liveRef.current !== value) onCommit?.(liveRef.current);
  };

  return (
    <span className={`group relative inline-flex h-6 items-center select-none ${disabled ? "opacity-50" : ""} ${className}`}>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={live}
        disabled={disabled}
        aria-label={label}
        onChange={(e) => {
          const next = parseFloat(e.target.value);
          liveRef.current = next;
          setLive(next);
          onChange?.(next);
        }}
        onPointerUp={commit}
        onKeyUp={commit}
        onBlur={commit}
        className="peer absolute inset-0 z-10 m-0 h-full w-full cursor-pointer appearance-none bg-transparent opacity-0 disabled:cursor-default [&::-webkit-slider-thumb]:h-6 [&::-webkit-slider-thumb]:w-1 [&::-webkit-slider-thumb]:appearance-none"
      />

      <span aria-hidden className="absolute inset-x-0 top-1/2 h-0.5 -translate-y-1/2 rounded-full bg-zinc-200 dark:bg-white/10" />
      <span aria-hidden className="absolute left-0 top-1/2 h-0.5 -translate-y-1/2 rounded-full bg-navi" style={{ width: x }} />

      <span aria-hidden className="pointer-events-none absolute inset-x-0.5 top-1/2 mt-1.5 h-2">
        {Array.from({ length: intervals + 1 }, (_, i) => {
          const at = i / intervals;
          const major = i === 0 || i === intervals || (intervals % 2 === 0 && i === intervals / 2);
          return (
            <span
              key={i}
              className={`absolute top-0 w-px -translate-x-1/2 ${major ? "h-2" : "h-1"} ${at <= fraction + 1e-6 ? "bg-navi/70" : "bg-zinc-300 dark:bg-white/20"}`}
              style={{ left: `${+(at * 100).toFixed(2)}%` }}
            />
          );
        })}
      </span>

      <span
        aria-hidden
        className="pointer-events-none absolute top-1/2 h-4 w-1 -translate-y-1/2 rounded-[2px] bg-navi shadow-sm transition-[height] group-hover:h-5 group-active:h-5 peer-focus-visible:h-5 peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-navi/50"
        style={{ left: `calc((100% - ${THUMB}px) * ${fraction})` }}
      />

      <span
        aria-hidden
        className="pointer-events-none absolute bottom-full mb-0.5 -translate-x-1/2 whitespace-nowrap rounded-md bg-zinc-900 px-1.5 py-0.5 text-[11px] tabular-nums text-white opacity-0 transition-opacity group-hover:opacity-100 peer-focus-visible:opacity-100 dark:bg-zinc-100 dark:text-zinc-900"
        style={{ left: x }}
      >
        {format ? format(live) : String(live)}
      </span>
    </span>
  );
}
