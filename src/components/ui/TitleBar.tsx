import { useEffect, useState, useRef } from "react";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useUI } from "../../hooks/useUI";
import { useWorkspace } from "../../hooks/useWorkspace";
import {
  Menu,
  X,
  Minus,
  Square,
  Map,
  Settings2,
  Undo2,
  Redo2,
  Film,
  Navivi,
  Folder,
} from "../ui/icons";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { invoke } from "@tauri-apps/api/core";
import { SaveAs } from "./SaveAs";
import { UnsavedChanges } from "./UnsavedChanges";
import { useFileActions } from "../../hooks/useFileActions";


export function TitleBar() {
  const {
    currentView,
    setCurrentView,
    editorMode,
    setEditorMode,
    showToast,
    setShowAppSettings,
  } = useUI();

  const {
    saveProject,
    metadata,
    loadProject,
    isDirty,
    setIsDirty,
    undoMap,
    redoMap,
    canUndoMap,
    canRedoMap,
    undoTimeline,
    redoTimeline,
    canUndoTimeline,
    canRedoTimeline,
    setActiveWaypointId,
    setWaypoints,
    setMetadata,
  } = useWorkspace();

  const { importRouteFile, importPhotos } = useFileActions();
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

  const clearProjectState = () => {
    if (setActiveWaypointId) setActiveWaypointId(null);
    if (setWaypoints) setWaypoints([]);
    if (setMetadata) {
      setMetadata((prevMetadata) => ({
        ...prevMetadata,
        project_name: t`Untitled Project`,
        project_id: undefined,
        directory_path: "",
        created_at: new Date().toISOString(),
        status: "draft",
      }));
    }
    setIsDirty(false);
  };

  const handleSafeNavigation = async (
    targetView: "title_screen" | "new_project",
  ) => {
    setIsMenuOpen(false);

    if (currentView === "editor" && isDirty) {
      setPendingNavigation(targetView);
      return;
    }
    clearProjectState();
    setCurrentView(targetView);
  };

  const handleWindow = async (action: "minimize" | "maximize" | "close") => {
    if (action === "close") {
      setIsMenuOpen(false);
      if (currentView === "editor" && isDirty) {
        setPendingNavigation("close");
        return;
      }
    }

    try {
      const appWindow = getCurrentWindow();
      if (action === "minimize") await appWindow.minimize();
      if (action === "maximize") await appWindow.toggleMaximize();
      if (action === "close") await appWindow.close();
    } catch (err) {
      console.error(t`Tauri Window API error:`, err);
      if (action === "close") {
        showToast(t`Cannot close window. Check Tauri capabilities`, "error");
      }
    }
  };

  const handleSave = async (): Promise<boolean> => {
    setIsMenuOpen(false);
    try {
      const path = await saveProject();
      if (path) {
        const fileName = path.split(/[/\\]/).filter(Boolean).pop() ?? "";
        showToast(t`Project saved to ${fileName}`, "success");
        return true;
      }
      return false;
    } catch (err) {
      showToast(t`Failed to save project.`, "error");
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
          isDuplicate ? t`Project duplicated successfully` : t`Project saved`,
          "success",
        );

        if (pendingNavigation) {
          if (pendingNavigation === "close") {
            try {
              await getCurrentWindow().close();
            } catch (e) {
              console.error(e);
            }
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

  const handleUndo = () => (editorMode === "map" ? undoMap() : undoTimeline());
  const canUndo = editorMode === "map" ? canUndoMap : canUndoTimeline;
  const handleRedo = () => (editorMode === "map" ? redoMap() : redoTimeline());
  const canRedo = editorMode === "map" ? canRedoMap : canRedoTimeline;

  return (
    <>
      <div
        data-tauri-drag-region
        className="absolute top-0 inset-x-0 h-10 bg-white/60 dark:bg-zinc-950/60 backdrop-blur-xl border-b border-white/40 dark:border-white/10 flex items-center justify-between select-none shrink-0 transition-colors z-9999 shadow-sm"
      >
        {/* --- LEFT: MENU & DOCUMENT ACTIONS --- */}
        <div className="flex items-center h-full shrink-0 px-2">
          <div className="relative h-full flex items-center" ref={menuRef}>
            <button
              onClick={() => setIsMenuOpen(!isMenuOpen)}
              className={`h-7 px-3 flex items-center justify-center rounded-lg font-medium transition-all ${isMenuOpen ? "bg-zinc-800 text-white dark:bg-white dark:text-zinc-900 shadow-md" : "text-zinc-600 dark:text-zinc-300 hover:bg-black/5 dark:hover:bg-white/10"}`}
            >
              <Menu className="w-4 h-4" />
            </button>

            {/* Dropdown Menu */}
            {isMenuOpen && (
              <div className="absolute top-10 w-56 -left-2 bg-white dark:bg-navidark-600 border border-zinc-200 dark:border-white/10 rounded-br-2xl shadow-2xl py-1 z-800 text-sm text-zinc-700 dark:text-zinc-300">
                {currentView === "editor" && (
                  <>
                    <button
                      onClick={() => {
                        setIsMenuOpen(false);
                        if (
                          !metadata.project_id &&
                          metadata.project_name === t`Untitled Project`
                        ) {
                          setSaveMode("initial");
                          setShowSaveAs(true);
                        } else {
                          handleSave();
                        }
                      }}
                      className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-zinc-100 dark:hover:bg-navidark-400 transition-colors"
                    >
                      <span><Trans>Save Project</Trans></span>
                      <span className="text-xs text-zinc-400">Ctrl+S</span>
                    </button>

                    <button
                      onClick={() => {
                        setIsMenuOpen(false);
                        setSaveMode("duplicate");
                        setShowSaveAs(true);
                      }}
                      className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-zinc-100 dark:hover:bg-navidark-400 transition-colors"
                    >
                      <span><Trans>Save As...</Trans></span>
                      <span className="text-xs text-zinc-400">
                        Ctrl+Shift+S
                      </span>
                    </button>
                    <div className="h-px bg-zinc-200 dark:bg-white/5 my-1 mx-2" />
                    <button
                      onClick={() => handleSafeNavigation("title_screen")}
                      className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-zinc-100 dark:hover:bg-navidark-400 transition-colors"
                    >
                      <span><Trans>Project Manager</Trans></span>
                    </button>
                    <button
                      onClick={async () => {
                        setIsMenuOpen(false);
                        const targetPath =
                          metadata.archive_path || metadata.directory_path;
                        if (!targetPath) {
                          showToast(t`No active project folder found`, "info");
                          return;
                        }
                        try {
                          await invoke("open_in_explorer", {
                            path: targetPath,
                          });
                        } catch (err) {
                          console.error(t`Failed to open file explorer:`, err);
                          showToast(t`Could not open file location`, "error");
                        }
                      }}
                      className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-zinc-100 dark:hover:bg-navidark-400 transition-colors"
                    >
                      <span className="flex items-center gap-2">
                        <Folder className="w-3.5 h-3.5 text-zinc-400" />
                        <Trans>Reveal in File Explorer</Trans>
                      </span>
                    </button>
                    <div className="h-px bg-zinc-200 dark:bg-white/5 my-1 mx-2" />
                  </>
                )}

                <button
                  onClick={() => handleSafeNavigation("new_project")}
                  className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-zinc-100 dark:hover:bg-navidark-400 transition-colors"
                >
                  <span><Trans>New Project</Trans></span>
                </button>
                <button
                  onClick={async () => {
                    setIsMenuOpen(false);
                    try {
                      const success = await loadProject();
                      if (success) {
                        setCurrentView("editor");
                        showToast(t`Project loaded successfully`, "success");
                      }
                    } catch (err) {
                      showToast(t`Failed to read project file`, "error");
                    }
                  }}
                  className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-zinc-100 dark:hover:bg-navidark-400 transition-colors"
                >
                  <span><Trans>Open Project File...</Trans></span>
                </button>
                <button
                  onClick={async () => {
                    setIsMenuOpen(false);
                    try {
                      const success = await loadProject(undefined, true);
                      if (success) {
                        setCurrentView("editor");
                        showToast(t`Project loaded successfully`, "success");
                      }
                    } catch (err) {
                      showToast(t`Failed to read project folder`, "error");
                    }
                  }}
                  className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-zinc-100 dark:hover:bg-navidark-400 transition-colors"
                >
                  <span><Trans>Open Project Folder...</Trans></span>
                </button>

                <div className="h-px bg-zinc-200 dark:bg-white/5 my-1 mx-2" />
                <button
                  onClick={async () => {
                    setIsMenuOpen(false);
                    await importPhotos();
                  }}
                  className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-zinc-100 dark:hover:bg-navidark-400 transition-colors"
                >
                  <span><Trans>Import Photos...</Trans></span>
                </button>
                <button
                  onClick={async () => {
                    setIsMenuOpen(false);
                    await importRouteFile();
                  }}
                  className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-zinc-100 dark:hover:bg-navidark-400 transition-colors"
                >
                  <span><Trans>Import GPX...</Trans></span>
                </button>

                <div className="h-px bg-zinc-200 dark:bg-white/5 my-1 mx-2" />
                <button
                  onClick={() => handleWindow("close")}
                  className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-500/10 dark:hover:text-red-400 transition-colors"
                >
                  <span><Trans>Exit</Trans></span>
                </button>
              </div>
            )}
          </div>

          <div className="w-px h-5 my-auto bg-zinc-200 dark:bg-white/10 mx-1"></div>

          {/* ✨ MOVED: Undo/Redo safely tucked away from the close button */}
          {currentView === "editor" && (
            <div className="flex items-center h-full text-zinc-600 dark:text-zinc-400 px-1">
              <button
                onClick={handleUndo}
                disabled={!canUndo}
                className="h-full px-3 flex items-center hover:bg-zinc-100 dark:hover:bg-white/5 transition-colors disabled:opacity-30 disabled:hover:bg-transparent"
                title={t`Undo (Ctrl+Z)`}
              >
                <Undo2 className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={handleRedo}
                disabled={!canRedo}
                className="h-full px-3 flex items-center hover:bg-zinc-100 dark:hover:bg-white/5 transition-colors disabled:opacity-30 disabled:hover:bg-transparent"
                title={t`Redo (Ctrl+Y)`}
              >
                <Redo2 className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
        </div>

        {/* --- CENTER: CONTEXT & STATUS --- */}
        <div
          data-tauri-drag-region
          className="flex-1 flex items-center justify-center h-full px-4"
        >
          <div
            data-tauri-drag-region
            className="flex items-center justify-center gap-2 text-xs font-medium text-zinc-500 dark:text-zinc-400"
          >
            <Navivi className="w-4 h-4 text-navi dark:text-navi pointer-events-none" />

            <span className="text-zinc-800 dark:text-zinc-200 pointer-events-none font-semibold">
              {currentView === "title_screen" ? (
                <Trans>Project Manager</Trans>
              ) : currentView === "new_project" ? (
                <Trans>Setup</Trans>
              ) : (
                metadata.project_name
              )}
            </span>

            {currentView === "editor" && (
              <span
                className={`text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded-sm font-bold ml-2 transition-colors pointer-events-none ${
                  isDirty
                    ? "bg-amber-100 text-amber-600 dark:bg-amber-500/20 dark:text-amber-400"
                    : "bg-emerald-100 text-emerald-600 dark:bg-emerald-500/20 dark:text-emerald-400"
                }`}
              >
                {isDirty ? t`Unsaved` : t`Saved`}
              </span>
            )}
          </div>
        </div>

        {/* --- RIGHT: VIEW & WINDOW CONTROLS --- */}
        <div className="flex items-center h-full shrink-0">
          {/* Map / Timeline Toggle */}
          {currentView === "editor" && (
            <div className="flex bg-black/5 dark:bg-white/5 rounded-full p-0.5 border border-black/5 dark:border-white/5 shadow-inner mr-4">
              <button
                onClick={() => setEditorMode("map")}
                className={`flex items-center gap-1.5 px-3 py-1 text-[11px] font-bold rounded-full transition-all ${
                  editorMode === "map"
                    ? "bg-white dark:bg-zinc-800 text-navi-600 dark:text-navi-400 shadow-sm"
                    : "text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
                }`}
                title={t`Map`}
              >
                <Map className="w-3.5 h-3.5" /> <Trans>Map</Trans>
              </button>

              <button
                onClick={() => setEditorMode("timeline")}
                className={`flex items-center gap-1.5 px-3 py-1 text-[11px] font-bold rounded-full transition-all ${
                  editorMode === "timeline"
                    ? "bg-white dark:bg-zinc-800 text-navi-600 dark:text-navi-400 shadow-sm"
                    : "text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
                }`}
                title={t`Timeline`}
              >
                <Film className="w-3.5 h-3.5" /> <Trans>Timeline</Trans>
              </button>
            </div>
          )}

          <button
            onClick={() => setShowAppSettings(true)}
            className="h-full px-4 text-zinc-600 dark:text-zinc-400 hover:bg-black/5 dark:hover:bg-white/10 hover:text-zinc-900 dark:hover:text-white transition-colors"
            title={t`App Settings`}
          >
            <Settings2 className="w-4 h-4" />
          </button>

          <div className="w-px h-5 my-auto bg-black/10 dark:bg-white/10 mx-1"></div>

          <div className="flex h-full text-zinc-600 dark:text-zinc-400">
            <button
              onClick={() => handleWindow("minimize")}
              className="h-full px-4 hover:bg-black/5 dark:hover:bg-white/10 transition-colors"
            >
              <Minus className="w-4 h-4" />
            </button>
            <button
              onClick={() => handleWindow("maximize")}
              className="h-full px-4 hover:bg-black/5 dark:hover:bg-white/10 transition-colors"
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
            try {
              await getCurrentWindow().close();
            } catch (e) {
              console.error(e);
            }
          } else if (
            pendingNavigation === "title_screen" ||
            pendingNavigation === "new_project"
          ) {
            setCurrentView(pendingNavigation);
          }
          setPendingNavigation(null);
        }}
        onSave={async () => {
          if (
            !metadata.project_id &&
            metadata.project_name === t`Untitled Project`
          ) {
            setSaveMode("initial");
            setShowSaveAs(true);
            return;
          }

          const saved = await handleSave();
          if (saved && pendingNavigation) {
            if (pendingNavigation === "close") {
              try {
                await getCurrentWindow().close();
              } catch (e) {
                console.error(e);
              }
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
