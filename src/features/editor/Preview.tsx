import { useEffect, useMemo, useRef } from "react";
import { t } from "@lingui/core/macro";
import { Pause, Play, SkipBack } from "../../components/ui/icons";
import { Tip } from "../../components/ui/Tip";
import { DEFAULT_EXTRA_VOLUME, layout, placedCues, segmentAt, trimmedLength, TimelineData } from "./model";
import { formatTime, mediaUrl, player, usePlayerTime, usePlaying } from "./player";

interface PreviewProps {
  timeline: TimelineData;
  projectDir: string;
}

function SubtitleOverlay({ cues, show }: { cues: ReturnType<typeof placedCues>; show: boolean }) {
  const time = usePlayerTime();
  const cue = show ? cues.find((c) => time >= c.globalStart && time < c.globalEnd) : null;
  if (!cue) return null;
  return (
    <div className="absolute inset-x-0 bottom-[7%] flex justify-center px-6 pointer-events-none">
      <span className="max-w-[85%] px-2.5 py-1 rounded-md bg-black/60 text-white text-[clamp(11px,1.6vw,20px)] leading-snug text-center whitespace-pre-line">
        {cue.text}
      </span>
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
  const voiceRef = useRef<HTMLAudioElement>(null);
  const musicRef = useRef<HTMLAudioElement>(null);
  const extraRef = useRef<HTMLAudioElement>(null);
  const loaded = useRef({ video: "", voice: "", music: "", extra: "" });
  const playing = usePlaying();

  const { placed, total } = useMemo(() => layout(timeline), [timeline]);
  const cues = useMemo(() => placedCues(timeline, placed), [timeline, placed]);

  const stateRef = useRef({ placed, total, timeline, projectDir });
  stateRef.current = { placed, total, timeline, projectDir };

  const sync = (time: number, isPlaying: boolean) => {
    const { placed, timeline, projectDir } = stateRef.current;
    const video = videoRef.current;
    const voice = voiceRef.current;
    const music = musicRef.current;
    const extra = extraRef.current;
    if (!video || !voice || !music || !extra) return;

    const p = segmentAt(placed, time);
    if (!p) {
      video.pause();
      voice.pause();
      music.pause();
      extra.pause();
      return;
    }
    const seg = p.seg;
    const local = Math.max(0, time - p.start);

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
    const voiceActive = !!seg.audio && wantVoice >= 0 && wantVoice < (seg.audioDuration ?? 0);
    if (audioSrc && loaded.current.voice !== audioSrc) {
      voice.src = audioSrc;
      loaded.current.voice = audioSrc;
    }
    voice.volume = seg.muted ? 0 : Math.min(1, Math.max(0, seg.volume));
    if (voiceActive) {
      if (Math.abs(voice.currentTime - wantVoice) > (isPlaying ? 0.35 : 0.03)) voice.currentTime = wantVoice;
      if (isPlaying) voice.play().catch(() => undefined);
      else voice.pause();
    } else {
      voice.pause();
    }

    // The footage's own sound (set up by the pipeline when "keep its sound" was on) plays with the clip.
    const extraSrc = mediaUrl(projectDir, seg.extraAudio);
    if (extraSrc) {
      if (loaded.current.extra !== extraSrc) {
        extra.src = extraSrc;
        loaded.current.extra = extraSrc;
      }
      extra.volume = Math.min(1, Math.max(0, seg.extraVolume ?? DEFAULT_EXTRA_VOLUME));
      if (Math.abs(extra.currentTime - local) > (isPlaying ? 0.35 : 0.03)) extra.currentTime = local;
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
          <audio ref={voiceRef} preload="auto" />
          <audio ref={musicRef} preload="auto" />
          <audio ref={extraRef} preload="auto" />
          {!placed.length && (
            <div className="absolute inset-0 flex items-center justify-center text-[13px] text-zinc-500">
              {t`Add a video to start`}
            </div>
          )}
          <SubtitleOverlay cues={cues} show />
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
