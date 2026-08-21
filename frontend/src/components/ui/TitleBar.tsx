import { useState, useRef, useEffect } from "react";
import { useUI } from "../../hooks/useUI";
import { useWorkspace } from "../../hooks/useWorkspace";
import {
  Menu,
  X,
  Minus,
  Square,
  Map,
  ChevronRight,
  PanelBottom,
  Settings2,
} from "lucide-react";
import { Window } from "@tauri-apps/api/window";
import { SaveAs } from "../modal/SaveAs";
import { UnsavedChanges } from "../modal/UnsavedChanges";
import { useFileActions } from "../../hooks/useFileActions";

export function TitleBar() {
  const {
    currentView,
    setCurrentView,
    showVideoPanel,
    setShowVideoPanel,
    showToast,
    setShowAppSettings,
  } = useUI();

  const { saveProject, metadata, loadProject, isDirty, setIsDirty } =
    useWorkspace();
  const { importRouteFile } = useFileActions();
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [showSaveAs, setShowSaveAs] = useState(false);
  const [saveMode, setSaveMode] = useState<"initial" | "duplicate">("initial");
  const [pendingNavigation, setPendingNavigation] = useState<
    "title_screen" | "new_project" | "close" | null
  >(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleSafeNavigation = async (
    targetView: "title_screen" | "new_project",
  ) => {
    setIsMenuOpen(false);

    if (currentView === "editor" && isDirty) {
      setPendingNavigation(targetView);
      return;
    }
    setCurrentView(targetView);
  };

  const handleWindow = async (action: "minimize" | "maximize" | "close") => {
    const appWindow = new Window("main");
    if (action === "minimize") await appWindow.minimize();
    if (action === "maximize") await appWindow.toggleMaximize();
    if (action === "close") {
      setIsMenuOpen(false);
      if (currentView === "editor" && isDirty) {
        setPendingNavigation("close");
        return;
      }
      await appWindow.close();
    }
  };

  const handleSave = async (): Promise<boolean> => {
    setIsMenuOpen(false);
    try {
      const path = await saveProject();
      if (path) {
        showToast(`Project saved to ${path.split(/[/\\]/).pop()}`, "success");
        return true;
      }
      return false;
    } catch (err) {
      showToast("Failed to save project.", "error");
      return false;
    }
  };

  const submitSaveAs = async (newName: string, safeFolderName: string) => {
    if (!newName.trim()) return;
    setShowSaveAs(false);

    try {
      const isDuplicate = saveMode === "duplicate";
      const path = await saveProject(newName, isDuplicate, safeFolderName);
      if (path) {
        showToast(
          isDuplicate ? "Project duplicated successfully." : "Project saved",
          "success",
        );

        if (pendingNavigation) {
          if (pendingNavigation === "close") {
            const appWindow = new Window("main");
            await appWindow.close();
          } else if (
            pendingNavigation === "title_screen" ||
            pendingNavigation === "new_project"
          ) {
            setCurrentView(pendingNavigation);
          }
          setPendingNavigation(null);
        }
      }
    } catch (err) {
      showToast("Failed to save project", "error");
    }
  };

  return (
    <>
      <div
        data-tauri-drag-region
        className="h-10 bg-white dark:bg-[#18181b] border-b border-zinc-200 dark:border-white/5 flex items-center justify-between select-none shrink-0 transition-colors"
      >
        <div className="flex items-center h-full">
          <div className="relative h-full flex items-center" ref={menuRef}>
            <button
              onClick={() => setIsMenuOpen(!isMenuOpen)}
              className={`h-full px-3 flex items-center transition-colors ${isMenuOpen ? "bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-white" : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-50 dark:hover:bg-white/5"}`}
            >
              <Menu className="w-4 h-4" />
            </button>

            {isMenuOpen && (
              <div className="absolute top-10 left-2 w-56 bg-white dark:bg-[#1f1f22] border border-zinc-200 dark:border-white/10 rounded-md shadow-2xl py-1 z-200 text-sm text-zinc-700 dark:text-zinc-300">
                <button
                  onClick={() => handleSafeNavigation("title_screen")}
                  className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-zinc-100 dark:hover:bg-zinc-700/50 transition-colors"
                >
                  <span>Project Manager</span>
                </button>
                <div className="h-px bg-zinc-200 dark:bg-white/5 my-1 mx-2" />
                <button
                  onClick={() => handleSafeNavigation("new_project")}
                  className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-zinc-100 dark:hover:bg-zinc-700/50 transition-colors"
                >
                  <span>New Project</span>
                </button>
                <div className="h-px bg-zinc-200 dark:bg-white/5 my-1 mx-2" />
                <button
                  onClick={async () => {
                    setIsMenuOpen(false);
                    try {
                      const success = await loadProject();
                      if (success) {
                        setCurrentView("editor");
                        showToast("Project loaded successfully.", "success");
                      }
                    } catch (err) {
                      showToast("Failed to read project file.", "error");
                    }
                  }}
                  className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-zinc-100 dark:hover:bg-zinc-700/50 transition-colors"
                >
                  <span>Open Project...</span>
                  <span className="text-xs text-zinc-400">Ctrl+O</span>
                </button>

                <div className="h-px bg-zinc-200 dark:bg-white/5 my-1 mx-2" />
                <button
                  onClick={async () => {
                    setIsMenuOpen(false);
                    await importRouteFile();
                  }}
                  className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-zinc-100 dark:hover:bg-zinc-700/50 transition-colors"
                >
                  <span>Import GPX...</span>
                  {/* Optional: Add an icon or shortcut here if you want */}
                </button>

                {/* Save options only visible when in the editor */}
                {currentView === "editor" && (
                  <>
                    <div className="h-px bg-zinc-200 dark:bg-white/5 my-1 mx-2" />
                    <button
                      onClick={() => {
                        setIsMenuOpen(false);
                        // Intercept First Save
                        if (
                          !metadata.project_id &&
                          metadata.project_name === "Untitled Project"
                        ) {
                          setSaveMode("initial");
                          setShowSaveAs(true);
                        } else {
                          handleSave();
                        }
                      }}
                      className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-zinc-100 dark:hover:bg-zinc-700/50 transition-colors"
                    >
                      <span>Save Project</span>
                      <span className="text-xs text-zinc-400">Ctrl+S</span>
                    </button>

                    <button
                      onClick={() => {
                        setIsMenuOpen(false);
                        setSaveMode("duplicate");
                        setShowSaveAs(true);
                      }}
                      className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-zinc-100 dark:hover:bg-zinc-700/50 transition-colors"
                    >
                      <span>Save As...</span>
                      <span className="text-xs text-zinc-400">
                        Ctrl+Shift+S
                      </span>
                    </button>
                  </>
                )}

                <div className="h-px bg-zinc-200 dark:bg-white/5 my-1 mx-2" />
                <button
                  onClick={() => handleWindow("close")}
                  className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-red-50 hover:text-red-600 transition-colors"
                >
                  <span>Exit</span>
                </button>
              </div>
            )}
          </div>

          <div className="flex items-center gap-2 px-3 text-xs font-medium text-zinc-500 dark:text-zinc-400 pointer-events-none">
            <Map className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-500" />
            <span className="text-zinc-800 dark:text-zinc-300">Navivi</span>
            <ChevronRight className="w-3 h-3 opacity-50" />
            <span className="text-zinc-600 dark:text-zinc-200">
              {currentView === "title_screen"
                ? "Project Manager"
                : currentView === "new_project"
                  ? "Setup"
                  : metadata.project_name}
              {currentView === "editor" && isDirty && "*"}
            </span>
          </div>
        </div>

        <div className="flex h-full text-zinc-600 dark:text-zinc-400">
          
          {currentView === "editor" && (
            <button
              onClick={() => setShowVideoPanel(!showVideoPanel)}
              className={`h-full px-3 flex items-center transition-colors ${showVideoPanel ? "text-emerald-600 bg-zinc-100 dark:bg-white/10" : "hover:bg-zinc-100 hover:text-zinc-900"}`}
              title="Toggle Preview Panel"
            >
              <PanelBottom className="w-4 h-4" />
            </button>
          )}
          <button
            onClick={() => setShowAppSettings(true)}
            className="h-full px-4 hover:bg-zinc-100 hover:text-zinc-900 transition-colors"
            title="App Settings"
          >
            <Settings2 className="w-4 h-4" />
          </button>
          <div className="w-px h-4 my-auto bg-zinc-200 dark:bg-white/10 mx-1"></div>
          <button
            onClick={() => handleWindow("minimize")}
            className="h-full px-4 hover:bg-zinc-100 transition-colors"
          >
            <Minus className="w-4 h-4" />
          </button>
          <button
            onClick={() => handleWindow("maximize")}
            className="h-full px-4 hover:bg-zinc-100 transition-colors"
          >
            <Square className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => handleWindow("close")}
            className="h-full px-4 hover:bg-red-500 hover:text-white transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      <SaveAs
        isOpen={showSaveAs}
        defaultName={metadata.project_name}
        mode={saveMode}
        onClose={() => setShowSaveAs(false)}
        onSubmit={submitSaveAs}
      />

      <UnsavedChanges
        isOpen={pendingNavigation !== null}
        projectName={metadata.project_name}
        onCancel={() => setPendingNavigation(null)}
        onDiscard={async () => {
          setIsDirty(false);
          if (pendingNavigation === "close") {
            const appWindow = new Window("main");
            await appWindow.close();
          } else if (
            pendingNavigation === "title_screen" ||
            pendingNavigation === "new_project"
          ) {
            setCurrentView(pendingNavigation); // TypeScript is now 100% happy
          }
          setPendingNavigation(null);
        }}
        onSave={async () => {
          // Intercept First Save from the warning modal
          if (
            !metadata.project_id &&
            metadata.project_name === "Untitled Project"
          ) {
            setSaveMode("initial");
            setShowSaveAs(true);
            // Do NOT navigate yet. Navigation will resume inside submitSaveAs.
            return;
          }

          // Normal save flow
          const saved = await handleSave();
          if (saved && pendingNavigation) {
            if (pendingNavigation === "close") {
              const appWindow = new Window("main");
              await appWindow.close();
            } else if (
              pendingNavigation === "title_screen" ||
              pendingNavigation === "new_project"
            ) {
              setCurrentView(pendingNavigation);
            }
            setPendingNavigation(null);
          }
        }}
      />
    </>
  );
}
