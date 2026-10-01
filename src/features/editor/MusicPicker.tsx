import { useEffect, useMemo, useRef, useState } from "react";
import { convertFileSrc, invoke } from "@tauri-apps/api/core";
import { documentDir, join } from "@tauri-apps/api/path";
import { exists, mkdir, readDir, readTextFile } from "@tauri-apps/plugin-fs";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Dialog, dialogButton } from "../../components/ui/Dialog";
import { Folder, Loader2, Music, Pause, Play } from "../../components/ui/icons";

export interface LibraryTrack {
  title: string;
  abs: string;
  tags: string[];
  credit?: string;
  license?: string;
  url?: string;
}

const AUDIO = /\.(mp3|wav|m4a|aac|ogg|flac)$/i;

export async function musicFolder(): Promise<string> {
  return join(await documentDir(), "Navivi", "Music");
}

// Every audio file in the folder; library.json (optional) adds a title, tags and the credit for a file.
export async function loadMusicLibrary(): Promise<{ dir: string; tracks: LibraryTrack[] }> {
  const dir = await musicFolder();
  if (!(await exists(dir))) await mkdir(dir, { recursive: true });

  let manifest: any[] = [];
  try {
    const parsed = JSON.parse(await readTextFile(await join(dir, "library.json")));
    manifest = Array.isArray(parsed) ? parsed : (parsed.tracks ?? []);
  } catch {
    // no manifest: titles come from the file names
  }
  const meta = new Map<string, any>(manifest.filter((m) => m?.file).map((m) => [String(m.file).toLowerCase(), m]));

  const tracks: LibraryTrack[] = [];
  for (const entry of await readDir(dir)) {
    if (!entry.name || !AUDIO.test(entry.name)) continue;
    const m = meta.get(entry.name.toLowerCase());
    tracks.push({
      title: m?.title || entry.name.replace(/\.[^.]+$/, ""),
      abs: await join(dir, entry.name),
      tags: Array.isArray(m?.tags) ? m.tags.map(String) : [],
      credit: m?.credit,
      license: m?.license,
      url: m?.url,
    });
  }
  return { dir, tracks: tracks.sort((a, b) => a.title.localeCompare(b.title)) };
}

interface MusicPickerProps {
  onPick: (track: LibraryTrack) => void;
  onChooseFile: () => void;
  onClose: () => void;
}

export function MusicPicker({ onPick, onChooseFile, onClose }: MusicPickerProps) {
  const [library, setLibrary] = useState<{ dir: string; tracks: LibraryTrack[] } | null>(null);
  const [tag, setTag] = useState<string | null>(null);
  const [selected, setSelected] = useState<LibraryTrack | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    loadMusicLibrary().then(setLibrary).catch(() => setLibrary({ dir: "", tracks: [] }));
    return () => audio.current?.pause();
  }, []);

  const tags = useMemo(() => [...new Set((library?.tracks ?? []).flatMap((x) => x.tags))].sort(), [library]);
  const shown = (library?.tracks ?? []).filter((x) => !tag || x.tags.includes(tag));

  const toggle = (track: LibraryTrack) => {
    if (playing === track.abs) {
      audio.current?.pause();
      setPlaying(null);
      return;
    }
    audio.current?.pause();
    audio.current = new Audio(convertFileSrc(track.abs.replace(/\\/g, "/")));
    audio.current.onended = () => setPlaying(null);
    audio.current.play().catch(() => setPlaying(null));
    setPlaying(track.abs);
  };

  const chip = (active: boolean) =>
    `h-6 px-2.5 rounded-full text-[11px] font-medium transition-colors ${
      active ? "bg-navi text-white" : "bg-zinc-100 dark:bg-white/5 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-white/10"
    }`;

  return (
    <Dialog
      width="w-[520px]"
      onClose={onClose}
      title={<Trans>Background music</Trans>}
      subtitle={t`Tracks in your Music folder`}
      footer={
        <>
          <button className={`${dialogButton.secondary} mr-auto flex items-center gap-1.5`} onClick={() => library?.dir && invoke("open_in_explorer", { path: library.dir })}>
            <Folder className="w-3.5 h-3.5" /> <Trans>Open music folder</Trans>
          </button>
          <button className={dialogButton.secondary} onClick={onChooseFile}>
            <Trans>Choose a file…</Trans>
          </button>
          <button className={dialogButton.primary} disabled={!selected} onClick={() => selected && onPick(selected)}>
            <Trans>Use this track</Trans>
          </button>
        </>
      }
    >
      {!library ? (
        <div className="flex items-center gap-2 py-6 text-[12px] text-zinc-400">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> <Trans>Loading…</Trans>
        </div>
      ) : library.tracks.length === 0 ? (
        <div className="py-6 text-center text-[12px] leading-relaxed text-zinc-500">
          <Music className="w-6 h-6 mx-auto mb-2 text-zinc-300 dark:text-zinc-600" />
          <Trans>
            No tracks yet. Put music files in the folder (use Open music folder), or choose a file from anywhere. An optional library.json
            can add titles, tags and credits.
          </Trans>
        </div>
      ) : (
        <>
          {tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-3">
              <button type="button" className={chip(tag === null)} onClick={() => setTag(null)}>
                <Trans>All</Trans>
              </button>
              {tags.map((x) => (
                <button key={x} type="button" className={chip(tag === x)} onClick={() => setTag(tag === x ? null : x)}>
                  {x}
                </button>
              ))}
            </div>
          )}
          <ul className="max-h-72 overflow-y-auto custom-scrollbar rounded-xl border border-zinc-200 dark:border-white/10 divide-y divide-zinc-100 dark:divide-white/5">
            {shown.map((track) => {
              const active = selected?.abs === track.abs;
              return (
                <li key={track.abs} className={active ? "bg-navi/10" : ""}>
                  <div className="flex items-center gap-2 px-2 py-1.5">
                    <button
                      type="button"
                      aria-label={playing === track.abs ? t`Pause` : t`Play`}
                      onClick={() => toggle(track)}
                      className="w-7 h-7 shrink-0 flex items-center justify-center rounded-lg text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-white/5 transition-colors"
                    >
                      {playing === track.abs ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                    </button>
                    <button type="button" onClick={() => setSelected(track)} onDoubleClick={() => onPick(track)} className="flex-1 min-w-0 text-left">
                      <span className="block truncate text-[13px] font-medium text-zinc-900 dark:text-zinc-100">{track.title}</span>
                      <span className="block truncate text-[11px] text-zinc-400">{[...track.tags, track.license].filter(Boolean).join(" · ")}</span>
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
          {selected?.credit && <p className="mt-2 text-[11px] text-zinc-400 leading-snug">{t`Credit: ${selected.credit}`}</p>}
        </>
      )}
    </Dialog>
  );
}
