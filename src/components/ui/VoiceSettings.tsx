import { useCallback, useEffect, useRef, useState } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useWorkspace } from "../../hooks/useWorkspace";
import { callSidecar, callSidecarShared } from "../../services/sidecar";
import { Loader2, Play, Plus, Trash2, Volume2 } from "./icons";
import { Segmented } from "./Segmented";
import { Slider } from "./Slider";

interface Voice {
  id: string;
  filename: string | null;
  bytes: number;
  duration_seconds: number | null;
  builtin: boolean;
}

interface KokoroInfo {
  ready: boolean;
  default_voice: string;
  voices: { id: string; label: string }[];
}

const DEFAULT_VOICE = "test1";
const fallback = DEFAULT_VOICE;
const DEFAULT_SPEED = 1.25;
const DEFAULT_QUALITY = "best";
const AUDIO_EXT = ["wav", "flac", "mp3", "m4a", "ogg", "opus", "aac", "webm"];

function slugFromPath(path: string): string {
  const stem = (path.split(/[\\/]/).pop() ?? "").replace(/\.[^.]+$/, "");
  const slug = stem.normalize("NFKD").replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "");
  return slug && slug.toLowerCase() !== "none" ? slug : "voice";
}

const inputClass =
  "h-8 min-w-0 px-2.5 rounded-lg bg-white dark:bg-zinc-950/40 border border-zinc-200 dark:border-white/10 text-[13px] text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 outline-none focus:border-navi focus:ring-2 focus:ring-navi/20 transition";
const secondaryButton =
  "inline-flex items-center justify-center gap-1.5 h-8 px-3 rounded-lg border border-zinc-200 dark:border-white/10 bg-white dark:bg-white/5 text-[12px] font-medium text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-white/10 disabled:opacity-40 disabled:pointer-events-none transition-colors";
const primaryButton =
  "inline-flex items-center justify-center gap-1.5 h-8 px-3 rounded-lg bg-navi text-white text-[12px] font-semibold hover:brightness-110 disabled:opacity-40 disabled:pointer-events-none transition";
const iconButton =
  "flex items-center justify-center w-7 h-7 rounded-lg text-zinc-500 hover:bg-zinc-100 dark:hover:bg-white/5 disabled:opacity-40 disabled:pointer-events-none transition-colors";

export function VoiceTab() {
  const { settings, updateSettings, setIsDirty } = useWorkspace();
  const [voices, setVoices] = useState<Voice[] | null>(null);
  const [busy, setBusy] = useState<null | "list" | "add" | "delete" | "preview" | "install">(null);
  const [kokoro, setKokoro] = useState<KokoroInfo | null>(null);
  const [qwen3Ready, setQwen3Ready] = useState<boolean | null>(null);
  const [irodoriReady, setIrodoriReady] = useState<boolean | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "error" | "info"; text: string } | null>(null);
  const [adding, setAdding] = useState<{ path: string; id: string; exists?: boolean } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const engine = settings.tts?.engine ?? "irodori";
  const kokoroVoice = settings.tts?.kokoro_voice ?? kokoro?.default_voice ?? "jf_tebukuro";
  const selected = settings.tts?.voice ?? DEFAULT_VOICE;
  const speed = settings.tts?.speed ?? DEFAULT_SPEED;
  const quality = settings.tts?.quality ?? DEFAULT_QUALITY;
  const missing = !!voices && !voices.some((v) => v.id === selected);
  const disabled = busy !== null;

  const refresh = useCallback(async () => {
    setBusy("list");
    // One after the other: the app runs one Python call at a time and a new call kills the running one.
    const res = await callSidecarShared<{ voices: Voice[] }>("tts_voices_list");
    const engines = res.success
      ? await callSidecarShared<{ kokoro: KokoroInfo; qwen3: { ready: boolean }; irodori: { ready: boolean } }>("tts_engines")
      : null;
    setBusy(null);
    if (engines?.success) {
      setKokoro(engines.kokoro);
      setQwen3Ready(engines.qwen3.ready);
      setIrodoriReady(engines.irodori.ready);
    }
    if (res.success) {
      setVoices(res.voices);
      setMessage((m) => (m?.tone === "error" ? null : m));
    } else if (!res.cancelled) {
      setMessage({ tone: "error", text: res.error });
    }
  }, []);

  useEffect(() => {
    void refresh();
    return () => audioRef.current?.pause();
  }, [refresh]);

  const save = (patch: NonNullable<typeof settings.tts>) => {
    updateSettings({ tts: { ...settings.tts, ...patch } });
    setIsDirty(true);
  };

  const preview = async (id: string) => {
    audioRef.current?.pause();
    setBusy("preview");
    setPreviewId(id);
    setMessage(null);
    const res = await callSidecar<{ path: string }>("tts_voice_preview", {
      engine,
      voice: id,
      speed,
      quality,
      hardware: settings.hardware_spec_override,
    });
    setBusy(null);
    setPreviewId(null);
    if (!res.success) return res.cancelled ? undefined : setMessage({ tone: "error", text: res.error });
    const audio = new Audio(`${convertFileSrc(res.path)}?t=${Date.now()}`);
    audioRef.current = audio;
    audio.play().catch((e) => setMessage({ tone: "error", text: String(e) }));
  };

  const install = async (which: "kokoro" | "qwen3" | "irodori") => {
    setBusy("install");
    setMessage(null);
    const res = await callSidecar(`tts_install_${which}`, {});
    setBusy(null);
    if (!res.success) return res.cancelled ? undefined : setMessage({ tone: "error", text: res.error });
    await refresh();
  };

  const pickFile = async () => {
    const path = await open({ multiple: false, filters: [{ name: t`Audio`, extensions: AUDIO_EXT }] });
    if (typeof path === "string") {
      setAdding({ path, id: slugFromPath(path) });
      setMessage(null);
    }
  };

  const add = async (replace = false) => {
    if (!adding) return;
    setBusy("add");
    const res = await callSidecar<{ voice: { id: string; warning: string | null } }>("tts_voice_add", {
      path: adding.path,
      id: adding.id,
      replace,
    });
    setBusy(null);
    if (!res.success) {
      if (/already exists/i.test(res.error)) return setAdding({ ...adding, exists: true });
      return setMessage({ tone: "error", text: res.error });
    }
    setMessage(res.voice.warning ? { tone: "info", text: res.voice.warning } : null);
    setAdding(null);
    await refresh();
  };

  const remove = async (id: string) => {
    setBusy("delete");
    const res = await callSidecar<{ id: string }>("tts_voice_delete", { id });
    setBusy(null);
    setConfirmDelete(null);
    if (!res.success) return setMessage({ tone: "error", text: res.error });
    await refresh();
  };

  const label = (v: Voice) => (v.builtin ? t`No reference (model default)` : v.id);

  return (
    <>
      <p className="text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400 select-text">
        <Trans>
          The voice reads every narration in this project. Changing the voice or the speed regenerates the narration the next time you
          generate. The voice library is shared by all projects.
        </Trans>
      </p>

      <section>
        <h4 className="mb-2 px-0.5 text-[12px] font-semibold text-zinc-500 dark:text-zinc-400"><Trans>Voice engine</Trans></h4>
        <div className="rounded-xl border border-zinc-200 dark:border-white/10 p-3 space-y-2.5">
          <Segmented
            value={engine}
            onChange={(e) =>
              save({ engine: e, ...(e === "qwen3" && selected === "none" ? { voice: voices?.find((v) => !v.builtin)?.id ?? DEFAULT_VOICE } : {}) })
            }
            options={[
              { id: "irodori", label: t`Natural voice` },
              { id: "qwen3", label: t`Balanced voice` },
              { id: "kokoro", label: t`Fast voice` },
            ]}
          />
          <p className="text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
            {engine === "irodori" ? (
              <Trans>
                Natural voice can clone a voice from a recording and sounds the most natural, but takes about half a minute per line on a PC
                without a graphics card.
              </Trans>
            ) : engine === "qwen3" ? (
              <Trans>
                Balanced voice also clones a voice from a recording, in less than half the time. It sounds a little less natural and can
                occasionally change the intonation of a short line. It uses about 3 GB of memory while it runs.
              </Trans>
            ) : (
              <Trans>
                Fast voice has a few built-in Japanese voices and takes a few seconds per line. It sounds a little flatter and cannot clone a voice.
              </Trans>
            )}
          </p>
        </div>
      </section>

      {engine === "kokoro" && (
        <section>
          <h4 className="mb-2 px-0.5 text-[12px] font-semibold text-zinc-500 dark:text-zinc-400"><Trans>Voice</Trans></h4>
          {!kokoro?.ready ? (
            <div className="rounded-xl border border-zinc-200 dark:border-white/10 p-3 space-y-2.5">
              <p className="text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
                <Trans>
                  The fast voice needs a one-time setup: a small separate Python environment and the model files (about 2 GB in all). It takes a few
                  minutes and needs an internet connection. Keep this window open while it runs.
                </Trans>
              </p>
              <button type="button" className={primaryButton} disabled={disabled || !kokoro} onClick={() => install("kokoro")}>
                {busy === "install" && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {busy === "install" ? t`Setting up…` : t`Set up fast voice`}
              </button>
            </div>
          ) : (
            <div className="rounded-xl border border-zinc-200 dark:border-white/10 divide-y divide-zinc-100 dark:divide-white/5">
              {kokoro.voices.map((v) => {
                const active = kokoroVoice === v.id;
                return (
                  <div key={v.id} className="flex items-center gap-2 px-3 py-2">
                    <button
                      type="button"
                      role="radio"
                      aria-checked={active}
                      disabled={disabled}
                      onClick={() => save({ kokoro_voice: v.id })}
                      className="flex items-center gap-3 flex-1 min-w-0 text-left disabled:pointer-events-none"
                    >
                      <span className={`w-4 h-4 rounded-full border-2 shrink-0 flex items-center justify-center ${active ? "border-navi" : "border-zinc-300 dark:border-zinc-600"}`}>
                        {active && <span className="w-2 h-2 rounded-full bg-navi" />}
                      </span>
                      <span className="block truncate text-[13px] font-medium text-zinc-900 dark:text-zinc-100">{v.label}</span>
                    </button>
                    <button type="button" aria-label={t`Preview ${v.label}`} title={t`Preview`} disabled={disabled} onClick={() => preview(v.id)} className={iconButton}>
                      {previewId === v.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
                    </button>
                  </div>
                );
              })}
            </div>
          )}
          {busy === "preview" && (
            <p className="mt-2 px-0.5 flex items-center gap-1.5 text-[11px] text-zinc-400">
              <Volume2 className="w-3 h-3" /> <Trans>Generating the sample. The first one takes about 20 seconds while the voice model loads.</Trans>
            </p>
          )}
        </section>
      )}

      {engine === "irodori" && irodoriReady === false && (
        <section>
          <h4 className="mb-2 px-0.5 text-[12px] font-semibold text-zinc-500 dark:text-zinc-400"><Trans>Natural voice setup</Trans></h4>
          <div className="rounded-xl border border-zinc-200 dark:border-white/10 p-3 space-y-2.5">
            <p className="text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
              <Trans>
                The natural voice needs a one-time setup: a separate Python environment and the model files (about 3 GB, more with a graphics card).
                It takes several minutes and needs an internet connection. Keep this window open while it runs.
              </Trans>
            </p>
            <button type="button" className={primaryButton} disabled={disabled} onClick={() => install("irodori")}>
              {busy === "install" && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {busy === "install" ? t`Setting up…` : t`Set up natural voice`}
            </button>
          </div>
        </section>
      )}

      {engine === "qwen3" && qwen3Ready === false && (
        <section>
          <h4 className="mb-2 px-0.5 text-[12px] font-semibold text-zinc-500 dark:text-zinc-400"><Trans>Balanced voice setup</Trans></h4>
          <div className="rounded-xl border border-zinc-200 dark:border-white/10 p-3 space-y-2.5">
            <p className="text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
              <Trans>
                The balanced voice needs a one-time setup: a separate Python environment and the model files (about 4 GB in all). It takes several
                minutes and needs an internet connection. Keep this window open while it runs.
              </Trans>
            </p>
            <button type="button" className={primaryButton} disabled={disabled} onClick={() => install("qwen3")}>
              {busy === "install" && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {busy === "install" ? t`Setting up…` : t`Set up balanced voice`}
            </button>
          </div>
        </section>
      )}

      {engine !== "kokoro" && (
      <section>
        <div className="flex items-center justify-between mb-2 px-0.5">
          <h4 className="text-[12px] font-semibold text-zinc-500 dark:text-zinc-400">
            <Trans>Voice</Trans>
          </h4>
          {missing && (
            <span className="h-4.5 px-1.5 inline-flex items-center rounded-md text-[10px] font-medium bg-amber-500/10 text-amber-700 dark:text-amber-400">
              {t`Voice "${selected}" is missing, using ${fallback}`}
            </span>
          )}
        </div>
        <div className="rounded-xl border border-zinc-200 dark:border-white/10 divide-y divide-zinc-100 dark:divide-white/5">
          {!voices && <div className="flex items-center gap-2 px-3 h-12 text-[12px] text-zinc-400"><Loader2 className="w-3.5 h-3.5 animate-spin" /> <Trans>Loading voices…</Trans></div>}
          {voices?.filter((v) => engine !== "qwen3" || !v.builtin).map((v) => {
            const active = !missing && selected === v.id;
            const previewing = previewId === v.id;
            return (
              <div key={v.id} className="flex items-center gap-2 px-3 py-2">
                <button
                  type="button"
                  role="radio"
                  aria-checked={active}
                  disabled={disabled}
                  onClick={() => save({ voice: v.id })}
                  className="flex items-center gap-3 flex-1 min-w-0 text-left disabled:pointer-events-none"
                >
                  <span className={`w-4 h-4 rounded-full border-2 shrink-0 flex items-center justify-center ${active ? "border-navi" : "border-zinc-300 dark:border-zinc-600"}`}>
                    {active && <span className="w-2 h-2 rounded-full bg-navi" />}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-[13px] font-medium text-zinc-900 dark:text-zinc-100">{label(v)}</span>
                    {!v.builtin && (
                      <span className="block text-[11px] text-zinc-400 tabular-nums">
                        {v.duration_seconds != null ? `${v.duration_seconds.toFixed(1)} s · ` : ""}
                        {(v.bytes / 1024 / 1024).toFixed(1)} MB
                      </span>
                    )}
                  </span>
                </button>

                {confirmDelete === v.id ? (
                  <div className="flex items-center gap-1.5 text-[11px]">
                    <span className="text-zinc-500"><Trans>Used by all projects.</Trans></span>
                    <button type="button" disabled={disabled} onClick={() => remove(v.id)} className="h-7 px-2 rounded-lg bg-red-500 text-white font-medium hover:bg-red-600 disabled:opacity-40 transition-colors">
                      <Trans>Delete</Trans>
                    </button>
                    <button type="button" disabled={disabled} onClick={() => setConfirmDelete(null)} className={`${iconButton} w-auto px-2 text-[11px]`}>
                      <Trans>Cancel</Trans>
                    </button>
                  </div>
                ) : (
                  <>
                    <button type="button" aria-label={t`Preview ${label(v)}`} title={t`Preview`} disabled={disabled} onClick={() => preview(v.id)} className={iconButton}>
                      {previewing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
                    </button>
                    {!v.builtin && (
                      <button type="button" aria-label={t`Delete ${v.id}`} title={t`Delete`} disabled={disabled} onClick={() => setConfirmDelete(v.id)} className={`${iconButton} hover:text-red-500`}>
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </>
                )}
              </div>
            );
          })}
        </div>
        {busy === "preview" && (
          <p className="mt-2 px-0.5 flex items-center gap-1.5 text-[11px] text-zinc-400">
            <Volume2 className="w-3 h-3" /> <Trans>Generating the sample. The first one can take a minute or more while the voice model loads.</Trans>
          </p>
        )}
      </section>
      )}

      <section>
        <div className="flex items-baseline justify-between mb-2 px-0.5">
          <h4 className="text-[12px] font-semibold text-zinc-500 dark:text-zinc-400"><Trans>Speed</Trans></h4>
          <span className="text-[12px] tabular-nums text-zinc-500">{speed.toFixed(2)}×</span>
        </div>
        <div className="rounded-xl border border-zinc-200 dark:border-white/10 px-3 py-3 flex items-center gap-3">
          <Slider
            min={0.5}
            max={2}
            step={0.05}
            value={speed}
            onChange={(v) => save({ speed: v })}
            label={t`Narration speed`}
            format={(v) => `${v.toFixed(2)}×`}
            className="flex-1"
          />
          <button type="button" className={secondaryButton} disabled={speed === DEFAULT_SPEED} onClick={() => save({ speed: DEFAULT_SPEED })}>
            <Trans>Reset</Trans>
          </button>
        </div>
      </section>

      {engine !== "kokoro" && (
      <>
      {engine === "irodori" && (
      <section>
        <h4 className="mb-2 px-0.5 text-[12px] font-semibold text-zinc-500 dark:text-zinc-400"><Trans>Narration quality</Trans></h4>
        <div className="rounded-xl border border-zinc-200 dark:border-white/10 p-3 space-y-2.5">
          <Segmented
            value={quality}
            onChange={(q) => save({ quality: q })}
            options={[
              { id: "fast", label: t`Fast draft` },
              { id: "balanced", label: t`Balanced` },
              { id: "best", label: t`Best` },
            ]}
          />
          <p className="text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
            <Trans>
              A fast draft takes about half the time per line and sounds a little rougher. Use it while you are checking a project and switch to
              Best for the final render. Narration you already have is kept; use Redo voice in the review step to remake it with this setting.
            </Trans>
          </p>
        </div>
      </section>
      )}

      <section>
        <h4 className="mb-2 px-0.5 text-[12px] font-semibold text-zinc-500 dark:text-zinc-400"><Trans>Add a voice</Trans></h4>
        <div className="rounded-xl border border-zinc-200 dark:border-white/10 p-3 space-y-3">
          <p className="text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
            <Trans>Upload 5–20 seconds of clear speech from one person, with no music or background noise.</Trans>
          </p>
          {adding ? (
            <>
              <div className="flex items-center gap-2">
                <span className="text-[12px] text-zinc-500 truncate flex-1" title={adding.path}>{adding.path.split(/[\\/]/).pop()}</span>
                <input
                  value={adding.id}
                  onChange={(e) => setAdding({ ...adding, id: e.target.value.replace(/[^A-Za-z0-9_-]/g, ""), exists: false })}
                  placeholder={t`Voice name`}
                  aria-label={t`Voice name`}
                  className={`${inputClass} w-40`}
                />
              </div>
              <div className="flex items-center gap-2">
                {adding.exists ? (
                  <button type="button" className={primaryButton} disabled={disabled} onClick={() => add(true)}>
                    <Trans>Replace existing voice</Trans>
                  </button>
                ) : (
                  <button type="button" className={primaryButton} disabled={disabled || !adding.id} onClick={() => add(false)}>
                    {busy === "add" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />} <Trans>Add voice</Trans>
                  </button>
                )}
                <button type="button" className={secondaryButton} disabled={disabled} onClick={() => setAdding(null)}>
                  <Trans>Cancel</Trans>
                </button>
                {adding.exists && <span className="text-[11px] text-amber-700 dark:text-amber-400"><Trans>A voice with this name already exists.</Trans></span>}
              </div>
            </>
          ) : (
            <button type="button" className={secondaryButton} disabled={disabled} onClick={pickFile}>
              <Plus className="w-3.5 h-3.5" /> <Trans>Choose a recording…</Trans>
            </button>
          )}
        </div>
      </section>
      </>
      )}

      {message && (
        <p className={`text-[12px] leading-snug select-text ${message.tone === "error" ? "text-red-500" : "text-amber-700 dark:text-amber-400"}`}>{message.text}</p>
      )}
    </>
  );
}
