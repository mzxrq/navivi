import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useWorkspace } from "../../hooks/useWorkspace";
import { aiEngine, isOnlineEngine } from "../../services/ai/engine";
import { deleteApiKey, saveApiKey } from "../../services/ai/keys";
import { cancelSignIn, signInWithOpenRouter } from "../../services/ai/openrouterAuth";
import { hasApiKey, listOnlineModels, testOnline } from "../../services/ai/online";
import {
  isOnlineProvider,
  ONLINE_PROVIDERS,
  PROVIDERS,
  type AiProviderId,
  type OnlineProvider,
} from "../../services/ai/providers";
import { AlertTriangle, CheckCircle2, ExternalLink, Loader2, RefreshCw, Trash2 } from "./icons";
import { ComboBox } from "./ComboBox";
import { inputClass, Row, secondaryButton, primaryButton, Section, selectClass } from "./SettingsParts";
import { Switch } from "./Switch";

type Check = { state: "idle" } | { state: "working" } | { state: "ok" } | { state: "failed"; message: string };

const messageOf = (e: unknown) => (e instanceof Error ? e.message : String(e));

// Settings > AI models: who writes the scripts. Local Ollama (the default) or a provider on the internet with the user's own key.
export function ProviderPicker() {
  const { settings, updateSettings, setIsDirty } = useWorkspace();
  const provider: AiProviderId = isOnlineProvider(settings.ai_provider) ? settings.ai_provider : "ollama";

  return (
    <Section title={t`Script writer`}>
      <Row
        title={t`Provider`}
        description={t`Where scripts are written. A provider on the internet is usually faster than a local model and does not need a powerful PC.`}
      >
        <select
          value={provider}
          onChange={(e) => {
            updateSettings({ ai_provider: e.target.value as AiProviderId });
            setIsDirty(true);
          }}
          className={`${selectClass} w-64`}
        >
          <option value="ollama">{t`This PC (Ollama)`}</option>
          {ONLINE_PROVIDERS.map((id) => (
            <option key={id} value={id}>
              {PROVIDERS[id].label}
            </option>
          ))}
        </select>
      </Row>
    </Section>
  );
}

export function OnlineProviderSettings({ provider }: { provider: OnlineProvider }) {
  const { settings, updateSettings, setIsDirty } = useWorkspace();
  const info = PROVIDERS[provider];
  const engine = aiEngine(settings);
  const model = isOnlineEngine(engine) ? engine.model : info.defaultModel;
  const baseUrl = settings.ai_online_base_url ?? "";

  const [saved, setSaved] = useState<boolean | null>(null);
  const [draftKey, setDraftKey] = useState("");
  const [keyError, setKeyError] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [listing, setListing] = useState<Check>({ state: "idle" });
  const [test, setTest] = useState<Check>({ state: "idle" });

  useEffect(() => {
    let current = true;
    setSaved(null);
    setDraftKey("");
    setKeyError("");
    setModels([]);
    setListing({ state: "idle" });
    setTest({ state: "idle" });
    hasApiKey(provider).then((has) => current && setSaved(has));
    return () => {
      current = false;
    };
  }, [provider]);

  const update = (patch: Parameters<typeof updateSettings>[0]) => {
    updateSettings(patch);
    setIsDirty(true);
  };

  const saveKey = async () => {
    setKeyError("");
    try {
      await saveApiKey(provider, draftKey);
      setDraftKey("");
      setSaved(true);
      setTest({ state: "idle" });
    } catch (e) {
      setKeyError(messageOf(e));
    }
  };

  const [signingIn, setSigningIn] = useState(false);
  const signIn = async () => {
    setKeyError("");
    setSigningIn(true);
    try {
      await saveApiKey(provider, await signInWithOpenRouter());
      setSaved(true);
      setTest({ state: "idle" });
    } catch (e) {
      setKeyError(messageOf(e));
    } finally {
      setSigningIn(false);
    }
  };

  const removeKey = async () => {
    try {
      await deleteApiKey(provider);
      setSaved(false);
      setModels([]);
      setTest({ state: "idle" });
    } catch (e) {
      setKeyError(messageOf(e));
    }
  };

  const refreshModels = async () => {
    setListing({ state: "working" });
    try {
      setModels(await listOnlineModels(provider, baseUrl));
      setListing({ state: "idle" });
    } catch (e) {
      setListing({ state: "failed", message: messageOf(e) });
    }
  };

  const runTest = async () => {
    if (!isOnlineEngine(engine)) return;
    setTest({ state: "working" });
    try {
      await testOnline(engine);
      setTest({ state: "ok" });
    } catch (e) {
      setTest({ state: "failed", message: messageOf(e) });
    }
  };

  const options = models.length ? models : info.suggested;
  const needsAddress = !!info.askBaseUrl;
  const ready = saved === true && model.trim() !== "" && (!needsAddress || baseUrl.trim() !== "");

  return (
    <>
      <Section title={info.label}>
        <Row
          title={t`API key`}
          description={
            saved
              ? t`Saved in this PC's credential store, not in the project.`
              : provider === "openrouter"
                ? t`Sign in to use Claude, GPT, Gemini and more through one OpenRouter account, billed by OpenRouter. Or paste a key. It is kept in this PC's credential store, never in the project.`
                : t`Paste your key. It is kept in this PC's credential store, never in the project or in shared files.`
          }
          stacked
        >
          <div className="flex items-center gap-2">
            {saved ? (
              <>
                <span className="inline-flex items-center gap-1 text-[12px] font-medium text-emerald-600 dark:text-emerald-400">
                  <CheckCircle2 className="w-3.5 h-3.5" /> <Trans>Key saved</Trans>
                </span>
                <button type="button" onClick={removeKey} className={secondaryButton}>
                  <Trash2 className="w-3.5 h-3.5" /> <Trans>Remove</Trans>
                </button>
              </>
            ) : (
              <>
                {provider === "openrouter" && (
                  <>
                    <button type="button" onClick={signIn} disabled={signingIn} className={primaryButton}>
                      {signingIn ? t`Waiting for the browser…` : t`Sign in with OpenRouter`}
                    </button>
                    {signingIn && (
                      <button type="button" onClick={cancelSignIn} className={secondaryButton}>
                        <Trans>Cancel</Trans>
                      </button>
                    )}
                  </>
                )}
                <input
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  value={draftKey}
                  onChange={(e) => setDraftKey(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && draftKey.trim() && saveKey()}
                  placeholder={t`API key`}
                  className={`${inputClass} flex-1`}
                />
                <button type="button" onClick={saveKey} disabled={!draftKey.trim()} className={primaryButton}>
                  <Trans>Save</Trans>
                </button>
              </>
            )}
            {info.keyPage && (
              <button
                type="button"
                onClick={() => invoke("plugin:opener|open_url", { url: info.keyPage }).catch(console.error)}
                className={secondaryButton}
              >
                <ExternalLink className="w-3.5 h-3.5" /> <Trans>Get a key</Trans>
              </button>
            )}
          </div>
          {keyError && <p className="text-[12px] text-red-500">{keyError}</p>}
        </Row>

        {needsAddress && (
          <Row
            title={t`Address`}
            description={t`The base address of a server that speaks the OpenAI API, for example https://example.com/v1`}
            stacked
          >
            <input
              type="url"
              value={baseUrl}
              onChange={(e) => update({ ai_online_base_url: e.target.value })}
              placeholder="https://example.com/v1"
              spellCheck={false}
              className={`${inputClass} w-full`}
            />
          </Row>
        )}

        <Row title={t`Model`} description={t`Pick one from the list or type its name. Refresh asks the provider what your key can use.`}>
          <div className="flex items-center gap-2">
            <ComboBox
              label={t`Model`}
              value={model}
              options={options}
              allowCustom
              onChange={(v) => update({ ai_online_models: { ...settings.ai_online_models, [provider]: v.trim() } })}
              className="w-56"
            />
            <button
              type="button"
              onClick={refreshModels}
              disabled={!saved || listing.state === "working"}
              title={t`Refresh the model list`}
              aria-label={t`Refresh the model list`}
              className={secondaryButton}
            >
              {listing.state === "working" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            </button>
          </div>
        </Row>
        {listing.state === "failed" && <p className="px-4 py-2 text-[12px] text-red-500 break-words">{listing.message}</p>}

        <Row title={t`Send photos`} description={t`Lets the model see a stop's photos (up to 4, shrunk first) when it writes the script.`}>
          <Switch
            checked={settings.ai_online_send_photos !== false}
            onChange={(v) => update({ ai_online_send_photos: v })}
            label={t`Send photos`}
          />
        </Row>

        <Row title={t`Test`} description={t`Sends a one-word request to check the key and the model.`}>
          <div className="flex items-center gap-2">
            {test.state === "ok" && (
              <span className="inline-flex items-center gap-1 text-[12px] font-medium text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 className="w-3.5 h-3.5" /> <Trans>Works</Trans>
              </span>
            )}
            <button type="button" onClick={runTest} disabled={!ready || test.state === "working"} className={secondaryButton}>
              {test.state === "working" && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              <Trans>Test connection</Trans>
            </button>
          </div>
        </Row>
        {test.state === "failed" && <p className="px-4 py-2 text-[12px] text-red-500 break-words">{test.message}</p>}
      </Section>

      <div className="flex items-start gap-2 rounded-lg bg-amber-500/10 px-3 py-2 text-[12px] leading-snug text-amber-700 dark:text-amber-400">
        <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
        <span>
          {settings.ai_online_send_photos !== false
            ? t`Auto-Write sends the prompt, the place name, its location facts and the stop's photos to ${info.label}. Generate Assets also sends your stops' names and scripts to ${info.label} when it drafts the overview narration. Nothing is sent before then, and usage is billed to your own account there.`
            : t`Auto-Write sends the prompt, the place name and its location facts to ${info.label}. Generate Assets also sends your stops' names and scripts to ${info.label} when it drafts the overview narration. Nothing is sent before then, and usage is billed to your own account there.`}
        </span>
      </div>
    </>
  );
}
