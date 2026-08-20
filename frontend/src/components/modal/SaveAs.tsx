import { useState, useEffect } from "react";
import { Folder, Map } from "lucide-react";

interface SaveAsProps {
  isOpen: boolean;
  defaultName: string;
  mode: "initial" | "duplicate";
  onClose: () => void;
  onSubmit: (newName: string) => void;
}

export function SaveAs({
  isOpen,
  defaultName,
  mode,
  onClose,
  onSubmit,
}: SaveAsProps) {
  const [saveAsName, setSaveAsName] = useState(defaultName);

  useEffect(() => {
    if (isOpen) setSaveAsName(defaultName);
  }, [isOpen, defaultName]);

  if (!isOpen) return null;

  const isValid = saveAsName.trim().length > 0;
  const folderPreview =
    saveAsName
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_") || "untitled";

  return (
    <div className="fixed inset-0 z-999 flex items-center justify-center bg-black/60 animate-in fade-in">
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
              e.key === "Enter" && isValid && onSubmit(saveAsName)
            }
            className="w-full bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 rounded-lg px-3 py-2 text-sm text-zinc-900 dark:text-white mb-5 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 transition-all"
            autoFocus
            placeholder="Your Project Name Here"
            spellCheck={false}
          />

          {/* Contextual Path Preview */}
          <div className="flex items-start gap-3 p-3 bg-zinc-50 dark:bg-zinc-900/50 rounded-lg border border-zinc-100 dark:border-white/5">
            <Folder className="w-4 h-4 text-zinc-400 mt-0.5 shrink-0" />
            <div className="overflow-hidden">
              <div className="text-[10px] font-semibold text-zinc-700 dark:text-zinc-300 mb-0.5">
                Save Location
              </div>
              <div
                className="text-[10px] text-zinc-500 dark:text-zinc-500 truncate"
                title={`Documents/Navivi/Projects/${folderPreview}`}
              >
                Documents/Navivi/Projects/
                <span className="font-mono text-zinc-400 dark:text-zinc-400">
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
            onClick={() => onSubmit(saveAsName)}
            disabled={!isValid}
            className="px-4 py-2 bg-emerald-500 disabled:bg-emerald-500/50 disabled:cursor-not-allowed text-white text-xs font-bold rounded-lg hover:bg-emerald-600 transition-colors shadow-sm"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
