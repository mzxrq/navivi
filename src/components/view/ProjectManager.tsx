import { useState, MouseEvent } from "react";
import { convertFileSrc, invoke } from "@tauri-apps/api/core";
import { readTextFile, readDir } from "@tauri-apps/plugin-fs";
import { join, dirname } from "@tauri-apps/api/path";
import { useLingui } from "@lingui/react";
import { useUI } from "../../hooks/useUI";
import { useWorkspace } from "../../hooks/useWorkspace";
import {
  ChevronRight,
  Copy,
  Edit3,
  Film,
  Folder,
  FolderOpen,
  Globe,
  LayoutGrid,
  List,
  Map,
  MoreVertical,
  Plus,
  Settings,
  Trash2,
  UploadCloud,
} from "../ui/icons";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { ProjectSettingsModal } from "./ProjectSettingsModal";
import { AssistantChat } from "../../features/assistant/AssistantChat";
import { useAiReady } from "../../hooks/useAiReady";
import { useEnglishVoiceReady } from "../../hooks/useEnglishVoiceReady";
import { duplicateProject, listRecents, removeRecent, renameRecent } from "../../services/projectStore";
import { runStage } from "../../services/sidecar";
import { MenuEntry, openContextMenu, separator } from "../ui/menuItems";
import { Dialog, dialogButton, dialogInput } from "../ui/Dialog";
import { LanguageVersionDialog } from "./LanguageVersionDialog";

type ModalActionType = "rename" | "duplicate" | "remove" | "settings" | "version" | null;

const VIEW_MODE_KEY = "navivi_project_view";

export function ProjectManager() {
  const aiReady = useAiReady();
  const englishVoiceReady = useEnglishVoiceReady();
  const { setCurrentView, showToast } = useUI();
  const {
    loadProject,
    recentProjects,
    setRecentProjects,
    resetWorkspace,
    isProjectLoading,
  } = useWorkspace();
  const { i18n } = useLingui();

  const [viewMode, setViewModeState] = useState<"grid" | "list">(() => {
    try {
      return localStorage.getItem(VIEW_MODE_KEY) === "list" ? "list" : "grid";
    } catch {
      return "grid";
    }
  });
  const setViewMode = (mode: "grid" | "list") => {
    setViewModeState(mode);
    try {
      localStorage.setItem(VIEW_MODE_KEY, mode);
    } catch {}
  };
  const [showTemplates, setShowTemplates] = useState(false);

  // Modal States
  const [modalState, setModalState] = useState<{
    type: ModalActionType;
    project: any;
  }>({ type: null, project: null });
  const [modalInput, setModalInput] = useState("");

  const handleQuickRender = async (project: any) => {
    try {
      let configPath = project.path;
      try {
        await readDir(project.path);
        // It's a folder!
        configPath = await join(project.path, "job_config.json");
      } catch {
        // It's a file
        if (project.path.endsWith(".nvv")) {
          try {
            const fileContent = await readTextFile(project.path);
            JSON.parse(fileContent);
          } catch {
            // It might be a legacy .nvv inside a folder
            const dir = await dirname(project.path);
            const candidate = await join(dir, "job_config.json");
            try {
              const fileContent = await readTextFile(candidate);
              JSON.parse(fileContent);
              configPath = candidate;
            } catch {
              showToast(
                t`This project is archived. Please open it first to render`,
                "info",
              );
              return;
            }
          }
        }
      }

      showToast(t`Quick Render started for ` + project.name, "info");
      await runStage(configPath, "concat");
      showToast(t`Quick Render complete for ` + project.name, "success");
    } catch (err: any) {
      showToast(
        t`Could not render project directly: ` + (err?.message || err),
        "error",
      );
    }
  };

  const handleOpenProject = async (path?: string, isFolder = false) => {
    try {
      const success = await loadProject(path, isFolder);
      if (success) {
        setCurrentView("editor");
        showToast(t`Project loaded successfully`, "success");
      }
    } catch (err: any) {
      showToast(t`Failed to load project: ` + (err?.message || err), "error");
    }
  };

  const handleOpenDemo = async () => {
    try {
      const demoPath = "/defaults/demo/kyoto_demo.nvv";
      const res = await fetch(demoPath);
      const demoText = await res.text();

      const { appLocalDataDir, join } = await import("@tauri-apps/api/path");
      const { writeTextFile, mkdir } = await import("@tauri-apps/plugin-fs");

      const localDataDir = await appLocalDataDir();
      const demoFolder = await join(localDataDir, "demo");
      try {
        await mkdir(demoFolder, { recursive: true });
      } catch (e) {}

      const absoluteDemoPath = await join(demoFolder, "kyoto_demo.nvv");
      await writeTextFile(absoluteDemoPath, demoText);

      await handleOpenProject(absoluteDemoPath);
    } catch (e) {
      console.error("Failed to load demo route:", e);
      showToast(t`Failed to load demo route`, "error");
    }
  };

  const handleNewProject = () => {
    resetWorkspace();
    setCurrentView("new_project");
  };

  const openModal = (type: ModalActionType, project: any) => {
    setModalState({ type, project });
    setModalInput(
      type === "duplicate" ? `${project.name} (Copy)` : project.name,
    );
  };

  const closeModal = () => {
    setModalState({ type: null, project: null });
    setModalInput("");
  };

  const executeModalAction = async () => {
    const { type, project } = modalState;
    if (!project) return;

    try {
      if (type === "remove") {
        await removeRecent(project);
        if (setRecentProjects) {
          setRecentProjects((prev: any[]) =>
            prev.filter((p) => p.path !== project.path),
          );
        }
        showToast(t`Project removed from recent list`, "success");
      } else if (type === "rename") {
        if (!modalInput.trim() || modalInput === project.name)
          return closeModal();
        await renameRecent(project, modalInput.trim());
        if (setRecentProjects) {
          setRecentProjects((prev: any[]) =>
            prev.map((p) =>
              p.path === project.path ? { ...p, name: modalInput } : p,
            ),
          );
        }
        showToast(t`Project renamed successfully`, "success");
      } else if (type === "duplicate") {
        if (!modalInput.trim()) return closeModal();
        await duplicateProject(project, modalInput.trim());
        if (setRecentProjects) setRecentProjects(await listRecents());
        showToast(t`Project duplicated`, "success");
      }
    } catch (err) {
      if (type === "rename") {
        showToast(t`Failed to rename project`, "error");
      } else if (type === "duplicate") {
        showToast(t`Failed to duplicate project`, "error");
      } else if (type === "remove") {
        showToast(t`Failed to remove project`, "error");
      } else {
        showToast(t`Failed to update project`, "error");
      }
    }

    closeModal();
  };

  const projectMenu = (project: any): MenuEntry[] => [
    {
      label: t`Open Project`,
      icon: FolderOpen,
      onSelect: () => handleOpenProject(project.path),
    },
    separator,
    {
      label: t`Rename`,
      icon: Edit3,
      onSelect: () => openModal("rename", project),
    },
    {
      label: t`Duplicate`,
      icon: Copy,
      onSelect: () => {
        if (project.path.toLowerCase().endsWith(".nvv")) {
          showToast(t`This project is still an archive file. Open it once, then duplicate it.`, "info");
          return;
        }
        openModal("duplicate", project);
      },
    },
    ...(aiReady && englishVoiceReady
      ? [
          {
            label: t`Make a language version...`,
            icon: Globe,
            onSelect: () => {
              if (project.path.toLowerCase().endsWith(".nvv")) {
                showToast(t`This project is still an archive file. Open it once, then make a version of it.`, "info");
                return;
              }
              openModal("version", project);
            },
          },
        ]
      : []),
    {
      label: t`Project settings`,
      icon: Settings,
      onSelect: () => openModal("settings", project),
    },
    {
      label: t`Export for sharing...`,
      icon: UploadCloud,
      onSelect: () => {
        // An entry that still points at an old .nvv archive is already one file to share.
        if (project.path.toLowerCase().endsWith(".nvv")) {
          showToast(t`This project is still an archive file. Open it once, then export.`, "info");
          return;
        }
        window.dispatchEvent(new CustomEvent("export-project", { detail: { dir: project.path, name: project.name } }));
      },
    },
    separator,
    {
      label: t`Quick Render`,
      icon: Film,
      onSelect: () => handleQuickRender(project),
    },
    {
      label: t`Reveal in File Explorer`,
      icon: Folder,
      onSelect: async () => {
        try {
          await invoke("open_in_explorer", { path: project.path });
        } catch {
          showToast(t`Could not open file location`, "error");
        }
      },
    },
    separator,
    {
      label: t`Remove from List`,
      icon: Trash2,
      danger: true,
      onSelect: () => openModal("remove", project),
    },
  ];

  const openMenuFromButton = (
    e: MouseEvent<HTMLButtonElement>,
    project: any,
  ) => {
    e.stopPropagation();
    const rect = e.currentTarget.getBoundingClientRect();
    openContextMenu(
      { clientX: rect.right - 4, clientY: rect.bottom + 4 },
      projectMenu(project),
    );
  };

  const formatOpened = (value: string | number) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return { relative: "", full: "" };
    const full = date.toLocaleString(i18n.locale, {
      dateStyle: "medium",
      timeStyle: "short",
    });
    const diffSeconds = (date.getTime() - Date.now()) / 1000;
    const units: [Intl.RelativeTimeFormatUnit, number][] = [
      ["year", 31536000],
      ["month", 2592000],
      ["week", 604800],
      ["day", 86400],
      ["hour", 3600],
      ["minute", 60],
    ];
    const rtf = new Intl.RelativeTimeFormat(i18n.locale, { numeric: "auto" });
    for (const [unit, seconds] of units) {
      if (Math.abs(diffSeconds) >= seconds) {
        return {
          relative: rtf.format(Math.round(diffSeconds / seconds), unit),
          full,
        };
      }
    }
    return { relative: rtf.format(0, "minute"), full };
  };

  const projects = recentProjects || [];

  return (
    <>
      {isProjectLoading && (
        <div className="fixed inset-x-0 top-10 bottom-0 z-9999 bg-white/60 dark:bg-zinc-950/60 backdrop-blur-sm flex flex-col items-center justify-center gap-3 animate-in fade-in duration-200">
          <div className="w-8 h-8 border-[3px] border-navi/25 border-t-navi rounded-full animate-spin" />
          <p className="text-[13px] font-medium text-zinc-600 dark:text-zinc-300">
            <Trans>Reading Project File...</Trans>
          </p>
        </div>
      )}

      <div className="flex-1 min-h-0 flex flex-col w-full h-full pt-10 bg-zinc-50 dark:bg-zinc-950 relative z-10 select-none">
        <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
          <div className="max-w-6xl mx-auto px-8 max-[900px]:px-5 pt-8 pb-12">
            <header className="flex flex-wrap items-end justify-between gap-4 mb-8">
              <div>
                <h1 className="text-[22px] font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
                  <Trans>Project Manager</Trans>
                </h1>
                <p className="mt-1 text-[13px] text-zinc-500 dark:text-zinc-400">
                  <Trans>
                    Select a recent route or create a new workspace to begin
                  </Trans>
                </p>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => handleOpenProject(undefined, false)}
                  className="flex items-center gap-1.5 h-9 px-3.5 rounded-lg border border-zinc-200 dark:border-white/10 bg-white dark:bg-white/5 text-[13px] font-medium text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-white/10 transition-colors whitespace-nowrap"
                  title={t`Open a single project file (.nvv or .zip archive)`}
                >
                  <FolderOpen className="w-4 h-4 text-zinc-400" />{" "}
                  <Trans>Open File...</Trans>
                </button>
                <button
                  type="button"
                  onClick={handleNewProject}
                  className="flex items-center gap-1.5 h-9 px-3.5 rounded-lg bg-navi text-white text-[13px] font-semibold hover:brightness-110 shadow-sm transition whitespace-nowrap"
                >
                  <Plus className="w-4 h-4" /> <Trans>New Project</Trans>
                </button>
              </div>
            </header>

            {aiReady && (
              <section className="my-10 mx-auto max-w-3xl">
                <AssistantChat variant="hero" />
              </section>
            )}

            <section className="mb-8">
              <button
                type="button"
                onClick={() => setShowTemplates(!showTemplates)}
                aria-expanded={showTemplates}
                className="flex items-center gap-1 -ml-1 h-7 px-1 rounded-md text-[13px] font-semibold text-zinc-700 dark:text-zinc-200 hover:text-zinc-900 dark:hover:text-white transition-colors"
              >
                <ChevronRight
                  className={`w-4 h-4 text-zinc-400 transition-transform ${showTemplates ? "rotate-90" : ""}`}
                />
                <Trans>Templates</Trans>
              </button>
              {showTemplates && (
                <div className="mt-3 grid grid-cols-[repeat(auto-fill,minmax(15rem,1fr))] gap-4 animate-in fade-in slide-in-from-top-1 duration-150">
                  <button
                    type="button"
                    onClick={handleOpenDemo}
                    className="group flex items-center gap-3 p-3 rounded-xl border border-dashed border-zinc-300 dark:border-white/15 bg-white/60 dark:bg-white/2 text-left hover:border-navi/50 hover:bg-navi/5 transition-colors"
                  >
                    <span className="w-10 h-10 rounded-lg bg-navi/10 text-navi flex items-center justify-center shrink-0">
                      <Map className="w-5 h-5" />
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[13px] font-medium text-zinc-900 dark:text-zinc-100">
                        <Trans>Kyoto Demo Route</Trans>
                      </span>
                      <span className="block text-[12px] text-zinc-500 dark:text-zinc-400">
                        <Trans>Pre-configured sample project</Trans>
                      </span>
                    </span>
                  </button>
                </div>
              )}
            </section>

            <section>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-[13px] font-semibold text-zinc-700 dark:text-zinc-200">
                  <Trans>Recent</Trans>
                  {projects.length > 0 && (
                    <span className="ml-1.5 font-normal text-zinc-400 tabular-nums">
                      {projects.length}
                    </span>
                  )}
                </h2>
                {projects.length > 0 && (
                  <div className="flex items-center p-0.5 rounded-lg bg-zinc-200/60 dark:bg-white/5">
                    {(
                      [
                        { id: "grid", icon: LayoutGrid, label: t`Grid View` },
                        { id: "list", icon: List, label: t`Table View` },
                      ] as const
                    ).map(({ id, icon: Icon, label }) => (
                      <button
                        key={id}
                        type="button"
                        onClick={() => setViewMode(id)}
                        aria-pressed={viewMode === id}
                        title={label}
                        aria-label={label}
                        className={`flex items-center justify-center w-7 h-6 rounded-md transition-colors ${
                          viewMode === id
                            ? "bg-white dark:bg-zinc-800 text-navi shadow-sm"
                            : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"
                        }`}
                      >
                        <Icon className="w-3.5 h-3.5" />
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {projects.length === 0 ? (
                <div className="flex flex-col items-center justify-center text-center py-16 px-6 rounded-2xl border border-dashed border-zinc-300 dark:border-white/10">
                  <span className="w-11 h-11 rounded-xl bg-zinc-100 dark:bg-white/5 text-zinc-400 flex items-center justify-center mb-3">
                    <Map className="w-5 h-5" />
                  </span>
                  <h3 className="text-[14px] font-semibold text-zinc-900 dark:text-zinc-100">
                    <Trans>No recent projects</Trans>
                  </h3>
                  <p className="mt-1 max-w-sm text-[13px] text-zinc-500 dark:text-zinc-400">
                    <Trans>
                      You don't have any recent workspaces. Create a new project
                      or open an existing .nvv file to get started.
                    </Trans>
                  </p>
                </div>
              ) : viewMode === "grid" ? (
                <div className="grid grid-cols-[repeat(auto-fill,minmax(15rem,1fr))] gap-4">
                  {projects.map((project) => {
                    const opened = formatOpened(project.lastOpened);
                    return (
                      <div
                        key={project.path}
                        role="button"
                        tabIndex={0}
                        onClick={() => handleOpenProject(project.path)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter")
                            handleOpenProject(project.path);
                        }}
                        onContextMenu={(e) =>
                          openContextMenu(e, projectMenu(project))
                        }
                        className="group rounded-xl overflow-hidden bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 cursor-pointer outline-none hover:border-zinc-300 dark:hover:border-white/20 hover:shadow-md focus-visible:ring-2 focus-visible:ring-navi/40 transition"
                      >
                        <div className="relative aspect-video bg-zinc-100 dark:bg-zinc-800/60 border-b border-zinc-100 dark:border-white/5 flex items-center justify-center overflow-hidden">
                          {project.thumbnailPath ? (
                            <img
                              src={convertFileSrc(project.thumbnailPath)}
                              alt=""
                              className="absolute inset-0 w-full h-full object-cover group-hover:scale-[1.02] transition-transform duration-300"
                            />
                          ) : (
                            <Map className="w-7 h-7 text-zinc-300 dark:text-zinc-700" />
                          )}
                        </div>
                        <div className="flex items-start gap-2 pl-3.5 pr-1.5 py-3">
                          <div className="flex-1 min-w-0">
                            <h3
                              className="text-[13px] font-medium text-zinc-900 dark:text-zinc-100 truncate"
                              title={project.name}
                            >
                              {project.name}
                            </h3>
                            <p
                              className="mt-0.5 text-[12px] text-zinc-500 dark:text-zinc-400 truncate"
                              title={opened.full}
                            >
                              {opened.relative}
                            </p>
                          </div>
                          <button
                            type="button"
                            onClick={(e) => openMenuFromButton(e, project)}
                            aria-label={t`More actions`}
                            title={t`More actions`}
                            className="flex items-center justify-center w-7 h-7 rounded-lg text-zinc-400 opacity-0 group-hover:opacity-100 focus:opacity-100 hover:text-zinc-800 hover:bg-zinc-100 dark:hover:text-zinc-100 dark:hover:bg-white/5 transition"
                          >
                            <MoreVertical className="w-4 h-4" />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="rounded-xl border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-900 overflow-hidden">
                  <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)_9rem_2.5rem] max-[800px]:grid-cols-[minmax(0,1fr)_9rem_2.5rem] items-center gap-4 h-9 px-4 border-b border-zinc-200 dark:border-white/10 bg-zinc-50 dark:bg-white/2 text-[12px] font-medium text-zinc-500">
                    <span className="pl-11">
                      <Trans>Project Name</Trans>
                    </span>
                    <span className="max-[800px]:hidden">
                      <Trans>File Path</Trans>
                    </span>
                    <span>
                      <Trans>Last Opened</Trans>
                    </span>
                    <span />
                  </div>
                  <div className="divide-y divide-zinc-100 dark:divide-white/5">
                    {projects.map((project) => {
                      const opened = formatOpened(project.lastOpened);
                      return (
                        <div
                          key={project.path}
                          role="button"
                          tabIndex={0}
                          onClick={() => handleOpenProject(project.path)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter")
                              handleOpenProject(project.path);
                          }}
                          onContextMenu={(e) =>
                            openContextMenu(e, projectMenu(project))
                          }
                          className="group grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)_9rem_2.5rem] max-[800px]:grid-cols-[minmax(0,1fr)_9rem_2.5rem] items-center gap-4 h-12 px-4 cursor-pointer outline-none hover:bg-zinc-50 dark:hover:bg-white/3 focus-visible:bg-zinc-50 dark:focus-visible:bg-white/3 transition-colors"
                        >
                          <div className="flex items-center gap-3 min-w-0">
                            <span className="w-8 h-8 rounded-md overflow-hidden bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center shrink-0">
                              {project.thumbnailPath ? (
                                <img
                                  src={convertFileSrc(project.thumbnailPath)}
                                  alt=""
                                  className="w-full h-full object-cover"
                                />
                              ) : (
                                <Map className="w-4 h-4 text-zinc-400" />
                              )}
                            </span>
                            <span
                              className="text-[13px] font-medium text-zinc-900 dark:text-zinc-100 truncate"
                              title={project.name}
                            >
                              {project.name}
                            </span>
                          </div>
                          <span
                            className="max-[800px]:hidden text-[12px] text-zinc-500 dark:text-zinc-400 truncate tracking-tight"
                            title={project.path}
                          >
                            {project.path}
                          </span>
                          <span
                            className="text-[12px] text-zinc-500 dark:text-zinc-400 truncate"
                            title={opened.full}
                          >
                            {opened.relative}
                          </span>
                          <button
                            type="button"
                            onClick={(e) => openMenuFromButton(e, project)}
                            aria-label={t`More actions`}
                            title={t`More actions`}
                            className="justify-self-end flex items-center justify-center w-7 h-7 rounded-lg text-zinc-400 opacity-0 group-hover:opacity-100 focus:opacity-100 hover:text-zinc-800 hover:bg-zinc-100 dark:hover:text-zinc-100 dark:hover:bg-white/5 transition"
                          >
                            <MoreVertical className="w-4 h-4" />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </section>
          </div>
        </div>

        {modalState.type === "settings" && modalState.project && (
          <ProjectSettingsModal
            project={modalState.project}
            onClose={closeModal}
          />
        )}

        {modalState.type === "remove" && modalState.project && (
          <Dialog
            title={<Trans>Remove Project</Trans>}
            onClose={closeModal}
            footer={
              <>
                <button
                  type="button"
                  onClick={closeModal}
                  className={dialogButton.secondary}
                >
                  <Trans>Cancel</Trans>
                </button>
                <button
                  type="button"
                  onClick={executeModalAction}
                  className={dialogButton.danger}
                  autoFocus
                >
                  <Trans>Remove</Trans>
                </button>
              </>
            }
          >
            <p className="text-[13px] leading-relaxed text-zinc-600 dark:text-zinc-300">
              <Trans>
                Are you sure you want to remove{" "}
                <strong className="font-medium text-zinc-900 dark:text-zinc-100">
                  {modalState.project?.name}
                </strong>{" "}
                from your recent list? The original files will remain on your
                computer.
              </Trans>
            </p>
          </Dialog>
        )}

        {modalState.type === "version" && modalState.project && (
          <LanguageVersionDialog
            project={modalState.project}
            onClose={closeModal}
            onError={(message) => showToast(t`Could not make the version: ${message}`, "error")}
            onDone={async ({ untranslated }) => {
              if (setRecentProjects) setRecentProjects(await listRecents());
              showToast(
                untranslated > 0
                  ? t`The new version is ready. ${untranslated} texts could not be translated and are still in the old language: check them before generating.`
                  : t`The new version is ready. Read the translation, then generate it.`,
                untranslated > 0 ? "info" : "success",
              );
              closeModal();
            }}
          />
        )}

        {(modalState.type === "rename" || modalState.type === "duplicate") &&
          modalState.project && (
            <Dialog
              title={
                modalState.type === "rename" ? (
                  <Trans>Rename Project</Trans>
                ) : (
                  <Trans>Duplicate Project</Trans>
                )
              }
              subtitle={modalState.project.name}
              onClose={closeModal}
              footer={
                <>
                  <button
                    type="button"
                    onClick={closeModal}
                    className={dialogButton.secondary}
                  >
                    <Trans>Cancel</Trans>
                  </button>
                  <button
                    type="button"
                    onClick={executeModalAction}
                    disabled={!modalInput.trim()}
                    className={dialogButton.primary}
                  >
                    <Trans>Confirm</Trans>
                  </button>
                </>
              }
            >
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  if (modalInput.trim()) executeModalAction();
                }}
              >
                <label className="block mb-1.5 text-[12px] font-medium text-zinc-600 dark:text-zinc-300">
                  {modalState.type === "rename"
                    ? t`New Project Name`
                    : t`Duplicate Project Name`}
                </label>
                <input
                  type="text"
                  value={modalInput}
                  onChange={(e) => setModalInput(e.target.value)}
                  onFocus={(e) => e.currentTarget.select()}
                  className={dialogInput}
                  autoFocus
                />
              </form>
            </Dialog>
          )}
      </div>
    </>
  );
}
