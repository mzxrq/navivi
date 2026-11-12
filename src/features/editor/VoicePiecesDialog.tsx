import { useEffect, useRef, useState } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import { join } from "@tauri-apps/api/path";
import { readTextFile, rename, writeTextFile } from "@tauri-apps/plugin-fs";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Dialog, dialogButton, dialogInput } from "../../components/ui/Dialog";
import { Checkbox } from "../../components/ui/Checkbox";
import { ChevronLeft, ChevronRight, Loader2, Lock, Pause, Play, Search, Unlock } from "../../components/ui/icons";
import { fileSystem } from "../../config/constants";
import { useUI } from "../../hooks/useUI";

type Manifest = { voice?: unknown; pieces?: { text: string; takes: string[]; locked?: boolean }[] };
/** One narration file (`file` = its name without .wav), `label` shown beside its sentences when there are several.
 *  No `redo`: its sentences can be heard and locked, not voiced again from here (an out-of-date timeline clip). */
export type PiecesSource = { file: string; label?: string; redo?: (pieces: number[]) => void };
type Row = { source: number; index: number; text: string; src: string; locked: boolean };

// Mirrors voice_pieces.py: <project>/.navivi/voice_pieces/<narration file stem>/pieces.json, sentences in order.
async function readManifest(dir: string, file: string) {
  const folder = await join(dir, fileSystem.metaFolder, "voice_pieces", file);
  const path = await join(folder, "pieces.json");
  try {
    const data: Manifest = JSON.parse(await readTextFile(path));
    const kept = (data?.pieces ?? []).filter((p) => p.takes?.length);
    const pieces = await Promise.all(kept.map(async (p) => ({ text: p.text, locked: !!p.locked, src: convertFileSrc(await join(folder, p.takes[0])) })));
    return { path, data: { ...data, pieces: kept }, pieces };
  } catch {
    return { path, data: {} as Manifest, pieces: [] };
  }
}

const key = (r: Pick<Row, "source" | "index">) => `${r.source}:${r.index}`;
const SIZES = [40, 100, Infinity];

/** Pick sentences of one or more narration files to voice again, listening to each first.
 *  A locked sentence keeps its take even when the whole narration is made again (pipeline --force). */
/** `busy`: narration files being voiced again right now; their sentences can't be ticked or locked, and reload when done. */
export function VoicePiecesDialog({ dir, sources, title, busy, onClose }: { dir: string; sources: PiecesSource[]; title: string; busy: ReadonlySet<string>; onClose: () => void }) {
  const { showToast } = useUI();
  const [manifests, setManifests] = useState<{ path: string; data: Manifest }[]>([]);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [playing, setPlaying] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [size, setSize] = useState(SIZES[0]);

  useEffect(() => {
    void Promise.all(sources.map((s) => readManifest(dir, s.file))).then((all) => {
      setManifests(all.map(({ path, data }) => ({ path, data })));
      setRows(all.flatMap(({ pieces }, source) => pieces.map((p, index) => ({ source, index, ...p }))));
    });
    return () => audio.current?.pause();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dir, sources.map((s) => s.file).join("|"), [...busy].join("|")]);

  const play = (r: Row) => {
    audio.current?.pause();
    if (playing === key(r)) return setPlaying(null);
    const a = new Audio(r.src);
    a.onended = () => setPlaying(null);
    audio.current = a;
    setPlaying(key(r));
    void a.play().catch(() => setPlaying(null));
  };
  const toggle = (k: string, on: boolean) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (on) next.add(k);
      else next.delete(k);
      return next;
    });

  const lock = async (r: Row) => {
    const m = manifests[r.source];
    if (!m || !rows) return;
    const locked = !r.locked;
    const data: Manifest = { ...m.data, pieces: m.data.pieces!.map((p, j) => (j === r.index ? { ...p, locked } : p)) };
    try {
      await writeTextFile(`${m.path}.part`, JSON.stringify(data, null, 2));
      await rename(`${m.path}.part`, m.path);
    } catch (e) {
      return showToast(t`Could not save the lock: ${String(e)}`, "error");
    }
    setManifests(manifests.map((x, i) => (i === r.source ? { ...x, data } : x)));
    setRows(rows.map((x) => (key(x) === key(r) ? { ...x, locked } : x)));
    if (locked) toggle(key(r), false);
  };

  const redo = () => {
    sources.forEach((s, i) => {
      if (busy.has(s.file)) return;
      const pieces = (rows ?? []).filter((r) => r.source === i && picked.has(key(r))).map((r) => r.index);
      if (pieces.length) s.redo?.(pieces);
    });
    onClose();
  };

  const many = sources.length > 1;
  // Matches the clip's name, its narration file or the sentence itself; ticks survive searching and paging.
  const q = query.trim().toLowerCase();
  const shown = !rows || !q ? rows ?? [] : rows.filter((r) => [sources[r.source].label ?? "", sources[r.source].file, r.text].some((x) => x.toLowerCase().includes(q)));
  const pages = Math.max(1, Math.ceil(shown.length / size));
  const at = Math.min(page, pages - 1);
  const first = size === Infinity ? 0 : at * size;
  const pageRows = shown.slice(first, first + size);
  const pager = "w-7 h-7 rounded-md flex items-center justify-center text-zinc-500 hover:bg-zinc-100 dark:hover:bg-white/5 disabled:opacity-40 disabled:pointer-events-none";
  return (
    <Dialog
      title={title}
      subtitle={t`Listen to each one, tick the ones to redo. The others keep their voice. Lock a good one to keep it even when everything is made again.`}
      width="w-[min(40rem,calc(100vw-2rem))]"
      onClose={onClose}
      footer={
        <>
          <button type="button" className={dialogButton.secondary} onClick={onClose}>
            <Trans>Cancel</Trans>
          </button>
          <button type="button" className={dialogButton.primary} disabled={picked.size === 0} onClick={redo}>
            {picked.size === 1 ? t`Voice 1 sentence again` : t`Voice ${picked.size} sentences again`}
          </button>
        </>
      }
    >
      {rows === null ? null : rows.length === 0 ? (
        <p className="text-[13px] text-zinc-500 dark:text-zinc-400">
          <Trans>No sentences are kept for this narration yet. Make its narration again once, and its sentences show up here.</Trans>
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {(many || rows.length > SIZES[0]) && (
            <>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-zinc-400 pointer-events-none" />
              <input
                autoFocus
                value={query}
                onChange={(e) => (setQuery(e.target.value), setPage(0))}
                placeholder={t`Search by clip, file or sentence`}
                className={`${dialogInput} pl-8`}
              />
            </div>
            <div className="flex items-center gap-1 text-[11px] text-zinc-500 dark:text-zinc-400">
              <span className="mr-auto">
                {shown.length ? t`${first + 1}–${first + pageRows.length} of ${shown.length}` : null}
              </span>
              <span className="mr-0.5">{t`Show`}</span>
              {SIZES.map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => (setSize(n), setPage(0))}
                  className={`h-6 px-2 rounded-md transition-colors ${size === n ? "bg-navi/10 text-navi" : "hover:bg-zinc-100 dark:hover:bg-white/5"}`}
                >
                  {n === Infinity ? t`All` : n}
                </button>
              ))}
              {pages > 1 && (
                <>
                  <button type="button" aria-label={t`Previous page`} title={t`Previous page`} className={`${pager} ml-1`} disabled={at === 0} onClick={() => setPage(at - 1)}>
                    <ChevronLeft className="w-3.5 h-3.5" />
                  </button>
                  <button type="button" aria-label={t`Next page`} title={t`Next page`} className={pager} disabled={at >= pages - 1} onClick={() => setPage(at + 1)}>
                    <ChevronRight className="w-3.5 h-3.5" />
                  </button>
                </>
              )}
            </div>
            </>
          )}
        <div className="max-h-[50vh] overflow-y-auto -mx-1 flex flex-col">
          {!pageRows.length && <p className="px-1 py-2 text-[13px] text-zinc-500 dark:text-zinc-400"><Trans>No sentences match.</Trans></p>}
          {pageRows.map((r) => {
            const k = key(r);
            const working = busy.has(sources[r.source].file);
            const stale = !sources[r.source].redo;
            return (
              <label key={k} className="flex items-start gap-2.5 px-1 py-1.5 rounded-md hover:bg-zinc-50 dark:hover:bg-white/5 cursor-pointer">
                <span className="pt-0.5">
                  <Checkbox checked={picked.has(k) && !working && !stale} disabled={r.locked || working || stale} onChange={(on) => toggle(k, on)} label={r.text} />
                </span>
                <button
                  type="button"
                  aria-label={playing === k ? t`Stop` : t`Listen`}
                  title={playing === k ? t`Stop` : t`Listen`}
                  onClick={(e) => (e.preventDefault(), play(r))}
                  className={`w-6 h-6 shrink-0 rounded-md flex items-center justify-center transition-colors ${
                    playing === k ? "bg-navi/10 text-navi" : "text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-white/5"
                  }`}
                >
                  {playing === k ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                </button>
                <span className="flex-1 min-w-0 text-[13px] leading-snug text-zinc-800 dark:text-zinc-200">
                  {r.text}
                  {many && sources[r.source].label && <span className="block text-[11px] text-zinc-400">{sources[r.source].label}</span>}
                  {stale && (
                    <span className="block text-[11px] text-amber-600 dark:text-amber-400">
                      <Trans>This clip is from before the stops changed: rebuild the timeline to voice it again.</Trans>
                    </span>
                  )}
                </span>
                {working ? (
                  <span title={t`Voicing again…`} className="w-6 h-6 shrink-0 flex items-center justify-center text-navi">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  </span>
                ) : (
                <button
                  type="button"
                  aria-label={r.locked ? t`Unlock` : t`Lock this take`}
                  title={r.locked ? t`Unlock` : t`Lock this take`}
                  onClick={(e) => (e.preventDefault(), void lock(r))}
                  className={`w-6 h-6 shrink-0 rounded-md flex items-center justify-center transition-colors ${
                    r.locked ? "bg-navi/10 text-navi" : "text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-white/5"
                  }`}
                >
                  {r.locked ? <Lock className="w-3.5 h-3.5" /> : <Unlock className="w-3.5 h-3.5" />}
                </button>
                )}
              </label>
            );
          })}
        </div>
        </div>
      )}
    </Dialog>
  );
}
