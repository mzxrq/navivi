import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { callSidecar, callSidecarShared } from "../../services/sidecar";
import { getLocalModels } from "../../services/ollamaApi";
import { hasApiKey } from "../../services/ai/online";
import { ONLINE_PROVIDERS, PROVIDERS, type OnlineProvider } from "../../services/ai/providers";
import { CheckCircle2, ExternalLink, Loader2 } from "./icons";
import { primaryButton, Row, secondaryButton, Section } from "./SettingsParts";

type Engine = "irodori" | "qwen3" | "kokoro";
type EngineStatus = Record<Engine, boolean | null>;

const OLLAMA_PAGE = "https://ollama.com/download";

// What can be set up after the media tools: the three voices, a script writer, and what is not available yet.
// Installs run one at a time: the app runs one Python call at a time and a new call would cancel the running one.
export function ComponentsChecklist() {
  const [engines, setEngines] = useState<EngineStatus>({ irodori: null, qwen3: null, kokoro: null });
  const [models, setModels] = useState<string[] | null>(null);
  const [keys, setKeys] = useState<OnlineProvider[] | null>(null);
  const [installing, setInstalling] = useState<Engine | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const reply = await callSidecarShared<Record<Engine, { ready: boolean } | undefined>>("tts_engines");
    if (reply.success) {
      setEngines({ irodori: !!reply.irodori?.ready, qwen3: !!reply.qwen3?.ready, kokoro: !!reply.kokoro?.ready });
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
    const reply = await callSidecar(`tts_install_${which}`, {});
    setInstalling(null);
    if (!reply.success && !reply.cancelled) setError(reply.error);
    await refresh();
  };

  const voice = (which: Engine, title: string, description: string) => {
    const ready = engines[which];
    return (
      <Row title={title} description={description}>
        {ready ? (
          <span className="inline-flex items-center gap-1 text-[12px] font-medium text-emerald-600 dark:text-emerald-400">
            <CheckCircle2 className="w-3.5 h-3.5" /> <Trans>Ready</Trans>
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

  return (
    <div className="space-y-5">
      <Section title={t`Voices`} hint={t`Pick at least one`}>
        {voice("kokoro", t`Fast voice · about 2 GB`, t`A few built-in Japanese voices, a few seconds per line. A little flatter, and it cannot clone a voice.`)}
        {voice("qwen3", t`Balanced voice · about 4 GB`, t`Clones a voice from a recording in about a third of the natural voice's time.`)}
        {voice("irodori", t`Natural voice · about 3 GB, more with a graphics card`, t`The most natural, and it clones a voice. Slowest on a PC without a graphics card.`)}
      </Section>

      <Section title={t`Script writer`}>
        <Row
          title={t`Ollama on this PC`}
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
          title={t`Online AI`}
          description={
            keys === null
              ? t`Checking…`
              : keys.length > 0
                ? t`Key saved for ${keys.map((p) => PROVIDERS[p].label).join(", ")}.`
                : t`Nothing to install: add your own API key in Settings > AI models (turn on AI features in General first).`
          }
        >
          {keys !== null && keys.length > 0 && (
            <span className="inline-flex items-center gap-1 text-[12px] font-medium text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="w-3.5 h-3.5" /> <Trans>Ready</Trans>
            </span>
          )}
        </Row>
      </Section>

      <Section title={t`Video`}>
        <Row title={t`Moving attraction videos`} description={t`Needs a powerful graphics card and is not part of the installer yet. Until then, attraction clips pan across the photo.`}>
          <span className="text-[12px] text-zinc-400">
            <Trans>Not available yet</Trans>
          </span>
        </Row>
      </Section>

      {installing && (
        <p className="flex items-center gap-1.5 text-[12px] text-zinc-500">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> <Trans>This takes several minutes. Keep this window open while it runs.</Trans>
        </p>
      )}
      {error && <p className="rounded-lg bg-red-500/10 px-3 py-2 text-[12px] leading-snug text-red-600 dark:text-red-400 break-words">{error}</p>}
    </div>
  );
}
