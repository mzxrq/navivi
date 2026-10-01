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
}

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
  music: MusicBed | null;
  burnSubtitles: boolean;
}

export const EDITOR_VERSION = 1;
export const MIN_SEGMENT = 0.5;
export const MIN_CUE = 0.3;
export const AUTO_FADE_SECONDS = 0.8;
export const DEFAULT_EXTRA_VOLUME = 0.5;

export const emptyTimeline = (): TimelineData => ({
  segments: [],
  subtitles: [],
  music: null,
  burnSubtitles: true,
});

export const newId = () => crypto.randomUUID();

export const trimmedLength = (s: Segment) => Math.max(MIN_SEGMENT, s.trimOut - s.trimIn);

export const segmentLength = (s: Segment) =>
  Math.max(trimmedLength(s), s.audio ? s.audioOffset + (s.audioDuration ?? 0) : 0);

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

export interface PlacedCue extends SubtitleCue {
  globalStart: number;
  globalEnd: number;
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

// Places a cue at global times; it belongs to the clip under its middle unless `keepSegment` pins it.
export function anchorCue(
  timeline: TimelineData,
  cue: SubtitleCue,
  globalStart: number,
  globalEnd: number,
  keepSegment = false,
): SubtitleCue {
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
    const from = speaking.length ? p.start + p.seg.audioOffset : p.start;
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

export function toManifest(projectName: string, timeline: TimelineData) {
  const { placed, total } = layout(timeline);
  const cues = placedCues(timeline, placed).map((c) => ({ start: c.globalStart, end: c.globalEnd, text: c.text }));
  return {
    project_name: projectName,
    total_duration_seconds: total,
    video_tracks: timeline.segments.map((s, i) => ({
      order: i,
      clip_name: s.label,
      file_path: s.video,
      audio_path: s.audio ?? null,
      audio_offset: s.audioOffset,
      subtitle_path: s.subtitleFile ?? null,
      extra_audio_path: s.extraAudio ?? null,
      extra_audio_volume: s.extraAudio ? (s.extraVolume ?? DEFAULT_EXTRA_VOLUME) : null,
      trim_in: s.trimIn,
      trim_out: s.trimOut < s.videoDuration - 0.01 ? s.trimOut : null,
      volume: s.volume,
      muted: s.muted,
      fade_into_next_seconds: s.fadeIntoNext,
    })),
    subtitles: cues,
    burn_subtitles: timeline.burnSubtitles,
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
    music: e.music ?? null,
    burnSubtitles: e.burnSubtitles ?? true,
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
  }
  return { ...emptyTimeline(), segments };
}
