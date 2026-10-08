import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { callSidecarShared } from "../../services/sidecar";
import { getOllamaState } from "../../services/ollamaApi";
import { hasApiKey } from "../../services/ai/online";
import { AI_KEYS_CHANGED } from "../../services/ai/keys";
import { isOnlineProvider, ONLINE_PROVIDERS, type OnlineProvider } from "../../services/ai/providers";
import { startInstall } from "../../services/installs";
import { installVcRuntime } from "../../services/setup";
import { useInstalls } from "../../hooks/useInstalls";
import { useWorkspace } from "../../hooks/useWorkspace";
import { MODEL_CREDITS } from "../../config/credits";
import { CheckCircle2, ExternalLink, Loader2 } from "./icons";
import { Dialog, dialogButton } from "./Dialog";
import { OnlineProviderSettings, ProviderPicker } from "./OnlineAiSettings";
import { primaryButton, Row, secondaryButton, Section } from "./SettingsParts";
import { Select } from "./Select";

type Engine = "irodori" | "qwen3" | "kokoro" | "comfyui";
type EngineStatus = Record<Engine, boolean | null>;

const INSTALL_ACTION: Record<Engine, string> = {
  kokoro: "tts_install_kokoro",
  qwen3: "tts_install_qwen3",
  irodori: "tts_install_irodori",
  comfyui: "comfyui_install",
};

const ENGINE_LABEL: Record<Engine, string> = {
  kokoro: "Kokoro-82M",
  qwen3: "Qwen3-TTS",
  irodori: "Irodori-TTS",
  comfyui: "ComfyUI",
};

const OLLAMA_PAGE = "https://ollama.com/download";
const OLLAMA_RECHECK_MS = 4000;

// What can be set up after the media tools: the three voices, a script writer, and the moving attraction videos.
// Installs run in the background (services/installs.ts, shown by InstallToast) one at a time: the app runs one Python call at a time.
export function ComponentsChecklist({ onReadyChange }: { onReadyChange?: (voiceReady: boolean) => void } = {}) {
  const { settings, updateSettings, setIsDirty } = useWorkspace();
  const jobs = useInstalls();
  const [engines, setEngines] = useState<EngineStatus>({ irodori: null, qwen3: null, kokoro: null, comfyui: null });
  const [nvidia, setNvidia] = useState<boolean | null>(null);
  const [vc, setVc] = useState<boolean | null>(null);
  const [ollama, setOllama] = useState<{ running: boolean; models: string[] } | null>(null);
  const [keys, setKeys] = useState<OnlineProvider[] | null>(null);
  const [vcBusy, setVcBusy] = useState(false);
  const [askOllama, setAskOllama] = useState(false);
  const [error, setError] = useState("");
  const models = ollama ? ollama.models : null;
  const online = isOnlineProvider(settings.ai_provider);
  const aiOff = settings.ai_features_enabled === false;
  const ollamaReady = !!ollama && ollama.models.length > 0;
  const running = jobs.find((j) => j.state === "running");
  const busy = !!running || vcBusy;
  const jobFor = (id: string) => jobs.find((j) => j.id === id && j.state === "running");

  // Ollama may be installed or started while this window is open, and a key may be saved by the sign-in flow: look again, not once.
  const recheck = useCallback(async () => {
    setOllama(await getOllamaState());
    const saved = await Promise.all(ONLINE_PROVIDERS.map(async (p) => ((await hasApiKey(p)) ? p : null)));
    setKeys(saved.filter((p): p is OnlineProvider => p !== null));
  }, []);

  const refresh = useCallback(async () => {
    const reply = await callSidecarShared<Record<Engine, { ready: boolean; nvidia?: boolean } | undefined> & { vc_runtime?: boolean }>("tts_engines");
    if (reply.success) {
      setVc(reply.vc_runtime !== false);
      setEngines({ irodori: !!reply.irodori?.ready, qwen3: !!reply.qwen3?.ready, kokoro: !!reply.kokoro?.ready, comfyui: !!reply.comfyui?.ready });
      setNvidia(!!reply.comfyui?.nvidia);
    }
    await recheck();
  }, [recheck]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // A background install that finishes (or fails) changes what is ready.
  const finished = jobs.filter((j) => j.state !== "running").map((j) => `${j.id}:${j.state}`).join();
  useEffect(() => {
    if (finished) void refresh();
  }, [finished, refresh]);

  useEffect(() => {
    const again = () => void recheck();
    window.addEventListener("focus", again);
    window.addEventListener(AI_KEYS_CHANGED, again);
    const timer = ollamaReady ? undefined : window.setInterval(again, OLLAMA_RECHECK_MS);
    return () => {
      window.removeEventListener("focus", again);
      window.removeEventListener(AI_KEYS_CHANGED, again);
      window.clearInterval(timer);
    };
  }, [recheck, ollamaReady]);

  const install = (which: Engine) => {
    setError("");
    void startInstall(which, ENGINE_LABEL[which], INSTALL_ACTION[which]);
  };

  const installOllama = () => {
    setAskOllama(false);
    setError("");
    void startInstall("ollama", "Ollama", "ollama_install");
  };

  const installVc = async () => {
    setVcBusy(true);
    setError("");
    try {
      await installVcRuntime();
      setVc(true);
    } catch (e) {
      setError(String(e));
    }
    setVcBusy(false);
  };

  const installControl = (which: string, ready: boolean | null, start: () => void, label = t`Set up`) => {
    const job = jobFor(which);
    if (job) {
      return (
        <div className="w-40 space-y-1" title={job.step}>
          <div className="flex items-center justify-between gap-2 text-[11px] text-zinc-500 dark:text-zinc-400">
            <span className="truncate">{job.step || t`Starting…`}</span>
            <span className="tabular-nums">{Math.round(job.fraction * 100)}%</span>
          </div>
          <div className="h-1 rounded-full overflow-hidden bg-zinc-200 dark:bg-white/10">
            <div className="h-full bg-navi transition-all duration-500" style={{ width: `${Math.max(4, job.fraction * 100)}%` }} />
          </div>
        </div>
      );
    }
    return (
      <button type="button" className={primaryButton} disabled={ready === null || busy} onClick={start}>
        {label}
      </button>
    );
  };

  const ReadyMark = () => (
    <span className="inline-flex items-center gap-1 text-[12px] font-medium text-emerald-600 dark:text-emerald-400">
      <CheckCircle2 className="w-3.5 h-3.5" /> <Trans>Ready</Trans>
    </span>
  );

  const engineRow = (which: Engine, title: string, description: string, info: string) => (
    <Row title={title} description={description} info={info}>
      {engines[which] ? <ReadyMark /> : which === "comfyui" && nvidia === false ? null : installControl(which, engines[which], () => install(which))}
    </Row>
  );

  const anyVoice = engines.kokoro || engines.qwen3 || engines.irodori;
  useEffect(() => onReadyChange?.(!!anyVoice), [anyVoice, onReadyChange]);
  const loaded = engines.kokoro !== null && ollama !== null && keys !== null;
  const todo: string[] = [];
  if (loaded) {
    if (vc === false) todo.push(t`Install the Microsoft Visual C++ runtime, or GPS files, rendering and the voices will not start.`);
    if (!anyVoice) todo.push(t`Set up at least one voice, or the video has no narration.`);
  }
  const videoBlocked = nvidia === false;

  return (
    <div className="space-y-5">
      {loaded && (
        <div className={`rounded-xl px-4 py-3 text-[12px] leading-relaxed ${todo.length === 0 ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" : "bg-amber-500/10 text-amber-700 dark:text-amber-300"}`}>
          {todo.length === 0 ? (
            <Trans>Everything you need is set up.</Trans>
          ) : (
            <ul className="space-y-1">
              {todo.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {vc === false && (
        <Section title={t`Windows`}>
          <Row
            title={t`Microsoft Visual C++ runtime`}
            description={t`Missing on this PC. About 25 MB from Microsoft.`}
            info={t`GPS files, rendering and the voices need it. Windows asks for permission before it installs.`}
          >
            <button type="button" className={primaryButton} disabled={busy} onClick={installVc}>
              {vcBusy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {vcBusy ? t`Installing…` : t`Install now`}
            </button>
          </Row>
        </Section>
      )}

      <Section title={t`Voices`} hint={t`Pick at least one`}>
        {engineRow(
          "kokoro",
          "Kokoro-82M",
          t`About 2 GB · fast, built-in voices`,
          t`A few built-in voices, Japanese and English, a few seconds per line. A little flatter, and it cannot clone a voice. By ${MODEL_CREDITS.kokoro.by}, ${MODEL_CREDITS.kokoro.license}.`,
        )}
        {engineRow(
          "qwen3",
          "Qwen3-TTS",
          t`About 4 GB · clones a voice`,
          t`Clones a voice from a recording in about a third of the natural voice's time. By ${MODEL_CREDITS.qwen3.by}, ${MODEL_CREDITS.qwen3.license}.`,
        )}
        {engineRow(
          "irodori",
          "Irodori-TTS",
          t`About 3 GB · most natural, clones a voice`,
          t`More than 3 GB with a graphics card. The most natural, and it clones a voice. Slowest on a PC without a graphics card. By ${MODEL_CREDITS.irodori.by}, ${MODEL_CREDITS.irodori.license}.`,
        )}
      </Section>

      <ProviderPicker allowNone>
        {!aiOff && !online && (
          <>
            <Row
              title="Ollama"
              description={
                ollama === null
                  ? t`Checking…`
                  : jobFor("ollama")
                    ? t`Installing Ollama. This takes a few minutes.`
                    : ollama.models.length > 0
                      ? t`Running, with ${ollama.models.length} model(s)`
                      : ollama.running
                        ? t`Running, but no model is downloaded yet`
                        : t`Not found on this PC`
              }
              info={t`Runs open models such as Gemma 4 on this PC. Download a model in Settings > AI models.`}
            >
              {ollamaReady ? (
                <ReadyMark />
              ) : ollama && !ollama.running ? (
                jobFor("ollama") ? (
                  installControl("ollama", true, () => setAskOllama(true))
                ) : (
                  <div className="flex items-center gap-2">
                    <button type="button" className={primaryButton} disabled={busy} onClick={() => setAskOllama(true)}>
                      <Trans>Install now</Trans>
                    </button>
                    <button type="button" className={secondaryButton} onClick={() => invoke("plugin:opener|open_url", { url: OLLAMA_PAGE }).catch(console.error)}>
                      <ExternalLink className="w-3.5 h-3.5" /> <Trans>Get Ollama</Trans>
                    </button>
                  </div>
                )
              ) : null}
            </Row>
            {ollamaReady && models && !models.includes(settings.ai_model ?? "") && (
              <Row title={t`Model to write scripts`} info={t`The model the assistant and Auto-Write use.`}>
                <Select
                  label={t`Model to write scripts`}
                  value={settings.ai_model ?? ""}
                  placeholder={t`Choose a model`}
                  onChange={(model) => {
                    updateSettings({ ai_model: model });
                    setIsDirty(true);
                  }}
                  options={models.map((m: string) => ({ value: m, label: m }))}
                  className="w-64"
                />
              </Row>
            )}
          </>
        )}
      </ProviderPicker>
      {!aiOff && online && <OnlineProviderSettings provider={settings.ai_provider as OnlineProvider} />}

      <div className={videoBlocked ? "opacity-50 pointer-events-none select-none" : ""} aria-disabled={videoBlocked}>
        <Section title={t`Video`} optional={t`Optional`} hint={videoBlocked ? t`Needs an NVIDIA graphics card` : undefined}>
          {engineRow(
            "comfyui",
            t`Moving attraction videos`,
            t`About 30 GB · NVIDIA graphics card`,
            t`Turns each photo into a camera move with ${MODEL_CREDITS.ltx.name} (${MODEL_CREDITS.ltx.by}) and ${MODEL_CREDITS.wan.name} (${MODEL_CREDITS.wan.by}, ${MODEL_CREDITS.wan.license}), run by ${MODEL_CREDITS.comfyui.name} (${MODEL_CREDITS.comfyui.license}). Without it, clips pan across the photo.`,
          )}
        </Section>
      </div>

      {running && (
        <p className="text-[12px] text-zinc-500">
          <Trans>Installing in the background. You can close this window; progress shows at the bottom left.</Trans>
        </p>
      )}
      {askOllama && (
        <Dialog
          title={t`Install Ollama?`}
          subtitle={t`Runs Ollama's own installer`}
          onClose={() => setAskOllama(false)}
          footer={
            <>
              <button type="button" className={dialogButton.secondary} onClick={() => setAskOllama(false)}>
                <Trans>Cancel</Trans>
              </button>
              <button type="button" className={dialogButton.primary} onClick={installOllama}>
                <Trans>Install</Trans>
              </button>
            </>
          }
        >
          <div className="space-y-2 pb-1 text-[13px] leading-relaxed text-zinc-600 dark:text-zinc-300">
            <p>
              <Trans>Navivi will run Ollama's official installer from ollama.com in PowerShell:</Trans>
            </p>
            <code className="block rounded-lg bg-zinc-100 dark:bg-zinc-950/60 px-2.5 py-1.5 text-[12px] text-zinc-700 dark:text-zinc-300">irm https://ollama.com/install.ps1 | iex</code>
            <p>
              <Trans>It downloads a large file (about 1 GB), installs Ollama for your account and starts it. You still need to download a model afterwards.</Trans>
            </p>
          </div>
        </Dialog>
      )}
      {error && <p className="rounded-lg bg-red-500/10 px-3 py-2 text-[12px] leading-snug text-red-600 dark:text-red-400 break-words">{error}</p>}
    </div>
  );
}
