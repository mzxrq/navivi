import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  Loader2,
  SquareTerminal,
  XCircle,
} from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  PipelineLine,
  PipelineLogState,
  PipelineStage,
  pipelineLogToText,
} from "../../utils/pipelineLog";

type LogView = "simple" | "details";
const VIEW_STORAGE_KEY = "navivi_pipeline_log_view";

function readStoredView(): LogView {
  try {
    return localStorage.getItem(VIEW_STORAGE_KEY) === "details" ? "details" : "simple";
  } catch {
    return "simple";
  }
}

const formatDuration = (seconds: number) => {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

// The stages run_full_pipeline announces (videopipeline/pipeline.py,
// PIPELINE_STAGES), in order. Matched against the tracker's stage title so the
// simple view can show friendly names and list the stages still to come.
const STAGE_MATCHERS: RegExp[] = [
  /parsing gps/i,
  /tts narration/i,
  /^(generating|skipping) subtitles\b/i,
  /attraction videos/i,
  /rendering overview/i,
  /subtitle burn|burning subtitles/i,
  /intro\/outro/i,
];

function useStageLabels(): string[] {
  return [
    t`GPS track`,
    t`Narration audio`,
    t`Subtitles`,
    t`Attraction videos`,
    t`Route video`,
    t`Subtitle burn-in`,
    t`Intro & outro`,
  ];
}

const stageLabelIndex = (title: string) => STAGE_MATCHERS.findIndex((re) => re.test(title));

interface PipelineLogPanelProps {
  log: PipelineLogState;
  /** True while the pipeline is still producing output. */
  isRunning: boolean;
  isOpen: boolean;
  onToggleOpen: () => void;
}

export function PipelineLogPanel({ log, isRunning, isOpen, onToggleOpen }: PipelineLogPanelProps) {
  const [view, setView] = useState<LogView>(readStoredView);
  const [copied, setCopied] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Follow new output only while the reader is at the bottom, so scrolling up
  // to read something isn't undone by the next line.
  const stickToBottom = useRef(true);

  useEffect(() => {
    try {
      localStorage.setItem(VIEW_STORAGE_KEY, view);
    } catch {
      // Storage unavailable: the choice just isn't remembered.
    }
    stickToBottom.current = true;
  }, [view]);

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [log, view, isOpen]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (el) stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(pipelineLogToText(log));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch (err) {
      console.warn("Copying the pipeline log failed:", err);
    }
  };

  return (
    <div className="w-full shrink-0 lg:w-80 xl:w-104 min-h-0 bg-zinc-950 rounded-2xl border border-zinc-800 shadow-2xl flex flex-col overflow-hidden pointer-events-auto animate-in slide-in-from-bottom-4 lg:slide-in-from-left-4 duration-300">
      <div className="flex items-center gap-2 pl-4 pr-2 py-2 border-b border-zinc-800/80 text-zinc-400 shrink-0 select-none">
        <SquareTerminal className="w-3.5 h-3.5 shrink-0" />
        <span className="text-[11px] font-semibold tracking-wide uppercase truncate">
          <Trans>Pipeline Log</Trans>
        </span>
        {isRunning && (
          <span className="w-1.5 h-1.5 rounded-full bg-navi-500 animate-pulse shrink-0" />
        )}

        <div
          role="tablist"
          aria-label={t`Log view`}
          className="ml-auto flex items-center rounded-md bg-zinc-900 p-0.5 shrink-0"
        >
          {(
            [
              ["simple", t`Simple`],
              ["details", t`Details`],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={view === id}
              onClick={() => {
                setView(id);
                if (!isOpen) onToggleOpen();
              }}
              className={`px-2 py-0.5 rounded text-[10px] font-semibold transition-colors ${
                view === id ? "bg-zinc-700 text-zinc-100" : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {view === "details" && (
          <button
            type="button"
            onClick={handleCopy}
            title={t`Copy log`}
            aria-label={t`Copy log`}
            className="p-1 rounded text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800 transition-colors shrink-0"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
          </button>
        )}

        <button
          type="button"
          onClick={onToggleOpen}
          aria-expanded={isOpen}
          aria-label={isOpen ? t`Hide log` : t`Show log`}
          className="lg:hidden p-1 rounded text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800 transition-colors shrink-0"
        >
          {isOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronUp className="w-3.5 h-3.5" />}
        </button>
      </div>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className={`${isOpen ? "block" : "hidden"} lg:block h-36 short:h-24 lg:h-auto lg:short:h-auto lg:flex-1 min-h-0 overflow-y-auto custom-scrollbar select-text`}
      >
        {view === "simple" ? (
          <SimpleView log={log} isRunning={isRunning} />
        ) : (
          <DetailsView lines={log.lines} />
        )}
      </div>
    </div>
  );
}

function SimpleView({ log, isRunning }: { log: PipelineLogState; isRunning: boolean }) {
  const labels = useStageLabels();
  const { stages, stageTotal } = log;
  // The app's own errors ("render failed", invoke failures) are only worth a
  // row when the pipeline didn't already explain what went wrong.
  const pipelineExplained = stages.some((s) => s.notes.some((n) => n.kind === "error"));
  const appErrors = pipelineExplained
    ? []
    : log.lines.filter((l) => l.fromApp && l.kind === "error");

  if (stages.length === 0) {
    return (
      <div className="flex items-center gap-2 px-4 py-3 text-xs text-zinc-500">
        {isRunning && <Loader2 className="w-3.5 h-3.5 animate-spin text-navi-400" />}
        {log.lines[log.lines.length - 1]?.text ?? <Trans>Waiting for pipeline...</Trans>}
      </div>
    );
  }

  const last = stages[stages.length - 1];
  // Only list upcoming stages by name when the run declares the known set.
  const upcoming =
    stageTotal === STAGE_MATCHERS.length
      ? labels.slice(last.index).map((label, i) => ({ index: last.index + 1 + i, label }))
      : [];
  const unnamedRemaining =
    upcoming.length === 0 && stageTotal > last.index ? stageTotal - last.index : 0;

  return (
    <ol className="px-2 py-2 space-y-0.5 text-xs">
      {stages.map((stage, i) => {
        const next = stages[i + 1];
        const isCurrent = !next && isRunning;
        const hasError = stage.notes.some((n) => n.kind === "error");
        return (
          <StageRow
            key={stage.index}
            stage={stage}
            label={labels[stageLabelIndex(stage.title)] ?? stage.title.replace(/\.{3}$/, "")}
            state={hasError ? "failed" : isCurrent ? "current" : "done"}
            duration={(next?.startedAt ?? stage.lastSeenAt) - stage.startedAt}
          />
        );
      })}
      {isRunning &&
        upcoming.map((u) => (
          <li key={u.index} className="flex items-center gap-2.5 px-2 py-1 text-zinc-600">
            <span className="w-4 h-4 rounded-full border border-zinc-800 shrink-0" />
            <span className="truncate">{u.label}</span>
          </li>
        ))}
      {isRunning && unnamedRemaining > 0 && (
        <li className="px-2 py-1 text-zinc-600">
          <Trans>{unnamedRemaining} more steps</Trans>
        </li>
      )}
      {appErrors.map((e) => (
        <li key={e.id} className="flex items-start gap-2 px-2 py-1 text-red-400">
          <XCircle className="w-3.5 h-3.5 mt-px shrink-0" />
          <span className="wrap-break-word min-w-0">{e.text}</span>
        </li>
      ))}
    </ol>
  );
}

function StageRow({
  stage,
  label,
  state,
  duration,
}: {
  stage: PipelineStage;
  label: string;
  state: "done" | "current" | "failed";
  duration: number;
}) {
  const skipped = /^skipping\b/i.test(stage.title);
  return (
    <li
      className={`rounded-lg px-2 py-1.5 ${state === "current" ? "bg-zinc-900/80" : ""}`}
    >
      <div className="flex items-center gap-2.5">
        {state === "failed" ? (
          <XCircle className="w-4 h-4 text-red-400 shrink-0" />
        ) : state === "current" ? (
          <Loader2 className="w-4 h-4 text-navi-400 animate-spin shrink-0" />
        ) : (
          <span className="w-4 h-4 rounded-full bg-navi-500/15 text-navi-400 flex items-center justify-center shrink-0">
            <Check className="w-2.5 h-2.5" strokeWidth={3} />
          </span>
        )}
        <span
          className={`truncate ${
            state === "current" ? "text-zinc-100 font-semibold" : skipped ? "text-zinc-500" : "text-zinc-300"
          }`}
          title={stage.title}
        >
          {label}
        </span>
        {skipped && (
          <span className="text-[10px] px-1.5 rounded bg-zinc-800 text-zinc-500 shrink-0">
            <Trans>Skipped</Trans>
          </span>
        )}
        {!skipped && duration > 0 && (
          <span className="ml-auto text-[10px] font-mono tabular-nums text-zinc-500 shrink-0">
            {formatDuration(duration)}
          </span>
        )}
      </div>
      {state === "current" && stage.detail && (
        <p className="mt-0.5 pl-6.5 text-[11px] text-zinc-400 truncate" title={stage.detail}>
          {stage.detail}
        </p>
      )}
      {stage.notes.map((note) => (
        <p
          key={note.id}
          className={`mt-1 pl-6.5 flex items-start gap-1.5 text-[11px] ${
            note.kind === "error" ? "text-red-400" : "text-amber-400/90"
          }`}
        >
          {note.kind === "error" ? (
            <XCircle className="w-3 h-3 mt-0.5 shrink-0" />
          ) : (
            <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />
          )}
          <span className="wrap-break-word min-w-0">{note.text}</span>
        </p>
      ))}
    </li>
  );
}

const KIND_CLASS: Record<PipelineLine["kind"], string> = {
  stage: "text-navi-400 font-semibold",
  status: "text-zinc-300",
  info: "text-zinc-400",
  warning: "text-amber-400",
  error: "text-red-400",
  system: "text-navi-300",
};

function DetailsView({ lines }: { lines: PipelineLine[] }) {
  if (lines.length === 0) {
    return (
      <p className="px-4 py-3 font-mono text-[11px] text-zinc-600">
        <Trans>Waiting for pipeline...</Trans>
      </p>
    );
  }
  return (
    <div className="px-2 py-2 space-y-px font-mono text-[11px] leading-relaxed">
      {lines.map((line) => (
        <div key={line.id} className="flex gap-2.5 px-2 py-0.5 rounded hover:bg-white/5">
          <span className="text-zinc-600 shrink-0 select-none">{line.time}</span>
          <div className="min-w-0 flex-1">
            <span className={`wrap-break-word whitespace-pre-wrap ${KIND_CLASS[line.kind]}`}>
              {line.raw}
            </span>
            {line.updates > 1 && (
              <span
                className="ml-1.5 text-[10px] text-zinc-600 select-none"
                title={t`Updated in place ${line.updates} times`}
              >
                ×{line.updates}
              </span>
            )}
            {line.tool && (
              <div className="text-[10px] text-zinc-500 truncate" title={line.tool}>
                <span className="select-none">↳ </span>
                {line.tool}
              </div>
            )}
            {line.details && (
              <details className="mt-0.5">
                <summary className="cursor-pointer text-[10px] text-zinc-500 hover:text-zinc-300 select-none">
                  <Trans>Traceback</Trans>
                </summary>
                <pre className="mt-1 p-2 rounded bg-black/40 text-[10px] text-red-300/80 whitespace-pre-wrap wrap-break-word">
                  {line.details}
                </pre>
              </details>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
