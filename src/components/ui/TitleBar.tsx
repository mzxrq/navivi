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
  Sparkles,
  Undo2,
  Redo2,
  Film,
} from "../ui/icons";
import { useAssistant } from "../../hooks/useAssistant";
import { useAiReady } from "../../hooks/useAiReady";
import { Tip } from "./Tip";
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
    isRendering,
    isBackgroundRender,
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

  const { importRouteFile, importDocument, importPhotos } = useFileActions();
  const { panelOpen, setPanelOpen } = useAssistant();
  const aiReady = useAiReady();
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [showSaveAs, setShowSaveAs] = useState(false);
  const [saveMode, setSaveMode] = useState<"initial" | "duplicate">("initial");
  const [pendingNavigation, setPendingNavigation] = useState<
    "title_screen" | "new_project" | "close" | "open_file" | "open_folder" | null
  >(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsMenuOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsMenuOpen(false);
    };
    document.addEventListener("mousedown", handleClickOutside);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      window.removeEventListener("keydown", handleKeyDown);
    };
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

  const openProject = async (folder: boolean) => {
    try {
      const success = await loadProject(undefined, folder || undefined);
      if (success) {
        setCurrentView("editor");
        showToast(t`Project loaded successfully`, "success");
      }
    } catch (err) {
      showToast(folder ? t`Failed to read project folder` : t`Failed to read project file`, "error");
    }
  };

  // Opening another project replaces the one in memory, so it asks first like New Project does.
  const askThenOpen = (folder: boolean) => {
    setIsMenuOpen(false);
    if (currentView === "editor" && isDirty) {
      setPendingNavigation(folder ? "open_folder" : "open_file");
      return;
    }
    void openProject(folder);
  };

  // What the unsaved-changes dialog was guarding, once the user has saved or chosen to discard.
  const finishPending = async (target: NonNullable<typeof pendingNavigation>) => {
    if (target === "close") {
      try {
        await getCurrentWindow().destroy();
      } catch (e) {
        console.error(e);
      }
    } else if (target === "title_screen" || target === "new_project") {
      setCurrentView(target);
    } else {
      await openProject(target === "open_folder");
    }
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
          const target = pendingNavigation;
          setPendingNavigation(null);
          await finishPending(target);
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
        className="absolute top-0 inset-x-0 h-10 z-100000 flex items-center justify-between select-none shrink-0 bg-zinc-50/85 dark:bg-zinc-950/85 backdrop-blur-xl border-b border-zinc-200/80 dark:border-white/10 transition-colors"
      >
        <div className="flex items-center gap-0.5 h-full shrink-0 pl-2">
          <div className="relative" ref={menuRef}>
            <button
              type="button"
              disabled={isRendering}
              onClick={() => setIsMenuOpen(!isMenuOpen)}
              aria-haspopup="menu"
              aria-expanded={isMenuOpen}
              aria-label={t`Menu`}
              className={`${barButton} ${isMenuOpen ? "bg-zinc-200/70 text-zinc-900 dark:bg-white/10 dark:text-zinc-100" : ""}`}
            >
              <Menu className="w-4 h-4" />
            </button>

            {isMenuOpen && (
              <div
                role="menu"
                className="absolute top-full left-0 mt-1.5 min-w-60 w-max p-1 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 shadow-lg z-800 animate-in fade-in zoom-in-95 duration-100 origin-top-left"
              >
                {currentView === "editor" && (
                  <>
                    <MenuItem
                      kbd="Ctrl+S"
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
                    >
                      <Trans>Save Project</Trans>
                    </MenuItem>
                    <MenuItem
                      kbd="Ctrl+Shift+S"
                      onClick={() => {
                        setIsMenuOpen(false);
                        setSaveMode("duplicate");
                        setShowSaveAs(true);
                      }}
                    >
                      <Trans>Save As...</Trans>
                    </MenuItem>
                    <MenuItem
                      onClick={() => {
                        setIsMenuOpen(false);
                        window.dispatchEvent(new CustomEvent("export-project", { detail: {} }));
                      }}
                    >
                      <Trans>Export for sharing...</Trans>
                    </MenuItem>
                    <MenuItem
                      onClick={() => {
                        setIsMenuOpen(false);
                        setShowAppSettings(true);
                        setTimeout(() => window.dispatchEvent(new CustomEvent("open-app-settings-tab", { detail: "project" })), 0);
                      }}
                    >
                      <Trans>Project settings...</Trans>
                    </MenuItem>
                    <MenuSeparator />
                    <MenuItem onClick={() => handleSafeNavigation("title_screen")}>
                      <Trans>Project Manager</Trans>
                    </MenuItem>
                    <MenuItem
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
                    >
                      <Trans>Reveal in File Explorer</Trans>
                    </MenuItem>
                    <MenuSeparator />
                  </>
                )}

                <MenuItem onClick={() => handleSafeNavigation("new_project")}>
                  <Trans>New Project</Trans>
                </MenuItem>
                <MenuItem onClick={() => askThenOpen(false)}>
                  <Trans>Open Project File...</Trans>
                </MenuItem>
                <MenuItem onClick={() => askThenOpen(true)}>
                  <Trans>Open Project Folder...</Trans>
                </MenuItem>

                {currentView === "editor" && (
                  <>
                    <MenuSeparator />
                    <MenuItem
                      onClick={async () => {
                        setIsMenuOpen(false);
                        await importPhotos();
                      }}
                    >
                      <Trans>Import Photos...</Trans>
                    </MenuItem>
                    <MenuItem
                      onClick={async () => {
                        setIsMenuOpen(false);
                        await importRouteFile();
                      }}
                    >
                      <Trans>Import GPX...</Trans>
                    </MenuItem>
                    <MenuItem
                      onClick={async () => {
                        setIsMenuOpen(false);
                        await importDocument();
                      }}
                    >
                      <Trans>Import document...</Trans>
                    </MenuItem>
                  </>
                )}

                <MenuSeparator />
                <MenuItem danger onClick={() => handleWindow("close")}>
                  <Trans>Exit</Trans>
                </MenuItem>
              </div>
            )}
          </div>

          {currentView === "editor" && (
            <>
              <div className="w-px h-4 mx-1 bg-zinc-200 dark:bg-white/10" />
              <button
                type="button"
                onClick={handleUndo}
                disabled={!canUndo}
                aria-label={t`Undo`}
                className={barButton}
              >
                <Undo2 className="w-3.5 h-3.5" />
                <Tip label={t`Undo`} kbd="Ctrl+Z" align="start" />
              </button>
              <button
                type="button"
                onClick={handleRedo}
                disabled={!canRedo}
                aria-label={t`Redo`}
                className={barButton}
              >
                <Redo2 className="w-3.5 h-3.5" />
                <Tip label={t`Redo`} kbd="Ctrl+Y" />
              </button>
            </>
          )}
        </div>

        <div
          data-tauri-drag-region
          className="absolute inset-y-0 left-1/2 -translate-x-1/2 max-w-[40%] flex items-center justify-center pointer-events-none"
        >
          <span className="truncate text-[12px] font-medium text-zinc-700 dark:text-zinc-300">
            {currentView === "title_screen" ? (
              <Trans>Project Manager</Trans>
            ) : currentView === "new_project" ? (
              <Trans>Setup</Trans>
            ) : (
              metadata.project_name
            )}
          </span>
        </div>

        <div className="flex items-center h-full shrink-0">
          {currentView === "editor" && (
            <div
              role="tablist"
              aria-label={t`Editor view`}
              className="flex items-center p-0.5 mr-1 rounded-lg bg-zinc-200/60 dark:bg-white/5"
            >
              {(
                [
                  { id: "map", icon: Map, label: t`Map` },
                  { id: "timeline", icon: Film, label: t`Timeline` },
                ] as const
              ).map(({ id, icon: Icon, label }) => {
                const active = editorMode === id;
                return (
                  <button
                    key={id}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    disabled={isRendering && !(isBackgroundRender && id === "timeline")}
                    onClick={() => setEditorMode(id)}
                    className={`flex items-center gap-1.5 h-6 px-2.5 rounded-md text-[12px] font-medium transition-colors disabled:opacity-50 ${
                      active
                        ? "bg-white dark:bg-zinc-800 text-navi shadow-sm"
                        : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"
                    }`}
                  >
                    <Icon className="w-3.5 h-3.5" /> {label}
                  </button>
                );
              })}
            </div>
          )}

          {currentView === "editor" && aiReady && (
            <button
              type="button"
              onClick={() => setPanelOpen(!panelOpen)}
              aria-label={t`Assistant`}
              aria-pressed={panelOpen}
              className={`${barButton} ${panelOpen ? "bg-navi/10! text-navi!" : ""}`}
            >
              <Sparkles className="w-4 h-4" />
              <Tip label={t`Assistant`} align="end" />
            </button>
          )}

          <button
            type="button"
            onClick={() => setShowAppSettings(true)}
            aria-label={t`App Settings`}
            className={`${barButton} mr-1`}
          >
            <Settings2 className="w-4 h-4" />
            <Tip label={t`App Settings`} align="end" />
          </button>

          <div className="flex h-full text-zinc-500 dark:text-zinc-400">
            <button
              type="button"
              onClick={() => handleWindow("minimize")}
              aria-label={t`Minimize`}
              className="h-full w-11 flex items-center justify-center hover:bg-black/5 hover:text-zinc-900 dark:hover:bg-white/10 dark:hover:text-white transition-colors"
            >
              <Minus className="w-4 h-4" />
            </button>
            <button
              type="button"
              onClick={() => handleWindow("maximize")}
              aria-label={t`Maximize`}
              className="h-full w-11 flex items-center justify-center hover:bg-black/5 hover:text-zinc-900 dark:hover:bg-white/10 dark:hover:text-white transition-colors"
            >
              <Square className="w-3 h-3" />
            </button>
            <button
              type="button"
              onClick={() => handleWindow("close")}
              aria-label={t`Close`}
              className="h-full w-11 flex items-center justify-center hover:bg-red-500 hover:text-white transition-colors"
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
          const target = pendingNavigation;
          setPendingNavigation(null);
          if (target) await finishPending(target);
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
            const target = pendingNavigation;
            setPendingNavigation(null);
            await finishPending(target);
          }
        }}
      />
    </>
  );
}

const barButton =
  "group/tool relative flex items-center justify-center w-8 h-7 rounded-lg text-zinc-500 hover:bg-zinc-200/70 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-white/10 dark:hover:text-zinc-100 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-navi/40 disabled:opacity-35 disabled:pointer-events-none";

function MenuItem({
  onClick,
  kbd,
  danger,
  children,
}: {
  onClick: () => void;
  kbd?: string;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={`w-full flex items-center justify-between gap-6 h-8 px-2.5 rounded-lg text-[13px] text-left text-zinc-700 dark:text-zinc-300 transition-colors ${
        danger
          ? "hover:bg-red-500/10 hover:text-red-600 dark:hover:text-red-400"
          : "hover:bg-zinc-100 dark:hover:bg-white/5"
      }`}
    >
      <span>{children}</span>
      {kbd && <span className="text-[11px] text-zinc-400 dark:text-zinc-500">{kbd}</span>}
    </button>
  );
}

function MenuSeparator() {
  return <div role="separator" className="h-px my-1 mx-1.5 bg-zinc-100 dark:bg-white/5" />;
}
