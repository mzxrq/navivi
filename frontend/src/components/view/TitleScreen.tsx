import { useUI } from "../../hooks/useUI";
import { useWorkspace } from "../../hooks/useWorkspace";
import { Plus, FolderOpen, Map, Clock } from "lucide-react";

export function TitleScreen() {
  const { setCurrentView, showToast } = useUI();
  const { loadProject, recentProject, resetWorkspace } = useWorkspace(); // <-- Extract resetWorkspace

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
    resetWorkspace(); // Wipe the slate clean
    setCurrentView("new_project");
  };

  // Safe fallback if recentProjects is undefined due to context errors
  const safeRecentProject = recentProject || [];

return (
    <div className="flex-1 flex flex-col w-full h-full p-8 relative z-10 animate-in fade-in duration-300">
      
      {/* Top Header Bar */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-8 gap-4">
        <div>
          <h1 className="text-2xl font-bold text-zinc-900 dark:text-white tracking-tight">
            Project Manager
          </h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-1">
            Select a project or create a new one to begin.
          </p>
        </div>

        <div className="flex gap-3">
          <button
            onClick={() => handleOpenProject()}
            className="flex items-center gap-2 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-white border border-zinc-200 dark:border-white/10 px-4 py-2 rounded-lg text-sm font-semibold hover:bg-zinc-50 dark:hover:bg-white/5 transition-colors"
          >
            <FolderOpen className="w-4 h-4" /> Open...
          </button>
          
          <button
            onClick={handleNewProject}
            className="flex items-center gap-2 bg-emerald-500 text-white px-4 py-2 rounded-lg text-sm font-bold hover:bg-emerald-600 shadow-sm transition-colors"
          >
            <Plus className="w-4 h-4" /> New Project
          </button>
        </div>
      </div>

      {/* Projects Grid */}
      {safeRecentProject.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center border-2 border-dashed border-zinc-200 dark:border-zinc-800 rounded-2xl">
          <Map className="w-12 h-12 text-zinc-300 dark:text-zinc-700 mb-4" />
          <h3 className="text-lg font-bold text-zinc-900 dark:text-white">No recent projects</h3>
          <p className="text-sm text-zinc-500 mt-1">Create a new project or open an existing .nvv file.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-6 overflow-y-auto custom-scrollbar p-2 -m-2 pb-12 content-start">
          {safeRecentProject.map((project) => (
            <button
              key={project.path}
              onClick={() => handleOpenProject(project.path)}
              className="group flex flex-col text-left bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/5 rounded-xl overflow-hidden hover:border-emerald-500 dark:hover:border-emerald-500 transition-all hover:shadow-lg hover:-translate-y-1 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            >
              {/* Thumbnail Area (16:9 Aspect Ratio) */}
              <div className="w-full aspect-video bg-zinc-100 dark:bg-zinc-950 flex items-center justify-center relative overflow-hidden">
                <Map className="w-8 h-8 text-zinc-300 dark:text-zinc-800 group-hover:scale-110 transition-transform duration-500" />
                <div className="absolute inset-0 bg-gradient-to-t from-black/20 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
              </div>
              
              {/* Metadata Area */}
              <div className="p-4 w-full">
                <h3 className="font-bold text-zinc-900 dark:text-zinc-100 truncate w-full">
                  {project.name}
                </h3>
                <div className="flex items-center gap-1.5 mt-2 text-xs text-zinc-500 dark:text-zinc-400">
                  <Clock className="w-3 h-3" />
                  <span>{new Date(project.lastOpened).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}</span>
                </div>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}