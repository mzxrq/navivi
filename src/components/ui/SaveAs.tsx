import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { exists } from "@tauri-apps/plugin-fs";
import { documentDir, join } from "@tauri-apps/api/path";
import { Folder, Map, Loader2 } from "./icons";
import { fileSystem } from "../../config/constants";

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
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) onClose();
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [isOpen, onClose]);

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
        const projectsRootPath = await join(docsPath, fileSystem.rootFolder, fileSystem.projectsFolder);
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
            baseName.toLowerCase().replace(/[^a-z0-9]+/g, "_") || "untitled"
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

  return createPortal(
    <div className="fixed inset-0 z-99999 flex items-center justify-center bg-zinc-950/40 backdrop-blur-[2px] animate-in fade-in duration-200">
      <div className="w-96 bg-white dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded-xl shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200">
        {/* Header Section */}
        <div className="px-5 py-4 border-b border-zinc-100 dark:border-navidark-400 bg-zinc-50/50 dark:bg-navidark-800 flex items-center gap-3">
          <div className="p-2 bg-navi-50 dark:bg-navi/10 text-navi-600 dark:text-navi-400 rounded-lg">
            <Map className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-zinc-900 dark:text-white">
              {mode === "initial" ? "Save New Project" : "Save Project As"}
            </h3>
            <p className="text-[10px] text-zinc-500 dark:text-navidark-125 mt-0.5">
              {mode === "initial"
                ? "Name your project to continue."
                : "Create a copy of this workspace."}
            </p>
          </div>
        </div>

        {/* Body Section */}
        <div className="p-5">
          <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1.5">
            Project Name
          </label>
          <input
            type="text"
            value={saveAsName}
            onChange={(e) => setSaveAsName(e.target.value)}
            onKeyDown={(e) =>
              e.key === "Enter" &&
              isValid &&
              onSubmit(saveAsName, folderPreview)
            }
            className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2 text-sm text-zinc-900 dark:text-white mb-5 outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all shadow-sm"
            autoFocus
            placeholder="Your Project Name Here"
            spellCheck={false}
          />

          {/* Contextual Path Preview */}
          <div className="flex items-start gap-3 p-3 bg-zinc-50 dark:bg-navidark-800 rounded-lg border border-zinc-100 dark:border-navidark-400 shadow-inner">
            <Folder className="w-4 h-4 text-zinc-400 dark:text-navidark-150 mt-0.5 shrink-0" />
            <div className="overflow-hidden w-full">
              <div className="flex items-center justify-between mb-0.5">
                <div className="text-[10px] font-semibold text-zinc-700 dark:text-zinc-300">
                  Save Location
                </div>
                {isChecking && (
                  <div className="flex items-center gap-1 text-[9px] text-zinc-400 dark:text-navidark-150 font-medium">
                    <Loader2 className="w-2.5 h-2.5 animate-spin" /> Checking...
                  </div>
                )}
              </div>
              <div
                className="text-[10px] text-zinc-500 dark:text-navidark-125 truncate flex items-center"
                title={`Documents/Navivi/Projects/${folderPreview}`}
              >
                <span className="truncate shrink">
                  Documents/Navivi/Projects/
                </span>
                <span
                  className={`font-medium shrink-0 ml-0.5 ${
                    folderPreview.includes("_")
                      ? "text-zinc-600 dark:text-navidark-100"
                      : "text-zinc-700 dark:text-zinc-300"
                  }`}
                >
                  {folderPreview}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Footer Section */}
        <div className="px-5 py-4 border-t border-zinc-100 dark:border-navidark-400 bg-zinc-50/50 dark:bg-navidark-800 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-xs font-semibold text-zinc-600 dark:text-navidark-150 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-navidark-700 rounded-lg transition-colors"
          >
            Cancel
          </button>

          <button
            onClick={() => onSubmit(saveAsName, folderPreview)}
            disabled={!isValid}
            className="flex items-center justify-center min-w-17.5 px-4 py-2 bg-navi disabled:bg-navi/50 disabled:cursor-not-allowed text-white text-xs font-bold rounded-lg hover:bg-navi-600 transition-colors shadow-sm"
          >
            {isChecking ? <Loader2 className="w-4 h-4 animate-spin" /> : "Save"}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}