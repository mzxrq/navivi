import { ReactNode, useEffect, useState } from "react";
import { t } from "@lingui/core/macro";
import { useInstalledFonts } from "../../hooks/useInstalledFonts";
import type { TextStyle } from "../../types";
import { DEFAULT_CAPTION_STYLE } from "../../utils/textStyle";
import { ColorPicker } from "./ColorPicker";
import { ComboBox } from "./ComboBox";
import { AlignVerticalJustifyCenter, AlignVerticalJustifyEnd, AlignVerticalJustifyStart, Bold, Italic, Underline } from "./icons";
import { Segmented } from "./Segmented";
import { StepButtons } from "./StepButtons";
import { Switch } from "./Switch";
import { ToggleGroup } from "./ToggleGroup";

const field =
  "h-8 w-full min-w-0 px-2 rounded-lg bg-white dark:bg-zinc-950/40 border border-zinc-200 dark:border-white/10 text-[12px] text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-2 focus:ring-navi/20 transition";

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
  const stepBy = (dir: 1 | -1) => {
    const n = Math.round(Number(text));
    const v = Math.min(max, Math.max(min, (Number.isFinite(n) ? n : Math.round(value)) + dir));
    setText(String(v));
    if (v !== Math.round(value)) onCommit(v);
  };
  return (
    <div className="relative w-full">
      <input
        type="number"
        value={text}
        min={min}
        max={max}
        onChange={(e) => setText(e.target.value)}
        onBlur={done}
        onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
        className={`${field} pr-6 text-right tabular-nums`}
      />
      <StepButtons onStep={stepBy} />
    </div>
  );
}

export type CaptionRow = (key: string, label: string, control: ReactNode, hint?: string) => ReactNode;

/** The installed fonts as a list that shows each name in its own face; any other name can still be typed. */
function FontField({ value, onChange }: { value: string; onChange: (font: string) => void }) {
  const fonts = useInstalledFonts();
  const options = fonts.some((f) => f.toLowerCase() === value.toLowerCase()) ? fonts : [value, ...fonts];
  return <ComboBox label={t`Font`} value={value} options={options} allowCustom previewFont onChange={onChange} className="w-full" />;
}

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
  const fonts = useInstalledFonts();
  const missing = fonts.length > 0 && !fonts.some((f) => f.toLowerCase() === style.font_family.toLowerCase());
  const icon = "w-3.5 h-3.5";

  return (
    <>
      {row(
        "font",
        t`Font`,
        <FontField value={style.font_family} onChange={(font_family) => onChange({ font_family })} />,
        missing ? t`Not installed on this PC, so the export uses ${fallbackFont}` : undefined,
      )}
      {row(
        "size",
        t`Size and style`,
        <div className="flex items-center gap-2 w-full">
          <div className="w-24 shrink-0">
            <IntInput value={style.font_size} min={8} max={300} onCommit={(v) => onChange({ font_size: v })} />
          </div>
          <ToggleGroup
            items={[
              { id: "bold", label: t`Bold`, icon: <Bold className={icon} />, pressed: style.bold, onToggle: () => onChange({ bold: !style.bold }) },
              { id: "italic", label: t`Italic`, icon: <Italic className={icon} />, pressed: style.italic, onToggle: () => onChange({ italic: !style.italic }) },
              { id: "underline", label: t`Underline`, icon: <Underline className={icon} />, pressed: style.underline, onToggle: () => onChange({ underline: !style.underline }) },
            ]}
          />
        </div>,
        t`Size in pixels on a 1080p frame`,
      )}
      {row("color", t`Text colour`, <ColorPicker label={t`Text colour`} value={style.color} onChange={(color) => onChange({ color })} />)}
      {caption && row("box", t`Background box`, <Switch checked={style.background} onChange={(v) => onChange({ background: v })} label={t`Background box`} />)}
      {caption && style.background ? (
        <>
          {row(
            "box-color",
            t`Box colour`,
            <ColorPicker label={t`Box colour`} value={style.background_color} onChange={(background_color) => onChange({ background_color })} />,
          )}
          {row(
            "box-opacity",
            t`Box opacity`,
            <div className="w-24">
              <IntInput value={style.background_opacity * 100} min={0} max={100} onCommit={(v) => onChange({ background_opacity: v / 100 })} />
            </div>,
            t`Percent`,
          )}
        </>
      ) : (
        row(
          "outline",
          t`Outline`,
          <div className="flex items-center gap-2 w-full">
            <ColorPicker
              label={t`Outline colour`}
              value={style.outline_color}
              onChange={(outline_color) => onChange({ outline_color })}
              className="flex-1 min-w-0"
            />
            <div className="w-20 shrink-0">
              <IntInput value={style.outline_width} min={0} max={20} onCommit={(v) => onChange({ outline_width: v })} />
            </div>
          </div>,
          t`Colour, and width in pixels (0 = none)`,
        )
      )}
      {caption &&
        row(
          "position",
          t`Position`,
          <Segmented
            compact
            iconOnly
            className="w-full"
            value={style.position}
            onChange={(position) => onChange({ position })}
            options={[
              { id: "top", label: t`Top`, icon: <AlignVerticalJustifyStart className={icon} /> },
              { id: "middle", label: t`Middle`, icon: <AlignVerticalJustifyCenter className={icon} /> },
              { id: "bottom", label: t`Bottom`, icon: <AlignVerticalJustifyEnd className={icon} /> },
            ]}
          />,
        )}
      {caption &&
        style.position !== "middle" &&
        row(
          "margin",
          style.position === "top" ? t`Distance from top` : t`Distance from bottom`,
          <div className="w-24">
            <IntInput value={style.margin_v} min={0} max={400} onCommit={(v) => onChange({ margin_v: v })} />
          </div>,
          t`Pixels on a 1080p frame`,
        )}
      {caption &&
        row(
          "max-chars",
          t`Max characters per line`,
          <div className="w-24">
            <IntInput value={style.max_chars_per_line} min={0} max={200} onCommit={(v) => onChange({ max_chars_per_line: v })} />
          </div>,
          t`0 = no limit`,
        )}
    </>
  );
}
