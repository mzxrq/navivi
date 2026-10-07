import type { ProjectSettings, TextStyle } from "../../types";

export type SegmentKind = "intro" | "overview" | "route" | "attraction" | "outro" | "custom";

export interface Segment {
  id: string;
  label: string;
  kind: SegmentKind;
  video: string;
  videoDuration: number;
  trimIn: number;
  trimOut: number;
  audio?: string;
  audioDuration?: number;
  audioOffset: number;
  // Set when the narration is unlinked: it plays at this timeline time, whatever the clips do.
  audioStart?: number;
  // The clip's length when its narration was unlinked, so unlinking doesn't shorten it.
  heldLength?: number;
  subtitleFile?: string;
  extraAudio?: string;
  extraVolume?: number;
  volume: number;
  muted: boolean;
  fadeIntoNext: number;
}

export interface SubtitleCue {
  id: string;
  segmentId: string;
  start: number;
  end: number;
  text: string;
  // Overrides on top of the project's caption_style; absent = the shared style.
  style?: TextStyle;
}

// A title + subtitle pair on the text track (e.g. the intro's), each line styled on its own.
export type LineAnimation = "pop" | "rise" | "fade" | "none";

export interface TextLine {
  text: string;
  style?: TextStyle;
  // How the line comes in and goes out, and how many seconds after the item
  // starts it appears (it leaves as long before the end). Absent = the intro's.
  animation?: LineAnimation;
  delay?: number;
}

export interface TextClip {
  id: string;
  segmentId: string;
  start: number;
  end: number;
  title: TextLine;
  subtitle: TextLine;
  kicker?: TextLine; // small line above the title (the intro's location)
  // Where the block sits; absent = centred.
  position?: "top" | "middle" | "bottom";
  margin_v?: number; // px from that edge (1080p frame)
  align?: "left" | "center" | "right"; // absent = centred
  margin_h?: number; // px from the left/right edge
  animation?: TextAnimation; // absent = "pop"
  // What made it: the intro's title, an attraction's place name, or added by hand.
  kind?: "intro" | "place";
}

export type TextAnimation = "pop" | "fade" | "none";

// The look a text item can share with others of its kind ("Apply to all").
export const TEXT_LOOK_KEYS = ["position", "margin_v", "align", "margin_h", "animation"] as const;

export interface MusicBed {
  path: string;
  label: string;
  duration?: number;
  volume: number;
  credit?: string;
}

export interface TimelineData {
  segments: Segment[];
  subtitles: SubtitleCue[];
  texts: TextClip[];
  music: MusicBed | null;
}

export const EDITOR_VERSION = 1;
export const MIN_SEGMENT = 0.5;
export const MIN_CUE = 0.3;
export const AUTO_FADE_SECONDS = 0.8;
export const DEFAULT_EXTRA_VOLUME = 0.5;

export const emptyTimeline = (): TimelineData => ({
  segments: [],
  subtitles: [],
  texts: [],
  music: null,
});

export const newId = () => crypto.randomUUID();

export const trimmedLength = (s: Segment) => Math.max(MIN_SEGMENT, s.trimOut - s.trimIn);

export const isUnlinked = (s: Segment) => !!s.audio && s.audioStart !== undefined;

export const segmentLength = (s: Segment) =>
  Math.max(trimmedLength(s), s.audio && !isUnlinked(s) ? s.audioOffset + (s.audioDuration ?? 0) : 0, s.heldLength ?? 0);

export interface PlacedSegment {
  seg: Segment;
  start: number;
  length: number;
}

export function layout(timeline: TimelineData): { placed: PlacedSegment[]; total: number } {
  let t = 0;
  const placed = timeline.segments.map((seg) => {
    const length = segmentLength(seg);
    const row = { seg, start: t, length };
    t += length;
    return row;
  });
  return { placed, total: t };
}

/** Seconds segment i dissolves in from i-1, as the export's _crossfade_pair applies it:
 * capped at half of segment i, skipped under 0.1s, and a segment joined to the one before
 * by a fade never fades into the next. */
export function fadeIns(placed: PlacedSegment[]): number[] {
  const fades = placed.map(() => 0);
  for (let i = 1; i < placed.length; i++) {
    if (fades[i - 1] > 0) continue;
    const d = Math.min(placed[i - 1].seg.fadeIntoNext, placed[i].length / 2);
    if (d >= 0.1) fades[i] = d;
  }
  return fades;
}

/** Where a clip's narration plays on the timeline. */
export const narrationStart = (p: PlacedSegment) => (isUnlinked(p.seg) ? p.seg.audioStart! : p.start + p.seg.audioOffset);

/** Frees a clip's narration where it is now; the clip keeps its length. */
export function unlinkAudio(timeline: TimelineData, id: string): TimelineData {
  const p = layout(timeline).placed.find((x) => x.seg.id === id);
  if (!p?.seg.audio || isUnlinked(p.seg)) return timeline;
  const patch = { audioStart: narrationStart(p), heldLength: p.length };
  return { ...timeline, segments: timeline.segments.map((s) => (s.id === id ? { ...s, ...patch } : s)) };
}

/** Ties a free narration back to its clip, at the same offset into the clip (never before it). */
export function linkAudio(timeline: TimelineData, id: string): TimelineData {
  const p = layout(timeline).placed.find((x) => x.seg.id === id);
  if (!p || !isUnlinked(p.seg)) return timeline;
  const { audioStart, heldLength: _held, ...rest } = p.seg;
  const linked = { ...rest, audioOffset: Math.max(0, +(audioStart! - p.start).toFixed(2)) };
  return { ...timeline, segments: timeline.segments.map((s) => (s.id === id ? linked : s)) };
}

export interface PlacedCue extends SubtitleCue {
  globalStart: number;
  globalEnd: number;
}

export interface PlacedText extends TextClip {
  globalStart: number;
  globalEnd: number;
}

export function placedTexts(timeline: TimelineData, placed: PlacedSegment[]): PlacedText[] {
  const bySegment = new Map(placed.map((p) => [p.seg.id, p]));
  return (timeline.texts ?? [])
    .map((x) => {
      const p = bySegment.get(x.segmentId);
      if (!p) return null;
      return { ...x, globalStart: p.start + x.start, globalEnd: p.start + Math.min(x.end, p.length) };
    })
    .filter((x): x is PlacedText => !!x)
    .sort((a, b) => a.globalStart - b.globalStart);
}

export function placedCues(timeline: TimelineData, placed: PlacedSegment[]): PlacedCue[] {
  const bySegment = new Map(placed.map((p) => [p.seg.id, p]));
  return timeline.subtitles
    .map((c) => {
      const p = bySegment.get(c.segmentId);
      if (!p) return null;
      return { ...c, globalStart: p.start + c.start, globalEnd: p.start + Math.min(c.end, p.length) };
    })
    .filter((c): c is PlacedCue => !!c)
    .sort((a, b) => a.globalStart - b.globalStart);
}

export function segmentAt(placed: PlacedSegment[], t: number): PlacedSegment | null {
  if (!placed.length) return null;
  for (const p of placed) if (t < p.start + p.length) return p;
  return placed[placed.length - 1];
}

export function kindFromName(name: string): SegmentKind {
  const n = name.toLowerCase();
  if (n.includes("intro")) return "intro";
  if (n.includes("outro")) return "outro";
  if (n.includes("overview")) return "overview";
  if (n.includes("attraction")) return "attraction";
  if (n.includes("waypoint")) return "route";
  return "custom";
}

const baseName = (p: string) => p.split(/[\\/]/).pop() ?? p;
const stem = (p: string) => baseName(p).replace(/\.[^.]+$/, "");

export function autoOrderKey(seg: Segment): [number, number] {
  const name = baseName(seg.video).replace(/^\d+_/, "");
  const n = Number(/_(\d+)(?:_|\.)/.exec(name)?.[1] ?? 0);
  switch (seg.kind) {
    case "intro":
      return [-2, 0];
    case "overview":
      return [-1, 0];
    case "attraction":
      return [n, 0];
    case "route":
      return [n - 1, 1];
    case "outro":
      return [1e6, 0];
    default:
      return [1e5, 0];
  }
}

// Intro, overview, then each stop's attraction followed by the leg to the next stop, outro last.
export function autoArrange(timeline: TimelineData): TimelineData {
  const sorted = timeline.segments
    .map((s, i) => ({ s, i, k: autoOrderKey(s) }))
    .sort((a, b) => a.k[0] - b.k[0] || a.k[1] - b.k[1] || a.i - b.i)
    .map(({ s }) => ({ ...s, fadeIntoNext: 0 }));
  for (let i = 0; i < sorted.length - 1; i++) {
    if (sorted[i].kind === "route" && sorted[i + 1].kind === "attraction") {
      sorted[i].fadeIntoNext = AUTO_FADE_SECONDS;
    }
  }
  return { ...timeline, segments: sorted };
}

// ── SRT ──────────────────────────────────────────────────────────────────────

const TIME = /(\d+):(\d{2}):(\d{2})[,.](\d{1,3})/;

const toSeconds = (m: RegExpExecArray) =>
  Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]) + Number(m[4].padEnd(3, "0")) / 1000;

export interface TimedText {
  start: number;
  end: number;
  text: string;
}

export function parseTimedSrt(raw: string): TimedText[] {
  const blocks = raw.replace(/^﻿/, "").replace(/\r/g, "").split(/\n{2,}/);
  const out: TimedText[] = [];
  for (const block of blocks) {
    const lines = block.split("\n").filter((l) => l.trim());
    const at = lines.findIndex((l) => l.includes("-->"));
    if (at < 0) continue;
    const [a, b] = lines[at].split("-->");
    const s = TIME.exec(a);
    const e = TIME.exec(b);
    const text = lines.slice(at + 1).join("\n").trim();
    if (s && e && text) out.push({ start: toSeconds(s), end: toSeconds(e), text });
  }
  return out;
}

// An SRT without timestamps (or any plain text): one block per entry/paragraph, else per line.
export function parsePlainBlocks(raw: string): string[] {
  const text = raw.replace(/^﻿/, "").replace(/\r/g, "").trim();
  if (!text) return [];
  const paragraphs = text
    .split(/\n{2,}/)
    .map((p) => p.split("\n").filter((l) => !/^\d+$/.test(l.trim())).join(" ").trim())
    .filter(Boolean);
  if (paragraphs.length > 1) return paragraphs;
  return text.split("\n").map((l) => l.trim()).filter((l) => l && !/^\d+$/.test(l));
}

export function formatSrtTime(seconds: number): string {
  const ms = Math.round(Math.max(0, seconds) * 1000);
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  const pad = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${pad(h)}:${pad(m)}:${pad(s)},${pad(ms % 1000, 3)}`;
}

export function cuesToSrt(cues: TimedText[]): string {
  return [...cues]
    .sort((a, b) => a.start - b.start)
    .map((c, i) => `${i + 1}\n${formatSrtTime(c.start)} --> ${formatSrtTime(c.end)}\n${c.text.trim()}\n`)
    .join("\n");
}

// ── Placing subtitles ────────────────────────────────────────────────────────

function clampToSegment(p: PlacedSegment, globalStart: number, globalEnd: number): { start: number; end: number } {
  const start = Math.min(Math.max(0, globalStart - p.start), Math.max(0, p.length - MIN_CUE));
  const end = Math.min(p.length, Math.max(start + MIN_CUE, globalEnd - p.start));
  return { start, end };
}

// Places a cue (or text clip) at global times; it belongs to the clip under its middle unless `keepSegment` pins it.
export function anchorCue<T extends { segmentId: string; start: number; end: number }>(
  timeline: TimelineData,
  cue: T,
  globalStart: number,
  globalEnd: number,
  keepSegment = false,
): T {
  const { placed } = layout(timeline);
  const p = (keepSegment ? placed.find((x) => x.seg.id === cue.segmentId) : null) ?? segmentAt(placed, (globalStart + globalEnd) / 2);
  if (!p) return cue;
  return { ...cue, segmentId: p.seg.id, ...clampToSegment(p, globalStart, globalEnd) };
}

export function cuesFromTimed(timeline: TimelineData, timed: TimedText[]): SubtitleCue[] {
  const { placed } = layout(timeline);
  const out: SubtitleCue[] = [];
  for (const t of timed) {
    const p = segmentAt(placed, (t.start + t.end) / 2);
    if (!p) continue;
    out.push({ id: newId(), segmentId: p.seg.id, text: t.text, ...clampToSegment(p, t.start, t.end) });
  }
  return out;
}

// Spreads text blocks over the time the narration is speaking (else over the whole video), by length of text.
export function autoTimeBlocks(timeline: TimelineData, blocks: string[]): SubtitleCue[] {
  const { placed, total } = layout(timeline);
  if (!blocks.length || !placed.length || total <= 0) return [];

  const speaking = placed.filter((p) => p.seg.audio && !p.seg.muted);
  const spans = (speaking.length ? speaking : placed).map((p) => {
    const from = speaking.length ? narrationStart(p) : p.start;
    const to = speaking.length ? from + (p.seg.audioDuration ?? p.length) : p.start + p.length;
    return { p, from, to };
  });
  const spanTotal = spans.reduce((a, s) => a + (s.to - s.from), 0);
  const weights = blocks.map((b) => Math.max(1, b.replace(/\s/g, "").length));
  const weightTotal = weights.reduce((a, b) => a + b, 0);

  const out: SubtitleCue[] = [];
  let acc = 0;
  blocks.forEach((text, i) => {
    const v0 = (acc / weightTotal) * spanTotal;
    acc += weights[i];
    const v1 = (acc / weightTotal) * spanTotal;
    const mid = (v0 + v1) / 2;
    let offset = 0;
    for (let k = 0; k < spans.length; k++) {
      const span = spans[k];
      const len = span.to - span.from;
      if (mid <= offset + len || k === spans.length - 1) {
        const g0 = span.from + Math.max(0, v0 - offset);
        const g1 = span.from + Math.min(len, v1 - offset);
        out.push({
          id: newId(),
          segmentId: span.p.seg.id,
          text,
          ...clampToSegment(span.p, g0, Math.max(g1, g0 + MIN_CUE)),
        });
        break;
      }
      offset += len;
    }
  });
  return out;
}

// The pipeline's own per-narration .srt files (times are relative to the audio).
export function cuesFromSegmentFile(seg: Segment, timed: TimedText[]): SubtitleCue[] {
  const limit = segmentLength(seg);
  return timed
    .map((t) => ({
      id: newId(),
      segmentId: seg.id,
      text: t.text,
      start: Math.min(t.start + seg.audioOffset, Math.max(0, limit - MIN_CUE)),
      end: Math.min(limit, t.end + seg.audioOffset),
    }))
    .filter((c) => c.end - c.start >= 0.05);
}

// ── Timeline manifest (timeline.json) ────────────────────────────────────────

export interface ExportOptions {
  /** Output height in px. Unset (or 1080) keeps the size the clips already have. */
  height?: number;
  fps?: number;
  /** Burn the subtitles into the picture; unset burns them. */
  burnSubtitles?: boolean;
  saveSrt?: boolean;
}

export const EXPORT_HEIGHTS: Record<NonNullable<ProjectSettings["default_export_resolution"]>, number> = {
  "720p": 720,
  "1080p": 1080,
  "1440p": 1440,
  "4k": 2160,
};

export function exportOptionsFrom(settings: Partial<ProjectSettings>): ExportOptions {
  const fps = settings.export_fps ?? settings.fps;
  return {
    height: EXPORT_HEIGHTS[settings.default_export_resolution ?? "1080p"],
    fps: fps && fps >= 1 && fps <= 120 ? fps : undefined,
    burnSubtitles: settings.export_burn_subtitles,
    saveSrt: settings.export_save_srt,
  };
}

export function toManifest(projectName: string, timeline: TimelineData, captionStyle?: TextStyle, options: ExportOptions = {}) {
  const { placed, total } = layout(timeline);
  const cues = placedCues(timeline, placed).map((c) => ({
    start: c.globalStart,
    end: c.globalEnd,
    text: c.text,
    ...(c.style ? { style: c.style } : {}),
  }));
  return {
    project_name: projectName,
    total_duration_seconds: total,
    video_tracks: timeline.segments.map((s, i) => ({
      order: i,
      clip_name: s.label,
      file_path: s.video,
      // A free narration goes in unlinked_audio instead, at its own time.
      audio_path: isUnlinked(s) ? null : (s.audio ?? null),
      audio_offset: isUnlinked(s) ? 0 : s.audioOffset,
      subtitle_path: s.subtitleFile ?? null,
      extra_audio_path: s.extraAudio ?? null,
      extra_audio_volume: s.extraAudio ? (s.extraVolume ?? DEFAULT_EXTRA_VOLUME) : null,
      trim_in: s.trimIn,
      trim_out: s.trimOut < s.videoDuration - 0.01 ? s.trimOut : null,
      // The export makes each clip exactly as long as the preview plays it.
      duration: segmentLength(s),
      volume: s.volume,
      muted: s.muted,
      fade_into_next_seconds: s.fadeIntoNext,
    })),
    unlinked_audio: placed
      .filter((p) => isUnlinked(p.seg) && !p.seg.muted)
      .map((p) => ({ path: p.seg.audio!, start: p.seg.audioStart!, volume: p.seg.volume })),
    subtitles: cues,
    texts: placedTexts(timeline, placed).map((x) => ({
      start: x.globalStart,
      end: x.globalEnd,
      title: x.title,
      subtitle: x.subtitle,
      ...(x.kicker?.text ? { kicker: x.kicker } : {}),
      ...(x.position ? { position: x.position } : {}),
      ...(x.margin_v !== undefined ? { margin_v: x.margin_v } : {}),
      ...(x.align ? { align: x.align } : {}),
      ...(x.margin_h !== undefined ? { margin_h: x.margin_h } : {}),
      ...(x.animation ? { animation: x.animation } : {}),
      ...(x.kind ? { kind: x.kind } : {}),
    })),
    burn_subtitles: options.burnSubtitles ?? true,
    // Absent keys keep the export as it was: the clips' own size and 30 fps.
    ...(options.height && options.height !== 1080 ? { export_height: options.height } : {}),
    ...(options.fps ? { fps: options.fps } : {}),
    ...(options.saveSrt ? { save_srt: true } : {}),
    // Omitted: the export falls back to the project's saved settings.
    ...(captionStyle ? { caption_style: captionStyle } : {}),
    music: timeline.music ? { path: timeline.music.path, volume: timeline.music.volume } : null,
    editor: { version: EDITOR_VERSION, ...timeline },
  };
}

export function timelineFromEditorState(raw: any): TimelineData | null {
  const e = raw?.editor;
  if (!e || e.version !== EDITOR_VERSION || !Array.isArray(e.segments)) return null;
  return {
    segments: e.segments,
    subtitles: Array.isArray(e.subtitles) ? e.subtitles : [],
    texts: Array.isArray(e.texts) ? e.texts : [],
    music: e.music ?? null,
  };
}

// Reads the pipeline's (or the older editor's) timeline.json. `probe` returns a media file's length in seconds.
export async function timelineFromPipeline(
  raw: any,
  probe: (relPath: string, kind: "video" | "audio") => Promise<number>,
): Promise<TimelineData> {
  const tracks: any[] = Array.isArray(raw?.video_tracks) ? raw.video_tracks : [];
  const legacy: any[] = raw?.ui_state?.clips ?? [];
  const voices = legacy.filter((c) => c.type === "audio" && c.source);
  const startOf = new Map(legacy.map((c) => [c.id, c.startTime ?? 0]));

  const segments: Segment[] = [];
  const subtitles: SubtitleCue[] = [];
  const texts: TextClip[] = [];
  for (const t of tracks) {
    if (!t.file_path || t.type === "static_popup") continue;
    let audio: string | undefined = t.audio_path || undefined;
    if (!audio && t.clip_id && startOf.has(t.clip_id)) {
      audio = voices.find((v) => Math.abs((v.startTime ?? 0) - startOf.get(t.clip_id)) < 0.05)?.source;
    }
    const videoDuration = await probe(t.file_path, "video");
    const audioDuration = audio ? await probe(audio, "audio") : undefined;
    const label = t.clip_name || stem(t.file_path);
    segments.push({
      id: newId(),
      label,
      kind: kindFromName(label),
      video: t.file_path,
      videoDuration,
      trimIn: Number(t.trim_in) || 0,
      trimOut: Number(t.trim_out) || videoDuration,
      audio,
      audioDuration,
      audioOffset: Number(t.audio_offset) || 0,
      subtitleFile: t.subtitle_path || undefined,
      extraAudio: t.extra_audio_path || undefined,
      extraVolume: typeof t.extra_audio_volume === "number" ? t.extra_audio_volume : undefined,
      volume: typeof t.volume === "number" ? t.volume : 1,
      muted: !!t.muted,
      fadeIntoNext: Number(t.fade_into_next_seconds) || 0,
    });
    // The pipeline's cues, already relative to the clip.
    const seg = segments[segments.length - 1];
    const limit = segmentLength(seg);
    for (const c of Array.isArray(t.subtitles) ? t.subtitles : []) {
      const start = Math.min(Number(c.start) || 0, Math.max(0, limit - MIN_CUE));
      const end = Math.min(limit, Number(c.end) || 0);
      if (c.text && end - start >= 0.05) subtitles.push({ id: newId(), segmentId: seg.id, start, end, text: String(c.text) });
    }
    // Text-track items (the intro's title + subtitle), relative to the clip like the cues.
    const line = (l: any): TextLine => ({
      text: String(l?.text ?? ""),
      ...(l?.style ? { style: l.style } : {}),
      ...(l?.animation ? { animation: l.animation } : {}),
      ...(typeof l?.delay === "number" ? { delay: l.delay } : {}),
    });
    for (const x of Array.isArray(t.texts) ? t.texts : []) {
      const start = Math.min(Number(x.start) || 0, Math.max(0, limit - MIN_CUE));
      const end = Math.min(limit, Number(x.end) || limit);
      if (end - start >= 0.05)
        texts.push({
          id: newId(),
          segmentId: seg.id,
          start,
          end,
          title: line(x.title),
          subtitle: line(x.subtitle),
          ...(x.kicker?.text ? { kicker: line(x.kicker) } : {}),
          ...(x.position ? { position: x.position } : {}),
          ...(typeof x.margin_v === "number" ? { margin_v: x.margin_v } : {}),
          ...(x.align ? { align: x.align } : {}),
          ...(typeof x.margin_h === "number" ? { margin_h: x.margin_h } : {}),
          ...(x.animation ? { animation: x.animation } : {}),
          ...(x.kind ? { kind: x.kind } : {}),
        });
    }
  }
  return { ...emptyTimeline(), segments, subtitles, texts };
}
