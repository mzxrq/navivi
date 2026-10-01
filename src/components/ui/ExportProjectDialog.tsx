import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { documentDir, join } from "@tauri-apps/api/path";
import { save } from "@tauri-apps/plugin-dialog";
import { mkdir, exists } from "@tauri-apps/plugin-fs";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useWorkspace } from "../../hooks/useWorkspace";
import { fileSystem } from "../../config/constants";
import { CheckCircle, Folder, Loader2 } from "./icons";
import { Dialog, dialogButton } from "./Dialog";
import { Switch } from "./Switch";

// Opened with: window.dispatchEvent(new CustomEvent("export-project", { detail: { dir?, name? } }))
// No `dir` means the project that is open in the editor (it is saved first).
interface Target {
  dir?: string;
  name?: string;
}

const formatSize = (bytes: number) =>
  bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(1)} GB` : `${Math.max(0.1, bytes / 1024 ** 2).toFixed(1)} MB`;

export function ExportProjectDialog() {
  const { metadata, saveProject } = useWorkspace();
  const [target, setTarget] = useState<Target | null>(null);
  const [withRendered, setWithRendered] = useState(false);
  const [phase, setPhase] = useState<"ready" | "working" | "done" | "error">("ready");
  const [result, setResult] = useState<{ path: string; bytes: number } | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const open = (e: Event) => {
      setTarget((e as CustomEvent<Target>).detail ?? {});
      setPhase("ready");
      setResult(null);
      setError("");
    };
    window.addEventListener("export-project", open);
    return () => window.removeEventListener("export-project", open);
  }, []);

  if (!target) return null;
  const name = target.name || metadata.project_name;
  const close = () => phase !== "working" && setTarget(null);

  const run = async () => {
    try {
      const folder = await join(await documentDir(), fileSystem.rootFolder, fileSystem.projectsFolder);
      if (!(await exists(folder))) await mkdir(folder, { recursive: true });
      const dest = await save({
        defaultPath: await join(folder, `${name}.${fileSystem.extensions.project}`),
        filters: [{ name: "Navivi Project", extensions: [fileSystem.extensions.project] }],
      });
      if (!dest) return;

      setPhase("working");
      const dir = target.dir ?? (await saveProject());
      if (!dir) throw new Error(t`Save the project first`);
      const bytes = await invoke<number>("export_project_archive", { sourceDir: dir, destFile: dest, includeRendered: withRendered });
      setResult({ path: dest, bytes });
      setPhase("done");
    } catch (e: any) {
      setError(String(e?.message ?? e));
      setPhase("error");
    }
  };

  return (
    <Dialog
      width="w-[440px]"
      title={phase === "done" ? <Trans>Project exported</Trans> : <Trans>Export for sharing</Trans>}
      subtitle={name}
      onClose={close}
      footer={
        phase === "done" ? (
          <>
            <button className={`${dialogButton.secondary} flex items-center gap-1.5`} onClick={() => invoke("open_in_explorer", { path: result?.path }).catch(() => undefined)}>
              <Folder className="w-3.5 h-3.5" /> <Trans>Show file</Trans>
            </button>
            <button className={dialogButton.primary} onClick={close}>
              <Trans>Done</Trans>
            </button>
          </>
        ) : (
          <>
            <button className={dialogButton.secondary} disabled={phase === "working"} onClick={close}>
              <Trans>Cancel</Trans>
            </button>
            <button className={dialogButton.primary} disabled={phase === "working"} onClick={run}>
              {phase === "working" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trans>Export…</Trans>}
            </button>
          </>
        )
      }
    >
      {phase === "done" && result ? (
        <div className="flex flex-col items-center gap-2 py-4 text-center">
          <CheckCircle className="w-9 h-9 text-emerald-500" />
          <p className="text-[13px] text-zinc-700 dark:text-zinc-200">{formatSize(result.bytes)}</p>
          <p className="text-[12px] text-zinc-500 break-all">{result.path}</p>
        </div>
      ) : (
        <>
          <p className="text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
            <Trans>
              One file you can send to someone, or keep as a backup. It holds the route, scripts, photos, your own videos, music and the narration audio.
              Map tiles and old versions are left out.
            </Trans>
          </p>
          <div className="mt-4 flex items-center justify-between gap-4">
            <div className="min-w-0">
              <p className="text-[13px] text-zinc-900 dark:text-zinc-100">
                <Trans>Include rendered video clips</Trans>
              </p>
              <p className="mt-0.5 text-[12px] leading-snug text-zinc-500 dark:text-zinc-400">
                <Trans>Makes the file much larger. Without them the other person renders the clips again.</Trans>
              </p>
            </div>
            <Switch checked={withRendered} onChange={setWithRendered} label={t`Include rendered video clips`} disabled={phase === "working"} />
          </div>
          {phase === "error" && <p className="mt-3 text-[12px] text-red-500 break-words">{error}</p>}
        </>
      )}
    </Dialog>
  );
}
