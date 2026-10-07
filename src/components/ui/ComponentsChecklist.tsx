import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { callSidecar, callSidecarShared } from "../../services/sidecar";
import { getOllamaState } from "../../services/ollamaApi";
import { hasApiKey } from "../../services/ai/online";
import { AI_KEYS_CHANGED } from "../../services/ai/keys";
import { isOnlineProvider, ONLINE_PROVIDERS, type OnlineProvider } from "../../services/ai/providers";
import { installVcRuntime } from "../../services/setup";
import { useWorkspace } from "../../hooks/useWorkspace";
import { MODEL_CREDITS } from "../../config/credits";
import { CheckCircle2, ExternalLink, Loader2 } from "./icons";
import { Dialog, dialogButton } from "./Dialog";
import { OnlineProviderSettings, ProviderPicker } from "./OnlineAiSettings";
import { primaryButton, Row, secondaryButton, Section, selectClass } from "./SettingsParts";

type Engine = "irodori" | "qwen3" | "kokoro" | "comfyui";
type EngineStatus = Record<Engine, boolean | null>;
type Installing = Engine | "ollama" | "vc";

const INSTALL_ACTION: Record<Engine, string> = {
  kokoro: "tts_install_kokoro",
  qwen3: "tts_install_qwen3",
  irodori: "tts_install_irodori",
  comfyui: "comfyui_install",
};

const OLLAMA_PAGE = "https://ollama.com/download";
const OLLAMA_RECHECK_MS = 4000;

// What can be set up after the media tools: the three voices, a script writer, and the moving attraction videos.
// Installs run one at a time: the app runs one Python call at a time and a new call would cancel the running one.
export function ComponentsChecklist() {
  const { settings, updateSettings, setIsDirty } = useWorkspace();
  const [engines, setEngines] = useState<EngineStatus>({ irodori: null, qwen3: null, kokoro: null, comfyui: null });
  const [nvidia, setNvidia] = useState<boolean | null>(null);
  const [vc, setVc] = useState<boolean | null>(null);
  const [ollama, setOllama] = useState<{ running: boolean; models: string[] } | null>(null);
  const [keys, setKeys] = useState<OnlineProvider[] | null>(null);
  const [installing, setInstalling] = useState<Installing | null>(null);
  const [askOllama, setAskOllama] = useState(false);
  const [error, setError] = useState("");
  const models = ollama ? ollama.models : null;
  const online = isOnlineProvider(settings.ai_provider);
  const ollamaReady = !!ollama && ollama.models.length > 0;

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

  const install = async (which: Engine) => {
    setInstalling(which);
    setError("");
    const reply = await callSidecar(INSTALL_ACTION[which], {});
    setInstalling(null);
    if (!reply.success && !reply.cancelled) setError(reply.error);
    await refresh();
  };

  const installOllama = async () => {
    setAskOllama(false);
    setInstalling("ollama");
    setError("");
    const reply = await callSidecar("ollama_install", {});
    setInstalling(null);
    if (!reply.success && !reply.cancelled) setError(reply.error);
    await recheck();
  };

  const installVc = async () => {
    setInstalling("vc");
    setError("");
    try {
      await installVcRuntime();
      setVc(true);
    } catch (e) {
      setError(String(e));
    }
    setInstalling(null);
  };

  const voice = (which: Engine, title: string, description: string) => {
    const ready = engines[which];
    const blocked = which === "comfyui" && nvidia === false;
    return (
      <Row title={title} description={description}>
        {ready ? (
          <span className="inline-flex items-center gap-1 text-[12px] font-medium text-emerald-600 dark:text-emerald-400">
            <CheckCircle2 className="w-3.5 h-3.5" /> <Trans>Ready</Trans>
          </span>
        ) : blocked ? (
          <span className="text-[12px] text-zinc-400">
            <Trans>Needs an NVIDIA graphics card</Trans>
          </span>
        ) : (
          <button type="button" className={primaryButton} disabled={ready === null || installing !== null} onClick={() => install(which)}>
            {installing === which && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {installing === which ? t`Setting up…` : t`Set up`}
          </button>
        )}
      </Row>
    );
  };

  const anyVoice = engines.kokoro || engines.qwen3 || engines.irodori;
  const loaded = engines.kokoro !== null && ollama !== null && keys !== null;
  const todo: string[] = [];
  if (loaded) {
    if (vc === false) todo.push(t`Install the Microsoft Visual C++ runtime, or GPS files, rendering and the voices will not start.`);
    if (!anyVoice) todo.push(t`Set up at least one voice, or the video has no narration.`);
    if (models !== null && models.length === 0 && keys.length === 0) todo.push(t`Optional: a script writer, for the assistant and Auto-Write. You can type every script yourself without one.`);
    if (!engines.comfyui && nvidia) todo.push(t`Optional: moving attraction videos. Without them, each clip pans across the photo.`);
  }

  return (
    <div className="space-y-5">
      <p className="text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
        <Trans>Check what you need. Only one voice is required; everything else is optional and can be added later.</Trans>
      </p>
      {loaded && (
        <div className={`rounded-xl px-4 py-3 text-[12px] leading-relaxed ${anyVoice && vc !== false ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" : "bg-amber-500/10 text-amber-700 dark:text-amber-300"}`}>
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
            description={t`Missing on this PC. GPS files, rendering and the voices need it. About 25 MB from Microsoft; Windows asks for permission first.`}
          >
            <button type="button" className={primaryButton} disabled={installing !== null} onClick={installVc}>
              {installing === "vc" && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {installing === "vc" ? t`Installing…` : t`Install now`}
            </button>
          </Row>
        </Section>
      )}

      <Section title={t`Voices`} hint={t`Pick at least one`}>
        {voice("kokoro", t`Fast voice · Kokoro-82M`, t`About 2 GB. A few built-in Japanese voices, a few seconds per line. A little flatter, and it cannot clone a voice. By ${MODEL_CREDITS.kokoro.by}, ${MODEL_CREDITS.kokoro.license}.`)}
        {voice("qwen3", t`Balanced voice · Qwen3-TTS`, t`About 4 GB. Clones a voice from a recording in about a third of the natural voice's time. By ${MODEL_CREDITS.qwen3.by}, ${MODEL_CREDITS.qwen3.license}.`)}
        {voice("irodori", t`Natural voice · Irodori-TTS`, t`About 3 GB, more with a graphics card. The most natural, and it clones a voice. Slowest on a PC without a graphics card. By ${MODEL_CREDITS.irodori.by}, ${MODEL_CREDITS.irodori.license}.`)}
      </Section>

      <ProviderPicker />
      {online ? (
        <OnlineProviderSettings provider={settings.ai_provider as OnlineProvider} />
      ) : (
        <Section title={t`Ollama`}>
          <Row
            title={t`Ollama on this PC · open models such as Gemma 4`}
            description={
              ollama === null
                ? t`Checking…`
                : installing === "ollama"
                  ? t`Installing Ollama. This downloads a large file and takes a few minutes.`
                  : ollama.models.length > 0
                    ? t`Running, with ${ollama.models.length} model(s). Download more in Settings > AI models.`
                    : ollama.running
                      ? t`Running, but no model is downloaded yet. Download one in Settings > AI models.`
                      : t`Not found. Install Ollama, then download a model in Settings > AI models.`
            }
          >
            {ollamaReady ? (
              <span className="inline-flex items-center gap-1 text-[12px] font-medium text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 className="w-3.5 h-3.5" /> <Trans>Ready</Trans>
              </span>
            ) : ollama && !ollama.running ? (
              <div className="flex items-center gap-2">
                <button type="button" className={primaryButton} disabled={installing !== null} onClick={() => setAskOllama(true)}>
                  {installing === "ollama" && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  {installing === "ollama" ? t`Installing…` : t`Install now`}
                </button>
                <button type="button" className={secondaryButton} onClick={() => invoke("plugin:opener|open_url", { url: OLLAMA_PAGE }).catch(console.error)}>
                  <ExternalLink className="w-3.5 h-3.5" /> <Trans>Get Ollama</Trans>
                </button>
              </div>
            ) : null}
          </Row>
          {ollamaReady && !ollama.models.includes(settings.ai_model ?? "") && (
            <Row title={t`Model to write scripts`} description={t`The model the assistant and Auto-Write use.`}>
              <select
                value={settings.ai_model ?? ""}
                onChange={(e) => {
                  updateSettings({ ai_model: e.target.value });
                  setIsDirty(true);
                }}
                className={`${selectClass} w-64`}
              >
                <option value="" disabled>
                  {t`Choose a model`}
                </option>
                {ollama.models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </Row>
          )}
        </Section>
      )}

      <Section title={t`Video`} hint={t`Optional`}>
        {voice(
          "comfyui",
          t`Moving attraction videos · ComfyUI`,
          t`About 30 GB and an NVIDIA graphics card. Turns each photo into a camera move with ${MODEL_CREDITS.ltx.name} (${MODEL_CREDITS.ltx.by}) and ${MODEL_CREDITS.wan.name} (${MODEL_CREDITS.wan.by}, ${MODEL_CREDITS.wan.license}), run by ${MODEL_CREDITS.comfyui.name} (${MODEL_CREDITS.comfyui.license}). Without it, clips pan across the photo.`,
        )}
      </Section>

      {installing && installing !== "vc" && (
        <p className="flex items-center gap-1.5 text-[12px] text-zinc-500">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />{" "}
          {installing === "comfyui" ? (
            <Trans>This downloads about 30 GB and can take an hour or more. Stay on this tab; a stopped download continues where it left off.</Trans>
          ) : (
            <Trans>This takes several minutes. Keep this window open while it runs.</Trans>
          )}
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
