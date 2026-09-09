import { useState, useEffect, MouseEvent } from "react";
import { createPortal } from "react-dom";
import { useUI } from "../../hooks/useUI";
import { useWorkspace } from "../../hooks/useWorkspace";
import { 
  Plus, FolderOpen, Map, Clock, ChevronRight, 
  LayoutGrid, List, MoreVertical, Trash2, Copy, Edit3, Settings2, AlertTriangle
} from "../ui/icons"; 

type ModalActionType = "rename" | "duplicate" | "remove" | null;

export function TitleScreen() {
  const { setCurrentView, showToast } = useUI();
  const { loadProject, recentProjects, setRecentProjects, resetWorkspace } = useWorkspace();
  
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [activeMenu, setActiveMenu] = useState<string | null>(null);

  // Modal States
  const [modalState, setModalState] = useState<{ type: ModalActionType; project: any }>({ type: null, project: null });
  const [modalInput, setModalInput] = useState("");

  // Close dropdowns when clicking anywhere else
  useEffect(() => {
    const handleClickOutside = () => setActiveMenu(null);
    window.addEventListener("click", handleClickOutside);
    return () => window.removeEventListener("click", handleClickOutside);
  }, []);

  // Press ESC to close modals
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape" && modalState.type) {
        closeModal();
      }
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [modalState.type]);

  const handleOpenProject = async (path?: string) => {
    try {
      const success = await loadProject(path);
      if (success) {
        setCurrentView("editor");
        showToast("Project loaded successfully.", "success");
      }
    } catch (err) {
      showToast("Failed to load project file.", "error");
    }
  };

  const handleNewProject = () => {
    resetWorkspace(); 
    setCurrentView("new_project");
  };

  const toggleMenu = (e: MouseEvent, path: string) => {
    e.stopPropagation();
    setActiveMenu(activeMenu === path ? null : path);
  };

  // ✨ UPDATED: Made 'e' optional so it can be called from the global context menu
  const openModal = (type: ModalActionType, project: any, e?: MouseEvent) => {
    if (e) e.stopPropagation();
    setModalState({ type, project });
    setModalInput(type === "duplicate" ? `${project.name} (Copy)` : project.name);
    setActiveMenu(null);
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
        if (setRecentProjects) {
          setRecentProjects((prev: any[]) => prev.filter((p) => p.path !== project.path));
        }
        showToast("Project removed from recent list.", "success");
      } 
      else if (type === "rename") {
        if (!modalInput.trim() || modalInput === project.name) return closeModal();
        if (setRecentProjects) {
          setRecentProjects((prev: any[]) => 
            prev.map((p) => p.path === project.path ? { ...p, name: modalInput } : p)
          );
        }
        showToast("Project renamed successfully.", "success");
      } 
      else if (type === "duplicate") {
        if (!modalInput.trim()) return closeModal();
        showToast("Project duplicated! (Requires backend integration)", "info");
      }
    } catch (err) {
      showToast(`Failed to ${type} project.`, "error");
    }

    closeModal();
  };

  // ✨ NEW: Fire the global context menu event on Right-Click
  const handleContextMenu = (e: MouseEvent, project: any) => {
    e.preventDefault();
    e.stopPropagation();
    setActiveMenu(null); // Close any inline menus if open

    window.dispatchEvent(
      new CustomEvent("open-context-menu", {
        detail: {
          x: e.clientX,
          y: e.clientY,
          type: "project-card",
          data: {
            project,
            onOpen: () => handleOpenProject(project.path),
            onRename: () => openModal("rename", project),
            onDuplicate: () => openModal("duplicate", project),
            onSettings: () => showToast("To change settings, open the project first.", "info"),
            onRemove: () => openModal("remove", project),
          },
        },
      })
    );
  };

  const safeRecentProject = recentProjects || [];

  return (
    <div className="flex-1 flex flex-col w-full h-full p-10 bg-zinc-50 dark:bg-navidark-800 relative z-10 animate-in fade-in duration-500 select-none">
      
      {/* Top Header Bar */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-10 gap-6">
        <div>
          <h1 className="text-3xl font-extrabold text-zinc-900 dark:text-white tracking-tight">
            Project Manager
          </h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-2">
            Select a recent route or create a new workspace to begin.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex bg-zinc-200/50 dark:bg-navidark-900 rounded-lg p-0.5 border border-zinc-300 dark:border-navidark-400 shadow-inner mr-2">
            <button
              onClick={() => setViewMode("grid")}
              className={`p-1.5 rounded-md transition-all ${
                viewMode === "grid"
                  ? "bg-white dark:bg-navidark-500 text-navi shadow-sm"
                  : "text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
              }`}
              title="Grid View"
            >
              <LayoutGrid className="w-4 h-4" />
            </button>
            <button
              onClick={() => setViewMode("list")}
              className={`p-1.5 rounded-md transition-all ${
                viewMode === "list"
                  ? "bg-white dark:bg-navidark-500 text-navi shadow-sm"
                  : "text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
              }`}
              title="Table View"
            >
              <List className="w-4 h-4" />
            </button>
          </div>

          <button
            onClick={() => handleOpenProject()}
            className="flex items-center gap-2 bg-white dark:bg-navidark-700 text-zinc-700 dark:text-zinc-200 border border-zinc-200 dark:border-white/10 px-5 py-2.5 rounded-xl text-sm font-semibold hover:bg-zinc-100 dark:hover:bg-navidark-600 transition-all shadow-sm"
          >
            <FolderOpen className="w-4 h-4" /> Open File...
          </button>
          
          <button
            onClick={handleNewProject}
            className="flex items-center gap-2 bg-navi text-white px-5 py-2.5 rounded-xl text-sm font-bold hover:bg-navi/90 shadow-md hover:shadow-lg transition-all"
          >
            <Plus className="w-4 h-4" /> New Project
          </button>
        </div>
      </div>

      {/* Projects Container */}
      {safeRecentProject.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center border-2 border-dashed border-zinc-200 dark:border-white/5 rounded-3xl bg-white/50 dark:bg-navidark-700/30">
          <div className="w-16 h-16 bg-zinc-100 dark:bg-navidark-600 rounded-full flex items-center justify-center mb-4 shadow-inner">
            <Map className="w-8 h-8 text-zinc-400 dark:text-zinc-500" />
          </div>
          <h3 className="text-xl font-bold text-zinc-900 dark:text-white">No recent projects</h3>
          <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-2 max-w-sm text-center">
            You don't have any recent workspaces. Create a new project or open an existing .nvv file to get started.
          </p>
        </div>
      ) : viewMode === "grid" ? (
        
        /* Grid View */
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-2 xl:grid-cols-3 gap-5 overflow-y-auto custom-scrollbar pr-2 pb-12 pt-2 -mt-2 content-start">
          {safeRecentProject.map((project) => (
            <div
              key={project.path}
              onClick={() => handleOpenProject(project.path)}
              onContextMenu={(e) => handleContextMenu(e, project)} // ✨ Trigger global context menu
              className="group flex cursor-pointer bg-white dark:bg-navidark-700 border border-zinc-200 dark:border-white/10 rounded-2xl overflow-visible hover:border-navi dark:hover:border-navi transition-all duration-200 hover:shadow-lg"
            >
              <div className="w-1/3 min-w-30 bg-linear-to-br from-zinc-100 to-zinc-200 dark:from-navidark-600 dark:to-navidark-800 flex items-center justify-center relative overflow-hidden rounded-l-2xl shrink-0">
                <Map className="w-8 h-8 text-zinc-300 dark:text-white/5 group-hover:text-navi/30 transition-colors duration-300" />
                <div className="absolute inset-0 bg-navi/0 group-hover:bg-navi/5 transition-colors duration-300" />
              </div>
              
              <div className="p-4 w-full flex flex-col justify-center flex-1 min-w-0 border-l border-zinc-100 dark:border-white/5 relative">
                <div className="flex items-start justify-between gap-2 w-full">
                  <h3 className="font-bold text-sm text-zinc-900 dark:text-zinc-100 truncate text-left group-hover:text-navi dark:group-hover:text-navi transition-colors flex-1 pt-0.5" title={project.name}>
                    {project.name}
                  </h3>
                  
                  <div className="relative shrink-0">
                    <button 
                      onClick={(e) => toggleMenu(e, project.path)}
                      className="p-1 -mt-1 -mr-2 text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200 rounded-md hover:bg-zinc-100 dark:hover:bg-navidark-600 transition-colors relative z-20"
                    >
                      <MoreVertical className="w-4 h-4" />
                    </button>

                    {activeMenu === project.path && (
                      <div className="absolute right-0 top-full mt-1 w-48 bg-white dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-xl shadow-xl py-1.5 z-50 animate-in fade-in zoom-in-95">
                        <button onClick={(e) => { e.stopPropagation(); handleOpenProject(project.path); }} className="w-full text-left px-4 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-navidark-600 flex items-center gap-2">
                          <FolderOpen className="w-3.5 h-3.5" /> Open Project
                        </button>
                        <button onClick={(e) => openModal("rename", project, e)} className="w-full text-left px-4 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-navidark-600 flex items-center gap-2">
                          <Edit3 className="w-3.5 h-3.5" /> Rename
                        </button>
                        <button onClick={(e) => openModal("duplicate", project, e)} className="w-full text-left px-4 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-navidark-600 flex items-center gap-2">
                          <Copy className="w-3.5 h-3.5" /> Duplicate
                        </button>
                        <button onClick={(e) => { e.stopPropagation(); showToast("To change settings, open the project first.", "info"); setActiveMenu(null); }} className="w-full text-left px-4 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-navidark-600 flex items-center gap-2">
                          <Settings2 className="w-3.5 h-3.5" /> Advanced Settings
                        </button>
                        <div className="h-px bg-zinc-200 dark:bg-navidark-400 my-1 mx-2" />
                        <button onClick={(e) => openModal("remove", project, e)} className="w-full text-left px-4 py-2 text-xs font-semibold text-red-600 hover:bg-red-50 dark:hover:bg-red-500/10 flex items-center gap-2">
                          <Trash2 className="w-3.5 h-3.5" /> Remove from list
                        </button>
                      </div>
                    )}
                  </div>
                </div>
                
                <div className="flex items-center gap-2 mt-4 text-[11px] font-medium text-zinc-500 dark:text-zinc-400 bg-zinc-50 dark:bg-navidark-800 w-fit px-2 py-1 rounded-md pointer-events-none">
                  <Clock className="w-3 h-3" />
                  <span>{new Date(project.lastOpened).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (

        /* Table/List View */
        <div className="flex flex-col border border-zinc-200 dark:border-navidark-400 bg-white dark:bg-navidark-700 rounded-xl shadow-sm overflow-hidden mb-12">
          <div className="grid grid-cols-12 gap-4 px-5 py-3 bg-zinc-50 dark:bg-navidark-800 border-b border-zinc-200 dark:border-navidark-400 text-xs font-bold text-zinc-500 uppercase tracking-wider">
            <div className="col-span-9 sm:col-span-4 pl-8">Project Name</div>
            <div className="col-span-5 hidden sm:block">File Path</div>
            <div className="col-span-2 hidden sm:block text-right pr-4">Last Opened</div>
            <div className="col-span-3 sm:col-span-1 text-right">Actions</div>
          </div>

          <div className="flex flex-col overflow-y-auto custom-scrollbar max-h-[60vh]">
            {safeRecentProject.map((project, index) => (
              <div
                key={project.path}
                onClick={() => handleOpenProject(project.path)} // ✨ Make entire list row clickable
                onContextMenu={(e) => handleContextMenu(e, project)} // ✨ Context menu for list view
                className={`group cursor-pointer grid grid-cols-12 gap-4 items-center px-5 py-3 hover:bg-zinc-50 dark:hover:bg-navidark-600 transition-colors text-left ${
                  index !== safeRecentProject.length - 1 ? "border-b border-zinc-100 dark:border-white/5" : ""
                }`}
              >
                <div className="col-span-9 sm:col-span-4 flex items-center gap-3 min-w-0 pointer-events-none text-left">
                  <Map className="w-4 h-4 text-zinc-400 shrink-0 group-hover:text-navi transition-colors" />
                  <span className="font-bold text-sm text-zinc-900 dark:text-zinc-100 truncate group-hover:text-navi transition-colors">
                    {project.name}
                  </span>
                </div>
                
                <div className="col-span-5 hidden sm:flex items-center min-w-0 pointer-events-none">
                  <span className="text-xs text-zinc-500 dark:text-zinc-400 truncate w-full" title={project.path}>
                    {project.path}
                  </span>
                </div>
                
                <div className="col-span-2 hidden sm:flex items-center justify-end text-xs font-medium text-zinc-500 dark:text-zinc-400 pr-4 pointer-events-none">
                  {new Date(project.lastOpened).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}
                </div>
                
                <div className="col-span-3 sm:col-span-1 flex items-center justify-end relative">
                  <button 
                    onClick={(e) => toggleMenu(e, project.path)}
                    className="p-1.5 text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200 rounded-md hover:bg-zinc-200 dark:hover:bg-navidark-500 transition-colors relative z-20"
                  >
                    <MoreVertical className="w-4 h-4" />
                  </button>

                  {activeMenu === project.path && (
                    <div className="absolute right-6 top-6 w-48 bg-white dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-xl shadow-xl py-1.5 z-50 animate-in fade-in zoom-in-95">
                        <button onClick={(e) => { e.stopPropagation(); handleOpenProject(project.path); }} className="w-full text-left px-4 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-navidark-600 flex items-center gap-2">
                          <FolderOpen className="w-3.5 h-3.5" /> Open Project
                        </button>
                        <button onClick={(e) => openModal("rename", project, e)} className="w-full text-left px-4 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-navidark-600 flex items-center gap-2">
                          <Edit3 className="w-3.5 h-3.5" /> Rename
                        </button>
                        <button onClick={(e) => openModal("duplicate", project, e)} className="w-full text-left px-4 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-navidark-600 flex items-center gap-2">
                          <Copy className="w-3.5 h-3.5" /> Duplicate
                        </button>
                        <div className="h-px bg-zinc-200 dark:bg-navidark-400 my-1 mx-2" />
                        <button onClick={(e) => openModal("remove", project, e)} className="w-full text-left px-4 py-2 text-xs font-semibold text-red-600 hover:bg-red-50 dark:hover:bg-red-500/10 flex items-center gap-2">
                          <Trash2 className="w-3.5 h-3.5" /> Remove from list
                        </button>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* SLEEK ACTION MODALS */}
      {modalState.type && createPortal(
        <div className="fixed inset-0 z-99999 bg-zinc-950/40 backdrop-blur-[2px] flex items-center justify-center p-4 animate-in fade-in duration-200">
          <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 rounded-2xl shadow-2xl w-full max-w-sm overflow-hidden animate-in zoom-in-95 duration-200">
            <div className="p-5">
              <h3 className="text-base font-bold text-zinc-900 dark:text-white mb-2 flex items-center gap-2">
                {modalState.type === "remove" && <><AlertTriangle className="w-4 h-4 text-red-500" /> Remove Project</>}
                {modalState.type === "rename" && <><Edit3 className="w-4 h-4 text-navi-500" /> Rename Project</>}
                {modalState.type === "duplicate" && <><Copy className="w-4 h-4 text-navi-500" /> Duplicate Project</>}
              </h3>
              
              {modalState.type === "remove" ? (
                <p className="text-xs text-zinc-500 dark:text-zinc-400 leading-relaxed">
                  Are you sure you want to remove <strong className="text-zinc-800 dark:text-zinc-200">{modalState.project?.name}</strong> from your recent list? The original files will remain on your computer.
                </p>
              ) : (
                <div className="space-y-3 mt-4">
                  <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                    {modalState.type === "rename" ? "New Project Name" : "Duplicate Project Name"}
                  </label>
                  <input
                    type="text"
                    value={modalInput}
                    onChange={(e) => setModalInput(e.target.value)}
                    className="w-full bg-zinc-50 dark:bg-navidark-800 border border-zinc-200 dark:border-navidark-400 rounded-lg px-3 py-2 text-sm text-zinc-900 dark:text-white outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
                    autoFocus
                  />
                </div>
              )}
            </div>
            
            <div className="p-4 bg-zinc-50 dark:bg-black/20 border-t border-zinc-100 dark:border-white/5 flex items-center justify-end gap-3">
              <button
                onClick={closeModal}
                className="px-4 py-2 text-xs font-bold text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={executeModalAction}
                disabled={modalState.type !== "remove" && !modalInput.trim()}
                className={`px-4 py-2 text-white text-xs font-bold rounded-lg shadow-md transition-colors disabled:opacity-50 ${
                  modalState.type === "remove" 
                    ? "bg-red-500 hover:bg-red-600" 
                    : "bg-navi hover:bg-navi-600"
                }`}
              >
                {modalState.type === "remove" ? "Remove" : "Confirm"}
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}