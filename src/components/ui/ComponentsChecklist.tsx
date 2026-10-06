import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { callSidecar, callSidecarShared } from "../../services/sidecar";
import { getLocalModels } from "../../services/ollamaApi";
import { hasApiKey } from "../../services/ai/online";
import { ONLINE_PROVIDERS, PROVIDERS, type OnlineProvider } from "../../services/ai/providers";
import { MODEL_CREDITS } from "../../config/credits";
import { CheckCircle2, ExternalLink, Loader2 } from "./icons";
import { primaryButton, Row, secondaryButton, Section } from "./SettingsParts";

type Engine = "irodori" | "qwen3" | "kokoro" | "comfyui";
type EngineStatus = Record<Engine, boolean | null>;

const INSTALL_ACTION: Record<Engine, string> = {
  kokoro: "tts_install_kokoro",
  qwen3: "tts_install_qwen3",
  irodori: "tts_install_irodori",
  comfyui: "comfyui_install",
};

const OLLAMA_PAGE = "https://ollama.com/download";

// What can be set up after the media tools: the three voices, a script writer, and the moving attraction videos.
// Installs run one at a time: the app runs one Python call at a time and a new call would cancel the running one.
export function ComponentsChecklist() {
  const [engines, setEngines] = useState<EngineStatus>({ irodori: null, qwen3: null, kokoro: null, comfyui: null });
  const [nvidia, setNvidia] = useState<boolean | null>(null);
  const [models, setModels] = useState<string[] | null>(null);
  const [keys, setKeys] = useState<OnlineProvider[] | null>(null);
  const [installing, setInstalling] = useState<Engine | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const reply = await callSidecarShared<Record<Engine, { ready: boolean; nvidia?: boolean } | undefined>>("tts_engines");
    if (reply.success) {
      setEngines({ irodori: !!reply.irodori?.ready, qwen3: !!reply.qwen3?.ready, kokoro: !!reply.kokoro?.ready, comfyui: !!reply.comfyui?.ready });
      setNvidia(!!reply.comfyui?.nvidia);
    }
    setModels(await getLocalModels());
    const saved = await Promise.all(ONLINE_PROVIDERS.map(async (p) => ((await hasApiKey(p)) ? p : null)));
    setKeys(saved.filter((p): p is OnlineProvider => p !== null));
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const install = async (which: Engine) => {
    setInstalling(which);
    setError("");
    const reply = await callSidecar(INSTALL_ACTION[which], {});
    setInstalling(null);
    if (!reply.success && !reply.cancelled) setError(reply.error);
    await refresh();
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
  const loaded = engines.kokoro !== null && models !== null && keys !== null;
  const todo: string[] = [];
  if (loaded) {
    if (!anyVoice) todo.push(t`Set up at least one voice, or the video has no narration.`);
    if (models.length === 0 && keys.length === 0) todo.push(t`Optional: a script writer, for the assistant and Auto-Write. You can type every script yourself without one.`);
    if (!engines.comfyui && nvidia) todo.push(t`Optional: moving attraction videos. Without them, each clip pans across the photo.`);
  }

  return (
    <div className="space-y-5">
      <p className="text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
        <Trans>Check what you need. Only one voice is required; everything else is optional and can be added later.</Trans>
      </p>
      {loaded && (
        <div className={`rounded-xl px-4 py-3 text-[12px] leading-relaxed ${anyVoice ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" : "bg-amber-500/10 text-amber-700 dark:text-amber-300"}`}>
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

      <Section title={t`Voices`} hint={t`Pick at least one`}>
        {voice("kokoro", t`Fast voice · Kokoro-82M`, t`About 2 GB. A few built-in Japanese voices, a few seconds per line. A little flatter, and it cannot clone a voice. By ${MODEL_CREDITS.kokoro.by}, ${MODEL_CREDITS.kokoro.license}.`)}
        {voice("qwen3", t`Balanced voice · Qwen3-TTS`, t`About 4 GB. Clones a voice from a recording in about a third of the natural voice's time. By ${MODEL_CREDITS.qwen3.by}, ${MODEL_CREDITS.qwen3.license}.`)}
        {voice("irodori", t`Natural voice · Irodori-TTS`, t`About 3 GB, more with a graphics card. The most natural, and it clones a voice. Slowest on a PC without a graphics card. By ${MODEL_CREDITS.irodori.by}, ${MODEL_CREDITS.irodori.license}.`)}
      </Section>

      <Section title={t`Script writer`}>
        <Row
          title={t`Ollama on this PC · open models such as Gemma 4`}
          description={
            models === null
              ? t`Checking…`
              : models.length > 0
                ? t`Running, with ${models.length} model(s). Download more in Settings > AI models.`
                : t`Not found. Install Ollama and keep it running, then download a model in Settings > AI models.`
          }
        >
          {models !== null && models.length > 0 ? (
            <span className="inline-flex items-center gap-1 text-[12px] font-medium text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="w-3.5 h-3.5" /> <Trans>Ready</Trans>
            </span>
          ) : (
            <button type="button" className={secondaryButton} onClick={() => invoke("plugin:opener|open_url", { url: OLLAMA_PAGE }).catch(console.error)}>
              <ExternalLink className="w-3.5 h-3.5" /> <Trans>Get Ollama</Trans>
            </button>
          )}
        </Row>
        <Row
          title={t`Online AI service · your own API key`}
          description={
            keys === null
              ? t`Checking…`
              : keys.length > 0
                ? t`Key saved for ${keys.map((p) => PROVIDERS[p].label).join(", ")}.`
                : t`Nothing to install. Add a key from OpenRouter, Anthropic, OpenAI, Google Gemini or another provider in Settings > AI models (turn on AI features in General first).`
          }
        >
          {keys !== null && keys.length > 0 && (
            <span className="inline-flex items-center gap-1 text-[12px] font-medium text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="w-3.5 h-3.5" /> <Trans>Ready</Trans>
            </span>
          )}
        </Row>
      </Section>

      <Section title={t`Video`} hint={t`Optional`}>
        {voice(
          "comfyui",
          t`Moving attraction videos · ComfyUI`,
          t`About 30 GB and an NVIDIA graphics card. Turns each photo into a camera move with ${MODEL_CREDITS.ltx.name} (${MODEL_CREDITS.ltx.by}) and ${MODEL_CREDITS.wan.name} (${MODEL_CREDITS.wan.by}, ${MODEL_CREDITS.wan.license}), run by ${MODEL_CREDITS.comfyui.name} (${MODEL_CREDITS.comfyui.license}). Without it, clips pan across the photo.`,
        )}
      </Section>

      {installing && (
        <p className="flex items-center gap-1.5 text-[12px] text-zinc-500">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />{" "}
          {installing === "comfyui" ? (
            <Trans>This downloads about 30 GB and can take an hour or more. Stay on this tab; a stopped download continues where it left off.</Trans>
          ) : (
            <Trans>This takes several minutes. Keep this window open while it runs.</Trans>
          )}
        </p>
      )}
      {error && <p className="rounded-lg bg-red-500/10 px-3 py-2 text-[12px] leading-snug text-red-600 dark:text-red-400 break-words">{error}</p>}
    </div>
  );
}
