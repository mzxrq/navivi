import { useEffect, useRef, useState } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import { join } from "@tauri-apps/api/path";
import { readTextFile, rename, writeTextFile } from "@tauri-apps/plugin-fs";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Dialog, dialogButton } from "../../components/ui/Dialog";
import { Checkbox } from "../../components/ui/Checkbox";
import { Lock, Pause, Play, Unlock } from "../../components/ui/icons";
import { fileSystem } from "../../config/constants";
import { useUI } from "../../hooks/useUI";

type Piece = { text: string; src: string; locked: boolean };
type Manifest = { voice?: unknown; pieces?: { text: string; takes: string[]; locked?: boolean }[] };

// Mirrors voice_pieces.py: <project>/.navivi/voice_pieces/<narration file stem>/pieces.json, sentences in order.
async function readManifest(dir: string, file: string): Promise<{ path: string; data: Manifest; pieces: Piece[] }> {
  const folder = await join(dir, fileSystem.metaFolder, "voice_pieces", file);
  const path = await join(folder, "pieces.json");
  try {
    const data: Manifest = JSON.parse(await readTextFile(path));
    const kept = (data?.pieces ?? []).filter((p) => p.takes?.length);
    const pieces = await Promise.all(kept.map(async (p) => ({ text: p.text, locked: !!p.locked, src: convertFileSrc(await join(folder, p.takes[0])) })));
    return { path, data: { ...data, pieces: kept }, pieces };
  } catch {
    return { path, data: {}, pieces: [] };
  }
}

/** Pick sentences of a narration file (`file` = its name without .wav) to voice again, listening to each first.
 *  A locked sentence keeps its take even when the whole narration is made again (pipeline --force). */
export function VoicePiecesDialog({ dir, file, title, onRedo, onClose }: { dir: string; file: string; title: string; onRedo: (pieces: number[]) => void; onClose: () => void }) {
  const { showToast } = useUI();
  const [manifest, setManifest] = useState<{ path: string; data: Manifest } | null>(null);
  const [pieces, setPieces] = useState<Piece[] | null>(null);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [playing, setPlaying] = useState<number | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    void readManifest(dir, file).then(({ path, data, pieces }) => (setManifest({ path, data }), setPieces(pieces)));
    return () => audio.current?.pause();
  }, [dir, file]);

  const play = (i: number) => {
    audio.current?.pause();
    if (playing === i) return setPlaying(null);
    const a = new Audio(pieces![i].src);
    a.onended = () => setPlaying(null);
    audio.current = a;
    setPlaying(i);
    void a.play().catch(() => setPlaying(null));
  };
  const toggle = (i: number, on: boolean) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (on) next.add(i);
      else next.delete(i);
      return next;
    });

  const lock = async (i: number) => {
    if (!manifest || !pieces) return;
    const locked = !pieces[i].locked;
    const data: Manifest = { ...manifest.data, pieces: manifest.data.pieces!.map((p, j) => (j === i ? { ...p, locked } : p)) };
    try {
      await writeTextFile(`${manifest.path}.part`, JSON.stringify(data, null, 2));
      await rename(`${manifest.path}.part`, manifest.path);
    } catch (e) {
      return showToast(t`Could not save the lock: ${String(e)}`, "error");
    }
    setManifest({ ...manifest, data });
    setPieces(pieces.map((p, j) => (j === i ? { ...p, locked } : p)));
    if (locked) toggle(i, false);
  };

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
          <button
            type="button"
            className={dialogButton.primary}
            disabled={picked.size === 0}
            onClick={() => (onRedo([...picked].sort((a, b) => a - b)), onClose())}
          >
            {picked.size === 1 ? t`Voice 1 sentence again` : t`Voice ${picked.size} sentences again`}
          </button>
        </>
      }
    >
      {pieces === null ? null : pieces.length === 0 ? (
        <p className="text-[13px] text-zinc-500 dark:text-zinc-400">
          <Trans>No sentences are kept for this narration yet. Make its narration again once, and its sentences show up here.</Trans>
        </p>
      ) : (
        <div className="max-h-[50vh] overflow-y-auto -mx-1 flex flex-col">
          {pieces.map((p, i) => (
            <label key={i} className="flex items-start gap-2.5 px-1 py-1.5 rounded-md hover:bg-zinc-50 dark:hover:bg-white/5 cursor-pointer">
              <span className="pt-0.5">
                <Checkbox checked={picked.has(i)} disabled={p.locked} onChange={(on) => toggle(i, on)} label={p.text} />
              </span>
              <button
                type="button"
                aria-label={playing === i ? t`Stop` : t`Listen`}
                title={playing === i ? t`Stop` : t`Listen`}
                onClick={(e) => (e.preventDefault(), play(i))}
                className={`w-6 h-6 shrink-0 rounded-md flex items-center justify-center transition-colors ${
                  playing === i ? "bg-navi/10 text-navi" : "text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-white/5"
                }`}
              >
                {playing === i ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
              </button>
              <span className="flex-1 min-w-0 text-[13px] leading-snug text-zinc-800 dark:text-zinc-200">{p.text}</span>
              <button
                type="button"
                aria-label={p.locked ? t`Unlock` : t`Lock this take`}
                title={p.locked ? t`Unlock` : t`Lock this take`}
                onClick={(e) => (e.preventDefault(), void lock(i))}
                className={`w-6 h-6 shrink-0 rounded-md flex items-center justify-center transition-colors ${
                  p.locked ? "bg-navi/10 text-navi" : "text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-white/5"
                }`}
              >
                {p.locked ? <Lock className="w-3.5 h-3.5" /> : <Unlock className="w-3.5 h-3.5" />}
              </button>
            </label>
          ))}
        </div>
      )}
    </Dialog>
  );
}
