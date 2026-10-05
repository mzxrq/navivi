import { useEffect, useRef, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useAssistant } from "../../hooks/useAssistant";
import { useUI } from "../../hooks/useUI";
import { useWorkspace } from "../../hooks/useWorkspace";
import { ArrowUp, FileText, Footprints, Map, Plus, Route, Square, X } from "../../components/ui/icons";
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
  const inputRef = useRef<HTMLTextAreaElement>(null);
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
  const starters = [
    { icon: Map, label: t`Day trip`, prompt: t`A day trip around Shirahama in Wakayama, Japanese narration, about 3 minutes` },
    { icon: Footprints, label: t`Pilgrimage guide`, prompt: t`A calm 5 minute video of the pilgrimage route in the PDF I attach, for visitors from abroad` },
    { icon: Route, label: t`Follow my GPS track`, prompt: t`A relaxed walking video that follows the GPX track I attach, with English narration, about 4 minutes` },
    { icon: FileText, label: t`From an itinerary`, prompt: t`Turn the itinerary I attach into a 3 minute video with Japanese narration` },
  ];
  const stepName = progress?.step === "places" ? t`Finding places` : progress?.step === "geocode" ? t`Locating places` : progress?.step === "scripts" ? t`Writing scripts` : t`Starting…`;
  const canSend = !!text.trim() || picked.length > 0;
  const stopLabel = t({ message: "Stop", context: "stop the assistant" });

  return (
    <div className={`flex flex-col min-h-0 ${hero ? "" : "h-full"}`}>
      {needsAi ? (
        <div className="rounded-2xl border border-zinc-200 dark:border-white/10 px-4 py-3 text-[13px] text-zinc-600 dark:text-zinc-300">
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
            <div ref={listRef} className={`overflow-y-auto custom-scrollbar space-y-4 pr-1 ${hero ? "max-h-96 mb-4" : "flex-1 min-h-0 mb-3"}`}>
              {messages.map((m, i) =>
                m.role === "user" ? (
                  <div key={i} className="flex justify-end">
                    <div className="max-w-[85%] rounded-2xl rounded-br-md bg-zinc-100 dark:bg-white/8 px-3.5 py-2 text-[14px] leading-relaxed whitespace-pre-wrap text-zinc-900 dark:text-zinc-100">
                      {m.text}
                      {m.files && m.files.length > 0 && <div className="mt-1 text-[11px] text-zinc-500 dark:text-zinc-400 break-all">{m.files.join(" · ")}</div>}
                    </div>
                  </div>
                ) : (
                  <p key={i} className="text-[14px] leading-relaxed whitespace-pre-wrap text-zinc-800 dark:text-zinc-200">
                    {m.text}
                  </p>
                ),
              )}
              {phase === "thinking" && <p className="text-[13px] text-zinc-400 animate-pulse">{t`Thinking…`}</p>}
            </div>
          )}

          {messages.length === 0 && !hero && (
            <div className="flex-1 min-h-0 flex flex-col items-center justify-center gap-2 px-6 text-center">
              <p className="font-serif text-[18px] text-zinc-800 dark:text-zinc-100">
                <Trans>Where are we going?</Trans>
              </p>
              <p className="text-[12px] leading-relaxed text-zinc-400">
                <Trans>Describe a trip and I will set up the stops and scripts for you. Attach an itinerary if you have one.</Trans>
              </p>
            </div>
          )}

          {phase === "building" && (
            <div className="mb-3 rounded-xl border border-zinc-200 dark:border-white/10 px-3.5 py-3">
              <div className="flex items-center justify-between gap-3 text-[13px]">
                <span className="font-medium text-zinc-800 dark:text-zinc-200">{stepName}</span>
                {progress && progress.total > 1 && <span className="tabular-nums text-[12px] text-zinc-400">{progress.done}/{progress.total}</span>}
              </div>
              {progress?.label && <div className="mt-0.5 truncate text-[12px] text-zinc-500 dark:text-zinc-400">{progress.label}</div>}
              <div className="mt-2.5 h-1 rounded-full bg-zinc-100 dark:bg-white/10 overflow-hidden">
                <div className="h-full bg-navi transition-all" style={{ width: `${progress && progress.total ? Math.max(4, (progress.done / progress.total) * 100) : 4}%` }} />
              </div>
            </div>
          )}

          {ready && phase === "idle" && (
            <div className="mb-3 rounded-xl border border-navi/30 bg-navi/5">
              <div className="flex items-start justify-between gap-3 px-3.5 pt-3">
                <div className="min-w-0">
                  <div className="text-[11px] text-zinc-500 dark:text-zinc-400">
                    <Trans>Ready to build</Trans>
                  </div>
                  <div className="truncate text-[14px] font-medium text-zinc-900 dark:text-zinc-100">{brief.name || (attachments.gpx ? baseName(attachments.gpx) : (sources[0]?.name ?? t`Your trip`))}</div>
                </div>
                <button type="button" className={`${primaryButton} shrink-0`} onClick={() => void build()}>
                  <Trans>Create project</Trans>
                </button>
              </div>
              {facts.length > 0 && (
                <dl className="flex flex-wrap gap-x-5 gap-y-1 px-3.5 pb-3 pt-2 text-[12px]">
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

          <div className="rounded-2xl border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-950/40 shadow-sm focus-within:border-navi/60 focus-within:ring-4 focus-within:ring-navi/10 transition">
            <textarea
              ref={inputRef}
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
              className={`block w-full max-h-48 resize-none bg-transparent px-4 pt-3.5 pb-1 leading-relaxed text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 outline-none ${hero ? "text-[14px]" : "text-[13px]"}`}
            />
            {picked.length > 0 && (
              <div className="flex flex-wrap gap-1.5 px-3 pb-1">
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
            <div className="flex items-center justify-between gap-2 px-2.5 pb-2.5 pt-1">
              <button type="button" onClick={attach} disabled={busy} aria-label={t`Attach files`} title={t`Attach an itinerary (PDF, Word, text), a GPX track or photos. Paste a web link into the message.`} className="w-8 h-8 rounded-lg flex items-center justify-center text-zinc-500 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-white/10 hover:text-zinc-800 dark:hover:text-zinc-100 disabled:opacity-40 transition-colors">
                <Plus className="w-[18px] h-[18px]" />
              </button>
              {busy ? (
                <button type="button" onClick={stop} aria-label={stopLabel} title={stopLabel} className="w-8 h-8 rounded-lg flex items-center justify-center bg-zinc-800 dark:bg-zinc-200 text-white dark:text-zinc-900 hover:opacity-85 transition">
                  <Square className="w-3 h-3 fill-current" />
                </button>
              ) : (
                <button type="button" onClick={submit} disabled={!canSend} aria-label={t`Send`} title={t`Send`} className="w-8 h-8 rounded-lg flex items-center justify-center bg-navi text-white hover:brightness-110 disabled:bg-zinc-200 dark:disabled:bg-white/10 disabled:text-zinc-400 disabled:pointer-events-none transition">
                  <ArrowUp className="w-4 h-4" strokeWidth={2.5} />
                </button>
              )}
            </div>
          </div>

          {messages.length === 0 && hero && (
            <div className="mt-3 flex flex-wrap gap-2">
              {starters.map(({ icon: Icon, label, prompt }) => (
                <button
                  key={label}
                  type="button"
                  title={prompt}
                  onClick={() => {
                    setText(prompt);
                    inputRef.current?.focus();
                  }}
                  className="inline-flex items-center gap-1.5 h-8 px-3 rounded-xl border border-zinc-200 dark:border-white/10 bg-white dark:bg-white/5 text-[13px] text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-white/10 hover:border-zinc-300 transition-colors"
                >
                  <Icon className="w-3.5 h-3.5 text-zinc-400" />
                  {label}
                </button>
              ))}
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
