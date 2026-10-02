import { ReactNode, useEffect, useId, useState } from "react";
import { t } from "@lingui/core/macro";
import { useInstalledFonts } from "../../hooks/useInstalledFonts";
import type { TextStyle } from "../../types";
import { DEFAULT_CAPTION_STYLE } from "../../utils/textStyle";
import { Switch } from "./Switch";

const field =
  "h-8 w-full min-w-0 px-2 rounded-lg bg-white dark:bg-zinc-950/40 border border-zinc-200 dark:border-white/10 text-[12px] text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-2 focus:ring-navi/20 transition";
const colorField = "h-8 w-12 cursor-pointer rounded-lg bg-transparent";
const toggle = (on: boolean) =>
  `h-8 flex-1 rounded-lg border text-[12px] transition-colors ${
    on
      ? "border-navi bg-navi/10 text-navi"
      : "border-zinc-200 dark:border-white/10 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-white/5"
  }`;

/** Whole-number input that commits on blur/Enter, clamped to [min, max]. */
export function IntInput({ value, min, max, onCommit }: { value: number; min: number; max: number; onCommit: (v: number) => void }) {
  const [text, setText] = useState(String(Math.round(value)));
  useEffect(() => setText(String(Math.round(value))), [value]);
  const done = () => {
    const n = Math.round(Number(text));
    if (!Number.isFinite(n)) return setText(String(Math.round(value)));
    const v = Math.min(max, Math.max(min, n));
    setText(String(v));
    if (v !== Math.round(value)) onCommit(v);
  };
  return (
    <input
      type="number"
      value={text}
      min={min}
      max={max}
      onChange={(e) => setText(e.target.value)}
      onBlur={done}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
      className={`${field} text-right tabular-nums`}
    />
  );
}

export type CaptionRow = (key: string, label: string, control: ReactNode, hint?: string) => ReactNode;

/** Look (+ placement, for captions) controls; `row` lays each one out in the host panel's own style.
 * kind "text" is a text-track line: no box, position or line limit, and its own fallback font. */
export function CaptionStyleFields({
  style,
  onChange,
  row,
  kind = "caption",
  fallbackFont = DEFAULT_CAPTION_STYLE.font_family,
}: {
  style: Required<TextStyle>;
  onChange: (patch: TextStyle) => void;
  row: CaptionRow;
  kind?: "caption" | "text";
  fallbackFont?: string;
}) {
  const caption = kind === "caption";
  const listId = useId();
  const fonts = useInstalledFonts();
  const [font, setFont] = useState(style.font_family);
  useEffect(() => setFont(style.font_family), [style.font_family]);
  const missing = fonts.length > 0 && !fonts.some((f) => f.toLowerCase() === style.font_family.toLowerCase());

  return (
    <>
      {row(
        "font",
        t`Font`,
        <>
          <input
            type="text"
            list={listId}
            value={font}
            onChange={(e) => setFont(e.target.value)}
            onBlur={() => font.trim() && font !== style.font_family && onChange({ font_family: font.trim() })}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
            className={field}
          />
          <datalist id={listId}>
            {fonts.map((f) => (
              <option key={f} value={f} />
            ))}
          </datalist>
        </>,
        missing ? t`Not installed on this PC, so the export uses ${fallbackFont}` : undefined,
      )}
      {row("size", t`Font size`, <IntInput value={style.font_size} min={8} max={300} onCommit={(v) => onChange({ font_size: v })} />, t`Pixels on a 1080p frame`)}
      {row(
        "weight",
        t`Style`,
        <div className="flex gap-1">
          <button type="button" className={`${toggle(style.bold)} font-bold`} aria-pressed={style.bold} onClick={() => onChange({ bold: !style.bold })}>
            B
          </button>
          <button type="button" className={`${toggle(style.italic)} italic`} aria-pressed={style.italic} onClick={() => onChange({ italic: !style.italic })}>
            I
          </button>
          <button type="button" className={`${toggle(style.underline)} underline`} aria-pressed={style.underline} onClick={() => onChange({ underline: !style.underline })}>
            U
          </button>
        </div>,
      )}
      {row("color", t`Text colour`, <input type="color" value={style.color} onChange={(e) => onChange({ color: e.target.value })} className={colorField} />)}
      {caption && row("box", t`Background box`, <Switch checked={style.background} onChange={(v) => onChange({ background: v })} label={t`Background box`} />)}
      {caption && style.background ? (
        <>
          {row("box-color", t`Box colour`, <input type="color" value={style.background_color} onChange={(e) => onChange({ background_color: e.target.value })} className={colorField} />)}
          {row(
            "box-opacity",
            t`Box opacity`,
            <IntInput value={style.background_opacity * 100} min={0} max={100} onCommit={(v) => onChange({ background_opacity: v / 100 })} />,
            t`Percent`,
          )}
        </>
      ) : (
        <>
          {row("outline-color", t`Outline colour`, <input type="color" value={style.outline_color} onChange={(e) => onChange({ outline_color: e.target.value })} className={colorField} />)}
          {row("outline", t`Outline width`, <IntInput value={style.outline_width} min={0} max={20} onCommit={(v) => onChange({ outline_width: v })} />)}
        </>
      )}
      {caption && row(
        "position",
        t`Position`,
        <select value={style.position} onChange={(e) => onChange({ position: e.target.value as TextStyle["position"] })} className={`${field} cursor-pointer`}>
          <option value="bottom">{t`Bottom`}</option>
          <option value="middle">{t`Middle`}</option>
          <option value="top">{t`Top`}</option>
        </select>,
      )}
      {caption && style.position !== "middle" &&
        row(
          "margin",
          style.position === "top" ? t`Distance from top` : t`Distance from bottom`,
          <IntInput value={style.margin_v} min={0} max={400} onCommit={(v) => onChange({ margin_v: v })} />,
          t`Pixels on a 1080p frame`,
        )}
      {caption && row(
        "max-chars",
        t`Max characters per line`,
        <IntInput value={style.max_chars_per_line} min={0} max={200} onCommit={(v) => onChange({ max_chars_per_line: v })} />,
        t`0 = no limit`,
      )}
    </>
  );
}
