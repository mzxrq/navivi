import { useEffect, useRef, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useAssistant } from "../../hooks/useAssistant";
import { useUI } from "../../hooks/useUI";
import { useWorkspace } from "../../hooks/useWorkspace";
import { Paperclip, X } from "../../components/ui/icons";
import { SOURCE_EXTENSIONS } from "../../services/assistant/sources";
import { primaryButton, secondaryButton } from "../../components/ui/SettingsParts";

const PICK_EXTENSIONS = [...SOURCE_EXTENSIONS, "gpx", "jpg", "jpeg", "png", "heic", "heif"];
const baseName = (p: string) => p.split(/[\\/]/).pop() ?? p;

function briefFacts(brief: ReturnType<typeof useAssistant>["brief"]): { label: string; value: string }[] {
  const facts: { label: string; value: string }[] = [];
  if (brief.places.length) facts.push({ label: t`Stops`, value: String(brief.places.length) });
  if (brief.durationMin) facts.push({ label: t`Length`, value: t`${brief.durationMin} min` });
  if (brief.languages.length) facts.push({ label: t`Narration`, value: brief.languages.map((l) => (l === "ja" ? t`Japanese` : t`English`)).join(" · ") });
  if (brief.tone) facts.push({ label: t`Tone`, value: brief.tone });
  return facts;
}

export function AssistantChat({ variant }: { variant: "hero" | "panel" }) {
  const { messages, brief, sources, attachments, phase, progress, ready, send, build, stop, reset } = useAssistant();
  const { settings } = useWorkspace();
  const { setShowAppSettings } = useUI();
  const [text, setText] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const listRef = useRef<HTMLDivElement>(null);
  const busy = phase !== "idle";
  const hero = variant === "hero";

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages, phase, progress]);

  const submit = () => {
    if (busy || (!text.trim() && picked.length === 0)) return;
    const message = text;
    const files = picked;
    setText("");
    setPicked([]);
    void send(message, files);
  };

  const attach = async () => {
    const chosen = await open({ multiple: true, filters: [{ name: t`Documents, GPS tracks and photos`, extensions: PICK_EXTENSIONS }] });
    if (!chosen) return;
    const paths = Array.isArray(chosen) ? chosen : [chosen];
    setPicked((p) => [...p, ...paths.filter((x) => !p.includes(x))]);
  };

  const needsAi = !settings.ai_features_enabled;
  const facts = briefFacts(brief);
  const examples = [
    t`A calm 5 minute video of the pilgrimage route in the PDF I attach, for visitors from abroad`,
    t`A day trip around Shirahama in Wakayama, Japanese narration, about 3 minutes`,
  ];
  const stepName = progress?.step === "places" ? t`Finding places` : progress?.step === "geocode" ? t`Locating places` : progress?.step === "scripts" ? t`Writing scripts` : t`Starting…`;

  return (
    <div className={`flex flex-col min-h-0 ${hero ? "" : "h-full"}`}>
      {needsAi ? (
        <div className="rounded-lg border border-zinc-200 dark:border-white/10 px-4 py-3 text-[13px] text-zinc-600 dark:text-zinc-300">
          <p>
            <Trans>The assistant needs an AI model. Turn on AI features, then pick a local model or add an API key.</Trans>
          </p>
          <button type="button" className={`${secondaryButton} mt-2`} onClick={() => { setShowAppSettings(true); window.dispatchEvent(new CustomEvent("open-app-settings-tab", { detail: "general" })); }}>
            <Trans>Open settings</Trans>
          </button>
        </div>
      ) : (
        <>
          {messages.length > 0 && (
            <div ref={listRef} className={`overflow-y-auto custom-scrollbar divide-y divide-zinc-100 dark:divide-white/5 ${hero ? "max-h-80 mb-3 rounded-lg border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-950/40" : "flex-1 min-h-0 mb-3"}`}>
              {messages.map((m, i) => (
                <div key={i} className="px-3 py-2.5">
                  <div className="mb-0.5 text-[11px] text-zinc-400 dark:text-zinc-500">{m.role === "user" ? t`You` : t`Assistant`}</div>
                  <p className="text-[13px] leading-relaxed whitespace-pre-wrap text-zinc-800 dark:text-zinc-200">{m.text}</p>
                  {m.role === "user" && m.files && m.files.length > 0 && <div className="mt-1 text-[11px] text-zinc-500 dark:text-zinc-400 break-all">{m.files.join(" · ")}</div>}
                </div>
              ))}
              {phase === "thinking" && <div className="px-3 py-2.5 text-[12px] text-zinc-400 animate-pulse">{t`Thinking…`}</div>}
            </div>
          )}

          {messages.length === 0 && !hero && (
            <p className="flex-1 min-h-0 flex items-center justify-center px-6 text-center text-[12px] leading-relaxed text-zinc-400">
              <Trans>Describe a trip and I will set up the stops and scripts for you. Attach an itinerary if you have one.</Trans>
            </p>
          )}

          {phase === "building" && (
            <div className="mb-3 rounded-lg border border-zinc-200 dark:border-white/10 px-3 py-2.5">
              <div className="flex items-center justify-between gap-3 text-[12px]">
                <span className="font-medium text-zinc-800 dark:text-zinc-200">{stepName}</span>
                {progress && progress.total > 1 && <span className="tabular-nums text-zinc-400">{progress.done}/{progress.total}</span>}
              </div>
              {progress?.label && <div className="mt-0.5 truncate text-[11px] text-zinc-500 dark:text-zinc-400">{progress.label}</div>}
              <div className="mt-2 h-1 rounded-full bg-zinc-100 dark:bg-white/10 overflow-hidden">
                <div className="h-full bg-navi transition-all" style={{ width: `${progress && progress.total ? Math.max(4, (progress.done / progress.total) * 100) : 4}%` }} />
              </div>
            </div>
          )}

          {ready && phase === "idle" && (
            <div className="mb-3 rounded-lg border border-navi/30 bg-navi/5">
              <div className="flex items-start justify-between gap-3 px-3 pt-2.5">
                <div className="min-w-0">
                  <div className="text-[11px] text-zinc-500 dark:text-zinc-400">
                    <Trans>Ready to build</Trans>
                  </div>
                  <div className="truncate text-[13px] font-medium text-zinc-900 dark:text-zinc-100">{brief.name || (attachments.gpx ? baseName(attachments.gpx) : (sources[0]?.name ?? t`Your trip`))}</div>
                </div>
                <button type="button" className={`${primaryButton} shrink-0`} onClick={() => void build()}>
                  <Trans>Create project</Trans>
                </button>
              </div>
              {facts.length > 0 && (
                <dl className="flex flex-wrap gap-x-5 gap-y-1 px-3 pb-2.5 pt-2 text-[12px]">
                  {facts.map((f) => (
                    <div key={f.label} className="flex items-baseline gap-1.5">
                      <dt className="text-zinc-400 dark:text-zinc-500">{f.label}</dt>
                      <dd className="text-zinc-700 dark:text-zinc-200">{f.value}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          )}

          <div className="rounded-lg border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-950/40 focus-within:border-navi focus-within:ring-2 focus-within:ring-navi/20 transition">
            <textarea
              value={text}
              rows={hero ? 3 : 2}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  submit();
                }
              }}
              placeholder={hero ? t`Describe the video you want: where it goes, how long, and in what tone.` : t`Ask or add details…`}
              className="block w-full max-h-40 resize-none bg-transparent px-3 pt-2.5 pb-1 text-[13px] leading-relaxed text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 outline-none"
            />
            {picked.length > 0 && (
              <div className="flex flex-wrap gap-1.5 px-3 pb-1.5">
                {picked.map((p) => (
                  <span key={p} className="inline-flex items-center gap-1 h-6 pl-2 pr-1 rounded-md border border-zinc-200 dark:border-white/10 text-[11px] text-zinc-600 dark:text-zinc-300">
                    {baseName(p)}
                    <button type="button" aria-label={t`Remove`} onClick={() => setPicked((x) => x.filter((y) => y !== p))} className="w-4 h-4 rounded hover:bg-zinc-100 dark:hover:bg-white/10 flex items-center justify-center">
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}
            <div className="flex items-center justify-between gap-2 border-t border-zinc-100 dark:border-white/5 px-2 py-1.5">
              <button type="button" onClick={attach} disabled={busy} title={t`Attach an itinerary (PDF, Word, text), a GPX track or photos. Paste a web link into the message.`} className="inline-flex items-center gap-1.5 h-7 px-2 rounded-md text-[12px] text-zinc-500 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-white/10 hover:text-zinc-800 dark:hover:text-zinc-100 disabled:opacity-40 transition-colors">
                <Paperclip className="w-3.5 h-3.5" />
                {hero ? <Trans>Attach a file</Trans> : <span className="sr-only">{t`Attach files`}</span>}
              </button>
              <div className="flex items-center gap-2">
                {hero && !busy && <span className="hidden sm:inline text-[11px] text-zinc-400 dark:text-zinc-500">{t`Enter to send · Shift+Enter for a new line`}</span>}
                {busy ? (
                  <button type="button" onClick={stop} className={secondaryButton}>
                    <Trans>Stop</Trans>
                  </button>
                ) : (
                  <button type="button" onClick={submit} disabled={!text.trim() && picked.length === 0} className={primaryButton}>
                    <Trans>Send</Trans>
                  </button>
                )}
              </div>
            </div>
          </div>

          {messages.length === 0 && hero && (
            <div className="mt-3 text-[12px] text-zinc-500 dark:text-zinc-400">
              <div className="mb-1">
                <Trans>Or start from an example</Trans>
              </div>
              <ul className="space-y-0.5">
                {examples.map((example) => (
                  <li key={example}>
                    <button type="button" onClick={() => setText(example)} className="text-left hover:text-navi hover:underline underline-offset-2 transition-colors">
                      {example}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {messages.length > 0 && phase === "idle" && (
            <button type="button" onClick={reset} className="mt-2 self-start text-[11px] text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 transition-colors">
              <Trans>Start over</Trans>
            </button>
          )}
        </>
      )}
    </div>
  );
}
