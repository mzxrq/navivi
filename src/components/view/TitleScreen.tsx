import { useState } from "react";
import { useUI } from "../../hooks/useUI";
import { useWorkspace } from "../../hooks/useWorkspace";
import { Plus, FolderOpen, Map, Clock, ChevronRight, LayoutGrid, List } from "../ui/icons"; 

export function TitleScreen() {
  const { setCurrentView, showToast } = useUI();
  const { loadProject, recentProjects, resetWorkspace } = useWorkspace();
  
  // ✨ Add state to track our current view mode
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");

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
          {/* ✨ View Mode Toggle */}
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
              title="List View"
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
            className="flex items-center gap-2 bg-navi text-white px-5 py-2.5 rounded-xl text-sm font-bold hover:bg-navi/90 shadow-md hover:shadow-lg hover:-translate-y-0.5 transition-all"
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
        /* ✨ Grid View */
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6 overflow-y-auto custom-scrollbar pr-2 pb-12 content-start">
          {safeRecentProject.map((project) => (
            <button
              key={project.path}
              onClick={() => handleOpenProject(project.path)}
              className="group flex flex-col text-left bg-white dark:bg-navidark-700 border border-zinc-200 dark:border-white/10 rounded-2xl overflow-hidden hover:border-navi dark:hover:border-navi transition-all duration-300 hover:shadow-xl hover:-translate-y-1 focus:outline-none focus:ring-2 focus:ring-navi focus:ring-offset-2 dark:focus:ring-offset-navidark-800"
            >
              <div className="w-full h-24 bg-gradient-to-br from-zinc-100 to-zinc-200 dark:from-navidark-600 dark:to-navidark-800 flex items-center justify-center relative overflow-hidden">
                <Map className="w-12 h-12 text-zinc-300 dark:text-white/5 group-hover:scale-110 group-hover:text-navi/20 transition-all duration-500" />
                <div className="absolute inset-0 bg-navi/0 group-hover:bg-navi/5 transition-colors duration-300" />
              </div>
              
              <div className="p-5 w-full bg-white dark:bg-navidark-700 flex flex-col justify-between flex-1">
                <div className="w-full flex items-center justify-between gap-4">
                  <h3 className="font-bold text-base text-zinc-900 dark:text-zinc-100 truncate">
                    {project.name}
                  </h3>
                  <ChevronRight className="w-4 h-4 text-zinc-300 dark:text-zinc-600 group-hover:text-navi transition-colors shrink-0" />
                </div>
                
                <div className="flex items-center gap-2 mt-3 text-xs font-medium text-zinc-500 dark:text-zinc-400 bg-zinc-50 dark:bg-navidark-800 w-fit px-2.5 py-1 rounded-md">
                  <Clock className="w-3.5 h-3.5" />
                  <span>{new Date(project.lastOpened).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}</span>
                </div>
              </div>
            </button>
          ))}
        </div>
      ) : (
        /* ✨ List View */
        <div className="flex flex-col gap-3 overflow-y-auto custom-scrollbar pr-2 pb-12">
          {safeRecentProject.map((project) => (
            <button
              key={project.path}
              onClick={() => handleOpenProject(project.path)}
              className="group flex items-center justify-between p-4 bg-white dark:bg-navidark-700 border border-zinc-200 dark:border-white/10 rounded-2xl hover:border-navi dark:hover:border-navi transition-all duration-300 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-navi focus:ring-offset-2 dark:focus:ring-offset-navidark-800"
            >
              <div className="flex items-center gap-4 min-w-0">
                <div className="w-12 h-12 bg-zinc-100 dark:bg-navidark-600 rounded-xl flex items-center justify-center shrink-0">
                  <Map className="w-5 h-5 text-zinc-400 dark:text-zinc-500 group-hover:text-navi transition-colors" />
                </div>
                <div className="flex flex-col items-start truncate">
                  <span className="font-bold text-zinc-900 dark:text-zinc-100 truncate w-full text-left">
                    {project.name}
                  </span>
                  <span className="text-xs text-zinc-500 dark:text-zinc-400 truncate w-full text-left mt-0.5">
                    {project.path}
                  </span>
                </div>
              </div>
              
              <div className="flex items-center gap-6 shrink-0 pl-4">
                <div className="flex items-center gap-2 text-xs font-medium text-zinc-500 dark:text-zinc-400 bg-zinc-50 dark:bg-navidark-800 px-3 py-1.5 rounded-md hidden sm:flex">
                  <Clock className="w-3.5 h-3.5" />
                  <span>{new Date(project.lastOpened).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}</span>
                </div>
                <ChevronRight className="w-5 h-5 text-zinc-300 dark:text-zinc-600 group-hover:text-navi transition-colors" />
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}