import { useEffect, useRef, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useAssistant } from "../../hooks/useAssistant";
import { useUI } from "../../hooks/useUI";
import { useWorkspace } from "../../hooks/useWorkspace";
import { ArrowUp, Paperclip, X } from "../../components/ui/icons";
import { SOURCE_EXTENSIONS } from "../../services/assistant/sources";
import { primaryButton, secondaryButton } from "../../components/ui/SettingsParts";

const PICK_EXTENSIONS = [...SOURCE_EXTENSIONS, "gpx", "jpg", "jpeg", "png", "heic", "heif"];
const baseName = (p: string) => p.split(/[\\/]/).pop() ?? p;

function briefSummary(brief: ReturnType<typeof useAssistant>["brief"]): string[] {
  const parts: string[] = [];
  if (brief.places.length) parts.push(brief.places.length === 1 ? t`1 stop` : t`${brief.places.length} stops`);
  if (brief.durationMin) parts.push(t`${brief.durationMin} min`);
  if (brief.languages.length) parts.push(brief.languages.map((l) => (l === "ja" ? t`Japanese` : t`English`)).join(" · "));
  if (brief.tone) parts.push(brief.tone);
  return parts;
}

export function AssistantChat({ variant }: { variant: "hero" | "panel" }) {
  const { messages, brief, attachments, phase, progress, ready, send, build, stop, reset } = useAssistant();
  const { settings } = useWorkspace();
  const { setShowAppSettings } = useUI();
  const [text, setText] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const listRef = useRef<HTMLDivElement>(null);
  const busy = phase !== "idle";

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
  const summary = briefSummary(brief);
  const examples = [
    t`A calm 5 minute video of the pilgrimage route in the PDF I attach, for visitors from abroad`,
    t`A day trip around Shirahama in Wakayama, Japanese narration, about 3 minutes`,
  ];

  return (
    <div className={`flex flex-col min-h-0 ${variant === "panel" ? "h-full" : ""}`}>
      {needsAi ? (
        <div className="rounded-xl border border-zinc-200 dark:border-white/10 px-4 py-3 text-[13px] text-zinc-600 dark:text-zinc-300">
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
            <div ref={listRef} className={`overflow-y-auto custom-scrollbar space-y-3 pr-1 ${variant === "panel" ? "flex-1 min-h-0" : "max-h-80 mb-3"}`}>
              {messages.map((m, i) =>
                m.role === "user" ? (
                  <div key={i} className="flex justify-end">
                    <div className="max-w-[85%] rounded-xl bg-zinc-100 dark:bg-white/8 px-3 py-2 text-[13px] leading-relaxed whitespace-pre-wrap text-zinc-900 dark:text-zinc-100">
                      {m.text}
                      {m.files && m.files.length > 0 && (
                        <div className="mt-1 text-[11px] text-zinc-500 dark:text-zinc-400 break-all">{m.files.join(" · ")}</div>
                      )}
                    </div>
                  </div>
                ) : (
                  <p key={i} className="text-[13px] leading-relaxed whitespace-pre-wrap text-zinc-700 dark:text-zinc-200">
                    {m.text}
                  </p>
                ),
              )}
              {phase === "thinking" && <p className="text-[12px] text-zinc-400">{t`Thinking…`}</p>}
            </div>
          )}

          {phase === "building" && (
            <div className="mb-3 rounded-xl border border-zinc-200 dark:border-white/10 px-3 py-2.5">
              <div className="flex items-center justify-between gap-3 text-[12px] text-zinc-600 dark:text-zinc-300">
                <span className="truncate">{progress?.label ?? t`Starting…`}</span>
                {progress && progress.total > 0 && <span className="tabular-nums text-zinc-400">{progress.done}/{progress.total}</span>}
              </div>
              <div className="mt-2 h-1 rounded-full bg-zinc-200 dark:bg-white/10 overflow-hidden">
                <div className="h-full bg-navi transition-all" style={{ width: `${progress && progress.total ? (progress.done / progress.total) * 100 : 5}%` }} />
              </div>
            </div>
          )}

          {messages.length === 0 && variant === "panel" && (
            <p className="flex-1 min-h-0 flex items-center justify-center px-6 text-center text-[12px] leading-relaxed text-zinc-400">
              <Trans>Describe a trip and I will set up the stops and scripts for you. Attach an itinerary if you have one.</Trans>
            </p>
          )}

          {ready && phase === "idle" && (
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-navi/30 bg-navi/5 px-3 py-2">
              <div className="min-w-0 text-[12px] text-zinc-600 dark:text-zinc-300">
                <span className="font-medium text-zinc-900 dark:text-zinc-100">{brief.name || (attachments.gpx ? baseName(attachments.gpx) : t`Your trip`)}</span>
                {summary.length > 0 && <span className="text-zinc-500 dark:text-zinc-400"> · {summary.join(" · ")}</span>}
              </div>
              <button type="button" className={primaryButton} onClick={() => void build()}>
                <Trans>Create project</Trans>
              </button>
            </div>
          )}

          {picked.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1.5">
              {picked.map((p) => (
                <span key={p} className="inline-flex items-center gap-1 h-6 pl-2 pr-1 rounded-md bg-zinc-100 dark:bg-white/8 text-[11px] text-zinc-600 dark:text-zinc-300">
                  {baseName(p)}
                  <button type="button" aria-label={t`Remove`} onClick={() => setPicked((x) => x.filter((y) => y !== p))} className="w-4 h-4 rounded hover:bg-zinc-200 dark:hover:bg-white/10 flex items-center justify-center">
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}
            </div>
          )}

          <div className="flex items-end gap-1.5 rounded-xl border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-950/40 p-1.5 focus-within:border-navi focus-within:ring-2 focus-within:ring-navi/20 transition">
            <button type="button" onClick={attach} disabled={busy} aria-label={t`Attach files`} title={t`Attach an itinerary (PDF, Word, text), a GPX track or photos. Paste a web link into the message.`} className="w-8 h-8 shrink-0 rounded-lg flex items-center justify-center text-zinc-500 hover:bg-zinc-100 dark:hover:bg-white/10 disabled:opacity-40 transition-colors">
              <Paperclip className="w-4 h-4" />
            </button>
            <textarea
              value={text}
              rows={variant === "hero" ? 2 : 1}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  submit();
                }
              }}
              placeholder={variant === "hero" ? t`Describe the video you want, or attach an itinerary…` : t`Ask or add details…`}
              className="flex-1 min-w-0 max-h-32 resize-none bg-transparent px-1 py-1.5 text-[13px] text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 outline-none"
            />
            {busy ? (
              <button type="button" onClick={stop} className={`${secondaryButton} shrink-0`}>
                <Trans>Stop</Trans>
              </button>
            ) : (
              <button type="button" onClick={submit} disabled={!text.trim() && picked.length === 0} aria-label={t`Send`} className="w-8 h-8 shrink-0 rounded-lg flex items-center justify-center bg-navi text-white hover:brightness-110 disabled:opacity-40 disabled:pointer-events-none transition">
                <ArrowUp className="w-4 h-4" />
              </button>
            )}
          </div>

          {messages.length === 0 && variant === "hero" && (
            <div className="mt-3 flex flex-wrap gap-2">
              {examples.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => setText(example)}
                  className="text-left px-3 py-1.5 rounded-lg border border-zinc-200 dark:border-white/10 text-[12px] text-zinc-500 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-white/5 transition-colors"
                >
                  {example}
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
