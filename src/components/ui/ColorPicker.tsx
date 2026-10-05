import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { t } from "@lingui/core/macro";
import { hexToHsv, hsvToHex, normalizeHex, type Hsv } from "../../utils/color";

const PRESETS = [
  "#FFFFFF", "#F4F4F5", "#A1A1AA", "#52525B", "#000000", "#EF4444", "#F97316", "#F59E0B",
  "#FACC15", "#22C55E", "#14B8A6", "#3B82F6", "#6366F1", "#8B5CF6", "#EC4899", "#FF7E5F",
];
const RECENT_KEY = "navivi.recentColors";
const RECENT_MAX = 8;
const WIDTH = 248;

const clamp = (n: number) => Math.min(1, Math.max(0, n));

function loadRecent(): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.map((c) => normalizeHex(String(c))).filter((c): c is string => !!c).slice(0, RECENT_MAX) : [];
  } catch {
    return [];
  }
}

function remember(hex: string): string[] {
  const next = [hex, ...loadRecent().filter((c) => c !== hex)].slice(0, RECENT_MAX);
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    // the recent row is a convenience
  }
  return next;
}

function Swatch({ color, active, label, onClick }: { color: string; active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      title={color}
      aria-label={label}
      aria-pressed={active}
      onClick={onClick}
      className={`h-5 w-5 rounded-md ring-1 ring-inset ring-black/15 dark:ring-white/20 transition-transform hover:scale-110 ${
        active ? "outline-2 outline-offset-2 outline-navi" : ""
      }`}
      style={{ backgroundColor: color }}
    />
  );
}

interface ColorPickerProps {
  value: string;
  onChange: (hex: string) => void;
  label: string;
  className?: string;
}

// A colour field: swatch and hex on the button; a popover with a colour square, hue bar, hex box, presets and recent colours.
// While a handle is dragged the popover shows the colour live and `onChange` fires once, on release.
export function ColorPicker({ value, onChange, label, className = "w-full" }: ColorPickerProps) {
  const id = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const squareRef = useRef<HTMLDivElement>(null);
  const hueRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [hsv, setHsvState] = useState<Hsv>(() => hexToHsv(value));
  const hsvRef = useRef(hsv);
  const dragging = useRef<"square" | "hue" | null>(null);
  const [hexText, setHexText] = useState(value.toUpperCase());
  const [bad, setBad] = useState(false);
  const [recent, setRecent] = useState<string[]>([]);

  const setHsv = (next: Hsv) => {
    hsvRef.current = next;
    setHsvState(next);
    setHexText(hsvToHex(next));
    setBad(false);
  };

  // Follow the saved value (undo, another control), but keep the hue of a grey, which hex cannot hold.
  useEffect(() => {
    if (dragging.current) return;
    if (hsvToHex(hsvRef.current) === value.toUpperCase()) return;
    const next = hexToHsv(value);
    hsvRef.current = next;
    setHsvState(next);
    setHexText(value.toUpperCase());
    setBad(false);
  }, [value]);

  const place = useCallback(() => {
    if (triggerRef.current) setRect(triggerRef.current.getBoundingClientRect());
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    setRecent(loadRecent());
    const away = (e: MouseEvent) => {
      const target = e.target as Node;
      if (!popRef.current?.contains(target) && !triggerRef.current?.contains(target)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", away);
    window.addEventListener("keydown", esc, true);
    return () => {
      document.removeEventListener("mousedown", away);
      window.removeEventListener("keydown", esc, true);
    };
  }, [open]);

  const commit = (hex = hsvToHex(hsvRef.current)) => {
    setRecent(remember(hex));
    if (hex !== value.toUpperCase()) onChange(hex);
  };

  const fromPointer = (kind: "square" | "hue", e: React.PointerEvent) => {
    const el = (kind === "square" ? squareRef : hueRef).current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const x = clamp((e.clientX - r.left) / r.width);
    const y = clamp((e.clientY - r.top) / r.height);
    setHsv(kind === "square" ? { ...hsvRef.current, s: x, v: 1 - y } : { ...hsvRef.current, h: x * 360 });
  };

  const drag = (kind: "square" | "hue") => ({
    onPointerDown: (e: React.PointerEvent) => {
      e.currentTarget.setPointerCapture(e.pointerId);
      dragging.current = kind;
      fromPointer(kind, e);
    },
    onPointerMove: (e: React.PointerEvent) => dragging.current === kind && fromPointer(kind, e),
    onPointerUp: () => {
      if (dragging.current !== kind) return;
      dragging.current = null;
      commit();
    },
    onPointerCancel: () => {
      dragging.current = null;
    },
  });

  const nudge = (kind: "square" | "hue") => (e: React.KeyboardEvent) => {
    const step = e.shiftKey ? 0.1 : 0.01;
    const cur = hsvRef.current;
    const move: Record<string, Hsv | undefined> =
      kind === "square"
        ? {
            ArrowLeft: { ...cur, s: clamp(cur.s - step) },
            ArrowRight: { ...cur, s: clamp(cur.s + step) },
            ArrowUp: { ...cur, v: clamp(cur.v + step) },
            ArrowDown: { ...cur, v: clamp(cur.v - step) },
          }
        : {
            ArrowLeft: { ...cur, h: Math.max(0, cur.h - step * 360) },
            ArrowDown: { ...cur, h: Math.max(0, cur.h - step * 360) },
            ArrowRight: { ...cur, h: Math.min(360, cur.h + step * 360) },
            ArrowUp: { ...cur, h: Math.min(360, cur.h + step * 360) },
          };
    const next = move[e.key];
    if (!next) return;
    e.preventDefault();
    setHsv(next);
    commit(hsvToHex(next));
  };

  const pick = (hex: string) => {
    const next = hexToHsv(hex);
    setHsv(next);
    commit(hex);
  };

  const finishHex = () => {
    const hex = normalizeHex(hexText);
    if (!hex) return setBad(true);
    pick(hex);
  };

  const current = hsvToHex(hsv);
  const hueColor = hsvToHex({ h: hsv.h, s: 1, v: 1 });
  const below = rect ? window.innerHeight - rect.bottom - 12 : 0;
  const placement: React.CSSProperties = rect
    ? {
        left: Math.max(8, Math.min(rect.left, window.innerWidth - WIDTH - 8)),
        ...(below < 330 && rect.top > below ? { bottom: window.innerHeight - rect.top + 6 } : { top: rect.bottom + 6 }),
      }
    : {};

  return (
    <div className={className}>
      <button
        ref={triggerRef}
        type="button"
        aria-label={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen((o) => !o)}
        className="h-8 w-full min-w-0 px-1.5 rounded-lg flex items-center gap-2 bg-white dark:bg-zinc-950/40 border border-zinc-200 dark:border-white/10 text-[12px] text-zinc-800 dark:text-zinc-100 hover:border-zinc-300 dark:hover:border-white/20 focus:outline-none focus-visible:border-navi focus-visible:ring-2 focus-visible:ring-navi/20 transition"
      >
        <span className="h-5 w-5 rounded-md shrink-0 ring-1 ring-inset ring-black/15 dark:ring-white/20" style={{ backgroundColor: value }} />
        <span className="tabular-nums tracking-tight truncate">{value.toUpperCase()}</span>
      </button>

      {open &&
        rect &&
        createPortal(
          <div
            ref={popRef}
            id={id}
            role="dialog"
            aria-label={label}
            style={{ position: "fixed", width: WIDTH, zIndex: 100000, ...placement }}
            className="rounded-xl border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-900 shadow-xl p-3 space-y-3 select-none"
          >
            <div
              ref={squareRef}
              role="slider"
              tabIndex={0}
              aria-label={t`Saturation and brightness`}
              aria-valuetext={current}
              onKeyDown={nudge("square")}
              {...drag("square")}
              className="relative h-36 rounded-lg cursor-crosshair touch-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-navi"
              style={{
                backgroundColor: hueColor,
                backgroundImage: "linear-gradient(to top, #000, rgba(0,0,0,0)), linear-gradient(to right, #fff, rgba(255,255,255,0))",
              }}
            >
              <span
                className="absolute h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white shadow-[0_0_0_1px_rgba(0,0,0,.4)] pointer-events-none"
                style={{ left: `${hsv.s * 100}%`, top: `${(1 - hsv.v) * 100}%`, backgroundColor: current }}
              />
            </div>

            <div
              ref={hueRef}
              role="slider"
              tabIndex={0}
              aria-label={t`Hue`}
              aria-valuemin={0}
              aria-valuemax={360}
              aria-valuenow={Math.round(hsv.h)}
              onKeyDown={nudge("hue")}
              {...drag("hue")}
              className="relative h-3 rounded-full cursor-pointer touch-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-navi"
              style={{ backgroundImage: "linear-gradient(to right, #f00, #ff0, #0f0, #0ff, #00f, #f0f, #f00)" }}
            >
              <span
                className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white shadow-[0_0_0_1px_rgba(0,0,0,.4)] pointer-events-none"
                style={{ left: `${(hsv.h / 360) * 100}%`, backgroundColor: hueColor }}
              />
            </div>

            <div className="flex items-center gap-2">
              <span className="h-8 w-8 rounded-lg shrink-0 ring-1 ring-inset ring-black/15 dark:ring-white/20" style={{ backgroundColor: current }} />
              <input
                value={hexText}
                aria-label={t`Hex colour`}
                spellCheck={false}
                maxLength={7}
                onChange={(e) => {
                  setHexText(e.target.value);
                  setBad(false);
                }}
                onBlur={finishHex}
                onKeyDown={(e) => e.key === "Enter" && finishHex()}
                className={`h-8 min-w-0 flex-1 px-2 rounded-lg bg-white dark:bg-zinc-950/40 border text-[12px] tabular-nums uppercase text-zinc-900 dark:text-zinc-100 outline-none focus:ring-2 transition ${
                  bad ? "border-red-400 focus:ring-red-400/25" : "border-zinc-200 dark:border-white/10 focus:border-navi focus:ring-navi/20"
                }`}
              />
            </div>

            <div className="grid grid-cols-8 gap-1.5 justify-items-center">
              {PRESETS.map((c) => (
                <Swatch key={c} color={c} active={c === current} label={c} onClick={() => pick(c)} />
              ))}
            </div>

            {recent.length > 0 && (
              <div>
                <p className="mb-1.5 text-[11px] text-zinc-400">{t`Recent`}</p>
                <div className="flex gap-1.5">
                  {recent.map((c) => (
                    <Swatch key={c} color={c} active={c === current} label={c} onClick={() => pick(c)} />
                  ))}
                </div>
              </div>
            )}
          </div>,
          document.body,
        )}
    </div>
  );
}
