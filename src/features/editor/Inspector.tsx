import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Copy, Download, Music, Trash2 } from "../../components/ui/icons";
import { StepButtons } from "../../components/ui/StepButtons";
import { Switch } from "../../components/ui/Switch";
import { CaptionRow, CaptionStyleFields, IntInput } from "../../components/ui/CaptionStyleFields";
import { useWorkspace } from "../../hooks/useWorkspace";
import type { TextStyle } from "../../types";
import {
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
  layout,
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
} from "./model";
import { formatTime, player, usePlayerTime } from "./player";
import type { Selection } from "./TimelinePane";

interface InspectorProps {
  timeline: TimelineData;
  selection: Selection;
  onSelect: (s: Selection) => void;
  commit: (t: TimelineData) => void;
  onDuplicate: (id: string) => void;
  onRemoveSegment: (id: string) => void;
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

function NumberField({ value, onCommit, min, max, step = 0.1 }: { value: number; onCommit: (v: number) => void; min?: number; max?: number; step?: number }) {
  const [text, setText] = useState(value.toFixed(2));
  useEffect(() => setText(value.toFixed(2)), [value]);
  const done = () => {
    const parsed = parseFloat(text);
    if (!Number.isFinite(parsed)) return setText(value.toFixed(2));
    const clamped = Math.min(max ?? Infinity, Math.max(min ?? -Infinity, parsed));
    setText(clamped.toFixed(2));
    if (Math.abs(clamped - value) > 0.001) onCommit(clamped);
  };
  const stepBy = (dir: 1 | -1) => {
    const base = parseFloat(text);
    const next = +Math.min(max ?? Infinity, Math.max(min ?? -Infinity, (Number.isFinite(base) ? base : value) + dir * step)).toFixed(2);
    setText(next.toFixed(2));
    if (Math.abs(next - value) > 0.001) onCommit(next);
  };
  return (
    <div className="relative">
      <input
        type="number"
        step={step}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={done}
        onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
        className={`${input} pr-6`}
      />
      <StepButtons onStep={stepBy} />
    </div>
  );
}

function Slider({ value, onCommit, min, max, step }: { value: number; onCommit: (v: number) => void; min: number; max: number; step: number }) {
  const [live, setLive] = useState(value);
  useEffect(() => setLive(value), [value]);
  return (
    <input
      type="range"
      min={min}
      max={max}
      step={step}
      value={live}
      onChange={(e) => setLive(parseFloat(e.target.value))}
      onPointerUp={() => live !== value && onCommit(live)}
      onKeyUp={() => live !== value && onCommit(live)}
      className="w-full accent-navi"
    />
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

const styleRow: CaptionRow = (key, label, control, hint) => (
  <div key={key}>
    <div className="flex items-center justify-between gap-3">
      <span className="text-[12px] text-zinc-600 dark:text-zinc-300 min-w-0">{label}</span>
      <div className="w-32 shrink-0 flex justify-end">{control}</div>
    </div>
    {hint && <p className="mt-0.5 text-[11px] text-zinc-400">{hint}</p>}
  </div>
);

/** The shared look (project caption_style, also in Settings) every subtitle starts from. */
function DefaultSubtitleStyleSection() {
  const { settings, updateSettings, setIsDirty } = useWorkspace();
  const save = (caption_style: TextStyle | undefined) => {
    updateSettings({ caption_style });
    setIsDirty(true);
  };
  return (
    <Section title={t`Default subtitle style`}>
      <p className="text-[11px] text-zinc-400">{t`Subtitles you have styled one by one keep their own style.`}</p>
      <CaptionStyleFields
        style={resolveCaptionStyle(settings)}
        onChange={(patch) => save({ ...(settings.caption_style ?? {}), ...patch })}
        row={styleRow}
      />
      {settings.caption_style && (
        <button type="button" className={iconButton} onClick={() => save(undefined)}>
          <Trans>Reset to default</Trans>
        </button>
      )}
    </Section>
  );
}

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
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => text !== line.text && onChange({ ...line, text })}
        onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
        placeholder={t`Leave empty to hide this line`}
        className={input}
      />
      <Row label={t`Animation`}>
        <select
          value={motion.animation}
          onChange={(e) => onChange({ ...line, animation: e.target.value as LineAnimation })}
          className={`${input} cursor-pointer`}
        >
          <option value="pop">{t`Pop in`}</option>
          <option value="rise">{t`Rise`}</option>
          <option value="fade">{t`Fade`}</option>
          <option value="none">{t`None`}</option>
        </select>
      </Row>
      <Row label={t`Appears after`}>
        <NumberField value={motion.delay} min={0} max={60} onCommit={(v) => onChange({ ...line, delay: +v.toFixed(2) })} />
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
        <select
          value={text.position ?? "middle"}
          onChange={(e) => patch({ position: e.target.value === "middle" ? undefined : (e.target.value as TextClip["position"]) })}
          className={`${input} cursor-pointer`}
        >
          <option value="top">{t`Top`}</option>
          <option value="middle">{t`Middle`}</option>
          <option value="bottom">{t`Bottom`}</option>
        </select>
      </Row>
      {text.position && text.position !== "middle" && (
        <Row label={text.position === "top" ? t`Distance from top` : t`Distance from bottom`}>
          <IntInput value={text.margin_v ?? TEXT_DEFAULT_MARGIN} min={0} max={500} onCommit={(v) => patch({ margin_v: v })} />
        </Row>
      )}
      <Row label={t`Align`}>
        <select
          value={text.align ?? "center"}
          onChange={(e) => patch({ align: e.target.value === "center" ? undefined : (e.target.value as TextClip["align"]) })}
          className={`${input} cursor-pointer`}
        >
          <option value="left">{t`Left`}</option>
          <option value="center">{t`Centre`}</option>
          <option value="right">{t`Right`}</option>
        </select>
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
  const cue = selection?.type === "cue" ? cues.find((c) => c.id === selection.id) : undefined;
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
          <Row label={t`Start`}>
            <NumberField value={seg.trimIn} min={0} max={seg.trimOut - MIN_SEGMENT} onCommit={(v) => patchSegment({ trimIn: v })} />
          </Row>
          <Row label={t`End`}>
            <NumberField value={seg.trimOut} min={seg.trimIn + MIN_SEGMENT} max={seg.videoDuration} onCommit={(v) => patchSegment({ trimOut: v })} />
          </Row>
          <button type="button" className={iconButton} disabled={seg.trimIn === 0 && seg.trimOut === seg.videoDuration} onClick={() => patchSegment({ trimIn: 0, trimOut: seg.videoDuration })}>
            <Trans>Reset trim</Trans>
          </button>
        </Section>
        {seg.audio && (
          <Section title={t`Narration`}>
            <Row label={t`Starts after`}>
              <NumberField value={seg.audioOffset} min={0} max={60} onCommit={(v) => patchSegment({ audioOffset: v })} />
            </Row>
            <Row label={t`Volume`}>
              <Slider value={seg.volume} min={0} max={1.5} step={0.05} onCommit={(v) => patchSegment({ volume: v })} />
            </Row>
            <Row label={t`Mute`}>
              <Switch checked={seg.muted} onChange={(v) => patchSegment({ muted: v })} label={t`Mute narration`} />
            </Row>
            <button type="button" className={iconButton} onClick={() => patchSegment({ audio: undefined, audioDuration: undefined, audioOffset: 0 })}>
              <Trans>Remove narration</Trans>
            </button>
          </Section>
        )}
        {seg.extraAudio && (
          <Section title={t`Original sound`}>
            <Row label={t`Volume`}>
              <Slider value={seg.extraVolume ?? DEFAULT_EXTRA_VOLUME} min={0} max={1} step={0.05} onCommit={(v) => patchSegment({ extraVolume: v })} />
            </Row>
            <p className="text-[11px] text-zinc-400">
              <Trans>The sound of your own video, mixed under the narration.</Trans>
            </p>
          </Section>
        )}
        <Section title={t`Transition`}>
          <Row label={t`Fade into next`}>
            <Slider value={seg.fadeIntoNext} min={0} max={2} step={0.1} onCommit={(v) => patchSegment({ fadeIntoNext: +v.toFixed(1) })} />
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
          <Row label={t`Start`}>
            <NumberField value={text.globalStart} min={0} max={text.globalEnd - MIN_CUE} onCommit={(v) => move(v, text.globalEnd)} />
          </Row>
          <Row label={t`End`}>
            <NumberField value={text.globalEnd} min={text.globalStart + MIN_CUE} onCommit={(v) => move(text.globalStart, v)} />
          </Row>
        </Section>
        <TextLookSection text={text} timeline={timeline} commit={commit} />
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

  if (cue) {
    const move = (g0: number, g1: number) => patchCue((c) => anchorCue(timeline, c, g0, g1, true));
    return (
      <div className="overflow-y-auto custom-scrollbar">
        <Section title={t`Subtitle`}>
          <TextBlock value={cue.text} onCommit={(text) => patchCue((c) => ({ ...c, text }))} />
        </Section>
        <Section title={t`Timing`}>
          <Row label={t`Start`}>
            <NumberField value={cue.globalStart} min={0} max={cue.globalEnd - MIN_CUE} onCommit={(v) => move(v, cue.globalEnd)} />
          </Row>
          <Row label={t`End`}>
            <NumberField value={cue.globalEnd} min={cue.globalStart + MIN_CUE} onCommit={(v) => move(cue.globalStart, v)} />
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
      <DefaultSubtitleStyleSection />
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
              <Slider value={timeline.music.volume} min={0} max={1} step={0.05} onCommit={(v) => commit({ ...timeline, music: { ...timeline.music!, volume: v } })} />
            </Row>
          </>
        ) : (
          <p className="text-[12px] text-zinc-400">{t`No music. Use Music in the toolbar.`}</p>
        )}
      </Section>
    </div>
  );
}
