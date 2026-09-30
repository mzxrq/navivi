import { useState, useEffect } from "react";
import { exists } from "@tauri-apps/plugin-fs";
import { documentDir, join } from "@tauri-apps/api/path";
import { Folder, Loader2 } from "./icons";
import { fileSystem } from "../../config/constants";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Dialog, dialogButton, dialogInput } from "./Dialog";

interface SaveAsProps {
  isOpen: boolean;
  defaultName: string;
  mode: "initial" | "duplicate";
  onClose: () => void;
  onSubmit: (newName: string, safeFolderName: string) => void;
}

export function SaveAs({
  isOpen,
  defaultName,
  mode,
  onClose,
  onSubmit,
}: SaveAsProps) {
  const [saveAsName, setSaveAsName] = useState(defaultName);
  const [folderPreview, setFolderPreview] = useState("untitled");
  const [isChecking, setIsChecking] = useState(false);

  useEffect(() => {
    if (isOpen) setSaveAsName(defaultName);
  }, [isOpen, defaultName]);

  useEffect(() => {
    if (!isOpen) return;

    const baseName = saveAsName.trim();
    if (!baseName) {
      setFolderPreview("untitled");
      setIsChecking(false);
      return;
    }

    let isActive = true;

    const checkAvailablePath = async () => {
      setIsChecking(true);
      try {
        const sanitizedBase =
          baseName.toLowerCase().replace(/[^a-z0-9]+/g, "_") || "untitled";

        const docsPath = await documentDir();
        const projectsRootPath = await join(
          docsPath,
          fileSystem.rootFolder,
          fileSystem.projectsFolder,
        );
        let currentTestName = sanitizedBase;
        let counter = 1;

        while (await exists(await join(projectsRootPath, currentTestName))) {
          currentTestName = `${sanitizedBase}_${counter}`;
          counter++;
        }

        if (isActive) setFolderPreview(currentTestName);
      } catch (error) {
        console.error("Failed to check folder existence:", error);
        if (isActive) {
          setFolderPreview(
            baseName.toLowerCase().replace(/[^a-z0-9]+/g, "_") || "untitled",
          );
        }
      } finally {
        if (isActive) setIsChecking(false);
      }
    };

    const timer = setTimeout(() => {
      checkAvailablePath();
    }, 300);

    return () => {
      isActive = false;
      clearTimeout(timer);
    };
  }, [saveAsName, isOpen]);

  if (!isOpen) return null;

  const isValid = saveAsName.trim().length > 0 && !isChecking;
  const submit = () => {
    if (isValid) onSubmit(saveAsName, folderPreview);
  };

  return (
    <Dialog
      title={mode === "initial" ? t`Save New Project` : t`Save Project As`}
      subtitle={
        mode === "initial" ? t`Name your project to continue` : t`Create a copy of this workspace`
      }
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className={dialogButton.secondary}>
            <Trans>Cancel</Trans>
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={!isValid}
            className={`${dialogButton.primary} min-w-16 flex items-center justify-center`}
          >
            {isChecking ? <Loader2 className="w-4 h-4 animate-spin" /> : t`Save`}
          </button>
        </>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <label className="block mb-1.5 text-[12px] font-medium text-zinc-600 dark:text-zinc-300">
          <Trans>Project Name</Trans>
        </label>
        <input
          type="text"
          value={saveAsName}
          onChange={(e) => setSaveAsName(e.target.value)}
          onFocus={(e) => e.currentTarget.select()}
          className={dialogInput}
          autoFocus
          placeholder={t`Your Project Name Here`}
          spellCheck={false}
        />
      </form>

      <div className="mt-3 flex items-center gap-2 min-w-0 text-[12px] text-zinc-500 dark:text-zinc-400">
        <Folder className="w-3.5 h-3.5 shrink-0 text-zinc-400" />
        <span
          className="truncate tracking-tight"
          title={`Documents/Navivi/Projects/${folderPreview}`}
        >
          Documents/Navivi/Projects/
          <span className="font-medium text-zinc-800 dark:text-zinc-200">{folderPreview}</span>
        </span>
        {isChecking && <Loader2 className="w-3 h-3 shrink-0 animate-spin text-zinc-400" />}
      </div>
    </Dialog>
  );
}
