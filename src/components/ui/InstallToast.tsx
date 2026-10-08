import { useEffect, useRef, useState } from "react";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useInstalls } from "../../hooks/useInstalls";
import { dismissInstall, type InstallJob } from "../../services/installs";
import { AlertCircle, CheckCircle2, Loader2, X } from "./icons";
import { Dialog, dialogButton } from "./Dialog";

const DONE_VISIBLE_MS = 5000;

export function InstallProgressBar({ job }: { job: InstallJob }) {
  const percent = Math.round(job.fraction * 100);
  return (
    <div
      role="progressbar"
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
      className="h-1 rounded-full overflow-hidden bg-zinc-200 dark:bg-white/10"
    >
      <div className={`h-full transition-all duration-500 ${job.state === "failed" ? "bg-red-500" : "bg-navi"}`} style={{ width: `${Math.max(4, percent)}%` }} />
    </div>
  );
}

function InstallDetails({ job, onClose }: { job: InstallJob; onClose: () => void }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => end.current?.scrollIntoView({ block: "end" }), [job.log.length]);
  return (
    <Dialog
      width="w-[34rem]"
      title={job.label}
      subtitle={job.state === "running" ? job.step || t`Starting…` : job.state === "done" ? t`Finished` : t`Failed`}
      onClose={onClose}
      footer={
        <button type="button" className={dialogButton.primary} onClick={onClose}>
          <Trans>Close</Trans>
        </button>
      }
    >
      <div className="space-y-3 pb-1">
        <InstallProgressBar job={job} />
        {job.error && <p className="rounded-lg bg-red-500/10 px-3 py-2 text-[12px] leading-snug text-red-600 dark:text-red-400 break-words select-text whitespace-pre-wrap">{job.error}</p>}
        <pre className="max-h-64 overflow-auto rounded-lg bg-zinc-100 dark:bg-zinc-950/60 p-2 text-[11px] leading-snug text-zinc-600 dark:text-zinc-400 whitespace-pre-wrap break-all select-text">
          {job.log.length ? job.log.join("\n") : t`No output yet.`}
          <div ref={end} />
        </pre>
      </div>
    </Dialog>
  );
}

function InstallItem({ job }: { job: InstallJob }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (job.state !== "done" || open) return;
    const timer = window.setTimeout(() => dismissInstall(job.id), DONE_VISIBLE_MS);
    return () => window.clearTimeout(timer);
  }, [job.state, job.id, open]);

  const Icon = job.state === "done" ? CheckCircle2 : job.state === "failed" ? AlertCircle : Loader2;
  const color = job.state === "done" ? "text-emerald-500" : job.state === "failed" ? "text-red-500" : "text-navi animate-spin";
  const headline =
    job.state === "done" ? t`${job.label} is ready` : job.state === "failed" ? t`${job.label} failed` : t`Setting up ${job.label}`;

  return (
    <>
      <div className="flex items-start gap-2.5 w-80 max-w-[calc(100vw-1.5rem)] pl-3 pr-1.5 py-2.5 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 shadow-lg pointer-events-auto select-none">
        <Icon className={`w-4 h-4 mt-px shrink-0 ${color}`} />
        <button type="button" onClick={() => setOpen(true)} className="flex-1 min-w-0 space-y-1.5 text-left" title={t`Show details`}>
          <p className="text-[13px] leading-snug text-zinc-800 dark:text-zinc-200 truncate">{headline}</p>
          {job.state !== "done" && <InstallProgressBar job={job} />}
          {job.state === "failed" && <p className="text-[11px] text-red-500">{t`Click for details`}</p>}
        </button>
        {job.state !== "running" && (
          <button
            type="button"
            onClick={() => dismissInstall(job.id)}
            aria-label={t`Dismiss`}
            title={t`Dismiss`}
            className="flex items-center justify-center w-6 h-6 -my-0.5 rounded-md shrink-0 text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 dark:hover:text-zinc-200 dark:hover:bg-white/5 transition-colors"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
      {open && <InstallDetails job={job} onClose={() => setOpen(false)} />}
    </>
  );
}

// Background installs: a small box per install; click it for the steps, the output and any error.
export function InstallToast() {
  const jobs = useInstalls();
  if (jobs.length === 0) return null;
  return (
    <div className="fixed bottom-9 left-3 z-999 flex flex-col items-start gap-2 pointer-events-none">
      {jobs.map((job) => (
        <InstallItem key={job.id} job={job} />
      ))}
    </div>
  );
}
