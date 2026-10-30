import { useEffect, useRef, useState } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import { join } from "@tauri-apps/api/path";
import { readTextFile } from "@tauri-apps/plugin-fs";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Dialog, dialogButton } from "../../components/ui/Dialog";
import { Checkbox } from "../../components/ui/Checkbox";
import { Pause, Play } from "../../components/ui/icons";
import { fileSystem } from "../../config/constants";
import type { RouteClip } from "../../services/stopRegen";

type Piece = { text: string; src: string };

// Mirrors voice_pieces.py: <project>/.navivi/voice_pieces/<narration file>/pieces.json, sentences in order.
async function readPieces(dir: string, clip: RouteClip): Promise<Piece[]> {
  const folder = await join(dir, fileSystem.metaFolder, "voice_pieces", clip === "intro" ? "00_intro_narration" : "00_overview_narration");
  try {
    const data = JSON.parse(await readTextFile(await join(folder, "pieces.json")));
    const pieces: { text: string; takes: string[] }[] = data?.pieces ?? [];
    return Promise.all(pieces.filter((p) => p.takes?.length).map(async (p) => ({ text: p.text, src: convertFileSrc(await join(folder, p.takes[0])) })));
  } catch {
    return [];
  }
}

/** Pick sentences of the intro / overview narration to voice again, listening to each first. */
export function VoicePiecesDialog({ dir, clip, onRedo, onClose }: { dir: string; clip: RouteClip; onRedo: (pieces: number[]) => void; onClose: () => void }) {
  const [pieces, setPieces] = useState<Piece[] | null>(null);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [playing, setPlaying] = useState<number | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    void readPieces(dir, clip).then(setPieces);
    return () => audio.current?.pause();
  }, [dir, clip]);

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

  return (
    <Dialog
      title={clip === "intro" ? t`Choose sentences of the intro to voice again` : t`Choose sentences of the overview to voice again`}
      subtitle={t`Listen to each one, tick the ones to redo. The others keep their voice.`}
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
                <Checkbox checked={picked.has(i)} onChange={(on) => toggle(i, on)} label={p.text} />
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
            </label>
          ))}
        </div>
      )}
    </Dialog>
  );
}
