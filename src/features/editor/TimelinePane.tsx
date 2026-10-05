import { useEffect, useMemo, useRef, useState } from "react";
import { t } from "@lingui/core/macro";
import { Music, Subtitles, Type, Video, Volume2, VolumeX } from "../../components/ui/icons";
import {
  anchorCue,
  layout,
  MIN_CUE,
  MIN_SEGMENT,
  newId,
  placedCues,
  PlacedCue,
  placedTexts,
  PlacedText,
  TextClip,
  Segment,
  SegmentKind,
  TimelineData,
} from "./model";
import { formatTime, mediaUrl, player, usePlayerTime, usePlaying } from "./player";

export type Selection = { type: "segment" | "text"; id: string } | { type: "cue"; id: string; ids?: string[] } | null;

export const selectedCueIds = (s: Selection): string[] => (s?.type === "cue" ? (s.ids ?? [s.id]) : []);
export const cueSelection = (ids: string[]): Selection => (ids.length ? { type: "cue", id: ids[0], ids } : null);
export type Lane = "video" | "text" | "subtitle" | "music";

interface PaneProps {
  timeline: TimelineData;
  projectDir: string;
  selection: Selection;
  pps: number;
  onZoom: (pps: number) => void;
  onSelect: (s: Selection) => void;
  setDraft: (t: TimelineData | null) => void;
  commit: (t: TimelineData) => void;
  onSegmentMenu: (e: React.MouseEvent, seg: Segment) => void;
  onCueMenu: (e: React.MouseEvent, cue: PlacedCue) => void;
  onTextMenu: (e: React.MouseEvent, text: PlacedText) => void;
  onLaneMenu: (e: React.MouseEvent, time: number, lane: Lane) => void;
  onAddText: (time: number) => void;
}

const LABEL_W = 36;
const GUTTER = 120;
const LANE = { ruler: 26, video: 68, voice: 26, text: 34, subtitle: 34, music: 26 };
// Lanes plus room for the horizontal scrollbar.
export const TIMELINE_HEIGHT = Object.values(LANE).reduce((a, b) => a + b, 0) + 48;

const kindColor: Record<SegmentKind, string> = {
  intro: "bg-violet-500",
  overview: "bg-sky-500",
  route: "bg-navi",
  attraction: "bg-amber-500",
  outro: "bg-violet-500",
  custom: "bg-zinc-500",
};

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

function rulerStep(pps: number): number {
  const steps = [1, 2, 5, 10, 15, 30, 60, 120, 300];
  return steps.find((s) => s * pps >= 70) ?? 600;
}

function Playhead({ scroller, pps }: { scroller: React.RefObject<HTMLDivElement | null>; pps: number }) {
  const time = usePlayerTime();
  const playing = usePlaying();
  const x = time * pps;
  useEffect(() => {
    const el = scroller.current;
    if (!playing || !el) return;
    const visible = x - el.scrollLeft;
    if (visible > el.clientWidth - 60 || visible < 0) el.scrollLeft = Math.max(0, x - 120);
  }, [x, playing, scroller]);
  return (
    <div className="absolute top-0 bottom-0 z-30 pointer-events-none" style={{ left: LABEL_W + x }}>
      <div className="absolute -top-0 -left-[5px] w-[11px] h-[10px] bg-navi" style={{ clipPath: "polygon(0 0,100% 0,50% 100%)" }} />
      <div className="w-px h-full bg-navi" />
    </div>
  );
}

export function TimelinePane(props: PaneProps) {
  const { timeline, projectDir, selection, pps, onSelect, setDraft, commit } = props;
  const scroller = useRef<HTMLDivElement>(null);
  const lanesRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ id: string; dx: number; drop: number } | null>(null);
  const [marquee, setMarquee] = useState<{ a: number; b: number } | null>(null);
  const pickedCues = useMemo(() => new Set(selectedCueIds(selection)), [selection]);
  const latest = useRef(timeline);
  latest.current = timeline;

  const { placed, total } = useMemo(() => layout(timeline), [timeline]);
  const cues = useMemo(() => placedCues(timeline, placed), [timeline, placed]);
  const texts = useMemo(() => placedTexts(timeline, placed), [timeline, placed]);
  const width = Math.max(total * pps + GUTTER, 600);

  const timeAt = (clientX: number) => {
    const rect = lanesRef.current?.getBoundingClientRect();
    return rect ? Math.max(0, (clientX - rect.left - LABEL_W) / pps) : 0;
  };

  const startDrag = (e: React.PointerEvent, onMove: (dt: number, ev: PointerEvent) => void, onEnd: (moved: boolean) => void) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    const x0 = e.clientX;
    let moved = false;
    const move = (ev: PointerEvent) => {
      const dx = ev.clientX - x0;
      if (!moved && Math.abs(dx) < 3) return;
      moved = true;
      onMove(dx / pps, ev);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      onEnd(moved);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const patchSegment = (base: TimelineData, id: string, patch: Partial<Segment>): TimelineData => ({
    ...base,
    segments: base.segments.map((s) => (s.id === id ? { ...s, ...patch } : s)),
  });

  const seekFromRuler = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    player.set({ playing: false, time: clamp(timeAt(e.clientX), 0, total) });
    const move = (ev: PointerEvent) => player.set({ time: clamp(timeAt(ev.clientX), 0, total) });
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const onSegmentDown = (e: React.PointerEvent, index: number) => {
    const base = timeline;
    const basePlaced = layout(base).placed;
    const me = basePlaced[index];
    onSelect({ type: "segment", id: me.seg.id });
    let drop = index;
    startDrag(
      e,
      (dt, ev) => {
        const pointer = timeAt(ev.clientX);
        const others = basePlaced.filter((_, i) => i !== index);
        drop = others.findIndex((p) => pointer < p.start + p.length / 2);
        if (drop < 0) drop = others.length;
        setDrag({ id: me.seg.id, dx: dt * pps, drop });
      },
      (moved) => {
        setDrag(null);
        if (!moved || drop === index) return;
        const segs = base.segments.filter((_, i) => i !== index);
        segs.splice(drop, 0, me.seg);
        commit({ ...base, segments: segs });
      },
    );
  };

  const onTrim = (e: React.PointerEvent, seg: Segment, edge: "in" | "out") => {
    const base = timeline;
    onSelect({ type: "segment", id: seg.id });
    startDrag(
      e,
      (dt) => {
        const patch =
          edge === "in"
            ? { trimIn: clamp(seg.trimIn + dt, 0, seg.trimOut - MIN_SEGMENT) }
            : { trimOut: clamp(seg.trimOut + dt, seg.trimIn + MIN_SEGMENT, seg.videoDuration) };
        setDraft(patchSegment(base, seg.id, patch));
      },
      (moved) => {
        if (moved) commit(latest.current);
        setDraft(null);
      },
    );
  };

  const onVoiceDown = (e: React.PointerEvent, seg: Segment) => {
    const base = timeline;
    onSelect({ type: "segment", id: seg.id });
    startDrag(
      e,
      (dt) => setDraft(patchSegment(base, seg.id, { audioOffset: Math.max(0, +(seg.audioOffset + dt).toFixed(2)) })),
      (moved) => {
        if (moved) commit(latest.current);
        setDraft(null);
      },
    );
  };

  const onCueDown = (e: React.PointerEvent, cue: PlacedCue, mode: "move" | "start" | "end") => {
    const base = timeline;
    const picked = selectedCueIds(selection);
    if (mode === "move" && (e.shiftKey || e.ctrlKey || e.metaKey)) {
      e.stopPropagation();
      onSelect(cueSelection(picked.includes(cue.id) ? picked.filter((id) => id !== cue.id) : [...picked, cue.id]));
      return;
    }
    const group = mode === "move" && picked.length > 1 && picked.includes(cue.id) ? cues.filter((c) => picked.includes(c.id)) : [cue];
    if (group.length === 1) onSelect(cueSelection([cue.id]));
    const from = Math.min(...group.map((c) => c.globalStart));
    const to = Math.max(...group.map((c) => c.globalEnd));
    const apply = (shift: number) => {
      const moved = new Map(group.map((c) => [c.id, anchorCue(base, c, c.globalStart + shift, c.globalEnd + shift, false)]));
      setDraft({ ...base, subtitles: base.subtitles.map((c) => moved.get(c.id) ?? c) });
    };
    const resize = (g0: number, g1: number) => {
      const next = anchorCue(base, cue, g0, g1, true);
      setDraft({ ...base, subtitles: base.subtitles.map((c) => (c.id === cue.id ? next : c)) });
    };
    startDrag(
      e,
      (dt) => {
        if (mode === "move") apply(clamp(dt, -from, Math.max(-from, total - to)));
        else if (mode === "start") resize(clamp(cue.globalStart + dt, 0, cue.globalEnd - MIN_CUE), cue.globalEnd);
        else resize(cue.globalStart, clamp(cue.globalEnd + dt, cue.globalStart + MIN_CUE, total));
      },
      (moved) => {
        if (moved) commit(latest.current);
        setDraft(null);
      },
    );
  };

  const onCueLaneDown = (e: React.PointerEvent) => {
    if (e.target !== e.currentTarget) return;
    const t0 = timeAt(e.clientX);
    const kept = e.shiftKey || e.ctrlKey || e.metaKey ? selectedCueIds(selection) : [];
    startDrag(
      e,
      (_dt, ev) => {
        const t1 = timeAt(ev.clientX);
        const [a, b] = t0 < t1 ? [t0, t1] : [t1, t0];
        setMarquee({ a, b });
        const hit = cues.filter((c) => c.globalEnd > a && c.globalStart < b).map((c) => c.id);
        onSelect(cueSelection([...new Set([...kept, ...hit])]));
      },
      (moved) => {
        setMarquee(null);
        if (!moved && !kept.length) onSelect(null);
      },
    );
  };

  const onTextDown = (e: React.PointerEvent, item: PlacedText, mode: "move" | "start" | "end") => {
    const base = timeline;
    onSelect({ type: "text", id: item.id });
    const apply = (g0: number, g1: number) => {
      const next: TextClip = anchorCue(base, item, g0, g1, mode !== "move");
      setDraft({ ...base, texts: base.texts.map((x) => (x.id === item.id ? { ...x, segmentId: next.segmentId, start: next.start, end: next.end } : x)) });
    };
    startDrag(
      e,
      (dt) => {
        if (mode === "move") {
          const len = item.globalEnd - item.globalStart;
          const g0 = clamp(item.globalStart + dt, 0, Math.max(0, total - len));
          apply(g0, g0 + len);
        } else if (mode === "start") {
          apply(clamp(item.globalStart + dt, 0, item.globalEnd - MIN_CUE), item.globalEnd);
        } else {
          apply(item.globalStart, clamp(item.globalEnd + dt, item.globalStart + MIN_CUE, total));
        }
      },
      (moved) => {
        if (moved) commit(latest.current);
        setDraft(null);
      },
    );
  };

  const addCueAt = (time: number) => {
    const at = layout(timeline).placed.find((p) => time < p.start + p.length) ?? placed[placed.length - 1];
    if (!at) return;
    const cue = anchorCue(
      timeline,
      { id: newId(), segmentId: at.seg.id, start: 0, end: 0, text: t`New subtitle` },
      time,
      time + 2,
    );
    commit({ ...timeline, subtitles: [...timeline.subtitles, cue] });
    onSelect({ type: "cue", id: cue.id });
  };

  const step = rulerStep(pps);
  const ticks = Array.from({ length: Math.ceil(width / pps / step) + 1 }, (_, i) => i * step);

  const dropX =
    drag && placed.length
      ? (() => {
          const others = placed.filter((p) => p.seg.id !== drag.id);
          const at = others[drag.drop];
          return (at ? at.start : others.length ? others[others.length - 1].start + others[others.length - 1].length : 0) * pps;
        })()
      : null;

  const laneLabel = "sticky left-0 z-20 flex items-center justify-center bg-zinc-50 dark:bg-[#09090b] text-zinc-400 dark:text-zinc-500";

  return (
    <div
      ref={scroller}
      className="relative flex-1 min-h-0 overflow-auto custom-scrollbar bg-zinc-50 dark:bg-[#09090b] select-none"
      onWheel={(e) => {
        if (!e.ctrlKey) return;
        e.preventDefault();
        props.onZoom(clamp(pps * (e.deltaY < 0 ? 1.15 : 1 / 1.15), 3, 240));
      }}
    >
      <div ref={lanesRef} className="relative" style={{ width, minWidth: "100%" }}>
        <Playhead scroller={scroller} pps={pps} />

        <div className="relative flex border-b border-zinc-200/70 dark:border-white/5 cursor-pointer" style={{ height: LANE.ruler }} onPointerDown={seekFromRuler}>
          <div className={laneLabel} style={{ width: LABEL_W }} />
          <div className="relative flex-1">
            {ticks.map((s) => (
              <div key={s} className="absolute top-0 bottom-0 border-l border-zinc-200 dark:border-white/10 pl-1.5 text-[10px] tabular-nums text-zinc-400 pointer-events-none" style={{ left: s * pps }}>
                <span className="leading-[26px]">{formatTime(s, false)}</span>
              </div>
            ))}
          </div>
        </div>

        <div
          className="relative flex border-b border-zinc-200/70 dark:border-white/5"
          style={{ height: LANE.video }}
          onPointerDown={(e) => {
            if (e.target === e.currentTarget || (e.target as HTMLElement).dataset.lane) onSelect(null);
          }}
          onContextMenu={(e) => props.onLaneMenu(e, timeAt(e.clientX), "video")}
        >
          <div className={laneLabel} style={{ width: LABEL_W }}>
            <Video className="w-3.5 h-3.5" />
          </div>
          <div className="relative flex-1" data-lane="video">
            {placed.map((p, i) => {
              const dragging = drag?.id === p.seg.id;
              const selected = selection?.type === "segment" && selection.id === p.seg.id;
              const thumb = mediaUrl(projectDir, p.seg.video);
              return (
                <div
                  key={p.seg.id}
                  onPointerDown={(e) => onSegmentDown(e, i)}
                  onContextMenu={(e) => {
                    onSelect({ type: "segment", id: p.seg.id });
                    props.onSegmentMenu(e, p.seg);
                  }}
                  className={`group/seg absolute top-1.5 bottom-1.5 rounded-lg overflow-hidden bg-zinc-200 dark:bg-zinc-800 cursor-grab active:cursor-grabbing transition-none ${
                    selected ? "ring-2 ring-navi" : "ring-1 ring-black/10 dark:ring-white/10"
                  } ${dragging ? "z-40 opacity-80 shadow-lg" : ""}`}
                  style={{
                    left: p.start * pps + 1,
                    width: Math.max(8, p.length * pps - 2),
                    transform: dragging ? `translateX(${drag!.dx}px)` : undefined,
                  }}
                >
                  <video src={`${thumb}#t=${p.seg.trimIn + 0.1}`} preload="metadata" muted playsInline className="absolute inset-0 w-full h-full object-cover opacity-60 pointer-events-none" />
                  <div className={`absolute left-0 top-0 bottom-0 w-1 ${kindColor[p.seg.kind]}`} />
                  <div className="absolute inset-x-2 top-1 flex items-center gap-1 text-[11px] font-medium text-zinc-900 dark:text-white drop-shadow-sm pointer-events-none">
                    <span className="truncate">{p.seg.label}</span>
                    {p.seg.muted && <VolumeX className="w-3 h-3 shrink-0" />}
                  </div>
                  <div className="absolute left-2 bottom-1 text-[10px] tabular-nums text-zinc-700 dark:text-zinc-200 pointer-events-none">{p.length.toFixed(1)}s</div>
                  {p.seg.fadeIntoNext > 0 && (
                    <div className="absolute right-0 bottom-0 w-4 h-4 bg-navi/70 pointer-events-none" style={{ clipPath: "polygon(100% 0,100% 100%,0 100%)" }} title={t`Fades into the next clip`} />
                  )}
                  <div onPointerDown={(e) => onTrim(e, p.seg, "in")} className="absolute left-0 top-0 bottom-0 w-2 cursor-ew-resize hover:bg-navi/60" />
                  <div onPointerDown={(e) => onTrim(e, p.seg, "out")} className="absolute right-0 top-0 bottom-0 w-2 cursor-ew-resize hover:bg-navi/60" />
                </div>
              );
            })}
            {dropX !== null && <div className="absolute top-0 bottom-0 w-0.5 bg-navi z-40 pointer-events-none" style={{ left: dropX }} />}
            {!placed.length && <div className="absolute inset-0 flex items-center px-3 text-[12px] text-zinc-400">{t`No clips yet`}</div>}
          </div>
        </div>

        <div className="relative flex border-b border-zinc-200/70 dark:border-white/5" style={{ height: LANE.voice }}>
          <div className={laneLabel} style={{ width: LABEL_W }}>
            <Volume2 className="w-3.5 h-3.5" />
          </div>
          <div className="relative flex-1">
            {placed
              .filter((p) => p.seg.audio)
              .map((p) => (
                <div
                  key={p.seg.id}
                  onPointerDown={(e) => onVoiceDown(e, p.seg)}
                  title={t`Drag to shift the narration`}
                  className={`absolute top-1 bottom-1 rounded-md cursor-ew-resize text-[10px] leading-[18px] px-1.5 truncate ${
                    p.seg.muted ? "bg-zinc-300/60 dark:bg-zinc-700/60 text-zinc-500" : "bg-emerald-500/25 text-emerald-800 dark:text-emerald-300 ring-1 ring-emerald-500/40"
                  }`}
                  style={{ left: (p.start + p.seg.audioOffset) * pps, width: Math.max(6, (p.seg.audioDuration ?? 0) * pps - 2) }}
                >
                  {p.seg.label}
                </div>
              ))}
          </div>
        </div>

        <div
          className="relative flex border-b border-zinc-200/70 dark:border-white/5"
          style={{ height: LANE.text }}
          onDoubleClick={(e) => {
            if (e.target === e.currentTarget || (e.target as HTMLElement).dataset.lane) props.onAddText(timeAt(e.clientX));
          }}
          onContextMenu={(e) => props.onLaneMenu(e, timeAt(e.clientX), "text")}
        >
          <div className={laneLabel} style={{ width: LABEL_W }}>
            <Type className="w-3.5 h-3.5" />
          </div>
          <div className="relative flex-1" data-lane="text">
            {texts.map((x) => {
              const selected = selection?.type === "text" && selection.id === x.id;
              return (
                <div
                  key={x.id}
                  onPointerDown={(e) => onTextDown(e, x, "move")}
                  onContextMenu={(e) => {
                    onSelect({ type: "text", id: x.id });
                    props.onTextMenu(e, x);
                  }}
                  className={`absolute top-1 bottom-1 rounded-md px-1.5 text-[11px] leading-[22px] truncate cursor-grab bg-fuchsia-500/15 text-zinc-800 dark:text-zinc-100 ${
                    selected ? "ring-2 ring-fuchsia-500" : "ring-1 ring-fuchsia-500/30"
                  }`}
                  style={{ left: x.globalStart * pps, width: Math.max(6, (x.globalEnd - x.globalStart) * pps - 1) }}
                >
                  <span className="font-semibold">{x.title.text}</span>
                  {x.subtitle.text && <span className="opacity-70"> · {x.subtitle.text}</span>}
                  <div onPointerDown={(e) => onTextDown(e, x, "start")} className="absolute left-0 top-0 bottom-0 w-1.5 cursor-ew-resize hover:bg-fuchsia-500/60" />
                  <div onPointerDown={(e) => onTextDown(e, x, "end")} className="absolute right-0 top-0 bottom-0 w-1.5 cursor-ew-resize hover:bg-fuchsia-500/60" />
                </div>
              );
            })}
            {!texts.length && <div className="absolute inset-0 flex items-center px-3 text-[12px] text-zinc-400 pointer-events-none">{t`Double-click to add a title`}</div>}
          </div>
        </div>

        <div
          className="relative flex border-b border-zinc-200/70 dark:border-white/5"
          style={{ height: LANE.subtitle }}
          onDoubleClick={(e) => {
            if (e.target === e.currentTarget || (e.target as HTMLElement).dataset.lane) addCueAt(timeAt(e.clientX));
          }}
          onContextMenu={(e) => props.onLaneMenu(e, timeAt(e.clientX), "subtitle")}
        >
          <div className={laneLabel} style={{ width: LABEL_W }}>
            <Subtitles className="w-3.5 h-3.5" />
          </div>
          <div className="relative flex-1" data-lane="subtitle" onPointerDown={onCueLaneDown}>
            {marquee && <div className="absolute top-0 bottom-0 bg-navi/10 border border-navi/50 rounded-sm pointer-events-none" style={{ left: marquee.a * pps, width: (marquee.b - marquee.a) * pps }} />}
            {cues.map((c) => {
              const selected = pickedCues.has(c.id);
              return (
                <div
                  key={c.id}
                  onPointerDown={(e) => onCueDown(e, c, "move")}
                  onContextMenu={(e) => {
                    if (!pickedCues.has(c.id)) onSelect(cueSelection([c.id]));
                    props.onCueMenu(e, c);
                  }}
                  className={`absolute top-1 bottom-1 rounded-md px-1.5 text-[11px] leading-[22px] truncate cursor-grab bg-navi/15 text-zinc-800 dark:text-zinc-100 ${
                    selected ? "ring-2 ring-navi" : "ring-1 ring-navi/30"
                  }`}
                  style={{ left: c.globalStart * pps, width: Math.max(6, (c.globalEnd - c.globalStart) * pps - 1) }}
                >
                  {c.style && <span title={t`Has its own style`} className="inline-block w-1.5 h-1.5 mr-1 mb-px rounded-full bg-amber-500 align-middle" />}
                  {c.text}
                  <div onPointerDown={(e) => onCueDown(e, c, "start")} className="absolute left-0 top-0 bottom-0 w-1.5 cursor-ew-resize hover:bg-navi/60" />
                  <div onPointerDown={(e) => onCueDown(e, c, "end")} className="absolute right-0 top-0 bottom-0 w-1.5 cursor-ew-resize hover:bg-navi/60" />
                </div>
              );
            })}
            {!cues.length && <div className="absolute inset-0 flex items-center px-3 text-[12px] text-zinc-400 pointer-events-none">{t`Double-click to add a subtitle`}</div>}
          </div>
        </div>

        <div className="relative flex" style={{ height: LANE.music }} onContextMenu={(e) => props.onLaneMenu(e, timeAt(e.clientX), "music")}>
          <div className={laneLabel} style={{ width: LABEL_W }}>
            <Music className="w-3.5 h-3.5" />
          </div>
          <div className="relative flex-1">
            {timeline.music && (
              <div className="absolute top-1 bottom-1 left-0 rounded-md bg-violet-500/20 ring-1 ring-violet-500/40 text-[10px] leading-[18px] px-1.5 truncate text-violet-800 dark:text-violet-300" style={{ width: Math.max(20, total * pps) }}>
                {timeline.music.label}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
