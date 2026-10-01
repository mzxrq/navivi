import { useState } from "react";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Check, Film, Mic, PlayCircle, Plus, RotateCcw, Trash2, X } from "./icons";

export type ReviewKind = "overview" | "leg" | "attraction" | "other";

export interface ReviewRow {
  id: string;
  kind: ReviewKind;
  title: string;
  fileName: string;
  videoUrl: string;
  filePath: string;
  wpId?: string;
  wpIndex?: number;
  voice?: { text: string; audioPath: string };
}

export interface PronunciationFix {
  word: string;
  reading: string;
  scope: "project" | "global";
}

export type ReviewSelection = Record<string, { video?: boolean; voice?: boolean }>;
export type ReviewEdits = Record<string, { text: string; fixes: PronunciationFix[] }>;

interface ReviewStepProps {
  rows: ReviewRow[];
  selection: ReviewSelection;
  onSelection: (next: ReviewSelection) => void;
  edits: ReviewEdits;
  onEdits: (next: ReviewEdits) => void;
  playingId: string | null;
  onPlay: (row: ReviewRow) => void;
  videoRedoGoesTo: "timeline" | "map";
  busy: boolean;
}

function RedoChip({ active, disabled, onClick, children }: { active: boolean; disabled?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 h-8 px-3 rounded-lg border text-[12px] font-medium transition-colors disabled:opacity-40 disabled:pointer-events-none ${
        active
          ? "border-amber-500/50 bg-amber-500/10 text-amber-700 dark:text-amber-400"
          : "border-zinc-200 dark:border-white/10 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-white/5"
      }`}
    >
      {active ? <Check className="w-3.5 h-3.5" /> : <RotateCcw className="w-3.5 h-3.5" />}
      {children}
    </button>
  );
}

const field =
  "h-8 min-w-0 px-2.5 rounded-lg bg-white dark:bg-zinc-950/40 border border-zinc-200 dark:border-white/10 text-[13px] text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 outline-none focus:border-navi focus:ring-2 focus:ring-navi/20 transition";

function PronunciationFixer({ fixes, onChange, disabled }: { fixes: PronunciationFix[]; onChange: (next: PronunciationFix[]) => void; disabled: boolean }) {
  const [word, setWord] = useState("");
  const [reading, setReading] = useState("");
  const [scope, setScope] = useState<PronunciationFix["scope"]>("project");
  const add = () => {
    if (!word.trim() || !reading.trim()) return;
    onChange([...fixes.filter((f) => f.word !== word.trim()), { word: word.trim(), reading: reading.trim(), scope }]);
    setWord("");
    setReading("");
  };
  return (
    <div className="space-y-2">
      <p className="text-[12px] text-zinc-500 dark:text-zinc-400">
        <Trans>Misread a word? Say how it should sound. It goes into the pronunciation dictionary and the voice is made again.</Trans>
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <input value={word} onChange={(e) => setWord(e.target.value)} placeholder={t`Word (e.g. 三段壁)`} disabled={disabled} className={`${field} w-36`} aria-label={t`Word`} />
        <input
          value={reading}
          onChange={(e) => setReading(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
          placeholder={t`Reading (e.g. さんだんべき)`}
          disabled={disabled}
          className={`${field} w-44`}
          aria-label={t`Reading`}
        />
        <select value={scope} onChange={(e) => setScope(e.target.value as PronunciationFix["scope"])} disabled={disabled} className={`${field} pr-6 cursor-pointer`} aria-label={t`Where to save`}>
          <option value="project">{t`This project`}</option>
          <option value="global">{t`All projects`}</option>
        </select>
        <button type="button" onClick={add} disabled={disabled || !word.trim() || !reading.trim()} className="inline-flex items-center gap-1 h-8 px-2.5 rounded-lg border border-zinc-200 dark:border-white/10 text-[12px] font-medium text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-white/5 disabled:opacity-40 transition-colors">
          <Plus className="w-3.5 h-3.5" /> <Trans>Add</Trans>
        </button>
      </div>
      {fixes.length > 0 && (
        <ul className="flex flex-wrap gap-1.5">
          {fixes.map((fix) => (
            <li key={fix.word} className="inline-flex items-center gap-1.5 h-6 pl-2 pr-1 rounded-md bg-zinc-100 dark:bg-white/5 text-[12px] text-zinc-700 dark:text-zinc-200">
              {fix.word} → {fix.reading}
              <span className="text-[10px] text-zinc-400">{fix.scope === "global" ? t`all projects` : t`this project`}</span>
              <button type="button" aria-label={t`Remove`} onClick={() => onChange(fixes.filter((f) => f.word !== fix.word))} className="w-4 h-4 flex items-center justify-center rounded text-zinc-400 hover:text-red-500">
                <X className="w-3 h-3" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ReviewStep({ rows, selection, onSelection, edits, onEdits, playingId, onPlay, videoRedoGoesTo, busy }: ReviewStepProps) {
  const toggle = (id: string, key: "video" | "voice", row?: ReviewRow) => {
    const on = !selection[id]?.[key];
    onSelection({ ...selection, [id]: { ...selection[id], [key]: on } });
    if (key === "voice" && on && row?.voice && !edits[id]) onEdits({ ...edits, [id]: { text: row.voice.text, fixes: [] } });
  };

  const selectAll = (key: "video" | "voice") => {
    const next: ReviewSelection = { ...selection };
    const nextEdits: ReviewEdits = { ...edits };
    for (const row of rows) {
      if (key === "video" && (row.kind === "leg" || row.kind === "attraction")) next[row.id] = { ...next[row.id], video: true };
      if (key === "voice" && row.voice && row.kind !== "other") {
        next[row.id] = { ...next[row.id], voice: true };
        if (!nextEdits[row.id]) nextEdits[row.id] = { text: row.voice.text, fixes: [] };
      }
    }
    onSelection(next);
    onEdits(nextEdits);
  };
  const clearAll = () => {
    onSelection({});
    onEdits({});
  };
  const anySelected = Object.values(selection).some((s) => s.video || s.voice);

  return (
    <div className="flex-1 flex flex-col gap-5 p-5 sm:p-6 short:p-4 animate-in fade-in duration-300">
      <div>
        <h3 className="text-[15px] font-semibold text-zinc-900 dark:text-zinc-100">
          <Trans>Check the results</Trans>
        </h3>
        <p className="mt-1 text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400 max-w-2xl">
          <Trans>
            Play anything you want to check. Mark what you want redone, then choose Redo selected. If it all looks right, accept and export. Turn on Fast render and
            Export automatically in the generate dialog to skip this check.
          </Trans>
        </p>
        <p className="mt-1 text-[11px] text-zinc-400">
          {videoRedoGoesTo === "timeline"
            ? t`Redoing a video clip opens the timeline editor on this computer.`
            : t`Redoing a video clip opens the map editor with that stop selected, so you can change its photo, script or route first.`}
        </p>
      </div>

      {rows.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-[12px]">
          <span className="text-zinc-400">
            <Trans>Select:</Trans>
          </span>
          <button type="button" disabled={busy} onClick={() => selectAll("video")} className="h-7 px-2.5 rounded-md border border-zinc-200 dark:border-white/10 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-white/5 disabled:opacity-40 transition-colors">
            <Trans>All video clips</Trans>
          </button>
          <button type="button" disabled={busy} onClick={() => selectAll("voice")} className="h-7 px-2.5 rounded-md border border-zinc-200 dark:border-white/10 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-white/5 disabled:opacity-40 transition-colors">
            <Trans>All voices</Trans>
          </button>
          {anySelected && (
            <button type="button" disabled={busy} onClick={clearAll} className="h-7 px-2.5 rounded-md text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 transition-colors">
              <Trans>Clear</Trans>
            </button>
          )}
        </div>
      )}

      {rows.length === 0 && (
        <div className="px-4 py-10 text-center rounded-xl border border-dashed border-zinc-200 dark:border-zinc-800 text-[13px] text-zinc-500">
          <Trans>Nothing to review yet.</Trans>
        </div>
      )}

      <div className="grid gap-4">
        {rows.map((row) => {
          const sel = selection[row.id] ?? {};
          const edit = edits[row.id];
          const canRedoVideo = row.kind === "leg" || row.kind === "attraction";
          return (
            <article
              key={row.id}
              className={`rounded-2xl border overflow-hidden bg-white dark:bg-zinc-900/40 transition-colors ${
                sel.video || sel.voice ? "border-amber-500/40" : "border-zinc-200 dark:border-zinc-800"
              }`}
            >
              <div className="flex flex-col md:flex-row">
                <div className="md:w-72 shrink-0 p-3">
                  <div className="aspect-video rounded-lg overflow-hidden bg-black">
                    <video src={row.videoUrl} controls preload="metadata" className="w-full h-full object-cover" />
                  </div>
                </div>

                <div className="flex-1 min-w-0 p-4 space-y-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-[13px] font-semibold text-zinc-900 dark:text-zinc-100 truncate" title={row.title}>
                        {row.title}
                      </p>
                      <p className="text-[11px] text-zinc-400 truncate">{row.fileName}</p>
                    </div>
                    {canRedoVideo && (
                      <RedoChip active={!!sel.video} disabled={busy} onClick={() => toggle(row.id, "video")}>
                        <Film className="w-3.5 h-3.5" /> <Trans>Redo clip</Trans>
                      </RedoChip>
                    )}
                  </div>

                  {row.voice && (
                    <div className="rounded-xl border border-zinc-100 dark:border-white/5 bg-zinc-50/60 dark:bg-white/2 p-3 space-y-2.5">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <button
                          type="button"
                          onClick={() => onPlay(row)}
                          className={`inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-[12px] font-medium transition-colors ${
                            playingId === row.id ? "bg-navi/10 text-navi" : "bg-zinc-100 dark:bg-white/5 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-200 dark:hover:bg-white/10"
                          }`}
                        >
                          <PlayCircle className={`w-4 h-4 ${playingId === row.id ? "animate-pulse" : ""}`} />
                          {playingId === row.id ? t`Playing...` : t`Listen to the narration`}
                        </button>
                        <RedoChip active={!!sel.voice} disabled={busy} onClick={() => toggle(row.id, "voice", row)}>
                          <Mic className="w-3.5 h-3.5" /> <Trans>Redo voice</Trans>
                        </RedoChip>
                      </div>

                      {sel.voice && edit ? (
                        <div className="space-y-3">
                          <textarea
                            value={edit.text}
                            disabled={busy}
                            readOnly={row.kind === "overview"}
                            onChange={(e) => onEdits({ ...edits, [row.id]: { ...edit, text: e.target.value } })}
                            className="w-full min-h-20 resize-y rounded-lg p-3 text-[13px] leading-relaxed text-zinc-800 dark:text-zinc-100 bg-white dark:bg-zinc-950/40 border border-zinc-200 dark:border-white/10 outline-none focus:border-navi focus:ring-2 focus:ring-navi/20"
                            aria-label={t`Narration text`}
                          />
                          {row.kind === "overview" && (
                            <p className="text-[11px] text-zinc-400">
                              <Trans>The overview script is edited in the Intro panel on the map. You can still fix pronunciations here.</Trans>
                            </p>
                          )}
                          <PronunciationFixer
                            fixes={edit.fixes}
                            disabled={busy}
                            onChange={(fixes) => onEdits({ ...edits, [row.id]: { ...edit, fixes } })}
                          />
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => {
                              toggle(row.id, "voice", row);
                              const { [row.id]: _drop, ...rest } = edits;
                              onEdits(rest);
                            }}
                            className="inline-flex items-center gap-1 text-[11px] text-zinc-400 hover:text-red-500 transition-colors"
                          >
                            <Trash2 className="w-3 h-3" /> <Trans>Don't redo this voice</Trans>
                          </button>
                        </div>
                      ) : (
                        <p className="text-[12px] leading-relaxed text-zinc-600 dark:text-zinc-400 wrap-break-word line-clamp-3">{row.voice.text || t`(Empty script)`}</p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}
