import { useState, useEffect } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { convertFileSrc } from "@tauri-apps/api/core";
import {
  readTextFile,
  writeTextFile,
  readDir,
  exists,
} from "@tauri-apps/plugin-fs";
import { join, dirname } from "@tauri-apps/api/path";
import { useUI } from "../../hooks/useUI";
import { useWorkspace } from "../../hooks/useWorkspace";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { MapPin } from "../ui/icons";
import { Dialog, dialogButton, dialogInput } from "../ui/Dialog";
import { StepButtons } from "../ui/StepButtons";
import { Select } from "../ui/Select";
import { Switch } from "../ui/Switch";
import { editorStyleForVideo, editorStyleLabel, resolveVideoStyle, videoMapStyles } from "../../config/constants";
import { db } from "../../services/db";
import { VideoLookSettings } from "../ui/VideoLookSettings";
import { applyOption, lookPatch } from "../../utils/videoLook";

const dialogWidth = "w-[clamp(36rem,52vw,48rem)]";

interface ProjectSettingsModalProps {
  project: any;
  onClose: () => void;
}

/** Project Manager: edits a project that is not open, straight in its job_config.json and the database. */
export function ProjectSettingsModal({
  project,
  onClose,
}: ProjectSettingsModalProps) {
  const { showToast } = useUI();
  const [config, setConfig] = useState<any>(null);
  const [configPath, setConfigPath] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    async function loadConfig() {
      try {
        let cp = project.path;
        let isFolder = false;
        try {
          await readDir(project.path);
          isFolder = true;
          cp = await join(project.path, "job_config.json");
        } catch {
          if (project.path.endsWith(".nvv")) {
            // Check for uncompressed legacy fallback
            const dir = await dirname(project.path);
            const candidate = await join(dir, "job_config.json");
            try {
              if (await exists(candidate)) {
                cp = candidate;
                isFolder = true;
              }
            } catch {}
          }
        }

        if (!isFolder && project.path.endsWith(".nvv")) {
          showToast(
            t`Cannot edit settings directly in .nvv archive. Please open project first.`,
            "error",
          );
          onClose();
          return;
        }

        setConfigPath(cp);
        const data = await readTextFile(cp);
        setConfig(JSON.parse(data));
      } catch (err) {
        showToast(t`Could not read project config.`, "error");
        onClose();
      } finally {
        setIsLoading(false);
      }
    }
    loadConfig();
  }, [project.path]);

  if (isLoading) return null;
  if (!config) return null;

  const handleSave = async () => {
    try {
      if (configPath) {
        const videoStyle = resolveVideoStyle(config.settings ?? {});
        config.settings = applyOption(config.settings ?? {}, { follow_editor_map_style: videoStyle.follow, mapbox_style_id: videoStyle.id });
        await writeTextFile(configPath, JSON.stringify(config, null, 2));
        // The database is what the app reads when it opens the project, so the file alone would be overwritten.
        if (project.projectId) {
          const s = config.settings ?? {};
          await db.settings.patch(project.projectId, {
            routeMarker: s.routeMarker ?? null,
            enable_attraction_videos: s.enable_attraction_videos,
            use_narration_cues: s.use_narration_cues,
            attraction_fade_seconds: s.attraction_fade_seconds,
            ...lookPatch(s),
            mapbox_style_id: s.mapbox_style_id ?? null,
            follow_editor_map_style: s.follow_editor_map_style,
            mapbox_retina: s.mapbox_retina ?? null,
          });
        }
        showToast(t`Project settings saved`, "success");
      }
      onClose();
    } catch (err) {
      showToast(t`Failed to save settings`, "error");
    }
  };

  const setOption = (patch: Record<string, unknown>) =>
    setConfig((prev: any) => ({ ...prev, settings: applyOption(prev.settings ?? {}, patch) }));

  return (
    <Dialog
      title={<Trans>Project Settings</Trans>}
      subtitle={project.name}
      onClose={onClose}
      width={dialogWidth}
      footer={
        <>
          <button type="button" onClick={onClose} className={dialogButton.secondary}>
            <Trans>Cancel</Trans>
          </button>
          <button type="button" onClick={handleSave} className={dialogButton.primary}>
            <Trans>Save Settings</Trans>
          </button>
        </>
      }
    >
      <ProjectSettingsForm options={config.settings ?? {}} setOption={setOption} onLeave={onClose} />
    </Dialog>
  );
}

/** Editor: the open project's settings live in the workspace, so changes apply at once and save with the project (the Project tab of App Settings). */
export function OpenProjectSettings() {
  const { settings, updateSettings, setIsDirty } = useWorkspace();

  const setOption = (patch: Record<string, unknown>) => {
    updateSettings(patch as Parameters<typeof updateSettings>[0]);
    setIsDirty(true);
  };

  return <ProjectSettingsForm options={settings as Record<string, any>} setOption={setOption} inProject />;
}

function ProjectSettingsForm({
  options,
  setOption,
  onLeave,
  inProject,
}: {
  options: Record<string, any>;
  setOption: (patch: Record<string, unknown>) => void;
  onLeave?: () => void;
  inProject?: boolean;
}) {
  const { setShowAppSettings } = useUI();
  const currentMarker: string = options.routeMarker || "";

  const markerSrc = (marker: string) =>
    marker.match(/^[a-zA-Z]:\\/) || (marker.startsWith("/") && !marker.startsWith("/defaults/"))
      ? convertFileSrc(marker)
      : marker;

  const editorStyle = editorStyleForVideo();
  const editorLabel = editorStyleLabel();
  const styleLabels: Record<string, string> = {
    "mapbox/outdoors-v12": t`Outdoors`,
    "mapbox/streets-v12": t`Streets`,
    "mapbox/satellite-streets-v12": t`Satellite Streets`,
    "mapbox/dark-v11": t`Dark`,
    "mapbox/light-v11": t`Light`,
  };
  const savedStyle: string = options.mapbox_style_id ?? "";
  const followsEditor = resolveVideoStyle(options).follow;
  const styleOptions = [
    { value: "", label: t`Default` },
    ...videoMapStyles.map((s) => ({ value: s.id, label: styleLabels[s.id] ?? s.label })),
    ...(savedStyle && !videoMapStyles.some((s) => s.id === savedStyle) ? [{ value: savedStyle, label: savedStyle }] : []),
    { value: "editor", label: t`Same as the editor` },
  ];
  // Picking "Same as the editor" (or pressing the sync button) makes the video follow the editor's map again; any other
  // choice is a manual one and the video stops following.
  const chooseStyle = (value: string) => {
    if (value === "editor") setOption({ follow_editor_map_style: true, mapbox_style_id: editorStyle ?? undefined });
    else setOption({ follow_editor_map_style: false, mapbox_style_id: value || undefined });
  };

  const setMarker = (routeMarker: string) => setOption({ routeMarker });

  const openAppSettings = (tab: string) => {
    setShowAppSettings(true);
    setTimeout(() => window.dispatchEvent(new CustomEvent("open-app-settings-tab", { detail: tab })), 0);
    onLeave?.();
  };

  return (
    <div className="space-y-5">
      {!inProject && (
      <div className="space-y-2.5">
        <div>
          <p className="text-[13px] font-medium text-zinc-900 dark:text-zinc-100">
            <Trans>Route marker</Trans>
          </p>
          <p className="mt-0.5 text-[12px] text-zinc-500 dark:text-zinc-400">
            <Trans>Default marker for all waypoints. Can be overridden per-stop.</Trans>{" "}
            <Trans>Your own image is also drawn as the pin in the video; the built-in icons show on the map only.</Trans>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-10 h-10 rounded-lg border border-zinc-200 dark:border-white/10 bg-zinc-50 dark:bg-white/5 flex items-center justify-center shrink-0">
            {currentMarker ? (
              <img src={markerSrc(currentMarker)} className="w-6 h-6 object-contain" alt="" />
            ) : (
              <MapPin className="w-4.5 h-4.5 text-zinc-400" />
            )}
          </span>
          <button
            type="button"
            onClick={async () => {
              const selected = await open({
                multiple: false,
                filters: [
                  {
                    name: "Images",
                    extensions: ["svg", "png", "jpg", "jpeg"],
                  },
                ],
              });
              if (selected && typeof selected === "string") setMarker(selected);
            }}
            className="h-8 px-3 rounded-lg border border-zinc-200 dark:border-white/10 bg-white dark:bg-white/5 text-[12px] font-medium text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-white/10 transition-colors"
          >
            <Trans>Choose file…</Trans>
          </button>
          {currentMarker && (
            <button
              type="button"
              onClick={() => setMarker("")}
              className="h-8 px-2.5 rounded-lg text-[12px] font-medium text-zinc-500 hover:text-zinc-800 hover:bg-zinc-100 dark:hover:text-zinc-200 dark:hover:bg-white/5 transition-colors"
            >
              <Trans>Reset</Trans>
            </button>
          )}
        </div>
      </div>
      )}

      <div className={`space-y-3 ${inProject ? "" : "pt-4 border-t border-zinc-100 dark:border-white/5"}`}>
        <p className="text-[13px] font-medium text-zinc-900 dark:text-zinc-100">
          <Trans>Rendering</Trans>
        </p>
        <OptionRow
          title={t`Animate photos at stops`}
          description={t`Turn the photos of a stop into a moving clip. Off skips them, which renders faster.`}
        >
          <Switch
            checked={options.enable_attraction_videos ?? true}
            onChange={(v) => setOption({ enable_attraction_videos: v })}
            label={t`Animate photos at stops`}
          />
        </OptionRow>
        <OptionRow
          title={t`Follow timing cues in scripts`}
          description={t`Timing cues written in a narration decide when the walker reaches the stop.`}
        >
          <Switch
            checked={options.use_narration_cues ?? true}
            onChange={(v) => setOption({ use_narration_cues: v })}
            label={t`Follow timing cues in scripts`}
          />
        </OptionRow>
        <OptionRow
          title={t`Fade into the stop's clip`}
          description={t`Seconds a leg dissolves into the clip that follows it. 0 is a hard cut.`}
        >
          <div className="relative w-20">
            <input
              type="number"
              min={0}
              max={3}
              step={0.1}
              value={options.attraction_fade_seconds ?? 0.8}
              onChange={(e) => setOption({ attraction_fade_seconds: Math.min(3, Math.max(0, Number(e.target.value) || 0)) })}
              className={`${dialogInput} w-full pr-6 text-right tabular-nums`}
            />
            <StepButtons
              onStep={(dir) =>
                setOption({ attraction_fade_seconds: +Math.min(3, Math.max(0, (options.attraction_fade_seconds ?? 0.8) + dir * 0.1)).toFixed(1) })
              }
            />
          </div>
        </OptionRow>
      </div>

      <div className="space-y-3 pt-4 border-t border-zinc-100 dark:border-white/5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-[13px] font-medium text-zinc-900 dark:text-zinc-100">
              <Trans>Look of the video</Trans>
            </p>
            <p className="mt-0.5 text-[12px] text-zinc-500 dark:text-zinc-400">
              <Trans>Anything you leave alone renders the way it always has.</Trans>
            </p>
          </div>
          <button
            type="button"
            onClick={() => setOption(Object.fromEntries(Object.keys(lookPatch({})).map((k) => [k, undefined])))}
            className="shrink-0 h-8 px-3 rounded-lg text-[12px] font-medium text-zinc-500 hover:text-zinc-800 hover:bg-zinc-100 dark:hover:text-zinc-200 dark:hover:bg-white/5 transition-colors"
          >
            <Trans>Reset the look</Trans>
          </button>
        </div>
        <VideoLookSettings options={options} onChange={setOption} />
      </div>
      <div className="space-y-3 pt-4 border-t border-zinc-100 dark:border-white/5">
        <p className="text-[13px] font-medium text-zinc-900 dark:text-zinc-100">
          <Trans>Map style in the video</Trans>
        </p>
        <OptionRow
          title={t`Map style`}
          description={
            !editorStyle
              ? t`The editor shows ${editorLabel}, which is not a Mapbox style, so the video cannot use it.`
              : followsEditor
                ? t`The video's map follows the map in the editor (${editorLabel}) until you pick a style here.`
                : t`What the video's map looks like. Default keeps the look the video always had.`
          }
        >
          <Select
            className="w-44"
            label={t`Map style`}
            value={followsEditor ? "editor" : savedStyle}
            onChange={chooseStyle}
            options={styleOptions}
          />
        </OptionRow>
        {editorStyle && !followsEditor && (
          <div className="flex items-center justify-between gap-4">
            <p className="text-[12px] text-zinc-500 dark:text-zinc-400">
              <Trans>The editor's map is {editorLabel}.</Trans>
            </p>
            <button
              type="button"
              onClick={() => chooseStyle("editor")}
              className="shrink-0 h-8 px-3 rounded-lg border border-zinc-200 dark:border-white/10 bg-white dark:bg-white/5 text-[12px] font-medium text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-white/10 transition-colors"
            >
              <Trans>Sync with the editor's map</Trans>
            </button>
          </div>
        )}
        <OptionRow
          title={t`Sharper map tiles`}
          description={t`Larger map tiles for a crisper picture. They take longer to download.`}
        >
          <Switch
            checked={options.mapbox_retina ?? true}
            onChange={(v) => setOption({ mapbox_retina: v ? undefined : false })}
            label={t`Sharper map tiles`}
          />
        </OptionRow>
      </div>

      {!inProject && (
        <div className="pt-4 border-t border-zinc-100 dark:border-white/5">
          <p className="text-[13px] font-medium text-zinc-900 dark:text-zinc-100">
            <Trans>Pronunciation dictionary</Trans>
          </p>
          <p className="mt-0.5 mb-2 text-[12px] text-zinc-500 dark:text-zinc-400">
            <Trans>Words every project shares live in App Settings, which you can open from here without opening a project.</Trans>
          </p>
          <button
            type="button"
            onClick={() => openAppSettings("tts_dictionary")}
            className="h-8 px-3 rounded-lg border border-zinc-200 dark:border-white/10 bg-white dark:bg-white/5 text-[12px] font-medium text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-white/10 transition-colors"
          >
            <Trans>Open dictionary…</Trans>
          </button>
        </div>
      )}
    </div>
  );
}

function OptionRow({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0">
        <p className="text-[13px] text-zinc-900 dark:text-zinc-100">{title}</p>
        <p className="mt-0.5 text-[12px] leading-snug text-zinc-500 dark:text-zinc-400">{description}</p>
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}
