import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { CheckCircle, Folder, Loader2 } from "../../components/ui/icons";
import { Dialog, dialogButton } from "../../components/ui/Dialog";
import { saveTimelineManifest } from "../../services/fileSystem";
import { layout, TimelineData } from "./model";
import { formatTime } from "./player";

interface ExportDialogProps {
  timeline: TimelineData;
  projectDir: string;
  projectName: string;
  onClose: () => void;
}

export function ExportDialog({ timeline, projectDir, projectName, onClose }: ExportDialogProps) {
  const [phase, setPhase] = useState<"ready" | "working" | "done" | "error">("ready");
  const [output, setOutput] = useState("");
  const [error, setError] = useState("");
  const [progress, setProgress] = useState(0);
  const startedAt = useRef(0);
  const [now, setNow] = useState(0);
  const { total } = layout(timeline);
  const narrated = timeline.segments.filter((s) => s.audio && !s.muted).length;

  const run = async () => {
    setPhase("working");
    setProgress(0);
    startedAt.current = Date.now();
    setNow(startedAt.current);
    const unlisten = await listen<number>("export-progress", (e) => setProgress((p) => Math.max(p, e.payload)));
    try {
      if (!(await saveTimelineManifest(projectDir, projectName, timeline))) throw new Error(t`Could not save the timeline`);
      setOutput(await invoke<string>("export_video", { projectDir }));
      setPhase("done");
    } catch (e: any) {
      setError(String(e?.message ?? e));
      setPhase("error");
    } finally {
      unlisten();
    }
  };

  useEffect(() => {
    if (phase !== "working") return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [phase]);

  // Time left from the pace so far; shown once there's enough progress to judge it.
  const elapsed = Math.max(0, (now - startedAt.current) / 1000);
  const remaining = progress >= 3 && elapsed >= 3 ? (elapsed * (100 - progress)) / progress : null;

  const reveal = () => invoke("open_in_explorer", { path: output || projectDir }).catch(() => undefined);

  const facts = [
    [t`Length`, formatTime(total, false)],
    [t`Clips`, String(timeline.segments.length)],
    [t`Narration`, narrated ? t`${narrated} clips` : t`None`],
    [t`Subtitles`, timeline.subtitles.length ? t`${timeline.subtitles.length} lines, burned in` : t`None`],
    [t`Music`, timeline.music ? timeline.music.label : t`None`],
  ];

  return (
    <Dialog
      width="w-[420px]"
      title={phase === "done" ? <Trans>Video exported</Trans> : <Trans>Export video</Trans>}
      subtitle={projectName}
      onClose={() => phase !== "working" && onClose()}
      footer={
        phase === "done" ? (
          <>
            <button className={dialogButton.secondary} onClick={reveal}>
              <Trans>Show video</Trans>
            </button>
            <button className={dialogButton.primary} onClick={onClose}>
              <Trans>Done</Trans>
            </button>
          </>
        ) : (
          <>
            <button className={dialogButton.secondary} disabled={phase === "working"} onClick={onClose}>
              <Trans>Cancel</Trans>
            </button>
            <button className={dialogButton.primary} disabled={phase === "working" || !timeline.segments.length} onClick={run}>
              {phase === "error" ? <Trans>Try again</Trans> : <Trans>Export</Trans>}
            </button>
          </>
        )
      }
    >
      {phase === "done" ? (
        <div className="flex flex-col items-center gap-2 py-4 text-center">
          <CheckCircle className="w-9 h-9 text-emerald-500" />
          <p className="text-[12px] text-zinc-500 break-all">{output}</p>
          <button type="button" onClick={reveal} className="flex items-center gap-1.5 text-[12px] text-navi hover:brightness-110">
            <Folder className="w-3.5 h-3.5" /> <Trans>Open folder</Trans>
          </button>
        </div>
      ) : (
        <>
          <dl className="rounded-xl border border-zinc-200 dark:border-white/10 divide-y divide-zinc-100 dark:divide-white/5">
            {facts.map(([k, v]) => (
              <div key={k} className="flex items-center justify-between px-3 h-9 text-[13px]">
                <dt className="text-zinc-500">{k}</dt>
                <dd className="text-zinc-800 dark:text-zinc-200 tabular-nums truncate ml-4">{v}</dd>
              </div>
            ))}
          </dl>
          {timeline.music?.credit && (
            <p className="mt-3 text-[11px] leading-snug text-zinc-400 select-text">
              <Trans>Music credit, to include where you publish the video:</Trans> {timeline.music.credit}
            </p>
          )}
          {phase === "working" && (
            <div className="mt-3">
              <div className="flex items-center justify-between text-[12px] text-zinc-500">
                <span className="flex items-center gap-2">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" /> <Trans>Stitching clips, narration and subtitles.</Trans>
                </span>
                <span className="tabular-nums">{Math.round(progress)}%</span>
              </div>
              <div
                className="mt-2 h-1.5 rounded-full bg-zinc-200 dark:bg-white/10 overflow-hidden"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(progress)}
              >
                <div className="h-full bg-navi transition-[width] duration-300" style={{ width: `${progress}%` }} />
              </div>
              <div className="mt-1.5 flex items-center justify-between text-[11px] text-zinc-400 tabular-nums">
                <span>{t`${formatTime(elapsed, false)} elapsed`}</span>
                <span>{remaining === null ? t`Estimating time left…` : t`About ${formatTime(remaining, false)} left`}</span>
              </div>
            </div>
          )}
          {phase === "error" && <p className="mt-3 max-h-32 overflow-y-auto text-[12px] text-red-500 whitespace-pre-wrap break-words">{error}</p>}
        </>
      )}
    </Dialog>
  );
}
