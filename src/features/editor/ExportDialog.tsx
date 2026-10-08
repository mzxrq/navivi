import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { CheckCircle, Folder, Loader2 } from "../../components/ui/icons";
import { Dialog, dialogButton } from "../../components/ui/Dialog";
import { Segmented } from "../../components/ui/Segmented";
import { Switch } from "../../components/ui/Switch";
import { useWorkspace } from "../../hooks/useWorkspace";
import { saveTimelineManifest } from "../../services/fileSystem";
import { collectCredits } from "../../utils/photoCredits";
import { exportOptionsFrom, layout, TimelineData } from "./model";
import { formatTime } from "./player";

interface ExportDialogProps {
  timeline: TimelineData;
  projectDir: string;
  projectName: string;
  onClose: () => void;
}

export function ExportDialog({ timeline, projectDir, projectName, onClose }: ExportDialogProps) {
  const { settings, waypoints, updateSettings } = useWorkspace();
  const photoCredits = collectCredits(waypoints);
  const [phase, setPhase] = useState<"ready" | "working" | "done" | "error">("ready");
  const [output, setOutput] = useState("");
  const [error, setError] = useState("");
  const [progress, setProgress] = useState(0);
  const startedAt = useRef(0);
  const stopped = useRef(false);
  const [now, setNow] = useState(0);
  const { total } = layout(timeline);
  const resolution = settings.default_export_resolution ?? "1080p";
  const options = exportOptionsFrom(settings);
  const burn = settings.export_burn_subtitles ?? true;
  const fpsChoices = [...new Set([24, 30, 60, options.fps ?? 30])].sort((a, b) => a - b);
  const narrated = timeline.segments.filter((s) => s.audio && !s.muted).length;

  const run = async () => {
    setPhase("working");
    setProgress(0);
    startedAt.current = Date.now();
    setNow(startedAt.current);
    stopped.current = false;
    let unlisten: (() => void) | undefined;
    try {
      // The progress bar is a nicety: if registering for it fails the export still runs, without one (and the dialog is not stuck).
      unlisten = await listen<number>("export-progress", (e) => setProgress((p) => Math.max(p, e.payload))).catch(() => undefined);
      if (!(await saveTimelineManifest(projectDir, projectName, timeline, settings.caption_style ?? {}, options))) throw new Error(t`Could not save the timeline`);
      setOutput(await invoke<string>("export_video", { projectDir }));
      setPhase("done");
    } catch (e: any) {
      if (stopped.current) {
        setPhase("ready");
      } else {
        setError(String(e?.message ?? e));
        setPhase("error");
      }
    } finally {
      unlisten?.();
    }
  };

  // Ends the export's Python process (and ffmpeg, Chromium with it); the call then comes back as cancelled.
  const stop = () => {
    stopped.current = true;
    invoke("cancel_export").catch(() => undefined);
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
    [t`Subtitles`, timeline.subtitles.length ? burn ? t`${timeline.subtitles.length} lines, burned in` : t`${timeline.subtitles.length} lines, not burned in` : t`None`],
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
            <button className={dialogButton.secondary} onClick={phase === "working" ? stop : onClose}>
              {phase === "working" ? <Trans>Stop export</Trans> : <Trans>Cancel</Trans>}
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
          {phase !== "working" && (
          <div className="mt-3 space-y-2.5">
            <OptionRow label={t`Size`}>
              <Segmented
                compact
                className="w-52"
                value={resolution}
                onChange={(v) => updateSettings({ default_export_resolution: v })}
                options={[
                  { id: "720p", label: "720p" },
                  { id: "1080p", label: "1080p" },
                  { id: "1440p", label: "1440p" },
                  { id: "4k", label: "4K" },
                ]}
              />
            </OptionRow>
            {(resolution === "1440p" || resolution === "4k") && (
              <p className="text-[11px] leading-snug text-zinc-400">
                <Trans>The clips are drawn at 1080p, so a larger size enlarges them: the file is bigger, not sharper.</Trans>
              </p>
            )}
            <OptionRow label={t`Frame rate`}>
              <Segmented
                compact
                className="w-40"
                value={String(options.fps ?? 30)}
                onChange={(v) => updateSettings({ export_fps: Number(v) })}
                options={fpsChoices.map((n) => ({ id: String(n), label: String(n) }))}
              />
            </OptionRow>
            <OptionRow label={t`Burn subtitles into the video`}>
              <Switch checked={burn} onChange={(v) => updateSettings({ export_burn_subtitles: v })} label={t`Burn subtitles into the video`} />
            </OptionRow>
            <OptionRow label={t`Also save subtitles as .srt`}>
              <Switch
                checked={!!settings.export_save_srt}
                onChange={(v) => updateSettings({ export_save_srt: v })}
                label={t`Also save subtitles as .srt`}
              />
            </OptionRow>
          </div>
          )}
          {timeline.music?.credit && (
            <p className="mt-3 text-[11px] leading-snug text-zinc-400 select-text">
              <Trans>Music credit, to include where you publish the video:</Trans> {timeline.music.credit}
            </p>
          )}
          {photoCredits.length > 0 && (
            <div className="mt-3 text-[11px] leading-snug text-zinc-400 select-text">
              <p>
                <Trans>Photo credits (Wikimedia Commons), to include where you publish the video:</Trans>
              </p>
              <ul className="mt-1 space-y-0.5 max-h-24 overflow-y-auto custom-scrollbar">
                {photoCredits.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>
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

function OptionRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 text-[13px]">
      <span className="text-zinc-700 dark:text-zinc-300">{label}</span>
      {children}
    </div>
  );
}
