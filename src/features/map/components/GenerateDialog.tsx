import { ReactNode, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Dialog, dialogButton } from "../../../components/ui/Dialog";
import { Switch } from "../../../components/ui/Switch";
import { AlertTriangle, Check, Clock, Film, ImageIcon, MapPin, Mic, Route } from "../../../components/ui/icons";
import { useWorkspace } from "../../../hooks/useWorkspace";

interface Estimate {
  total_seconds: number;
  stages: Record<string, number>;
  measured_stages: number;
  active_stages: number;
  hardware: { gpu: string | null; cpu_cores: number };
}

export const formatDuration = (seconds: number) => {
  const m = Math.max(1, Math.round(seconds / 60));
  if (m < 60) return t`${m} min`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return rest ? t`${h} h ${rest} min` : t`${h} h`;
};

const hasText = (s?: string) => !!s && s.trim().length > 0;

export function GenerateDialog({ onClose, onConfirm }: { onClose: () => void; onConfirm: () => void }) {
  const { waypoints, settings, metadata, updateSettings, setIsDirty, saveProject } = useWorkspace();
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setEstimate(null);
    setFailed(false);
    const timer = setTimeout(async () => {
      try {
        await saveProject();
        const raw = await invoke<string>("run_python_blueprint", {
          action: "estimate",
          payload: `${metadata.directory_path}/job_config.json`,
        });
        const data = JSON.parse(raw.trim().split(String.fromCharCode(10)).pop() ?? "");
        if (!cancelled && data.success) setEstimate(data);
        else if (!cancelled) setFailed(true);
      } catch {
        if (!cancelled) setFailed(true);
      }
    }, 150);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [settings.skip_rich_media]);

  const skipRich = !!settings.skip_rich_media;
  const quick = !!settings.quick_export;
  const intro = metadata.enable_intro !== false;

  const active = waypoints.filter((w) => !w.skipAssetGeneration && !w.isStub);
  const legs = Math.max(0, waypoints.length - 1);
  const voiced = active.filter((w) => hasText(w.arrivingNarration) || hasText(w.attractionNarration));
  const silent = active.filter((w) => !hasText(w.arrivingNarration) && !hasText(w.attractionNarration));
  const withPhotos = active.filter((w) => (w.images?.length ?? 0) > 0);

  const setOption = (patch: { skip_rich_media?: boolean; quick_export?: boolean }) => {
    updateSettings(patch);
    setIsDirty(true);
  };

  const steps: { key: string[]; icon: ReactNode; label: string; detail: string; off?: boolean }[] = [
    {
      key: ["route"],
      icon: <Route className="w-3.5 h-3.5" />,
      label: t`Route videos`,
      detail: legs === 1 ? t`1 leg` : t`${legs} legs`,
    },
    {
      key: ["tts", "subtitles"],
      icon: <Mic className="w-3.5 h-3.5" />,
      label: t`AI voiceover`,
      detail: skipRich ? t`Skipped` : t`${voiced.length} of ${active.length} stops`,
      off: skipRich,
    },
    {
      key: ["attraction"],
      icon: <ImageIcon className="w-3.5 h-3.5" />,
      label: t`Photo clips`,
      detail: skipRich ? t`Skipped` : t`${withPhotos.length} stops with photos`,
      off: skipRich,
    },
    {
      key: ["intro"],
      icon: <Film className="w-3.5 h-3.5" />,
      label: t`Title card`,
      detail: intro ? t`Included` : t`Off`,
      off: !intro,
    },
  ];

  return (
    <Dialog
      width="w-[460px]"
      onClose={onClose}
      title={<Trans>Generate assets</Trans>}
      subtitle={metadata.project_name}
      footer={
        <>
          <button onClick={onClose} className={dialogButton.secondary}>
            <Trans>Cancel</Trans>
          </button>
          <button onClick={onConfirm} className={dialogButton.primary}>
            <Trans>Generate assets</Trans>
          </button>
        </>
      }
    >
      <div className="flex items-center gap-4 text-[12px] text-zinc-500 dark:text-zinc-400">
        <span className="flex items-center gap-1.5">
          <MapPin className="w-3.5 h-3.5" />
          {waypoints.length === 1 ? t`1 stop` : t`${waypoints.length} stops`}
        </span>
        <span className="flex items-center gap-1.5">
          <Clock className="w-3.5 h-3.5" />
          {estimate ? t`About ${formatDuration(estimate.total_seconds)}` : failed ? t`Time unavailable` : t`Estimating…`}
        </span>
      </div>

      <ul className="mt-3 rounded-xl border border-zinc-200 dark:border-white/10 divide-y divide-zinc-100 dark:divide-white/5">
        {steps.map((s) => (
          <li
            key={s.label}
            className={`flex items-center gap-2.5 px-3 h-9 text-[13px] ${
              s.off ? "text-zinc-400 dark:text-zinc-600" : "text-zinc-800 dark:text-zinc-200"
            }`}
          >
            <span className={s.off ? "" : "text-navi"}>{s.icon}</span>
            <span className="flex-1">{s.label}</span>
            <span className="text-[12px] text-zinc-500 dark:text-zinc-500">{s.detail}</span>
            {estimate && !s.off && (
              <span className="w-14 text-right text-[12px] tabular-nums text-zinc-700 dark:text-zinc-300">
                {formatDuration(s.key.reduce((a, k) => a + (estimate.stages[k] ?? 0), 0))}
              </span>
            )}
          </li>
        ))}
      </ul>

      {!skipRich && silent.length > 0 && (
        <div className="mt-3 flex items-start gap-2 rounded-lg bg-amber-500/10 px-3 py-2 text-[12px] leading-snug text-amber-700 dark:text-amber-400">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <span>
            {silent.length === 1
              ? t`1 stop has no narration and will be silent`
              : t`${silent.length} stops have no narration and will be silent`}
            {": "}
            {silent.slice(0, 3).map((w) => w.name || t`Untitled`).join(", ")}
            {silent.length > 3 ? "…" : ""}
          </span>
        </div>
      )}

      <div className="mt-4 space-y-1">
        <OptionRow
          label={t`Fast render`}
          hint={t`Route only. Skips voiceover and photo clips.`}
          checked={skipRich}
          onChange={(v) => setOption({ skip_rich_media: v })}
        />
        <OptionRow
          label={t`Export automatically`}
          hint={t`Stitch the clips and export when done, without pausing to review.`}
          checked={quick}
          onChange={(v) => setOption({ quick_export: v })}
        />
      </div>

      <p className="mt-3 flex items-start gap-1.5 text-[11px] leading-snug text-zinc-400 dark:text-zinc-500">
        <Check className="w-3 h-3 mt-0.5 shrink-0" />
        <span>
          {estimate && estimate.measured_stages > 0 ? (
            <Trans>Based on your earlier renders on this PC. Unchanged clips are reused, so it may finish sooner.</Trans>
          ) : (
            <Trans>Rough estimate from this PC's hardware. It becomes accurate after your first render.</Trans>
          )}
        </span>
      </p>
    </Dialog>
  );
}

function OptionRow({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div
      onClick={() => onChange(!checked)}
      className="flex items-center gap-3 -mx-2 px-2 py-2 rounded-lg cursor-pointer hover:bg-zinc-50 dark:hover:bg-white/5 transition-colors"
    >
      <span className="flex-1 min-w-0">
        <span className="block text-[13px] font-medium text-zinc-800 dark:text-zinc-200">{label}</span>
        <span className="block text-[11px] text-zinc-500 dark:text-zinc-400 leading-snug">{hint}</span>
      </span>
      <Switch checked={checked} onChange={onChange} label={label} />
    </div>
  );
}
