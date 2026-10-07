import { useEffect, useMemo, useRef, useState } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import { ChevronDown, Mic, PencilSparkles, Play, Undo2 } from "../../../components/ui/icons";
import { ScriptInput } from "../../../components/ui/ScriptInput";
import { useUI } from "../../../hooks/useUI";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { callSidecar, callSidecarShared } from "../../../services/sidecar";
import { estimateSeconds, lengthVerdict, type OverviewLength } from "../../../utils/overviewScript";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";

type Busy = "draft" | "plain" | "hear" | "frame" | null;
type Confirm = "replace" | "plain" | "revert" | null;

interface DraftReply extends OverviewLength {
  script: string;
  source_ids: string;
  model: string | null;
}

const buttonClass =
  "h-7 px-2 inline-flex items-center gap-1.5 rounded-md border border-zinc-200 dark:border-white/10 text-[11px] text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-white/5 disabled:opacity-50 disabled:cursor-not-allowed transition-colors";

export function OverviewNarration() {
  const { metadata, updateMetadata, saveProject } = useWorkspace();
  const { showToast, isRendering } = useUI();
  const [isOpen, setIsOpen] = useState(false);
  const [busy, setBusy] = useState<Busy>(null);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [limits, setLimits] = useState<OverviewLength | null>(null);
  const [voiceSeconds, setVoiceSeconds] = useState<number | null>(null);
  const [frame, setFrame] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const dir = metadata.directory_path;
  const configPath = `${dir}/job_config.json`;
  const text = metadata.overview_narration || "";
  const hasText = text.trim().length > 0;
  const isAuto = metadata.overview_narration_is_auto === true;
  const userWritten = hasText && !isAuto;
  const locked = busy !== null || isRendering;

  const seconds = useMemo(() => (limits ? estimateSeconds(text, limits.chars_per_second) : 0), [text, limits]);
  const verdict = limits ? lengthVerdict(seconds, limits) : "empty";

  // The voice speed and the aimed length come from the project's files; a hand edit is re-timed here without another call.
  useEffect(() => {
    if (!isOpen || !dir || limits) return;
    let live = true;
    callSidecarShared<OverviewLength>("overview_length", { config: configPath, text: "" }).then((reply) => {
      if (live && reply.success) setLimits(reply);
    });
    return () => {
      live = false;
    };
  }, [isOpen, dir, limits, configPath]);

  useEffect(() => () => audioRef.current?.pause(), []);

  const setText = (value: string) => {
    updateMetadata({
      overview_narration: value,
      overview_narration_is_auto: !value.trim(),
      overview_narration_source_ids: undefined,
    });
    setVoiceSeconds(null);
  };

  const failed = (error: string) => showToast(error, "error");

  const write = async (withAi: boolean) => {
    setConfirm(null);
    setBusy(withAi ? "draft" : "plain");
    try {
      await saveProject(undefined, undefined, undefined, false);
      const reply = await callSidecar<DraftReply>(configPath, withAi ? "overview-script" : "overview-script --no-llm");
      if (!reply.success) return reply.cancelled ? undefined : failed(reply.error);
      if (!reply.script.trim()) return showToast(t`Add some stops first; there is nothing to describe yet.`, "warning");
      updateMetadata({
        overview_narration: reply.script,
        overview_narration_is_auto: true,
        overview_narration_source_ids: reply.source_ids,
      });
      setLimits(reply);
      setVoiceSeconds(null);
    } catch (e) {
      failed(String(e));
    } finally {
      setBusy(null);
    }
  };

  const ask = (kind: "replace" | "plain", withAi: boolean) => (userWritten ? setConfirm(kind) : write(withAi));

  const hear = async () => {
    audioRef.current?.pause();
    setBusy("hear");
    try {
      await saveProject(undefined, undefined, undefined, false);
      const reply = await callSidecar<{ clip: { audio_path: string; duration_seconds: number } | null }>(configPath, "overview-tts");
      if (!reply.success) return reply.cancelled ? undefined : failed(reply.error);
      if (!reply.clip) return showToast(t`There is no overview narration to read yet.`, "warning");
      setVoiceSeconds(Math.round(reply.clip.duration_seconds * 10) / 10);
      const audio = new Audio(`${convertFileSrc(reply.clip.audio_path)}?t=${Date.now()}`);
      audioRef.current = audio;
      await audio.play().catch((e) => failed(String(e)));
    } catch (e) {
      failed(String(e));
    } finally {
      setBusy(null);
    }
  };

  const previewFraming = async () => {
    setBusy("frame");
    try {
      await saveProject(undefined, undefined, undefined, false);
      const reply = await callSidecar<{ map_path: string }>(configPath, "map");
      if (!reply.success) return reply.cancelled ? undefined : failed(reply.error);
      setFrame(`${convertFileSrc(reply.map_path)}?t=${Date.now()}`);
    } catch (e) {
      failed(String(e));
    } finally {
      setBusy(null);
    }
  };

  const summary = !hasText
    ? t`Written automatically when you make the video`
    : isAuto
      ? t`Written automatically`
      : t`Your own script`;

  const readout = (() => {
    if (!hasText) return null;
    if (!limits) return voiceSeconds !== null ? t`Voice: ${voiceSeconds} s` : null;
    const range = `${limits.min_seconds}-${limits.max_seconds}`;
    const base = t`About ${seconds} s spoken (aim ${limits.target_seconds} s, allowed ${range} s)`;
    const tail = verdict === "long" ? t`Too long` : verdict === "short" ? t`Too short` : t`In range`;
    return `${base} · ${tail}`;
  })();

  return (
    <section className="rounded-lg border border-zinc-200 dark:border-white/8 bg-white dark:bg-white/2">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        className="w-full flex items-center gap-2.5 pl-2 pr-2.5 py-2 text-left rounded-lg hover:bg-zinc-50 dark:hover:bg-white/4 transition-colors"
      >
        <span className="w-7 h-7 rounded-md flex items-center justify-center shrink-0 bg-navi/10 text-navi">
          <Mic className="w-3.5 h-3.5" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[13px] font-medium text-zinc-900 dark:text-zinc-100">
            <Trans>Overview narration</Trans>
          </span>
          <span className="block text-[11px] truncate text-zinc-500" title={summary}>
            {summary}
          </span>
        </span>
        <ChevronDown className={`w-3.5 h-3.5 text-zinc-400 shrink-0 transition-transform ${isOpen ? "rotate-180" : ""}`} />
      </button>

      {isOpen && (
        <div className="px-3 pb-3 pt-2 space-y-2.5 border-t border-zinc-100 dark:border-white/5">
          <p className="text-[11px] text-zinc-500 leading-relaxed">
            <Trans>
              The voice-over of the whole-route map shot at the start. Leave it blank and it is written for you when you make the video;
              once you edit it, it is never replaced.
            </Trans>
          </p>

          <ScriptInput
            value={text}
            onChange={setText}
            onGenerate={() => undefined}
            isGenerating={false}
            showLabel={false}
            cues={["start", "n", "go", "end"]}
          />

          {readout && (
            <p
              className={`text-[11px] tabular-nums ${
                verdict === "ok" || !limits ? "text-zinc-500" : "text-amber-600 dark:text-amber-400"
              }`}
              role="status"
            >
              {readout}
              {voiceSeconds !== null && limits ? ` · ${t`Voice: ${voiceSeconds} s`}` : ""}
            </p>
          )}

          {!dir && (
            <p className="text-[11px] text-zinc-400">
              <Trans>Save the project first to write or hear the narration.</Trans>
            </p>
          )}

          <div className="flex flex-wrap gap-1.5">
            <button type="button" className={buttonClass} disabled={locked || !dir} onClick={() => ask("replace", true)}>
              <PencilSparkles className="w-3 h-3" />
              {busy === "draft" ? t`Writing...` : t`Auto-write`}
            </button>
            <button
              type="button"
              className={buttonClass}
              disabled={locked || !dir}
              onClick={() => ask("plain", false)}
              title={t`Built from the route facts alone, with no AI model`}
            >
              {busy === "plain" ? t`Writing...` : t`Write without AI`}
            </button>
            <button type="button" className={buttonClass} disabled={locked || !dir || !hasText} onClick={hear}>
              <Play className="w-3 h-3" />
              {busy === "hear" ? t`Reading...` : t`Hear it`}
            </button>
            <button
              type="button"
              className={buttonClass}
              disabled={locked || !dir}
              onClick={previewFraming}
              title={t`Fetch the overview map image to check how the route is framed`}
            >
              {busy === "frame" ? t`Fetching...` : t`Preview framing`}
            </button>
            {userWritten && (
              <button type="button" className={buttonClass} disabled={locked} onClick={() => setConfirm("revert")}>
                <Undo2 className="w-3 h-3" />
                <Trans>Use automatic</Trans>
              </button>
            )}
          </div>

          {confirm && (
            <div className="rounded-md bg-amber-500/10 px-2.5 py-2 space-y-1.5" role="alert">
              <p className="text-[11px] text-amber-700 dark:text-amber-300">
                {confirm === "revert" ? (
                  <Trans>Throw away your script? The video will write its own when you make it.</Trans>
                ) : (
                  <Trans>This replaces the script you wrote.</Trans>
                )}
              </p>
              <div className="flex gap-1.5">
                <button
                  type="button"
                  className={buttonClass}
                  onClick={() => (confirm === "revert" ? (setText(""), setConfirm(null)) : write(confirm === "replace"))}
                >
                  {confirm === "revert" ? t`Use automatic` : t`Replace`}
                </button>
                <button type="button" className={buttonClass} onClick={() => setConfirm(null)}>
                  <Trans>Cancel</Trans>
                </button>
              </div>
            </div>
          )}

          {frame && <img src={frame} alt={t`Overview map framing`} className="w-full max-h-48 object-contain rounded-md bg-zinc-100 dark:bg-zinc-900" />}
        </div>
      )}
    </section>
  );
}
