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
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { MapPin } from "../ui/icons";
import { Dialog, dialogButton } from "../ui/Dialog";

interface ProjectSettingsModalProps {
  project: any;
  onClose: () => void;
}

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

  const currentMarker = config.settings?.routeMarker || "";

  const handleSave = async () => {
    try {
      if (configPath) {
        await writeTextFile(configPath, JSON.stringify(config, null, 2));
        showToast(t`Project settings saved`, "success");
      }
      onClose();
    } catch (err) {
      showToast(t`Failed to save settings`, "error");
    }
  };

  const markerSrc = (marker: string) =>
    marker.match(/^[a-zA-Z]:\\/) || (marker.startsWith("/") && !marker.startsWith("/defaults/"))
      ? convertFileSrc(marker)
      : marker;

  const setMarker = (routeMarker: string) =>
    setConfig((prev: any) => ({
      ...prev,
      settings: { ...prev.settings, routeMarker },
    }));

  return (
    <Dialog
      title={<Trans>Project Settings</Trans>}
      subtitle={project.name}
      onClose={onClose}
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
      <div className="space-y-2.5">
        <div>
          <p className="text-[13px] font-medium text-zinc-900 dark:text-zinc-100">
            <Trans>Route marker</Trans>
          </p>
          <p className="mt-0.5 text-[12px] text-zinc-500 dark:text-zinc-400">
            <Trans>Default marker for all waypoints. Can be overridden per-stop.</Trans>
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
    </Dialog>
  );
}
