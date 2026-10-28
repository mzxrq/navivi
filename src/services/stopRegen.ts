import { runStage } from "./sidecar";
import { cuesFromSegmentFile, parseTimedSrt, segmentLength } from "../features/editor/model";
import type { Segment, TimelineData } from "../features/editor/model";

export type RegenKind = "voice" | "subtitles" | "photo";

export interface RegenStop {
  hasArrivalVoice: boolean;
  hasAttractionVoice: boolean;
}

// The single-stop CLI modes of main.py, in the order they must run. The stop's index is its place in job_config's waypoints.
export function regenModes(kind: RegenKind, index: number, stop: RegenStop): string[] {
  // The attraction narration's subtitles have no single-stop mode; subtitle-all remakes them (all subtitles are cheap).
  if (kind === "subtitles") return [stop.hasArrivalVoice ? `subtitle ${index} --force` : "subtitle-all --force"];
  if (kind === "photo") return [...(stop.hasAttractionVoice ? [`attraction-tts ${index}`] : []), `attraction ${index} --force`];
  return [
    ...(stop.hasArrivalVoice ? [`tts ${index} --force`] : []),
    ...(stop.hasAttractionVoice ? [`attraction-tts ${index} --force`] : []),
    ...(stop.hasArrivalVoice ? [`subtitle ${index} --force`] : []),
    ...(stop.hasAttractionVoice ? ["subtitle-all"] : []),
  ];
}

// main.py prints its result indented, so the reply is the block that starts at the last unindented brace.
export function lastJson(stdout: string): { success?: boolean; error?: string; skipped?: string } {
  const start = stdout.lastIndexOf("\n{");
  try {
    return JSON.parse(start >= 0 ? stdout.slice(start + 1) : stdout.trim());
  } catch {
    return {};
  }
}

// One sidecar call at a time (a new call kills the running one), so the modes run in sequence.
// A mode that has nothing to make for this stop answers success with `skipped`; the first such reason is returned.
export async function runRegen(configPath: string, modes: string[], onStep?: (done: number, total: number) => void): Promise<{ skipped?: string }> {
  let skipped: string | undefined;
  for (let i = 0; i < modes.length; i++) {
    onStep?.(i, modes.length);
    const reply = lastJson(await runStage(configPath, modes[i]));
    if (reply.success === false) throw new Error(reply.error ?? "The media pipeline reported an error");
    if (reply.skipped && !skipped) skipped = String(reply.skipped);
  }
  return { skipped };
}

const base = (path?: string) => (path ?? "").replace(/\\/g, "/").split("/").pop() ?? "";
const pad = (n: number) => String(n).padStart(2, "0");

// The files the pipeline names after a stop: the arrival narration is 02_waypoint_<index+1>_*, the attraction clip and its narration 04_attraction_<index>_*.
export const arrivalAudioPrefix = (index: number) => `02_waypoint_${pad(index + 1)}_`;
export const attractionPrefix = (index: number) => `04_attraction_${pad(index)}_`;

/** The stop a timeline clip belongs to, from those names (its photo clip or narration); null for other clips. */
export function stopIndexOf(seg: Pick<Segment, "video" | "audio">): number | null {
  const attraction = /^04_attraction_(\d+)_/.exec(base(seg.video)) ?? /^04_attraction_(\d+)_/.exec(base(seg.audio));
  if (attraction) return Number(attraction[1]);
  const arrival = /^02_waypoint_(\d+)_/.exec(base(seg.audio));
  return arrival ? Number(arrival[1]) - 1 : null;
}

/** The intro or overview clip: not a stop, made again through its own modes. */
export type RouteClip = "intro" | "overview";

export function routeClipOf(seg: Pick<Segment, "video">): RouteClip | null {
  const name = base(seg.video);
  return name === "00_intro.mp4" ? "intro" : name.startsWith("01_overview") ? "overview" : null;
}

/** What a timeline clip is made from: a stop's index, the intro or the overview; null for other clips. */
export const regenTargetOf = (seg: Pick<Segment, "video" | "audio">) => stopIndexOf(seg) ?? routeClipOf(seg);

// The overview narration is one script for both clips (the opening plays on the intro), so "voice" redoes both files.
// No --force on the voice: only a file whose words changed is voiced again, so the other clip stays as it is.
export function routeClipModes(clip: RouteClip, kind: "voice" | "video"): string[] {
  if (kind === "voice") return ["overview-tts", "subtitle-all"];
  return [clip === "intro" ? "intro" : "overview --force"];
}

const OVERVIEW_VOICES = ["00_intro_narration", "00_overview_narration"];

/** refreshStopMedia for the intro or overview clip. */
export function refreshRouteClip(timeline: TimelineData, clip: RouteClip, kind: "voice" | "video", io: RefreshIo) {
  return refreshMedia(timeline, kind === "voice" ? "voice" : "photo", {
    audio: (name) => OVERVIEW_VOICES.some((v) => name.startsWith(v)),
    video: (name) => routeClipOf({ video: name }) === clip,
  }, io);
}

export type StopNarration = "arrival" | "attraction";

/** Which of its stop's narrations a timeline clip plays: the walk's arrival one or the place clip's attraction one. */
export function narrationOf(seg: Pick<Segment, "video" | "audio">): StopNarration | null {
  if (base(seg.audio).startsWith("02_waypoint_")) return "arrival";
  return /^04_attraction_/.test(base(seg.video)) || /^04_attraction_/.test(base(seg.audio)) ? "attraction" : null;
}

/** The stop limited to one narration, so "Make again" from a clip redoes only what that clip plays. */
export function onlyNarration<T extends RegenStop>(stop: T, which: StopNarration | null): T {
  if (!which) return stop;
  return { ...stop, hasArrivalVoice: which === "arrival" && stop.hasArrivalVoice, hasAttractionVoice: which === "attraction" && stop.hasAttractionVoice };
}

export interface RefreshIo {
  probe: (relPath: string, kind: "video" | "audio") => Promise<number>;
  readText: (relPath: string) => Promise<string>;
}

// The timeline keeps what it read from timeline.json, so after a stop's files were remade the clips that play them are read again:
// narration length, the subtitle cues made from the new .srt, and the photo clip's length. Edits elsewhere stay. Null = nothing to change.
export function refreshStopMedia(timeline: TimelineData, index: number, kind: RegenKind, io: RefreshIo): Promise<TimelineData | null> {
  const voicePrefixes = [arrivalAudioPrefix(index), attractionPrefix(index)];
  return refreshMedia(timeline, kind, {
    audio: (name) => voicePrefixes.some((p) => name.startsWith(p)),
    video: (name) => name.startsWith(attractionPrefix(index)),
  }, io);
}

async function refreshMedia(
  timeline: TimelineData, kind: RegenKind, match: { audio: (name: string) => boolean; video: (name: string) => boolean }, io: RefreshIo,
): Promise<TimelineData | null> {
  let changed = false;
  const replaced = new Set<string>();
  const cues: TimelineData["subtitles"] = [];
  const segments: Segment[] = [];

  for (const seg of timeline.segments) {
    let next = seg;
    const audioName = base(seg.audio);
    if (kind !== "photo" && seg.audio && match.audio(audioName)) {
      if (kind === "voice") {
        const length = await io.probe(seg.audio, "audio");
        if (length > 0 && Math.abs(length - (seg.audioDuration ?? 0)) > 0.01) next = { ...next, audioDuration: length };
      }
      if (seg.subtitleFile) {
        try {
          const timed = parseTimedSrt(await io.readText(seg.subtitleFile));
          replaced.add(seg.id);
          cues.push(...cuesFromSegmentFile(next, timed));
        } catch {
          // a narration without a readable subtitle file keeps the cues it has
        }
      }
    }
    if (kind === "photo" && match.video(base(seg.video))) {
      const length = await io.probe(seg.video, "video");
      if (length > 0 && Math.abs(length - seg.videoDuration) > 0.01) {
        const untrimmed = seg.trimOut >= seg.videoDuration - 0.01;
        next = { ...next, videoDuration: length, trimOut: untrimmed ? length : Math.min(seg.trimOut, length) };
      }
    }
    if (next !== seg) changed = true;
    segments.push(next);
  }

  if (replaced.size) changed = true;
  if (!changed) return null;
  const kept = timeline.subtitles.filter((c) => !replaced.has(c.segmentId));
  // Cues are cut to their clip, so a clip whose narration got longer or shorter is measured again here.
  const limits = new Map(segments.map((s) => [s.id, segmentLength(s)]));
  return { ...timeline, segments, subtitles: [...kept, ...cues.filter((c) => c.start < (limits.get(c.segmentId) ?? Infinity))] };
}
