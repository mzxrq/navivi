import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { CheckCircle, Folder, Loader2 } from "../../components/ui/icons";
import { Dialog, dialogButton } from "../../components/ui/Dialog";
import { useWorkspace } from "../../hooks/useWorkspace";
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
  const { settings } = useWorkspace();
  const [phase, setPhase] = useState<"ready" | "working" | "done" | "error">("ready");
  const [output, setOutput] = useState("");
  const [error, setError] = useState("");
  const { total } = layout(timeline);
  const narrated = timeline.segments.filter((s) => s.audio && !s.muted).length;

  const run = async () => {
    setPhase("working");
    try {
      if (!(await saveTimelineManifest(projectDir, projectName, timeline, settings))) throw new Error(t`Could not save the timeline`);
      setOutput(await invoke<string>("export_video", { projectDir }));
      setPhase("done");
    } catch (e: any) {
      setError(String(e?.message ?? e));
      setPhase("error");
    }
  };

  const reveal = () => invoke("open_in_explorer", { path: output || projectDir }).catch(() => undefined);

  const facts = [
    [t`Length`, formatTime(total, false)],
    [t`Clips`, String(timeline.segments.length)],
    [t`Narration`, narrated ? t`${narrated} clips` : t`None`],
    [t`Subtitles`, timeline.subtitles.length ? (timeline.burnSubtitles ? t`${timeline.subtitles.length} lines, burned in` : t`${timeline.subtitles.length} lines, not shown`) : t`None`],
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
            <p className="mt-3 flex items-center gap-2 text-[12px] text-zinc-500">
              <Loader2 className="w-3.5 h-3.5 animate-spin" /> <Trans>Stitching clips, narration and subtitles. This can take a few minutes.</Trans>
            </p>
          )}
          {phase === "error" && <p className="mt-3 max-h-32 overflow-y-auto text-[12px] text-red-500 whitespace-pre-wrap break-words">{error}</p>}
        </>
      )}
    </Dialog>
  );
}
