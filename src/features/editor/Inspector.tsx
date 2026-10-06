import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  AlignVerticalJustifyCenter,
  AlignVerticalJustifyEnd,
  AlignVerticalJustifyStart,
  Copy,
  Download,
  Music,
  Trash2,
} from "../../components/ui/icons";
import { Segmented } from "../../components/ui/Segmented";
import { Select } from "../../components/ui/Select";
import { Slider } from "../../components/ui/Slider";
import { StepButtons } from "../../components/ui/StepButtons";
import { Switch } from "../../components/ui/Switch";
import { CaptionRow, CaptionStyleFields, IntInput } from "../../components/ui/CaptionStyleFields";
import { useWorkspace } from "../../hooks/useWorkspace";
import type { TextStyle } from "../../types";
import { formatTimeValue, parseTime } from "../../utils/timeInput";
import {
  DEFAULT_TEXT_KICKER_STYLE,
  DEFAULT_TEXT_SUBTITLE_STYLE,
  DEFAULT_TEXT_TITLE_STYLE,
  LineAnimation,
  lineMotion,
  resolveCaptionStyle,
  TEXT_DEFAULT_MARGIN,
} from "../../utils/textStyle";
import {
  anchorCue,
  DEFAULT_EXTRA_VOLUME,
  isUnlinked,
  layout,
  linkAudio,
  MIN_CUE,
  MIN_SEGMENT,
  PlacedCue,
  placedCues,
  placedTexts,
  Segment,
  SubtitleCue,
  TEXT_LOOK_KEYS,
  TextClip,
  TextLine,
  TimelineData,
  unlinkAudio,
} from "./model";
import { formatTime, player, usePlayerTime } from "./player";
import { selectedCueIds, type Selection } from "./TimelinePane";

const percent = (v: number) => `${Math.round(v * 100)}%`;

interface InspectorProps {
  timeline: TimelineData;
  selection: Selection;
  onSelect: (s: Selection) => void;
  commit: (t: TimelineData) => void;
  onDuplicate: (id: string) => void;
  onRemoveSegment: (id: string) => void;
  onRemoveCues: (ids: string[]) => void;
  onSaveSrt: () => void;
}

const input =
  "h-8 w-full px-2 rounded-lg bg-white dark:bg-zinc-950/40 border border-zinc-200 dark:border-white/10 text-[12px] text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-2 focus:ring-navi/20 transition tabular-nums";

const iconButton =
  "flex items-center justify-center gap-1.5 h-8 px-2.5 rounded-lg text-[12px] font-medium text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-white/5 transition-colors";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="px-4 py-3 border-b border-zinc-100 dark:border-white/5">
      <h4 className="mb-2 text-[11px] font-medium text-zinc-400 dark:text-zinc-500">{title}</h4>
      <div className="space-y-2.5">{children}</div>
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-[12px] text-zinc-600 dark:text-zinc-300 shrink-0">{label}</span>
      <div className="w-28">{children}</div>
    </div>
  );
}

// "Start" and "End" here are moments on the timeline; the same words elsewhere mean a route's start (the Japanese differs).
const startLabel = () => t({ message: "Start", context: "a moment on the timeline" });
const endLabel = () => t({ message: "End", context: "a moment on the timeline" });
const unitLabel = (unit: "sec" | "min") =>
  unit === "min" ? t({ message: "min", context: "unit of time" }) : t({ message: "sec", context: "unit of time" });

// A time in seconds, written the way people read it: `12.50 sec` under a minute, `1:06.00 min` from a minute on. Typing
// "75", "1:15", "1m15s" or "1.5m" all work; the unit shown in the box says which one you are looking at.
function TimeField({ value, onCommit, min, max, step = 0.1 }: { value: number; onCommit: (v: number) => void; min?: number; max?: number; step?: number }) {
  const shown = formatTimeValue(value);
  const [text, setText] = useState(shown.text);
  useEffect(() => setText(formatTimeValue(value).text), [value]);
  const clampTime = (v: number) => +Math.min(max ?? Infinity, Math.max(min ?? -Infinity, v)).toFixed(2);
  const done = () => {
    const parsed = parseTime(text);
    if (parsed === null) return setText(shown.text);
    const clamped = clampTime(parsed);
    setText(formatTimeValue(clamped).text);
    if (Math.abs(clamped - value) > 0.001) onCommit(clamped);
  };
  const stepBy = (dir: 1 | -1) => {
    const next = clampTime((parseTime(text) ?? value) + dir * step);
    setText(formatTimeValue(next).text);
    if (Math.abs(next - value) > 0.001) onCommit(next);
  };
  return (
    <div className="relative">
      <input
        type="text"
        inputMode="decimal"
        value={text}
        title={t`Type seconds, or a time like 1:15 or 1m15s`}
        onChange={(e) => setText(e.target.value)}
        onBlur={done}
        onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
        className={`${input} pr-[3.25rem] text-right`}
      />
      <span className="pointer-events-none absolute right-6 top-0 h-8 flex items-center text-[11px] text-zinc-400">{unitLabel(shown.unit)}</span>
      <StepButtons onStep={stepBy} />
    </div>
  );
}

function TextBlock({ value, onCommit }: { value: string; onCommit: (v: string) => void }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <textarea
      value={text}
      rows={3}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => text !== value && onCommit(text)}
      className="w-full px-2 py-1.5 rounded-lg bg-white dark:bg-zinc-950/40 border border-zinc-200 dark:border-white/10 text-[13px] leading-snug text-zinc-900 dark:text-zinc-100 outline-none focus:border-navi focus:ring-2 focus:ring-navi/20 transition resize-none"
    />
  );
}

/** Every subtitle, with the one under the playhead highlighted and kept in view. */
function CueList({ cues, onPick }: { cues: PlacedCue[]; onPick: (id: string) => void }) {
  const time = usePlayerTime();
  const listRef = useRef<HTMLUListElement>(null);
  const current = cues.find((c) => time >= c.globalStart && time < c.globalEnd)?.id;

  useEffect(() => {
    const list = listRef.current;
    const row = current ? list?.querySelector<HTMLElement>(`[data-cue="${current}"]`) : null;
    if (!list || !row) return;
    // Scrolls only the list, never the panel around it.
    if (row.offsetTop < list.scrollTop) list.scrollTop = row.offsetTop;
    else if (row.offsetTop + row.offsetHeight > list.scrollTop + list.clientHeight)
      list.scrollTop = row.offsetTop + row.offsetHeight - list.clientHeight;
  }, [current]);

  return (
    <ul ref={listRef} className="relative max-h-64 overflow-y-auto custom-scrollbar -mx-2">
      {cues.map((c) => {
        const on = c.id === current;
        return (
          <li key={c.id} data-cue={c.id}>
            <button
              type="button"
              onClick={() => {
                onPick(c.id);
                player.set({ playing: false, time: c.globalStart });
              }}
              aria-current={on || undefined}
              className={`w-full flex gap-2 px-2 py-1.5 rounded-md text-left transition-colors ${
                on ? "bg-navi/10" : "hover:bg-zinc-100 dark:hover:bg-white/5"
              }`}
            >
              <span className={`shrink-0 w-11 text-[11px] tabular-nums pt-px ${on ? "text-navi" : "text-zinc-400"}`}>
                {formatTime(c.globalStart, false)}
              </span>
              <span className={`text-[12px] leading-snug line-clamp-2 ${on ? "text-zinc-900 dark:text-white" : "text-zinc-700 dark:text-zinc-300"}`}>
                {c.text}
              </span>
            </button>
          </li>
        );
      })}
      {!cues.length && <li className="px-2 text-[12px] text-zinc-400">{t`No subtitles yet. Use Subtitles in the toolbar.`}</li>}
    </ul>
  );
}

// The panel is narrow, so a style control gets the full width under its label (a switch stays beside it).
const styleRow: CaptionRow = (key, label, control, hint) =>
  key === "box" ? (
    <div key={key} className="flex items-center justify-between gap-3">
      <span className="text-[12px] text-zinc-600 dark:text-zinc-300">{label}</span>
      {control}
    </div>
  ) : (
    <div key={key}>
      <span className="mb-1 block text-[12px] text-zinc-600 dark:text-zinc-300">{label}</span>
      {control}
      {hint && <p className="mt-1 text-[11px] text-zinc-400">{hint}</p>}
    </div>
  );

/** One subtitle's own style: overrides on top of the default, or pushed to every subtitle. */
function CueStyleSection({ cue, timeline, commit }: { cue: SubtitleCue; timeline: TimelineData; commit: (t: TimelineData) => void }) {
  const { settings, updateSettings, setIsDirty } = useWorkspace();
  const style = resolveCaptionStyle(settings, cue.style);
  const setOwn = (own: TextStyle | undefined) =>
    commit({ ...timeline, subtitles: timeline.subtitles.map((c) => (c.id === cue.id ? { ...c, style: own } : c)) });
  const othersStyled = timeline.subtitles.some((c) => c.id !== cue.id && c.style);
  const applyToAll = () => {
    if (othersStyled && !window.confirm(t`Other subtitles have their own style. Replace it with this one?`)) return;
    updateSettings({ caption_style: { ...style } });
    setIsDirty(true);
    commit({ ...timeline, subtitles: timeline.subtitles.map(({ style: _own, ...c }) => c) });
  };
  return (
    <Section title={t`Style`}>
      <p className="text-[11px] text-zinc-400">
        {cue.style ? t`This subtitle has its own style.` : t`Uses the default subtitle style. Changes here apply to this subtitle only.`}
      </p>
      <CaptionStyleFields style={style} onChange={(patch) => setOwn({ ...(cue.style ?? {}), ...patch })} row={styleRow} />
      <div className="flex flex-wrap items-center gap-1 -mx-1">
        <button type="button" className={iconButton} onClick={applyToAll}>
          <Trans>Apply to all subtitles</Trans>
        </button>
        {cue.style && (
          <button type="button" className={iconButton} onClick={() => setOwn(undefined)}>
            <Trans>Use default style</Trans>
          </button>
        )}
      </div>
    </Section>
  );
}

/** Several subtitles at once: a style change is written into each one's own style. Shows the first one's values. */
function MultiCueSection({ ids, timeline, commit, onRemove }: { ids: string[]; timeline: TimelineData; commit: (t: TimelineData) => void; onRemove: (ids: string[]) => void }) {
  const { settings } = useWorkspace();
  const first = timeline.subtitles.find((c) => ids.includes(c.id));
  const style = resolveCaptionStyle(settings, first?.style);
  const patchAll = (fn: (c: SubtitleCue) => SubtitleCue) =>
    commit({ ...timeline, subtitles: timeline.subtitles.map((c) => (ids.includes(c.id) ? fn(c) : c)) });
  return (
    <div className="overflow-y-auto custom-scrollbar">
      <Section title={t`${ids.length} subtitles selected`}>
        <p className="text-[11px] text-zinc-400">
          <Trans>Drag them on the timeline to move them together. Style changes apply to every selected subtitle.</Trans>
        </p>
      </Section>
      <Section title={t`Style`}>
        <CaptionStyleFields style={style} onChange={(patch) => patchAll((c) => ({ ...c, style: { ...(c.style ?? {}), ...patch } }))} row={styleRow} />
        <div className="flex flex-wrap items-center gap-1 -mx-1">
          <button type="button" className={iconButton} onClick={() => patchAll(({ style: _own, ...c }) => c)}>
            <Trans>Use default style</Trans>
          </button>
        </div>
      </Section>
      <div className="px-3 py-3">
        <button type="button" className={`${iconButton} text-red-500 dark:text-red-400`} onClick={() => onRemove(ids)}>
          <Trash2 className="w-3.5 h-3.5" /> <Trans>Delete {ids.length} subtitles</Trans>
        </button>
      </div>
    </div>
  );
}

/** One line of a text clip (title or subtitle): its words and its own look. */
function TextLineSection({
  title,
  line,
  defaults,
  motion,
  onChange,
}: {
  title: string;
  line: TextLine;
  defaults: Required<TextStyle>;
  motion: { animation: LineAnimation; delay: number };
  onChange: (line: TextLine) => void;
}) {
  const [text, setText] = useState(line.text);
  useEffect(() => setText(line.text), [line.text]);
  return (
    <Section title={title}>
      <div>
        <span className="mb-1 block text-[12px] text-zinc-600 dark:text-zinc-300">{t`Text`}</span>
        <textarea
          value={text}
          rows={2}
          aria-label={title}
          onChange={(e) => setText(e.target.value.replace(/\n/g, " "))}
          onBlur={() => text !== line.text && onChange({ ...line, text })}
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLTextAreaElement).blur()}
          placeholder={t`Type the words here`}
          className="w-full px-2.5 py-2 rounded-lg bg-white dark:bg-zinc-950/40 border border-zinc-200 dark:border-white/10 text-[13px] leading-snug text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 outline-none focus:border-navi focus:ring-2 focus:ring-navi/20 transition resize-none"
        />
        <p className="mt-1 text-[11px] text-zinc-400">{t`Leave empty to hide this line`}</p>
      </div>
      <Row label={t`Animation`}>
        <Select<LineAnimation>
          label={t`Animation`}
          value={motion.animation}
          onChange={(animation) => onChange({ ...line, animation })}
          options={[
            { value: "pop", label: t`Pop in` },
            { value: "rise", label: t`Rise` },
            { value: "fade", label: t`Fade` },
            { value: "none", label: t`None` },
          ]}
        />
      </Row>
      <Row label={t`Appears after`}>
        <TimeField value={motion.delay} min={0} max={60} onCommit={(v) => onChange({ ...line, delay: +v.toFixed(2) })} />
      </Row>
      <p className="-mt-1 text-[11px] text-zinc-400">{t`Seconds after the title item starts. It leaves the same time before the end.`}</p>
      <CaptionStyleFields
        kind="text"
        fallbackFont={defaults.font_family}
        style={{ ...defaults, ...(line.style ?? {}) }}
        onChange={(patch) => onChange({ ...line, style: { ...(line.style ?? {}), ...patch } })}
        row={styleRow}
      />
      {(line.style || line.animation || line.delay !== undefined) && (
        <button type="button" className={iconButton} onClick={() => onChange({ text: line.text })}>
          <Trans>Reset style</Trans>
        </button>
      )}
    </Section>
  );
}

/** Where a text item sits and how it moves, plus sharing that look with others of its kind. */
function TextLookSection({ text, timeline, commit }: { text: TextClip; timeline: TimelineData; commit: (t: TimelineData) => void }) {
  const { updateSettings, setIsDirty } = useWorkspace();
  const patch = (change: Partial<TextClip>) =>
    commit({ ...timeline, texts: timeline.texts.map((x) => (x.id === text.id ? { ...x, ...change } : x)) });
  const sameKind = (x: TextClip) => (x.kind ?? "custom") === (text.kind ?? "custom");
  const peers = timeline.texts.filter((x) => x.id !== text.id && sameKind(x));

  const applyToAll = () => {
    const look: Partial<TextClip> = {};
    for (const k of TEXT_LOOK_KEYS) (look as any)[k] = text[k];
    commit({
      ...timeline,
      texts: timeline.texts.map((x) =>
        x.id === text.id || !sameKind(x)
          ? x
          : { ...x, ...look, title: { ...text.title, text: x.title.text }, subtitle: { ...text.subtitle, text: x.subtitle.text } },
      ),
    });
    // Place names come from the pipeline: keep the look for its next run too.
    if (text.kind === "place") {
      const saved: Record<string, unknown> = {};
      for (const which of ["title", "subtitle"] as const) {
        saved[`${which}_style`] = text[which].style;
        saved[`${which}_animation`] = text[which].animation;
        saved[`${which}_delay`] = text[which].delay;
      }
      for (const k of TEXT_LOOK_KEYS) saved[k] = text[k];
      updateSettings({ place_label_look: JSON.parse(JSON.stringify(saved)) });
      setIsDirty(true);
    }
  };

  return (
    <Section title={t`Position`}>
      <Row label={t`Place`}>
        <Segmented<NonNullable<TextClip["position"]>>
          compact
          iconOnly
          value={text.position ?? "middle"}
          onChange={(v) => patch({ position: v === "middle" ? undefined : v })}
          options={[
            { id: "top", label: t`Top`, icon: <AlignVerticalJustifyStart className="w-3.5 h-3.5" /> },
            { id: "middle", label: t`Middle`, icon: <AlignVerticalJustifyCenter className="w-3.5 h-3.5" /> },
            { id: "bottom", label: t`Bottom`, icon: <AlignVerticalJustifyEnd className="w-3.5 h-3.5" /> },
          ]}
        />
      </Row>
      {text.position && text.position !== "middle" && (
        <Row label={text.position === "top" ? t`Distance from top` : t`Distance from bottom`}>
          <IntInput value={text.margin_v ?? TEXT_DEFAULT_MARGIN} min={0} max={500} onCommit={(v) => patch({ margin_v: v })} />
        </Row>
      )}
      <Row label={t`Align`}>
        <Segmented<NonNullable<TextClip["align"]>>
          compact
          iconOnly
          value={text.align ?? "center"}
          onChange={(v) => patch({ align: v === "center" ? undefined : v })}
          options={[
            { id: "left", label: t`Left`, icon: <AlignLeft className="w-3.5 h-3.5" /> },
            { id: "center", label: t`Centre`, icon: <AlignCenter className="w-3.5 h-3.5" /> },
            { id: "right", label: t`Right`, icon: <AlignRight className="w-3.5 h-3.5" /> },
          ]}
        />
      </Row>
      {text.align && text.align !== "center" && (
        <Row label={text.align === "left" ? t`Distance from left` : t`Distance from right`}>
          <IntInput value={text.margin_h ?? TEXT_DEFAULT_MARGIN} min={0} max={900} onCommit={(v) => patch({ margin_h: v })} />
        </Row>
      )}
      {(peers.length > 0 || text.kind === "place") && (
        <>
          <button type="button" className={iconButton} onClick={applyToAll}>
            {text.kind === "place" ? <Trans>Apply to all place names</Trans> : <Trans>Apply to all titles like this</Trans>}
          </button>
          <p className="text-[11px] text-zinc-400">
            {text.kind === "place"
              ? t`Copies position and both lines' animation and style. Place names made later use it too.`
              : t`Copies position and both lines' animation and style; the words stay.`}
          </p>
        </>
      )}
    </Section>
  );
}

export function Inspector(p: InspectorProps) {
  const { timeline, selection, commit } = p;
  const { placed } = useMemo(() => layout(timeline), [timeline]);
  const cues = useMemo(() => placedCues(timeline, placed), [timeline, placed]);

  const seg = selection?.type === "segment" ? timeline.segments.find((s) => s.id === selection.id) : undefined;
  const pickedCues = selectedCueIds(selection);
  const cue = selection?.type === "cue" && pickedCues.length === 1 ? cues.find((c) => c.id === selection.id) : undefined;
  const text = selection?.type === "text" ? placedTexts(timeline, placed).find((x) => x.id === selection.id) : undefined;
  const patchText = (patch: Partial<TextClip>) =>
    text && commit({ ...timeline, texts: timeline.texts.map((x) => (x.id === text.id ? { ...x, ...patch } : x)) });

  const patchSegment = (patch: Partial<Segment>) =>
    seg && commit({ ...timeline, segments: timeline.segments.map((s) => (s.id === seg.id ? { ...s, ...patch } : s)) });

  const patchCue = (patchFn: (c: SubtitleCue) => SubtitleCue) =>
    cue && commit({ ...timeline, subtitles: timeline.subtitles.map((c) => (c.id === cue.id ? patchFn(c) : c)) });

  if (seg) {
    return (
      <div className="overflow-y-auto custom-scrollbar">
        <Section title={t`Clip`}>
          <input
            defaultValue={seg.label}
            key={seg.id}
            onBlur={(e) => e.target.value.trim() && e.target.value !== seg.label && patchSegment({ label: e.target.value.trim() })}
            className={`${input} tabular-nums`}
          />
        </Section>
        <Section title={t`Trim`}>
          <Row label={startLabel()}>
            <TimeField value={seg.trimIn} min={0} max={seg.trimOut - MIN_SEGMENT} onCommit={(v) => patchSegment({ trimIn: v })} />
          </Row>
          <Row label={endLabel()}>
            <TimeField value={seg.trimOut} min={seg.trimIn + MIN_SEGMENT} max={seg.videoDuration} onCommit={(v) => patchSegment({ trimOut: v })} />
          </Row>
          <button type="button" className={iconButton} disabled={seg.trimIn === 0 && seg.trimOut === seg.videoDuration} onClick={() => patchSegment({ trimIn: 0, trimOut: seg.videoDuration })}>
            <Trans>Reset trim</Trans>
          </button>
        </Section>
        {seg.audio && (
          <Section title={t`Narration`}>
            <Row label={t`Linked to clip`}>
              <Switch
                checked={!isUnlinked(seg)}
                onChange={(on) => commit(on ? linkAudio(timeline, seg.id) : unlinkAudio(timeline, seg.id))}
                label={t`Linked to clip`}
              />
            </Row>
            {isUnlinked(seg) ? (
              <Row label={t`Starts at`}>
                <TimeField value={seg.audioStart!} min={0} onCommit={(v) => patchSegment({ audioStart: v })} />
              </Row>
            ) : (
              <Row label={t`Starts after`}>
                <TimeField value={seg.audioOffset} min={0} max={60} onCommit={(v) => patchSegment({ audioOffset: v })} />
              </Row>
            )}
            <Row label={t`Volume`}>
              <Slider label={t`Volume`} format={percent} value={seg.volume} min={0} max={1.5} step={0.05} onCommit={(v) => patchSegment({ volume: v })} />
            </Row>
            <Row label={t`Mute`}>
              <Switch checked={seg.muted} onChange={(v) => patchSegment({ muted: v })} label={t`Mute narration`} />
            </Row>
            <button type="button" className={iconButton} onClick={() => patchSegment({ audio: undefined, audioDuration: undefined, audioOffset: 0, audioStart: undefined })}>
              <Trans>Remove narration</Trans>
            </button>
          </Section>
        )}
        {seg.extraAudio && (
          <Section title={t`Original sound`}>
            <Row label={t`Volume`}>
              <Slider label={t`Original sound volume`} format={percent} value={seg.extraVolume ?? DEFAULT_EXTRA_VOLUME} min={0} max={1} step={0.05} onCommit={(v) => patchSegment({ extraVolume: v })} />
            </Row>
            <p className="text-[11px] text-zinc-400">
              <Trans>The sound of your own video, mixed under the narration.</Trans>
            </p>
          </Section>
        )}
        <Section title={t`Transition`}>
          <Row label={t`Fade into next`}>
            <Slider label={t`Fade into next`} format={(v) => `${v.toFixed(1)} ${unitLabel("sec")}`} value={seg.fadeIntoNext} min={0} max={2} step={0.1} onCommit={(v) => patchSegment({ fadeIntoNext: +v.toFixed(1) })} />
          </Row>
          <p className="text-[11px] text-zinc-400">{seg.fadeIntoNext > 0 ? t`${seg.fadeIntoNext.toFixed(1)} s dissolve` : t`Hard cut`}</p>
        </Section>
        <div className="flex items-center gap-1 px-3 py-3">
          <button type="button" className={iconButton} onClick={() => p.onDuplicate(seg.id)}>
            <Copy className="w-3.5 h-3.5" /> <Trans>Duplicate</Trans>
          </button>
          <button type="button" className={`${iconButton} text-red-500 dark:text-red-400`} onClick={() => p.onRemoveSegment(seg.id)}>
            <Trash2 className="w-3.5 h-3.5" /> <Trans>Remove</Trans>
          </button>
        </div>
      </div>
    );
  }

  if (text) {
    const paired = !!text.title.text.trim() && !!text.subtitle.text.trim();
    const move = (g0: number, g1: number) => {
      const next = anchorCue(timeline, text, g0, g1, true);
      patchText({ segmentId: next.segmentId, start: next.start, end: next.end });
    };
    return (
      <div className="overflow-y-auto custom-scrollbar">
        <Section title={t`Timing`}>
          <Row label={startLabel()}>
            <TimeField value={text.globalStart} min={0} max={text.globalEnd - MIN_CUE} onCommit={(v) => move(v, text.globalEnd)} />
          </Row>
          <Row label={endLabel()}>
            <TimeField value={text.globalEnd} min={text.globalStart + MIN_CUE} onCommit={(v) => move(text.globalStart, v)} />
          </Row>
        </Section>
        <TextLookSection text={text} timeline={timeline} commit={commit} />
        {(text.kind === "intro" || text.kicker) && (
          <TextLineSection
            title={t`Location line`}
            line={text.kicker ?? { text: "" }}
            defaults={DEFAULT_TEXT_KICKER_STYLE}
            motion={lineMotion("kicker", text.kicker?.animation, text.kicker?.delay, text.animation, text.globalEnd - text.globalStart, paired)}
            onChange={(kicker) => patchText({ kicker })}
          />
        )}
        <TextLineSection
          title={t`Title`}
          line={text.title}
          defaults={DEFAULT_TEXT_TITLE_STYLE}
          motion={lineMotion("title", text.title.animation, text.title.delay, text.animation, text.globalEnd - text.globalStart, paired)}
          onChange={(title) => patchText({ title })}
        />
        <TextLineSection
          title={t`Subtitle`}
          line={text.subtitle}
          defaults={DEFAULT_TEXT_SUBTITLE_STYLE}
          motion={lineMotion("subtitle", text.subtitle.animation, text.subtitle.delay, text.animation, text.globalEnd - text.globalStart, paired)}
          onChange={(subtitle) => patchText({ subtitle })}
        />
        <div className="flex items-center gap-1 px-3 py-3">
          <button
            type="button"
            className={`${iconButton} text-red-500 dark:text-red-400`}
            onClick={() => {
              commit({ ...timeline, texts: timeline.texts.filter((x) => x.id !== text.id) });
              p.onSelect(null);
            }}
          >
            <Trash2 className="w-3.5 h-3.5" /> <Trans>Delete</Trans>
          </button>
        </div>
      </div>
    );
  }

  if (pickedCues.length > 1) return <MultiCueSection ids={pickedCues} timeline={timeline} commit={commit} onRemove={p.onRemoveCues} />;

  if (cue) {
    const move = (g0: number, g1: number) => patchCue((c) => anchorCue(timeline, c, g0, g1, true));
    return (
      <div className="overflow-y-auto custom-scrollbar">
        <Section title={t`Subtitle`}>
          <TextBlock value={cue.text} onCommit={(text) => patchCue((c) => ({ ...c, text }))} />
        </Section>
        <Section title={t`Timing`}>
          <Row label={startLabel()}>
            <TimeField value={cue.globalStart} min={0} max={cue.globalEnd - MIN_CUE} onCommit={(v) => move(v, cue.globalEnd)} />
          </Row>
          <Row label={endLabel()}>
            <TimeField value={cue.globalEnd} min={cue.globalStart + MIN_CUE} onCommit={(v) => move(cue.globalStart, v)} />
          </Row>
        </Section>
        <CueStyleSection cue={cue} timeline={timeline} commit={commit} />
        <div className="flex items-center gap-1 px-3 py-3">
          <button
            type="button"
            className={`${iconButton} text-red-500 dark:text-red-400`}
            onClick={() => {
              commit({ ...timeline, subtitles: timeline.subtitles.filter((c) => c.id !== cue.id) });
              p.onSelect(null);
            }}
          >
            <Trash2 className="w-3.5 h-3.5" /> <Trans>Delete</Trans>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col min-h-0 overflow-y-auto custom-scrollbar">
      <Section title={t`Subtitles`}>
        {cues.length > 0 && (
          <div className="flex items-center gap-1 -mx-1">
            <button type="button" className={iconButton} onClick={p.onSaveSrt}>
              <Download className="w-3.5 h-3.5" /> <Trans>Save .srt</Trans>
            </button>
            <button type="button" className={`${iconButton} text-red-500 dark:text-red-400`} onClick={() => commit({ ...timeline, subtitles: [] })}>
              <Trash2 className="w-3.5 h-3.5" /> <Trans>Clear all</Trans>
            </button>
          </div>
        )}
        <CueList cues={cues} onPick={(id) => p.onSelect({ type: "cue", id })} />
      </Section>
      <Section title={t`Music`}>
        {timeline.music ? (
          <>
            <div className="flex items-center gap-2 text-[12px] text-zinc-700 dark:text-zinc-300">
              <Music className="w-3.5 h-3.5 shrink-0 text-violet-500" />
              <span className="truncate flex-1">{timeline.music.label}</span>
              <button type="button" aria-label={t`Remove music`} onClick={() => commit({ ...timeline, music: null })} className="text-zinc-400 hover:text-red-500 transition-colors">
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
            <Row label={t`Volume`}>
              <Slider label={t`Music volume`} format={percent} value={timeline.music.volume} min={0} max={1} step={0.05} onCommit={(v) => commit({ ...timeline, music: { ...timeline.music!, volume: v } })} />
            </Row>
          </>
        ) : (
          <p className="text-[12px] text-zinc-400">{t`No music. Use Music in the toolbar.`}</p>
        )}
      </Section>
    </div>
  );
}
