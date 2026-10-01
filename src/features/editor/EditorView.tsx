import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open as dialogOpen, save as dialogSave } from "@tauri-apps/plugin-dialog";
import { readTextFile, writeTextFile } from "@tauri-apps/plugin-fs";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useWorkspace } from "../../hooks/useWorkspace";
import { useUI } from "../../hooks/useUI";
import { Copy, FileText, Film, Maximize, Music, Plus, Sparkles, Subtitles, Trash2, Video, VolumeX, ZoomIn, ZoomOut } from "../../components/ui/icons";
import { Tip } from "../../components/ui/Tip";
import { openContextMenu, separator } from "../../components/ui/menuItems";
import { probeDuration, toAbsoluteProjectPath, toRelativeProjectPath } from "../../services/fileSystem";
import { convertFileSrc } from "@tauri-apps/api/core";
import {
  autoArrange,
  autoTimeBlocks,
  cuesFromSegmentFile,
  cuesFromTimed,
  cuesToSrt,
  layout,
  newId,
  parsePlainBlocks,
  parseTimedSrt,
  placedCues,
  Segment,
  SubtitleCue,
  TimelineData,
} from "./model";
import { ExportDialog } from "./ExportDialog";
import { LibraryTrack, MusicPicker } from "./MusicPicker";
import { Inspector } from "./Inspector";
import { player } from "./player";
import { Preview } from "./Preview";
import { Selection, TimelinePane } from "./TimelinePane";

const VIDEO_EXT = ["mp4", "mov", "mkv", "webm", "m4v"];
const AUDIO_EXT = ["mp3", "wav", "m4a", "aac", "ogg", "flac"];
const baseName = (p: string) => p.split(/[\\/]/).pop() ?? p;
const stem = (p: string) => baseName(p).replace(/\.[^.]+$/, "");

const toolButton =
  "group/tool relative flex items-center justify-center w-8 h-8 rounded-lg text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-white/5 disabled:opacity-40 disabled:pointer-events-none transition-colors";

export function EditorView() {
  const { timeline, setTimeline, metadata, autoLoadTimeline } = useWorkspace();
  const { showToast, isBackgroundBusy } = useUI();
  const dir = metadata.directory_path;

  const [draft, setDraft] = useState<TimelineData | null>(null);
  const [selection, setSelection] = useState<Selection>(null);
  const [pps, setPps] = useState(0);
  const [exportOpen, setExportOpen] = useState(false);
  const [musicOpen, setMusicOpen] = useState(false);
  const view = draft ?? timeline;
  const { placed, total } = useMemo(() => layout(view), [view]);

  useEffect(() => {
    if (dir && timeline.segments.length === 0) void autoLoadTimeline(dir);
    return () => player.set({ playing: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dir]);

  useEffect(() => {
    if (!pps && total > 0) setPps(Math.min(80, Math.max(4, (window.innerWidth - 220) / total)));
  }, [pps, total]);

  const commit = useCallback((next: TimelineData) => setTimeline(next), [setTimeline]);

  const toRel = (abs: string) => toRelativeProjectPath(abs, dir);

  const importMedia = async (kind: "video" | "audio", subdir: string) => {
    const picked = await dialogOpen({
      multiple: kind === "video",
      filters: [{ name: kind === "video" ? t`Video` : t`Audio`, extensions: kind === "video" ? VIDEO_EXT : AUDIO_EXT }],
    });
    if (!picked) return [];
    const files = Array.isArray(picked) ? picked : [picked];
    const out: { rel: string; duration: number; name: string }[] = [];
    for (const file of files) {
      const copied = await invoke<string>("copy_asset_file", { sourcePath: file, targetDir: `${dir}/assets/${subdir}` });
      const rel = toRel(copied);
      const abs = await toAbsoluteProjectPath(rel, dir);
      out.push({ rel, duration: await probeDuration(convertFileSrc(abs), kind, kind === "video" ? 5 : 0), name: stem(file) });
    }
    return out;
  };

  const addVideos = async () => {
    try {
      const files = await importMedia("video", "video/custom");
      if (!files.length) return;
      const added: Segment[] = files.map((f) => ({
        id: newId(),
        label: f.name,
        kind: "custom",
        video: f.rel,
        videoDuration: f.duration,
        trimIn: 0,
        trimOut: f.duration,
        audioOffset: 0,
        volume: 1,
        muted: false,
        fadeIntoNext: 0,
      }));
      const at = selection?.type === "segment" ? timeline.segments.findIndex((s) => s.id === selection.id) + 1 : timeline.segments.length;
      const segments = [...timeline.segments];
      segments.splice(at, 0, ...added);
      commit({ ...timeline, segments });
      setSelection({ type: "segment", id: added[0].id });
    } catch (e: any) {
      showToast(t`Could not add the video: ${e?.message ?? e}`, "error");
    }
  };

  const placeMusic = async (source: string, label: string, credit?: string) => {
    const copied = await invoke<string>("copy_asset_file", { sourcePath: source, targetDir: `${dir}/assets/audio/music` });
    const rel = toRel(copied);
    const duration = await probeDuration(convertFileSrc((await toAbsoluteProjectPath(rel, dir)).split(String.fromCharCode(92)).join("/")), "audio", 0);
    commit({ ...timeline, music: { path: rel, label, duration, volume: timeline.music?.volume ?? 0.25, credit } });
  };

  const useLibraryTrack = async (track: LibraryTrack) => {
    setMusicOpen(false);
    try {
      await placeMusic(track.abs, track.title, track.credit);
    } catch (e: any) {
      showToast(t`Could not add the music: ${e?.message ?? e}`, "error");
    }
  };

  const addMusicFile = async () => {
    setMusicOpen(false);
    try {
      const [file] = await importMedia("audio", "audio/music");
      if (file) commit({ ...timeline, music: { path: file.rel, label: file.name, duration: file.duration, volume: timeline.music?.volume ?? 0.25 } });
    } catch (e: any) {
      showToast(t`Could not add the music: ${e?.message ?? e}`, "error");
    }
  };

  const addMusic = () => setMusicOpen(true);

  const withSubtitles = (subtitles: SubtitleCue[], message: string) => {
    commit({ ...timeline, subtitles });
    showToast(message, "success");
  };

  const subtitlesFromNarration = async (base: TimelineData = timeline) => {
    const out: SubtitleCue[] = [];
    for (const seg of base.segments) {
      if (!seg.subtitleFile || !seg.audio || seg.muted) continue;
      try {
        const raw = await readTextFile(await toAbsoluteProjectPath(seg.subtitleFile, dir));
        out.push(...cuesFromSegmentFile(seg, parseTimedSrt(raw)));
      } catch {
        // a narration without a subtitle file is simply skipped
      }
    }
    return out;
  };

  const importSubtitleFile = async () => {
    if (!timeline.segments.length) return showToast(t`Add a video first, then import subtitles`, "error");
    const file = await dialogOpen({ multiple: false, filters: [{ name: t`Subtitles`, extensions: ["srt", "txt", "vtt"] }] });
    if (!file || Array.isArray(file)) return;
    try {
      const raw = await readTextFile(file);
      const timed = parseTimedSrt(raw);
      if (timed.length) {
        withSubtitles(cuesFromTimed(timeline, timed), t`${timed.length} subtitles imported`);
      } else {
        const blocks = parsePlainBlocks(raw);
        withSubtitles(autoTimeBlocks(timeline, blocks), t`${blocks.length} lines timed automatically. Drag them to adjust.`);
      }
    } catch (e: any) {
      showToast(t`Could not read the file: ${e?.message ?? e}`, "error");
    }
  };

  const fromNarration = async () => {
    const cues = await subtitlesFromNarration();
    if (!cues.length) return showToast(t`No narration subtitles found for these clips`, "error");
    withSubtitles(cues, t`${cues.length} subtitles added from the narration`);
  };

  const autoEdit = async () => {
    if (!timeline.segments.length) return;
    const arranged = autoArrange(timeline);
    const fresh = timeline.subtitles.length ? timeline.subtitles : await subtitlesFromNarration(arranged);
    commit({ ...arranged, subtitles: fresh });
    showToast(t`Clips ordered, fades added and subtitles filled in`, "success");
  };

  const saveSrt = async () => {
    const cues = placedCues(view, placed).map((c) => ({ start: c.globalStart, end: c.globalEnd, text: c.text }));
    const target = await dialogSave({ defaultPath: `${metadata.project_name || "subtitles"}.srt`, filters: [{ name: "SRT", extensions: ["srt"] }] });
    if (target) await writeTextFile(target, cuesToSrt(cues));
  };

  const duplicate = (id: string) => {
    const i = timeline.segments.findIndex((s) => s.id === id);
    if (i < 0) return;
    const copy = { ...timeline.segments[i], id: newId(), audio: undefined, audioDuration: undefined, audioOffset: 0, subtitleFile: undefined, fadeIntoNext: 0 };
    const segments = [...timeline.segments];
    segments.splice(i + 1, 0, copy);
    commit({ ...timeline, segments });
    setSelection({ type: "segment", id: copy.id });
  };

  const removeSegment = (id: string) => {
    commit({ ...timeline, segments: timeline.segments.filter((s) => s.id !== id), subtitles: timeline.subtitles.filter((c) => c.segmentId !== id) });
    setSelection(null);
  };

  const patchSegment = (id: string, patch: Partial<Segment>) =>
    commit({ ...timeline, segments: timeline.segments.map((s) => (s.id === id ? { ...s, ...patch } : s)) });

  const removeCue = (id: string) => {
    commit({ ...timeline, subtitles: timeline.subtitles.filter((c) => c.id !== id) });
    setSelection(null);
  };

  const keyRef = useRef({ selection, removeSegment, removeCue, patchSegment, timeline, total });
  keyRef.current = { selection, removeSegment, removeCue, patchSegment, timeline, total };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const k = keyRef.current;
      if (e.key === " ") {
        e.preventDefault();
        if (player.playing) player.set({ playing: false });
        else {
          if (player.time >= k.total - 0.05) player.set({ time: 0 });
          player.set({ playing: true });
        }
      } else if ((e.key === "Delete" || e.key === "Backspace") && k.selection) {
        e.preventDefault();
        if (k.selection.type === "segment") k.removeSegment(k.selection.id);
        else k.removeCue(k.selection.id);
      } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        const step = e.shiftKey ? 5 : 1;
        player.set({ time: Math.min(k.total, Math.max(0, player.time + (e.key === "ArrowLeft" ? -step : step))) });
      } else if (e.key.toLowerCase() === "m" && k.selection?.type === "segment") {
        const seg = k.timeline.segments.find((s) => s.id === k.selection!.id);
        if (seg?.audio) k.patchSegment(seg.id, { muted: !seg.muted });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const segmentMenu = (e: React.MouseEvent, seg: Segment) =>
    openContextMenu(e, [
      { label: t`Duplicate`, icon: Copy, onSelect: () => duplicate(seg.id) },
      !!seg.audio && {
        label: seg.muted ? t`Unmute narration` : t`Mute narration`,
        icon: VolumeX,
        kbd: "M",
        onSelect: () => patchSegment(seg.id, { muted: !seg.muted }),
      },
      (seg.trimIn > 0 || seg.trimOut < seg.videoDuration) && {
        label: t`Reset trim`,
        onSelect: () => patchSegment(seg.id, { trimIn: 0, trimOut: seg.videoDuration }),
      },
      { label: seg.fadeIntoNext > 0 ? t`Cut to next clip` : t`Fade into next clip`, onSelect: () => patchSegment(seg.id, { fadeIntoNext: seg.fadeIntoNext > 0 ? 0 : 0.8 }) },
      separator,
      { label: t`Remove`, icon: Trash2, danger: true, kbd: "Del", onSelect: () => removeSegment(seg.id) },
    ]);

  const cueMenu = (e: React.MouseEvent, cue: { id: string }) =>
    openContextMenu(e, [{ label: t`Delete subtitle`, icon: Trash2, danger: true, kbd: "Del", onSelect: () => removeCue(cue.id) }]);

  const laneMenu = (e: React.MouseEvent, time: number, lane: "video" | "subtitle" | "music") => {
    if (lane === "video") openContextMenu(e, [{ label: t`Add video`, icon: Video, onSelect: addVideos }]);
    else if (lane === "music") openContextMenu(e, [{ label: t`Add music`, icon: Music, onSelect: addMusic }, timeline.music && { label: t`Remove music`, icon: Trash2, danger: true, onSelect: () => commit({ ...timeline, music: null }) }]);
    else
      openContextMenu(e, [
        {
          label: t`Add subtitle here`,
          icon: Plus,
          onSelect: () => {
            const at = placed.find((p) => time < p.start + p.length) ?? placed[placed.length - 1];
            if (!at) return;
            const cue: SubtitleCue = { id: newId(), segmentId: at.seg.id, start: Math.max(0, time - at.start), end: Math.min(at.length, time - at.start + 2), text: t`New subtitle` };
            commit({ ...timeline, subtitles: [...timeline.subtitles, cue] });
            setSelection({ type: "cue", id: cue.id });
          },
        },
        { label: t`From narration`, icon: Sparkles, onSelect: fromNarration },
        { label: t`From a file…`, icon: FileText, onSelect: importSubtitleFile },
      ]);
  };

  const subtitleMenu = (e: React.MouseEvent) =>
    openContextMenu(
      { clientX: e.currentTarget.getBoundingClientRect().left, clientY: e.currentTarget.getBoundingClientRect().bottom + 4, preventDefault: () => e.preventDefault(), stopPropagation: () => e.stopPropagation() },
      [
        { label: t`From narration`, icon: Sparkles, onSelect: fromNarration },
        { label: t`From a file…`, icon: FileText, onSelect: importSubtitleFile },
      ],
    );

  const empty = timeline.segments.length === 0;

  return (
    <div className="flex flex-col h-full w-full pt-10 bg-white dark:bg-[#0c0c0e]">
      <div className="flex items-center gap-0.5 h-11 px-3 shrink-0 border-b border-zinc-200 dark:border-white/5">
        <button type="button" aria-label={t`Add video`} onClick={addVideos} className={toolButton}>
          <Video className="w-4 h-4" />
          <Tip label={t`Add video`} align="start" />
        </button>
        <button type="button" aria-label={t`Add music`} onClick={addMusic} className={toolButton}>
          <Music className="w-4 h-4" />
          <Tip label={t`Add music`} />
        </button>
        <button type="button" aria-label={t`Subtitles`} onClick={subtitleMenu} disabled={empty} className={toolButton}>
          <Subtitles className="w-4 h-4" />
          <Tip label={t`Subtitles`} />
        </button>
        <span className="w-px h-5 mx-1.5 bg-zinc-200 dark:bg-white/10" />
        <button type="button" aria-label={t`Auto edit`} onClick={autoEdit} disabled={empty} className={toolButton}>
          <Sparkles className="w-4 h-4" />
          <Tip label={t`Auto edit: order clips, add fades and subtitles`} />
        </button>
        <div className="flex-1" />
        <button type="button" aria-label={t`Zoom out`} onClick={() => setPps((v) => Math.max(3, v / 1.3))} className={toolButton}>
          <ZoomOut className="w-4 h-4" />
          <Tip label={t`Zoom out`} />
        </button>
        <button type="button" aria-label={t`Fit to window`} onClick={() => total > 0 && setPps(Math.min(80, Math.max(3, (window.innerWidth - 220) / total)))} className={toolButton}>
          <Maximize className="w-4 h-4" />
          <Tip label={t`Fit to window`} />
        </button>
        <button type="button" aria-label={t`Zoom in`} onClick={() => setPps((v) => Math.min(240, v * 1.3))} className={toolButton}>
          <ZoomIn className="w-4 h-4" />
          <Tip label={t`Zoom in`} align="end" />
        </button>
        <button
          type="button"
          disabled={empty || isBackgroundBusy}
          onClick={() => setExportOpen(true)}
          className="ml-2 flex items-center gap-1.5 h-8 px-3.5 rounded-lg bg-navi text-white text-[13px] font-semibold hover:brightness-110 disabled:opacity-40 disabled:pointer-events-none transition"
        >
          <Film className="w-4 h-4" /> <Trans>Export</Trans>
        </button>
      </div>

      <div className="flex flex-1 min-h-0">
        <div className="flex-1 min-w-0 flex flex-col bg-zinc-50 dark:bg-[#09090b]">
          <Preview timeline={view} projectDir={dir} />
        </div>
        <aside className="w-72 shrink-0 flex flex-col min-h-0 border-l border-zinc-200 dark:border-white/5">
          <Inspector
            timeline={timeline}
            selection={selection}
            onSelect={setSelection}
            commit={commit}
            onDuplicate={duplicate}
            onRemoveSegment={removeSegment}
            onSaveSrt={saveSrt}
          />
        </aside>
      </div>

      <div className="h-[228px] shrink-0 flex flex-col border-t border-zinc-200 dark:border-white/5">
        <TimelinePane
          timeline={view}
          projectDir={dir}
          selection={selection}
          pps={pps || 20}
          onZoom={setPps}
          onSelect={setSelection}
          setDraft={setDraft}
          commit={commit}
          onSegmentMenu={segmentMenu}
          onCueMenu={cueMenu}
          onLaneMenu={laneMenu}
        />
      </div>

      {musicOpen && <MusicPicker onPick={useLibraryTrack} onChooseFile={addMusicFile} onClose={() => setMusicOpen(false)} />}
      {exportOpen && <ExportDialog timeline={timeline} projectDir={dir} projectName={metadata.project_name} onClose={() => setExportOpen(false)} />}
    </div>
  );
}
