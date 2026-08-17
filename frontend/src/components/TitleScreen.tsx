import { useUI } from '../hooks/useUI';
import { useWorkspace } from '../hooks/useWorkspace';
import { Map, Plus, FolderOpen, Clock } from 'lucide-react';
import { open } from '@tauri-apps/plugin-dialog';
import { readTextFile } from '@tauri-apps/plugin-fs';

export function TitleScreen() {
  const { setCurrentView } = useUI();
  const { setWaypoints } = useWorkspace();

  const handleNewProject = () => {
    setWaypoints([]);
    setCurrentView('editor');
  }

  const handleOpenProject = async () => {
    try {
        // open file browser
        const selected = await open({
            multiple: false,
            filters: [{
                name: '',
                extensions: ['json']
            }]
        });
        // user select file (didnt hit cancel)
        if (selected && typeof selected === 'string') {
            const fileContents = await readTextFile(selected);
            const data = JSON.parse(fileContents);

            // parse data
            if (data.waypoints && Array.isArray(data.waypoints)) {
                const importedWaypoints = data.waypoints.map((wp: any) => ({
                    id: wp.id || crypto.randomUUID(),
                    lat: wp.lat,
                    lng: wp.lng,
                    name: wp.label || wp.name || "Unnamed Location",
                    image: wp.popup_image || wp.image || null,
                    narration: wp.narration || "",
                    routeMode: wp.routeMode || 'driving'
                }));

                // inject global state and switch views
                setWaypoints(importedWaypoints);
                setCurrentView('editor');
            } else {
                console.error("Invalid project file format.");
            }
        }
    } catch (err) {
        console.error("Failed to open file:", err);
    }
  };

  const projects = [
    { id: 1, name: "Kyoto", date: "2 hours ago" },
    { id: 2, name: "Osaka", date: "Yesterday" },
    { id: 3, name: "Shikoku", date: "3 days ago" },
  ];

return (
    <div className="flex-1 flex flex-col bg-zinc-50 dark:bg-[#09090b] text-zinc-800 dark:text-zinc-300 overflow-y-auto p-10 transition-colors duration-300">
      
      <div className="max-w-6xl mx-auto w-full flex flex-col gap-8">
        
        {/* Header Area */}
        <div className="flex items-end justify-between">
          <div>
            <h1 className="text-3xl font-bold text-zinc-900 dark:text-zinc-100 tracking-tight mb-2">Projects</h1>
            <p className="text-sm text-zinc-500 dark:text-zinc-400">Select a recent project or create a new workspace.</p>
          </div>
          <button 
            onClick={handleOpenProject}
            className="flex items-center gap-2 px-4 py-2 bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-transparent hover:bg-zinc-100 dark:hover:bg-zinc-700 text-zinc-700 dark:text-zinc-200 rounded-lg text-sm font-medium transition-colors shadow-sm dark:shadow-none"
          >
            <FolderOpen className="w-4 h-4" /> Browse Local Files
          </button>
        </div>

        {/* Unified Project Grid */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-6">
          
          {/* Action Card: New Project */}
          <button 
            onClick={handleNewProject}
            className="group flex flex-col items-center justify-center gap-3 aspect-video bg-emerald-50 dark:bg-emerald-500/10 hover:bg-emerald-100 dark:hover:bg-emerald-500/20 border border-emerald-200 dark:border-emerald-500/20 hover:border-emerald-300 dark:hover:border-emerald-500/40 rounded-xl transition-all"
          >
            <div className="p-3 bg-emerald-500 rounded-full text-white dark:text-zinc-950 shadow-lg group-hover:scale-110 transition-transform">
              <Plus className="w-6 h-6" />
            </div>
            <span className="text-sm font-bold text-emerald-600 dark:text-emerald-500">New Project</span>
          </button>

          {/* Recent Project Cards */}
          {projects.map((proj) => (
            <div 
              key={proj.id} 
              // For now, these just open the editor. We'll wire them to actual files later.
              onClick={() => setCurrentView('editor')} 
              className="group flex flex-col cursor-pointer"
            >
              <div className="aspect-video rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 group-hover:border-zinc-300 dark:group-hover:border-zinc-600 transition-colors flex items-center justify-center mb-3 relative overflow-hidden shadow-sm dark:shadow-none">
                <Map className="w-8 h-8 text-zinc-300 dark:text-zinc-700 group-hover:text-zinc-400 dark:group-hover:text-zinc-500 transition-colors" />
                <div className="absolute top-2 right-2 flex items-center gap-1 bg-zinc-100/90 dark:bg-zinc-950/80 backdrop-blur-sm px-2 py-1 rounded text-[10px] font-medium text-zinc-600 dark:text-zinc-400">
                  <Clock className="w-3 h-3" /> {proj.date}
                </div>
              </div>
              <span className="text-sm font-medium text-zinc-800 dark:text-zinc-300 group-hover:text-zinc-900 dark:group-hover:text-zinc-100 truncate px-1">
                {proj.name}
              </span>
            </div>
          ))}

        </div>
      </div>
    </div>
  );
}