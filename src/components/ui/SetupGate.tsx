import { useEffect, useRef, useState } from "react";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { db } from "../../services/db";
import { getRuntimeStatus, installRuntime, needsSetup, SETUP_REQUIRED_EVENT, type SetupStep } from "../../services/setup";
import { ComponentsChecklist } from "./ComponentsChecklist";
import { Dialog, dialogButton } from "./Dialog";
import { CheckCircle2, Loader2 } from "./icons";

type Phase = "idle" | "running" | "failed";

const CHECKLIST_DONE = "firstRunChecklistDone";

const MAX_LOG_LINES = 200;

// First run of an installed app: the media tools need their own Python, made here. Not shown when running from the repo.
export function SetupGate() {
  const [open, setOpen] = useState(false);
  const [checklist, setChecklist] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [step, setStep] = useState<SetupStep | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [showLog, setShowLog] = useState(false);
  const logEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let current = true;
    const check = () =>
      getRuntimeStatus()
        .then(async (status) => {
          if (!current) return;
          if (needsSetup(status)) return setOpen(true);
          // The media tools are there: offer the optional parts once, on the first run of an installed app.
          if (status.installed && !(await db.appSettings.get<boolean>(CHECKLIST_DONE))) setChecklist(true);
        })
        .catch(() => {});
    check();
    window.addEventListener(SETUP_REQUIRED_EVENT, check);
    return () => {
      current = false;
      window.removeEventListener(SETUP_REQUIRED_EVENT, check);
    };
  }, []);

  useEffect(() => {
    if (showLog) logEnd.current?.scrollIntoView({ block: "end" });
  }, [log, showLog]);

  const closeChecklist = () => {
    setChecklist(false);
    void db.appSettings.set(CHECKLIST_DONE, true).catch(() => {});
  };

  if (checklist && !open) {
    return (
      <Dialog
        width="w-[36rem]"
        title={t`What else do you want to set up?`}
        subtitle={t`You can do this later in Settings > Setup`}
        onClose={closeChecklist}
        footer={
          <button type="button" className={dialogButton.primary} onClick={closeChecklist}>
            <Trans>Done</Trans>
          </button>
        }
      >
        <ComponentsChecklist />
      </Dialog>
    );
  }

  if (!open) return null;

  const run = async () => {
    setPhase("running");
    setError("");
    setLog([]);
    setStep(null);
    try {
      await installRuntime(setStep, (line) => setLog((prev) => [...prev.slice(-(MAX_LOG_LINES - 1)), line]));
      setOpen(false);
      setPhase("idle");
      setChecklist(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("failed");
    }
  };

  const lastLine = log[log.length - 1] ?? "";

  return (
    <Dialog
      width="w-[30rem]"
      title={t`Set up Navivi`}
      subtitle={t`One-time setup`}
      onClose={() => phase !== "running" && setOpen(false)}
      footer={
        <>
          {phase !== "running" && (
            <button type="button" className={dialogButton.secondary} onClick={() => setOpen(false)}>
              <Trans>Not now</Trans>
            </button>
          )}
          <button type="button" className={dialogButton.primary} disabled={phase === "running"} onClick={run}>
            {phase === "running" ? <Trans>Installing…</Trans> : phase === "failed" ? <Trans>Try again</Trans> : <Trans>Install</Trans>}
          </button>
        </>
      }
    >
      <div className="space-y-3 pb-1">
        <p className="text-[13px] leading-relaxed text-zinc-600 dark:text-zinc-300">
          <Trans>
            Navivi needs its media tools before it can make videos: a Python environment, the video and map libraries, and the browser that
            draws the route. That is about 800 MB. It needs an internet connection and takes a few minutes. Voices and AI models are set up
            later from Settings.
          </Trans>
        </p>

        {phase === "running" && (
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 text-[13px] font-medium text-zinc-900 dark:text-zinc-100">
              <Loader2 className="w-3.5 h-3.5 animate-spin text-navi" />
              {step ? (
                <span>
                  {step.index}/{step.total} · {step.title}
                </span>
              ) : (
                <Trans>Starting…</Trans>
              )}
            </div>
            {step && (
              <div className="h-1 rounded-full overflow-hidden bg-zinc-200 dark:bg-white/10">
                <div className="h-full bg-navi transition-all duration-500" style={{ width: `${((step.index - 1) / step.total) * 100 + 5}%` }} />
              </div>
            )}
            {!showLog && lastLine && <p className="truncate text-[11px] text-zinc-400" title={lastLine}>{lastLine}</p>}
          </div>
        )}

        {phase === "failed" && (
          <div className="rounded-lg bg-red-500/10 px-3 py-2 text-[12px] leading-snug text-red-600 dark:text-red-400 break-words">{error}</div>
        )}

        {log.length > 0 && (
          <div>
            <button type="button" className="text-[12px] text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200" onClick={() => setShowLog(!showLog)}>
              {showLog ? t`Hide details` : t`Show details`}
            </button>
            {showLog && (
              <pre className="mt-1.5 max-h-48 overflow-auto rounded-lg bg-zinc-100 dark:bg-zinc-950/60 p-2 text-[11px] leading-snug text-zinc-600 dark:text-zinc-400 whitespace-pre-wrap break-all">
                {log.join("\n")}
                <div ref={logEnd} />
              </pre>
            )}
          </div>
        )}

        {phase === "idle" && (
          <p className="flex items-center gap-1.5 text-[11px] text-zinc-400">
            <CheckCircle2 className="w-3 h-3" /> <Trans>Nothing is installed outside Navivi's own folder.</Trans>
          </p>
        )}
      </div>
    </Dialog>
  );
}
