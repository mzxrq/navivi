import { runStage } from "./sidecar";
import { cuesFromSegmentFile, isUnlinked, parseTimedSrt, segmentLength } from "../features/editor/model";
import type { Segment, TimelineData } from "../features/editor/model";

export type RegenKind = "voice" | "subtitles" | "photo";

export interface RegenStop {
  hasArrivalVoice: boolean;
  hasAttractionVoice: boolean;
}

// The single-stop CLI modes of main.py, in the order they must run. The stop's index is its place in job_config's waypoints.
// `pieces`: voice only those kept sentences again (VoicePiecesDialog); the others keep their audio.
export function regenModes(kind: RegenKind, index: number, stop: RegenStop, pieces?: number[]): string[] {
  // The attraction narration's subtitles have no single-stop mode; subtitle-all remakes them (all subtitles are cheap).
  if (kind === "subtitles") return [stop.hasArrivalVoice ? `subtitle ${index} --force` : "subtitle-all --force"];
  if (kind === "photo") return [...(stop.hasAttractionVoice ? [`attraction-tts ${index}`] : []), `attraction ${index} --force`];
  const redo = pieces?.length ? `--retake=${pieces.join(",")}` : "--force";
  return [
    ...(stop.hasArrivalVoice ? [`tts ${index} ${redo}`] : []),
    ...(stop.hasAttractionVoice ? [`attraction-tts ${index} ${redo}`] : []),
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

/** The intro, overview or outro clip: not a stop, made again through its own modes. */
export type RouteClip = "intro" | "overview" | "outro";

export function routeClipOf(seg: Pick<Segment, "video">): RouteClip | null {
  const name = base(seg.video);
  return name === "00_intro.mp4" ? "intro" : name.startsWith("01_overview") ? "overview" : name === "99_outro.mp4" ? "outro" : null;
}

/** What a timeline clip is made from: a stop's index, the intro or the overview; null for other clips. */
export const regenTargetOf = (seg: Pick<Segment, "video" | "audio">) => stopIndexOf(seg) ?? routeClipOf(seg);

// The overview narration is one script for both clips (the opening plays on the intro), so "voice" redoes both files.
// No --force on the voice: only the edited sentences are voiced again, so the other clip stays as it is.
// --retake: the clicked clip's words are unchanged, so it gets a new take instead of the same one back;
// `pieces`: only those of its sentences (VoicePiecesDialog).
export function routeClipModes(clip: RouteClip, kind: "voice" | "video", pieces?: number[]): string[] {
  if (kind === "voice") return [`overview-tts --retake=${clip}${pieces?.length ? `:${pieces.join(",")}` : ""}`, "subtitle-all"];
  return [clip === "overview" ? "overview --force" : clip];
}

const OVERVIEW_VOICES = ["00_intro_narration", "00_overview_narration"];

/** refreshStopMedia for the intro or overview clip. */
export function refreshRouteClip(timeline: TimelineData, clip: RouteClip, kind: "voice" | "video", io: RefreshIo) {
  return refreshMedia(timeline, kind === "voice" ? "voice" : "photo", {
    audio: (name) => OVERVIEW_VOICES.some((v) => name.startsWith(v)),
    video: (name) => routeClipOf({ video: name }) === clip,
  }, io);
}

/** The NN of a walking clip (02_waypoint_NN_*.mp4, its pieces included); null for other clips. */
export function legOf(seg: Pick<Segment, "video">): number | null {
  const m = /^02_waypoint_(\d+)_/.exec(base(seg.video));
  return m ? Number(m[1]) : null;
}

// The other legs are only worked out (street views, the walk going on), so this one matches a full render.
export const legModes = (leg: number) => [`leg ${leg} --force`];

/** After `leg NN`: its clips get their new length and voice start (from <clip>.timing.json); their cues move with the voice. */
export function refreshLeg(timeline: TimelineData, leg: number, io: RefreshIo) {
  return refreshMedia(timeline, "photo", { audio: () => false, video: (name) => name.startsWith(`02_waypoint_${pad(leg)}_`), timing: true }, io);
}

/** Whether a timeline clip is being remade by this queue job: a walking clip job only its leg, a photo clip job only the attraction clip. */
export function isBusyClip(seg: Pick<Segment, "video" | "audio">, job: { index: number | RouteClip; kind: string; leg?: number }): boolean {
  if (job.kind === "walk") return legOf(seg) === job.leg;
  if (job.kind === "photo" && legOf(seg) !== null) return false;
  return regenTargetOf(seg) === job.index;
}

const letters = (s: string) => s.normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
/** Whether a narration file (02_waypoint_NN_<label> / 04_attraction_NN_<label>, label = the stop's name) was made for
 *  this stop: after a stop is added or removed, an old timeline's file numbers point at its neighbour. */
export const fileIsStop = (file: string, wp: { name?: string } | undefined) =>
  !!wp?.name && letters(file.replace(/^0[24]_(?:waypoint|attraction)_\d+_?/, "")) === letters(wp.name);

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
  timeline: TimelineData, kind: RegenKind,
  match: { audio: (name: string) => boolean; video: (name: string) => boolean; timing?: boolean }, io: RefreshIo,
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
      if (match.timing && seg.audio && !isUnlinked(seg)) {
        try {
          const sidecar = seg.video.replace(/(_subtitled|_padded)*\.[^./\\]+$/, ".timing.json");
          const offset = Math.max(0, Number(JSON.parse(await io.readText(sidecar)).audio_offset_seconds) || 0);
          if (Math.abs(offset - seg.audioOffset) > 0.01) {
            next = { ...next, audioOffset: offset };
            if (seg.subtitleFile) {
              replaced.add(seg.id);
              cues.push(...cuesFromSegmentFile(next, parseTimedSrt(await io.readText(seg.subtitleFile))));
            }
          }
        } catch {
          // no readable timing.json: the voice start stays
        }
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

// outrocard's end card: its doors and the logo's hold (tuning.OUTRO_LOGO_FADE_SECONDS + OUTRO_LOGO_HOLD_SECONDS).
const OUTRO_END_CARD_SECONDS = 3.8;

/** A scrapbook outro's title after its clip was made again: it is drawn into the clip now (under the logo doors),
 *  so the text track only keeps it for editing, up to where the end card starts. Null when nothing changes. */
export function withOutroBurnedIn(timeline: TimelineData): TimelineData | null {
  let changed = false;
  const texts = timeline.texts.map((x) => {
    const seg = x.kind === "outro" ? timeline.segments.find((s) => s.id === x.segmentId) : undefined;
    if (!seg) return x;
    const end = Math.max(x.start + 0.5, seg.videoDuration - OUTRO_END_CARD_SECONDS);
    if (x.burned_in && x.wipe_out === undefined && Math.abs(x.end - end) < 0.01) return x;
    changed = true;
    const { wipe_out: _w, ...rest } = x;
    return { ...rest, burned_in: true, end };
  });
  return changed ? { ...timeline, texts } : null;
}
