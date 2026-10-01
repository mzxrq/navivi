import { ReactNode, useEffect, useMemo, useState } from "react";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Copy, Download, Music, Trash2 } from "../../components/ui/icons";
import { Switch } from "../../components/ui/Switch";
import { anchorCue, DEFAULT_EXTRA_VOLUME, layout, MIN_CUE, MIN_SEGMENT, placedCues, Segment, SubtitleCue, TimelineData } from "./model";
import { formatTime, player } from "./player";
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
  return (
    <input
      type="number"
      step={step}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={done}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
      className={input}
    />
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

export function Inspector(p: InspectorProps) {
  const { timeline, selection, commit } = p;
  const { placed } = useMemo(() => layout(timeline), [timeline]);
  const cues = useMemo(() => placedCues(timeline, placed), [timeline, placed]);

  const seg = selection?.type === "segment" ? timeline.segments.find((s) => s.id === selection.id) : undefined;
  const cue = selection?.type === "cue" ? cues.find((c) => c.id === selection.id) : undefined;

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
        <Row label={t`Burn into video`}>
          <Switch checked={timeline.burnSubtitles} onChange={(v) => commit({ ...timeline, burnSubtitles: v })} label={t`Burn subtitles into the video`} />
        </Row>
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
        <ul className="max-h-64 overflow-y-auto custom-scrollbar -mx-2">
          {cues.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => {
                  p.onSelect({ type: "cue", id: c.id });
                  player.set({ playing: false, time: c.globalStart });
                }}
                className="w-full flex gap-2 px-2 py-1.5 rounded-md text-left hover:bg-zinc-100 dark:hover:bg-white/5 transition-colors"
              >
                <span className="shrink-0 w-11 text-[11px] tabular-nums text-zinc-400 pt-px">{formatTime(c.globalStart, false)}</span>
                <span className="text-[12px] leading-snug text-zinc-700 dark:text-zinc-300 line-clamp-2">{c.text}</span>
              </button>
            </li>
          ))}
          {!cues.length && <li className="px-2 text-[12px] text-zinc-400">{t`No subtitles yet. Use Subtitles in the toolbar.`}</li>}
        </ul>
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
