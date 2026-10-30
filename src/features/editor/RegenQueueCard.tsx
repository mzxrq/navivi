import { createPortal } from "react-dom";
import { invoke } from "@tauri-apps/api/core";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { ArrowDown, ArrowUp, Loader2, Trash2 } from "../../components/ui/icons";
import { moveQueued, removeQueued } from "../../hooks/useStopRegen";

type Job = { index: number | "intro" | "overview"; kind: string };

const iconButton =
  "w-6 h-6 rounded-md flex items-center justify-center text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-white/5 disabled:opacity-30 disabled:pointer-events-none transition-colors";

// The "make again" queue as a corner card, like the background render's.
export function RegenQueueCard({ busy, waiting, label }: { busy: Job; waiting: Job[]; label: (job: Job) => string }) {
  return createPortal(
    <div className="fixed bottom-10 right-4 z-99999 animate-in slide-in-from-bottom-5 duration-300">
      <div className="w-[min(22rem,calc(100vw-2rem))] rounded-xl border border-zinc-200 dark:border-white/10 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl shadow-[0_10px_40px_-10px_rgba(0,0,0,0.5)] p-3.5 flex flex-col gap-2.5">
        <div className="flex items-start gap-2.5">
          <div className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 bg-navi/10 text-navi">
            <Loader2 className="w-4 h-4 animate-spin" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-medium text-zinc-900 dark:text-zinc-100">
              <Trans>Making it again</Trans>
            </p>
            <p className="text-[11px] text-zinc-500 dark:text-zinc-400 truncate">{label(busy)}</p>
          </div>
        </div>

        {waiting.length > 0 && (
          <div className="flex flex-col gap-0.5 border-t border-zinc-100 dark:border-white/5 pt-2">
            <p className="text-[11px] text-zinc-400 mb-0.5">{waiting.length === 1 ? t`1 waiting` : t`${waiting.length} waiting`}</p>
            <div className="max-h-40 overflow-y-auto flex flex-col gap-0.5">
              {waiting.map((job, i) => (
                <div key={`${job.index}-${job.kind}`} className="flex items-center gap-1 h-7 pl-1 rounded-md hover:bg-zinc-50 dark:hover:bg-white/5">
                  <span className="text-[11px] tabular-nums text-zinc-400 w-4 shrink-0">{i + 1}</span>
                  <span className="flex-1 min-w-0 truncate text-[12px] text-zinc-700 dark:text-zinc-200">{label(job)}</span>
                  <button type="button" aria-label={t`Move up`} title={t`Move up`} disabled={i === 0} onClick={() => moveQueued(i, -1)} className={iconButton}>
                    <ArrowUp className="w-3.5 h-3.5" />
                  </button>
                  <button type="button" aria-label={t`Move down`} title={t`Move down`} disabled={i === waiting.length - 1} onClick={() => moveQueued(i, 1)} className={iconButton}>
                    <ArrowDown className="w-3.5 h-3.5" />
                  </button>
                  <button type="button" aria-label={t`Remove from queue`} title={t`Remove from queue`} onClick={() => removeQueued(i)} className={`${iconButton} hover:text-red-500!`}>
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="flex items-center gap-1.5 -mb-0.5">
          <button
            type="button"
            onClick={() => invoke("cancel_python_blueprint").catch(console.error)}
            className="h-7 px-2.5 rounded-md text-[12px] text-zinc-500 hover:text-red-500 hover:bg-zinc-100 dark:hover:bg-white/5 transition-colors"
          >
            <Trans>Stop this one</Trans>
          </button>
          {waiting.length > 0 && (
            <button
              type="button"
              onClick={() => waiting.forEach(() => removeQueued(0))}
              className="ml-auto h-7 px-2.5 rounded-md text-[12px] text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-white/5 transition-colors"
            >
              <Trans>Clear the queue</Trans>
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
