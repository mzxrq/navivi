import { useState, useEffect } from "react";
import { exists } from "@tauri-apps/plugin-fs";
import { documentDir, join } from "@tauri-apps/api/path";
import { Folder, Map, Loader2 } from "lucide-react";
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
    if (!isOpen) return;

    const baseName = saveAsName.trim();
    if (!baseName) {
      setFolderPreview("untitled");
      return;
    }

    const checkAvailablePath = async () => {
      setIsChecking(true);
      try {
        const sanitizedBase =
          baseName.toLowerCase().replace(/[^a-z0-9]+/g, "_") || "untitled";

        const docsPath = await documentDir();
        let currentTestName = sanitizedBase;
        let counter = 1;

        while (
          await exists(
            await join(
              docsPath,
              fileSystem.rootFolder,
              fileSystem.projectsFolder,
              currentTestName,
            ),
          )
        ) {
          currentTestName = `${sanitizedBase}_${counter}`;
          counter++;
        }

        setFolderPreview(currentTestName);
      } catch (error) {
        console.error("Failed to check folder existence:", error);
        setFolderPreview(
          baseName.toLowerCase().replace(/[^a-z0-9]+/g, "_") || "untitled",
        );
      } finally {
        setIsChecking(false);
      }
    };

    const timer = setTimeout(() => {
      checkAvailablePath();
    }, 300);

    return () => clearTimeout(timer);
  }, [saveAsName, isOpen]);

  if (!isOpen) return null;

  const isValid = saveAsName.trim().length > 0 && !isChecking;

  return (
    <div className="fixed inset-0 z-[999] flex items-center justify-center bg-black/60 animate-in fade-in">
      <div className="w-96 bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-white/10 rounded-xl shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200">
        {/* Header Section */}
        <div className="px-5 py-4 border-b border-zinc-100 dark:border-white/5 bg-zinc-50/50 dark:bg-zinc-900/50 flex items-center gap-3">
          <div className="p-2 bg-emerald-100 dark:bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 rounded-lg">
            <Map className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-zinc-900 dark:text-white">
              {mode === "initial" ? "Save New Project" : "Save Project As"}
            </h3>
            <p className="text-[10px] text-zinc-500 dark:text-zinc-400 mt-0.5">
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
            className="w-full bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 rounded-lg px-3 py-2 text-sm text-zinc-900 dark:text-white mb-5 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 transition-all"
            autoFocus
            placeholder="Your Project Name Here"
            spellCheck={false}
          />

          {/* Contextual Path Preview */}
          <div className="flex items-start gap-3 p-3 bg-zinc-50 dark:bg-zinc-900/50 rounded-lg border border-zinc-100 dark:border-white/5">
            <Folder className="w-4 h-4 text-zinc-400 mt-0.5 shrink-0" />
            <div className="overflow-hidden w-full">
              <div className="flex items-center justify-between mb-0.5">
                <div className="text-[10px] font-semibold text-zinc-700 dark:text-zinc-300">
                  Save Location
                </div>
                {isChecking && (
                  <div className="flex items-center gap-1 text-[9px] text-zinc-400 font-medium">
                    <Loader2 className="w-2.5 h-2.5 animate-spin" /> Checking...
                  </div>
                )}
              </div>
              <div
                className="text-[10px] text-zinc-500 dark:text-zinc-500 truncate flex items-center"
                title={`Documents/Navivi/Projects/${folderPreview}`}
              >
                <span className="truncate shrink">
                  Documents/Navivi/Projects/
                </span>
                <span
                  className={`font-medium shrink-0 ml-0.5 ${
                    folderPreview.includes("_")
                      ? "text-zinc-600 dark:text-zinc-500"
                      : "text-zinc-700 dark:text-zinc-400"
                  }`}
                >
                  {folderPreview}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Footer Section */}
        <div className="px-5 py-4 border-t border-zinc-100 dark:border-white/5 bg-zinc-50/50 dark:bg-zinc-900/50 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-xs font-semibold text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-lg transition-colors"
          >
            Cancel
          </button>

          <button
            onClick={() => onSubmit(saveAsName, folderPreview)}
            disabled={!isValid}
            className="flex items-center justify-center min-w-17.5 px-4 py-2 bg-emerald-500 disabled:bg-emerald-500/50 disabled:cursor-not-allowed text-white text-xs font-bold rounded-lg hover:bg-emerald-600 transition-colors shadow-sm"
          >
            {isChecking ? <Loader2 className="w-4 h-4 animate-spin" /> : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
