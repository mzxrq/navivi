import { useCallback, useEffect, useRef, useState } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useWorkspace } from "../../hooks/useWorkspace";
import { useInstalls } from "../../hooks/useInstalls";
import { startInstall } from "../../services/installs";
import { callSidecar, callSidecarShared } from "../../services/sidecar";
import { Loader2, Play, Plus, Trash2, Volume2 } from "./icons";
import { Segmented } from "./Segmented";
import { Slider } from "./Slider";
import { Switch } from "./Switch";
import { DEFAULT_TTS_CAPTION, TTS_SPEED_RANGE, formatBytes, ttsCaptionPresets } from "./voiceOptions";

interface Voice {
  id: string;
  filename: string | null;
  bytes: number;
  duration_seconds: number | null;
  builtin: boolean;
}

interface CacheInfo {
  files: number;
  bytes: number;
  max_bytes: number;
}

interface KokoroInfo {
  ready: boolean;
  english_ready?: boolean;
  default_voice: string;
  voices: { id: string; label: string }[];
}

const ENGINE_NAME = { irodori: "Irodori-TTS", qwen3: "Qwen3-TTS", kokoro: "Kokoro-82M" } as const;

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
  const [voicesDir, setVoicesDir] = useState("");
  const [busy, setBusy] = useState<null | "list" | "add" | "delete" | "preview" | "install" | "cache">(null);
  const [cache, setCache] = useState<CacheInfo | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [styleText, setStyleText] = useState<string | null>(null);
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
  const savedStyle = settings.tts?.caption ?? DEFAULT_TTS_CAPTION;
  const autoOverviewCues = settings.auto_overview_cues ?? true;
  const autoNarrationCues = settings.auto_narration_cues ?? true;
  const missing = !!voices && !voices.some((v) => v.id === selected);
  const disabled = busy !== null;

  const refresh = useCallback(async () => {
    setBusy("list");
    // One after the other: the app runs one Python call at a time and a new call kills the running one.
    const res = await callSidecarShared<{ voices: Voice[]; voices_dir: string }>("tts_voices_list");
    const engines = res.success
      ? await callSidecarShared<{ kokoro: KokoroInfo; qwen3: { ready: boolean }; irodori: { ready: boolean } }>("tts_engines")
      : null;
    const cacheInfo = engines?.success ? await callSidecarShared<CacheInfo>("tts_cache_info") : null;
    setBusy(null);
    if (cacheInfo?.success) setCache({ files: cacheInfo.files, bytes: cacheInfo.bytes, max_bytes: cacheInfo.max_bytes });
    if (engines?.success) {
      setKokoro(engines.kokoro);
      setQwen3Ready(engines.qwen3.ready);
      setIrodoriReady(engines.irodori.ready);
    }
    if (res.success) {
      setVoices(res.voices);
      setVoicesDir(res.voices_dir);
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

  // undefined drops the key, so the project goes back to the engine's default style.
  const saveStyle = (caption: string | undefined) => {
    setStyleText(null);
    if (caption === settings.tts?.caption) return;
    updateSettings({ tts: { ...settings.tts, caption } });
    setIsDirty(true);
  };

  const saveCues = (patch: { auto_overview_cues?: boolean; auto_narration_cues?: boolean }) => {
    updateSettings(patch);
    setIsDirty(true);
  };

  const clearCache = async () => {
    setBusy("cache");
    setMessage(null);
    const res = await callSidecar<{ files: number; bytes: number }>("tts_cache_clear", {});
    setConfirmClear(false);
    if (!res.success) {
      setBusy(null);
      return res.cancelled ? undefined : setMessage({ tone: "error", text: res.error });
    }
    const info = await callSidecar<CacheInfo>("tts_cache_info", {});
    setBusy(null);
    if (info.success) setCache({ files: info.files, bytes: info.bytes, max_bytes: info.max_bytes });
  };

  const engineReady = engine === "kokoro" ? !!kokoro?.ready : engine === "qwen3" ? !!qwen3Ready : !!irodoriReady;

  const preview = async (id: string) => {
    audioRef.current?.pause();
    const source = voices?.find((v) => v.id === id);
    if (!engineReady && source?.filename && voicesDir) {
      const audio = new Audio(convertFileSrc(`${voicesDir}/${source.filename}`));
      audioRef.current = audio;
      setMessage({ tone: "info", text: t`Playing the original recording. Set up this voice engine to hear it read your text.` });
      audio.play().catch((e) => setMessage({ tone: "error", text: String(e) }));
      return;
    }
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

  const install = (which: "kokoro" | "qwen3" | "irodori") => {
    setMessage(null);
    void startInstall(which, ENGINE_NAME[which], `tts_install_${which}`);
  };

  // A finished background install changes which engines are ready.
  const jobs = useInstalls();
  const finished = jobs.filter((j) => j.state !== "running").map((j) => `${j.id}:${j.state}`).join();
  useEffect(() => {
    if (finished) void refresh();
  }, [finished, refresh]);
  const installing = jobs.some((j) => j.state === "running");
  const installingNow = (id: string) => jobs.some((j) => j.state === "running" && j.id === id);

  // With exactly one engine set up, that is the one to use, whatever the project's default says.
  useEffect(() => {
    const ready = (["irodori", "qwen3", "kokoro"] as const).filter((e) => (e === "kokoro" ? kokoro?.ready : e === "qwen3" ? qwen3Ready : irodoriReady));
    if (ready.length === 1 && ready[0] !== engine) {
      updateSettings({ tts: { ...settings.tts, engine: ready[0] } });
      setIsDirty(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kokoro?.ready, qwen3Ready, irodoriReady]);

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
        <h4 className="mb-2 px-0.5 text-[12px] font-semibold text-zinc-500 dark:text-zinc-400"><Trans>Narration language</Trans></h4>
        <div className="rounded-xl border border-zinc-200 dark:border-white/10 p-3 space-y-2.5">
          <Segmented
            value={settings.narration_language ?? "auto"}
            onChange={(language) => {
              updateSettings({ narration_language: language });
              setIsDirty(true);
            }}
            options={[
              { id: "auto", label: t`Auto` },
              { id: "ja", label: t`Japanese` },
              { id: "en", label: t`English` },
            ]}
          />
          <p className="text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
            <Trans>
              The language the AI writes stop scripts in (Auto-Write, imported documents, the assistant). Auto follows the language of the
              project's own text. English narration is read by an English voice: Kokoro, with its English voices added below.
            </Trans>
          </p>
        </div>
      </section>

      <section>
        <h4 className="mb-2 px-0.5 text-[12px] font-semibold text-zinc-500 dark:text-zinc-400"><Trans>Voice engine</Trans></h4>
        <div className="rounded-xl border border-zinc-200 dark:border-white/10 p-3 space-y-2.5">
          <Segmented
            value={engine}
            onChange={(e) =>
              save({ engine: e, ...(e === "qwen3" && selected === "none" ? { voice: voices?.find((v) => !v.builtin)?.id ?? DEFAULT_VOICE } : {}) })
            }
            options={[
              { id: "irodori", label: ENGINE_NAME.irodori },
              { id: "qwen3", label: ENGINE_NAME.qwen3 },
              { id: "kokoro", label: ENGINE_NAME.kokoro },
            ]}
          />
          <p className="text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
            {engine === "irodori" ? (
              <Trans>
                Irodori-TTS can clone a voice from a recording and sounds the most natural, but takes about half a minute per line on a PC
                without a graphics card.
              </Trans>
            ) : engine === "qwen3" ? (
              <Trans>
                Qwen3-TTS also clones a voice from a recording, in less than half the time. It sounds a little less natural and can
                occasionally change the intonation of a short line. It uses about 3 GB of memory while it runs.
              </Trans>
            ) : (
              <Trans>
                Kokoro-82M has a few built-in voices, Japanese and English, and takes a few seconds per line. It sounds a little flatter and cannot clone a voice.
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
                  Kokoro-82M needs a one-time setup: a small separate Python environment and the model files (about 2 GB in all). It takes a few
                  minutes and needs an internet connection. It continues in the background if you close this window.
                </Trans>
              </p>
              <button type="button" className={primaryButton} disabled={disabled || installing || !kokoro} onClick={() => install("kokoro")}>
                {installingNow("kokoro") && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {installingNow("kokoro") ? t`Setting up…` : t`Set up Kokoro-82M`}
              </button>
            </div>
          ) : (
            <div className="rounded-xl border border-zinc-200 dark:border-white/10 divide-y divide-zinc-100 dark:divide-white/5">
              {kokoro.voices.filter((v) => kokoro.english_ready || v.id.startsWith("j")).map((v) => {
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
              {!kokoro.english_ready && (
                <div className="px-3 py-2.5 space-y-2">
                  <p className="text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
                    <Trans>
                      This voice can also speak English. The English voices are needed to make an English version of a project (in the project list menu). Adding them downloads a small language file and four voices.
                    </Trans>
                  </p>
                  <button type="button" className={secondaryButton} disabled={disabled || installing} onClick={() => install("kokoro")}>
                    {installingNow("kokoro") && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                    {installingNow("kokoro") ? t`Adding…` : t`Add English voices`}
                  </button>
                </div>
              )}
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
          <h4 className="mb-2 px-0.5 text-[12px] font-semibold text-zinc-500 dark:text-zinc-400"><Trans>Irodori-TTS setup</Trans></h4>
          <div className="rounded-xl border border-zinc-200 dark:border-white/10 p-3 space-y-2.5">
            <p className="text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
              <Trans>
                Irodori-TTS needs a one-time setup: a separate Python environment and the model files (about 3 GB, more with a graphics card).
                It takes several minutes and needs an internet connection. It continues in the background if you close this window.
              </Trans>
            </p>
            <button type="button" className={primaryButton} disabled={disabled || installing} onClick={() => install("irodori")}>
              {installingNow("irodori") && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {installingNow("irodori") ? t`Setting up…` : t`Set up Irodori-TTS`}
            </button>
          </div>
        </section>
      )}

      {engine === "qwen3" && qwen3Ready === false && (
        <section>
          <h4 className="mb-2 px-0.5 text-[12px] font-semibold text-zinc-500 dark:text-zinc-400"><Trans>Qwen3-TTS setup</Trans></h4>
          <div className="rounded-xl border border-zinc-200 dark:border-white/10 p-3 space-y-2.5">
            <p className="text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
              <Trans>
                Qwen3-TTS needs a one-time setup: a separate Python environment and the model files (about 4 GB in all). It takes several
                minutes and needs an internet connection. It continues in the background if you close this window.
              </Trans>
            </p>
            <button type="button" className={primaryButton} disabled={disabled || installing} onClick={() => install("qwen3")}>
              {installingNow("qwen3") && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {installingNow("qwen3") ? t`Setting up…` : t`Set up Qwen3-TTS`}
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
            min={TTS_SPEED_RANGE.min}
            max={TTS_SPEED_RANGE.max}
            step={TTS_SPEED_RANGE.step}
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

      {engine === "irodori" && (
        <section>
          <div className="flex items-baseline justify-between mb-2 px-0.5">
            <h4 className="text-[12px] font-semibold text-zinc-500 dark:text-zinc-400"><Trans>Speaking style</Trans></h4>
            <button
              type="button"
              className="text-[11px] text-navi hover:underline disabled:opacity-40 disabled:pointer-events-none"
              disabled={settings.tts?.caption === undefined}
              aria-label={t`Reset speaking style`}
              onClick={() => saveStyle(undefined)}
            >
              <Trans>Reset</Trans>
            </button>
          </div>
          <div className="rounded-xl border border-zinc-200 dark:border-white/10 p-3 space-y-2.5">
            <div className="flex flex-wrap gap-1.5">
              {ttsCaptionPresets().map((p) => (
                <button
                  key={p.id}
                  type="button"
                  aria-pressed={savedStyle === p.text}
                  onClick={() => saveStyle(p.text === DEFAULT_TTS_CAPTION ? undefined : p.text)}
                  className={`h-7 px-2.5 rounded-lg border text-[12px] font-medium transition-colors ${
                    savedStyle === p.text
                      ? "border-navi bg-navi/10 text-navi"
                      : "border-zinc-200 dark:border-white/10 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-white/5"
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <input
              value={styleText ?? savedStyle}
              onChange={(e) => setStyleText(e.target.value)}
              onBlur={() => styleText !== null && saveStyle(styleText.trim() === DEFAULT_TTS_CAPTION ? undefined : styleText.trim())}
              onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
              placeholder={t`Describe how the voice should speak`}
              aria-label={t`Speaking style`}
              className={`${inputClass} w-full`}
            />
            <p className="text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
              <Trans>
                A short description of the way the natural voice speaks, written in Japanese. Leave it empty for no style. Changing it
                regenerates the narration the next time you generate.
              </Trans>
            </p>
          </div>
        </section>
      )}

      <section>
        <h4 className="mb-2 px-0.5 text-[12px] font-semibold text-zinc-500 dark:text-zinc-400"><Trans>Timing cues</Trans></h4>
        <div className="rounded-xl border border-zinc-200 dark:border-white/10 divide-y divide-zinc-100 dark:divide-white/5">
          <div className="flex items-center gap-3 px-3 py-2.5">
            <div className="flex-1 min-w-0">
              <div className="text-[13px] font-medium text-zinc-900 dark:text-zinc-100"><Trans>Place cues in the overview narration</Trans></div>
              <p className="text-[11px] text-zinc-500 dark:text-zinc-400"><Trans>The overview stops at each stop while the voice describes it, then moves on.</Trans></p>
            </div>
            <Switch checked={autoOverviewCues} onChange={(v) => saveCues({ auto_overview_cues: v })} label={t`Place cues in the overview narration`} />
          </div>
          <div className="flex items-center gap-3 px-3 py-2.5">
            <div className="flex-1 min-w-0">
              <div className="text-[13px] font-medium text-zinc-900 dark:text-zinc-100"><Trans>Place cues in each stop's narration</Trans></div>
              <p className="text-[11px] text-zinc-500 dark:text-zinc-400"><Trans>The walk reaches the stop by the time its name is spoken. Cues you type yourself always win.</Trans></p>
            </div>
            <Switch checked={autoNarrationCues} onChange={(v) => saveCues({ auto_narration_cues: v })} label={t`Place cues in each stop's narration`} />
          </div>
        </div>
      </section>

      <section>
        <h4 className="mb-2 px-0.5 text-[12px] font-semibold text-zinc-500 dark:text-zinc-400"><Trans>Voice cache</Trans></h4>
        <div className="rounded-xl border border-zinc-200 dark:border-white/10 px-3 py-2.5 flex items-center gap-3">
          <div className="flex-1 min-w-0">
            <div className="text-[13px] font-medium text-zinc-900 dark:text-zinc-100 tabular-nums">
              {cache ? t`${formatBytes(cache.bytes)} of ${formatBytes(cache.max_bytes)}` : t`Checking…`}
            </div>
            <p className="text-[11px] text-zinc-500 dark:text-zinc-400">
              <Trans>Spoken lines are kept so a repeated line is not spoken again. Narration already in your projects is not touched.</Trans>
            </p>
          </div>
          {confirmClear ? (
            <div className="flex items-center gap-1.5 text-[11px]">
              <button type="button" disabled={disabled} onClick={clearCache} className="h-7 px-2 rounded-lg bg-red-500 text-white font-medium hover:bg-red-600 disabled:opacity-40 transition-colors">
                <Trans>Clear</Trans>
              </button>
              <button type="button" disabled={disabled} onClick={() => setConfirmClear(false)} className={`${iconButton} w-auto px-2 text-[11px]`}>
                <Trans>Cancel</Trans>
              </button>
            </div>
          ) : (
            <button type="button" className={secondaryButton} disabled={disabled || !cache || cache.files === 0} onClick={() => setConfirmClear(true)}>
              {busy === "cache" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />} <Trans>Clear cache</Trans>
            </button>
          )}
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
