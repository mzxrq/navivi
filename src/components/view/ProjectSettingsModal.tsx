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
import { Settings2, X, MapPin } from "../ui/icons";

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

  return (
    <div className="fixed inset-0 z-999999 bg-zinc-950/40 backdrop-blur-[2px] flex items-center justify-center p-4 animate-in fade-in duration-200">
      <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 rounded-2xl shadow-2xl w-full max-w-sm overflow-hidden animate-in zoom-in-95 duration-200">
        <div className="p-5 border-b border-zinc-100 dark:border-navidark-400">
          <h3 className="text-base font-bold text-zinc-900 dark:text-white flex items-center gap-2">
            <Settings2 className="w-4 h-4 text-navi-500" />
            <Trans>Project Settings</Trans>
          </h3>
          <p className="text-xs text-zinc-500 mt-1 truncate">{project.name}</p>
        </div>

        <div className="p-5 space-y-4">
          <div className="space-y-3">
            <label className="text-[11px] font-bold text-zinc-500 dark:text-navidark-125 uppercase tracking-widest flex items-center gap-1.5">
              <MapPin className="w-3.5 h-3.5" />{" "}
              <Trans>Global Route Marker</Trans>
            </label>
            <div className="flex items-center gap-3">
              {currentMarker ? (
                <div className="relative w-12 h-12 rounded-lg border border-zinc-200 dark:border-white/10 flex items-center justify-center bg-zinc-50 dark:bg-navidark-700/50 group">
                  <img
                    src={
                      currentMarker.startsWith("/") ||
                      currentMarker.match(/^[a-zA-Z]:\\/)
                        ? convertFileSrc(currentMarker)
                        : currentMarker
                    }
                    className="w-8 h-8 object-contain"
                    alt="Marker"
                  />
                  <button
                    onClick={() => {
                      setConfig((prev: any) => ({
                        ...prev,
                        settings: { ...prev.settings, routeMarker: "" },
                      }));
                    }}
                    className="absolute -top-2 -right-2 p-1 bg-red-500 text-white rounded-full opacity-0 group-hover:opacity-100 transition-opacity shadow-md"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ) : (
                <div className="w-12 h-12 rounded-lg border border-dashed border-zinc-300 dark:border-white/20 flex items-center justify-center bg-zinc-50 dark:bg-navidark-700/30">
                  <MapPin className="w-5 h-5 text-zinc-300 dark:text-zinc-600" />
                </div>
              )}
              <button
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
                  if (selected && typeof selected === "string") {
                    setConfig((prev: any) => ({
                      ...prev,
                      settings: { ...prev.settings, routeMarker: selected },
                    }));
                  }
                }}
                className="flex-1 py-2 text-xs font-semibold rounded-xl border border-zinc-200 dark:border-white/10 bg-white dark:bg-navidark-600 hover:bg-zinc-50 dark:hover:bg-white/5 transition-colors text-zinc-700 dark:text-zinc-300"
              >
                {currentMarker ? t`Change Marker` : t`Select Custom Marker`}
              </button>
            </div>
          </div>
        </div>

        <div className="p-4 bg-zinc-50 dark:bg-black/20 border-t border-zinc-100 dark:border-white/5 flex items-center justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-xs font-bold text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded-lg transition-colors"
          >
            <Trans>Cancel</Trans>
          </button>
          <button
            onClick={handleSave}
            className="px-4 py-2 bg-navi hover:bg-navi-600 text-white text-xs font-bold rounded-lg shadow-md transition-colors"
          >
            <Trans>Save Settings</Trans>
          </button>
        </div>
      </div>
    </div>
  );
}
