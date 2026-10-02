import { useEffect, useMemo, useRef } from "react";
import { t } from "@lingui/core/macro";
import { Pause, Play, SkipBack } from "../../components/ui/icons";
import { Tip } from "../../components/ui/Tip";
import { DEFAULT_EXTRA_VOLUME, fadeIns, isUnlinked, layout, placedCues, placedTexts, PlacedText, segmentAt, trimmedLength, TimelineData } from "./model";
import { formatTime, mediaUrl, player, usePlayerTime, usePlaying } from "./player";
import { useWorkspace } from "../../hooks/useWorkspace";
import {
  DEFAULT_TEXT_SUBTITLE_STYLE,
  DEFAULT_TEXT_TITLE_STYLE,
  resolveCaptionStyle,
  TEXT_DEFAULT_MARGIN,
  textBlockCenterY,
  lineFrame,
  lineMotion,
  textStyleToCss,
  wrapText,
} from "../../utils/textStyle";

interface PreviewProps {
  timeline: TimelineData;
  projectDir: string;
}


// Wraps to max_chars_per_line, then drops each line's closing 。/、 so the caption box
// is even on both sides (same as _subtitle_display_text in the export).
const subtitleDisplayText = (text: string, maxChars: number) =>
  wrapText(
    text
      .trim()
      .split(/\r?\n/)
      .map((line) => line.trim())
      .join("\n"),
    maxChars,
  )
    .split("\n")
    .map((line) => line.trim().replace(/[。、]+$/, "").trimEnd() || line.trim())
    .join("\n");

const ALIGN = { bottom: "items-end", middle: "items-center", top: "items-start" } as const;

function SubtitleOverlay({ cues, show }: { cues: ReturnType<typeof placedCues>; show: boolean }) {
  const time = usePlayerTime();
  const { settings } = useWorkspace();
  const cue = show ? cues.find((c) => time >= c.globalStart && time < c.globalEnd) : null;
  // Same look and placement the export burns in (caption_style + this subtitle's own style).
  const caption = useMemo(() => resolveCaptionStyle(settings, cue?.style), [settings, cue?.style]);
  const style = useMemo(() => textStyleToCss(caption), [caption]);
  if (!cue) return null;
  const edge = `${(caption.margin_v / 1080) * 100}cqh`;
  return (
    <div
      className={`absolute inset-0 flex ${ALIGN[caption.position]} justify-center px-6 pointer-events-none`}
      style={{
        containerType: "size",
        paddingBottom: caption.position === "bottom" ? edge : undefined,
        paddingTop: caption.position === "top" ? edge : undefined,
      }}
    >
      <span style={style} className="max-w-[85%] rounded-md leading-snug text-center whitespace-pre-line">
        {subtitleDisplayText(cue.text, caption.max_chars_per_line)}
      </span>
    </div>
  );
}

// Text-track items: centred title + subtitle, animated like the export (introclip.title_events).
function TextOverlay({ texts }: { texts: PlacedText[] }) {
  const time = usePlayerTime();
  const active = texts.filter((x) => time >= x.globalStart && time < x.globalEnd);
  if (!active.length) return null;
  const cq = (px: number) => `${(px / 1080) * 100}cqh`;
  return (
    <div className="absolute inset-0 pointer-events-none" style={{ containerType: "size" }}>
      {active.map((x) => {
        const title = { ...DEFAULT_TEXT_TITLE_STYLE, ...(x.title.style ?? {}) };
        const sub = { ...DEFAULT_TEXT_SUBTITLE_STYLE, ...(x.subtitle.style ?? {}) };
        const hasTitle = !!x.title.text.trim();
        const hasSub = !!x.subtitle.text.trim();
        const t = time - x.globalStart;
        const dur = x.globalEnd - x.globalStart;
        const paired = hasTitle && hasSub;
        const tm = lineMotion("title", x.title.animation, x.title.delay, x.animation, dur, paired);
        const sm = lineMotion("subtitle", x.subtitle.animation, x.subtitle.delay, x.animation, dur, paired);
        const tf = lineFrame(t, dur, tm.animation, tm.delay);
        const sf = lineFrame(t, dur, sm.animation, sm.delay);
        // Same anchors as the export: the block's left/centre/right edge, vertically centred.
        const side = cq(x.margin_h ?? TEXT_DEFAULT_MARGIN);
        const place: React.CSSProperties =
          x.align === "left"
            ? { left: side, transformOrigin: "left center" }
            : x.align === "right"
              ? { right: side, transformOrigin: "right center" }
              : { left: "50%", transformOrigin: "center" };
        const shift = x.align === "left" ? "translate(0, -50%)" : x.align === "right" ? "translate(0, -50%)" : "translate(-50%, -50%)";
        const cy = textBlockCenterY(x.position, x.margin_v, title.font_size, sub.font_size, hasTitle, hasSub);
        const titleY = hasTitle && hasSub ? cy - Math.trunc(sub.font_size * 0.6) : cy;
        const subY = hasTitle && hasSub ? cy + Math.trunc(title.font_size * 0.6) : cy;
        const line = "absolute whitespace-nowrap leading-none";
        return (
          <div key={x.id}>
            {hasTitle && tf.opacity > 0 && (
              <span
                className={line}
                style={{ ...textStyleToCss(title), ...place, top: cq(titleY + tf.rise), opacity: tf.opacity * title.opacity, transform: `${shift} scale(${tf.scale})` }}
              >
                {x.title.text}
              </span>
            )}
            {hasSub && sf.opacity > 0 && (
              <span
                className={line}
                style={{ ...textStyleToCss(sub), ...place, top: cq(subY + sf.rise), opacity: sf.opacity * sub.opacity, transform: `${shift} scale(${sf.scale})` }}
              >
                {x.subtitle.text}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Timecode({ total }: { total: number }) {
  const time = usePlayerTime();
  return (
    <span className="text-[12px] tabular-nums text-zinc-500 dark:text-zinc-400">
      {formatTime(time)} <span className="text-zinc-300 dark:text-zinc-600">/</span> {formatTime(total)}
    </span>
  );
}

export function Preview({ timeline, projectDir }: PreviewProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const fadeRef = useRef<HTMLVideoElement>(null);
  const voiceRef = useRef<HTMLAudioElement>(null);
  const musicRef = useRef<HTMLAudioElement>(null);
  const extraRef = useRef<HTMLAudioElement>(null);
  const loaded = useRef({ video: "", fade: "", voice: "", music: "", extra: "" });
  // Narration goes through a gain node once it's set above 100%: an <audio> element can't
  // play louder, the export can.
  const audioCtx = useRef<AudioContext | null>(null);
  const gains = useRef(new WeakMap<HTMLAudioElement, GainNode>());
  const setLevel = (el: HTMLAudioElement, level: number) => {
    let gain = gains.current.get(el);
    if (!gain && level > 1) {
      try {
        audioCtx.current ??= new AudioContext();
        gain = audioCtx.current.createGain();
        audioCtx.current.createMediaElementSource(el).connect(gain).connect(audioCtx.current.destination);
        gains.current.set(el, gain);
      } catch {
        // Falls back to the element's own volume, capped at 100%.
      }
    }
    if (gain) {
      el.volume = 1;
      gain.gain.value = level;
      if (audioCtx.current?.state === "suspended") audioCtx.current.resume().catch(() => undefined);
    } else el.volume = Math.min(1, level);
  };
  // Unlinked narration plays at its own timeline time, one element per clip, alongside the rest.
  const freeVoices = useRef(new Map<string, HTMLAudioElement>());
  const syncFree = (time: number, isPlaying: boolean) => {
    const { placed, projectDir } = stateRef.current;
    const active = new Set<string>();
    for (const p of placed) {
      const seg = p.seg;
      if (!isUnlinked(seg)) continue;
      const want = time - seg.audioStart!;
      if (want < 0 || want >= (seg.audioDuration ?? 0)) continue;
      active.add(seg.id);
      let el = freeVoices.current.get(seg.id);
      if (!el) {
        el = new Audio();
        el.crossOrigin = "anonymous";
        el.preload = "auto";
        freeVoices.current.set(seg.id, el);
      }
      const src = mediaUrl(projectDir, seg.audio);
      if (el.dataset.src !== src) {
        el.src = src;
        el.dataset.src = src;
      }
      setLevel(el, seg.muted ? 0 : Math.max(0, seg.volume));
      if (Math.abs(el.currentTime - want) > (isPlaying ? 0.35 : 0.03)) el.currentTime = want;
      if (isPlaying) el.play().catch(() => undefined);
      else el.pause();
    }
    for (const [id, el] of freeVoices.current) if (!active.has(id)) el.pause();
  };
  const playing = usePlaying();

  const { placed, total } = useMemo(() => layout(timeline), [timeline]);
  const cues = useMemo(() => placedCues(timeline, placed), [timeline, placed]);
  const texts = useMemo(() => placedTexts(timeline, placed), [timeline, placed]);
  const fades = useMemo(() => fadeIns(placed), [placed]);

  const stateRef = useRef({ placed, total, timeline, projectDir, fades });
  stateRef.current = { placed, total, timeline, projectDir, fades };

  const sync = (time: number, isPlaying: boolean) => {
    const { placed, timeline, projectDir, fades } = stateRef.current;
    const video = videoRef.current;
    const fadeVideo = fadeRef.current;
    const voice = voiceRef.current;
    const music = musicRef.current;
    const extra = extraRef.current;
    if (!video || !voice || !music || !extra) return;

    syncFree(time, isPlaying);
    const p = segmentAt(placed, time);
    if (!p) {
      if (fadeVideo) fadeVideo.style.opacity = "0";
      video.pause();
      voice.pause();
      music.pause();
      extra.pause();
      return;
    }
    const seg = p.seg;
    const local = Math.max(0, time - p.start);
    // Dissolving in from the clip before, as the export does: its last frame fades out over this
    // clip's opening, and this clip's sound fades in.
    const index = placed.indexOf(p);
    const fade = fades[index] ?? 0;
    const fading = fade > 0 && local < fade;
    const fadeIn = fading ? local / fade : 1;
    if (fadeVideo) {
      const prev = placed[index - 1]?.seg;
      if (fading && prev) {
        const src = mediaUrl(projectDir, prev.video);
        if (loaded.current.fade !== src) {
          fadeVideo.src = src;
          loaded.current.fade = src;
        }
        const last = Math.max(0, prev.trimIn + trimmedLength(prev) - 0.04);
        if (Math.abs(fadeVideo.currentTime - last) > 0.05) fadeVideo.currentTime = last;
        fadeVideo.style.opacity = String(1 - fadeIn);
      } else {
        fadeVideo.style.opacity = "0";
      }
    }

    const videoSrc = mediaUrl(projectDir, seg.video);
    if (loaded.current.video !== videoSrc) {
      video.src = videoSrc;
      loaded.current.video = videoSrc;
    }
    const holding = local >= trimmedLength(seg);
    const wantVideo = seg.trimIn + Math.min(local, trimmedLength(seg));
    if (Math.abs(video.currentTime - wantVideo) > (isPlaying ? 0.35 : 0.03)) video.currentTime = wantVideo;
    if (isPlaying && !holding) video.play().catch(() => undefined);
    else video.pause();

    const audioSrc = mediaUrl(projectDir, seg.audio);
    const wantVoice = local - seg.audioOffset;
    const voiceActive = !!seg.audio && !isUnlinked(seg) && wantVoice >= 0 && wantVoice < (seg.audioDuration ?? 0);
    if (audioSrc && loaded.current.voice !== audioSrc) {
      voice.src = audioSrc;
      loaded.current.voice = audioSrc;
    }
    setLevel(voice, seg.muted ? 0 : Math.max(0, seg.volume) * fadeIn);
    if (voiceActive) {
      if (Math.abs(voice.currentTime - wantVoice) > (isPlaying ? 0.35 : 0.03)) voice.currentTime = wantVoice;
      if (isPlaying) voice.play().catch(() => undefined);
      else voice.pause();
    } else {
      voice.pause();
    }

    // The footage's own sound (set up by the pipeline when "keep its sound" was on) follows the
    // trimmed picture and stops while its last frame is held.
    const extraSrc = mediaUrl(projectDir, seg.extraAudio);
    if (extraSrc && !holding) {
      if (loaded.current.extra !== extraSrc) {
        extra.src = extraSrc;
        loaded.current.extra = extraSrc;
      }
      extra.volume = Math.min(1, Math.max(0, seg.extraVolume ?? DEFAULT_EXTRA_VOLUME)) * fadeIn;
      if (Math.abs(extra.currentTime - wantVideo) > (isPlaying ? 0.35 : 0.03)) extra.currentTime = wantVideo;
      if (isPlaying) extra.play().catch(() => undefined);
      else extra.pause();
    } else {
      extra.pause();
    }

    const bed = timeline.music;
    const musicSrc = mediaUrl(projectDir, bed?.path);
    if (bed && musicSrc) {
      if (loaded.current.music !== musicSrc) {
        music.src = musicSrc;
        loaded.current.music = musicSrc;
      }
      music.volume = Math.min(1, Math.max(0, bed.volume));
      const dur = bed.duration || music.duration;
      const wantMusic = dur && Number.isFinite(dur) ? time % dur : time;
      if (Math.abs(music.currentTime - wantMusic) > (isPlaying ? 0.6 : 0.05)) music.currentTime = wantMusic;
      if (isPlaying) music.play().catch(() => undefined);
      else music.pause();
    } else {
      music.pause();
    }
  };

  useEffect(() => {
    if (!playing) {
      sync(player.time, false);
      return;
    }
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      const next = player.time + dt;
      if (next >= stateRef.current.total) {
        player.set({ time: stateRef.current.total, playing: false });
        return;
      }
      player.set({ time: next });
      sync(next, true);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing]);

  useEffect(() => {
    if (!player.playing) sync(player.time, false);
    const unsubscribe = player.subscribe(() => {
      if (!player.playing) sync(player.time, false);
    });
    return () => {
      unsubscribe();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placed, timeline.music]);

  useEffect(() => {
    if (player.time > total) player.set({ time: total });
  }, [total]);

  useEffect(() => {
    const voices = freeVoices.current;
    return () => {
      for (const el of voices.values()) {
        el.pause();
        el.removeAttribute("src");
      }
      voices.clear();
      audioCtx.current?.close().catch(() => undefined);
    };
  }, []);

  const toggle = () => {
    if (!placed.length) return;
    if (player.playing) player.set({ playing: false });
    else {
      if (player.time >= total - 0.05) player.set({ time: 0 });
      player.set({ playing: true });
    }
  };

  const transport =
    "group/tool relative flex items-center justify-center w-8 h-8 rounded-lg text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-white/5 transition-colors";

  return (
    <div className="flex flex-col min-h-0 flex-1">
      <div className="flex-1 min-h-0 flex items-center justify-center p-4">
        <div className="relative max-h-full max-w-full aspect-video h-full bg-black rounded-xl overflow-hidden shadow-sm ring-1 ring-black/10 dark:ring-white/10">
          <video ref={videoRef} muted playsInline preload="auto" className="absolute inset-0 w-full h-full object-contain" />
          <video ref={fadeRef} muted playsInline preload="auto" className="absolute inset-0 w-full h-full object-contain pointer-events-none" style={{ opacity: 0 }} />
          <audio ref={voiceRef} preload="auto" crossOrigin="anonymous" />
          <audio ref={musicRef} preload="auto" />
          <audio ref={extraRef} preload="auto" />
          {!placed.length && (
            <div className="absolute inset-0 flex items-center justify-center text-[13px] text-zinc-500">
              {t`Add a video to start`}
            </div>
          )}
          <SubtitleOverlay cues={cues} show />
          <TextOverlay texts={texts} />
        </div>
      </div>
      <div className="flex items-center justify-center gap-2 h-10 shrink-0">
        <button type="button" aria-label={t`Back to start`} onClick={() => player.set({ time: 0, playing: false })} className={transport}>
          <SkipBack className="w-4 h-4" />
          <Tip label={t`Back to start`} />
        </button>
        <button
          type="button"
          aria-label={playing ? t`Pause` : t`Play`}
          onClick={toggle}
          className="group/tool relative flex items-center justify-center w-9 h-9 rounded-full bg-navi text-white hover:brightness-110 transition"
        >
          {playing ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4 ml-0.5" />}
          <Tip label={playing ? t`Pause` : t`Play`} kbd="Space" />
        </button>
        <Timecode total={total} />
      </div>
    </div>
  );
}
