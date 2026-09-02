import { useState } from "react";
import { useWorkspace } from "../../hooks/useWorkspace";
import { useUI } from "../../hooks/useUI";
import { FolderPlus, MapPin, Monitor, ChevronRight, Clock } from "../ui/icons";

const startingLocations = [
  { id: "osaka", name: "Osaka, Japan", coords: [34.6937, 135.5023] },
  { id: "tokyo", name: "Tokyo, Japan", coords: [35.6762, 139.6503] },
];

export function NewProject() {
  const { setCurrentView } = useUI();
  const { updateMetadata, updateSettings, resetWorkspace } = useWorkspace();

  const [projectName, setProjectName] = useState("Untitled Project");
  const [location, setLocation] = useState(startingLocations[0].id);
  const [resolution, setResolution] = useState("1080p");
  const [fps, setFps] = useState(30);

  const handleCreate = () => {
    resetWorkspace();
    const selectedLoc = startingLocations.find((loc) => loc.id === location);
    const coords = selectedLoc ? selectedLoc.coords : [34.6937, 135.5023];

    updateMetadata({
      project_name: projectName,
      project_id: "",
      status: "initialized",
    });

    updateSettings({
      start_coords: coords as [number, number],
      resolution: resolution,
      fps: fps,
    });
    
    setCurrentView("editor");
  };

  return (
    <div className="fixed inset-0 z-100 flex items-center justify-center bg-black/60 animate-in fade-in duration-200">
      <div className="w-full max-w-120 bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-white/10 rounded-2xl shadow-xl p-8 animate-in fade-in zoom-in-95 duration-300">
        <div className="flex items-center gap-3 mb-8">
          <div className="w-10 h-10 rounded-xl bg-emerald-50 dark:bg-emerald-500/10 flex items-center justify-center border border-emerald-200 dark:border-emerald-500/20">
            <FolderPlus className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-zinc-900 dark:text-white tracking-tight">
              Create New Project
            </h2>
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              Setup your map canvas and video output
            </p>
          </div>
        </div>

        <div className="space-y-6">
          {/* Project Name */}
          <div className="space-y-2">
            <label className="text-[11px] font-bold text-zinc-500 uppercase tracking-widest flex items-center gap-1.5">
              Project Name
            </label>
            <input
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              className="w-full bg-zinc-50 dark:bg-zinc-900/50 border border-zinc-200 dark:border-white/10 rounded-xl px-3 py-2.5 text-sm font-medium text-zinc-900 dark:text-zinc-200 outline-none focus:border-emerald-500 dark:focus:border-emerald-500 transition-colors"
              placeholder="e.g. My Osaka Trip"
            />
          </div>

          {/* Starting Location */}
          <div className="space-y-2">
            <label className="text-[11px] font-bold text-zinc-500 uppercase tracking-widest flex items-center gap-1.5">
              <MapPin className="w-3.5 h-3.5" /> Starting Location
            </label>
            <select
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              className="w-full bg-zinc-50 dark:bg-zinc-900/50 border border-zinc-200 dark:border-white/10 rounded-xl px-3 py-2.5 text-sm font-medium text-zinc-900 dark:text-zinc-200 outline-none focus:border-emerald-500 dark:focus:border-emerald-500 transition-colors cursor-pointer appearance-none"
            >
              {startingLocations.map((loc) => (
                <option key={loc.id} value={loc.id}>
                  {loc.name}
                </option>
              ))}
            </select>
          </div>

          {/* Output Resolution */}
          <div className="space-y-2">
            <label className="text-[11px] font-bold text-zinc-500 uppercase tracking-widest flex items-center gap-1.5">
              <Monitor className="w-3.5 h-3.5" /> Output Resolution
            </label>
            <div className="grid grid-cols-3 gap-3">
              {[
                { id: "720p", label: "720p", sub: "Fastest" },
                { id: "1080p", label: "1080p", sub: "Standard" },
                { id: "4k", label: "4K", sub: "Highest Quality" },
              ].map((res) => (
                <button
                  key={res.id}
                  onClick={() => setResolution(res.id)}
                  className={`flex flex-col items-center justify-center p-3 rounded-xl border transition-all ${
                    resolution === res.id
                      ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                      : "border-zinc-200 dark:border-white/10 bg-zinc-50 dark:bg-zinc-900/50 text-zinc-600 dark:text-zinc-400 hover:border-zinc-300 dark:hover:border-zinc-700"
                  }`}
                >
                  <span className="text-sm font-bold">{res.label}</span>
                  <span className="text-[9px] font-medium uppercase tracking-wider opacity-70">
                    {res.sub}
                  </span>
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-[11px] font-bold text-zinc-500 uppercase tracking-widest flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5" /> Default FPS
            </label>
            <div className="flex flex-col gap-2">
              {[
                { val: 24, label: "Cinematic" },
                { val: 30, label: "Standard" },
                { val: 60, label: "Smooth" },
              ].map((f) => (
                <button
                  key={f.val}
                  onClick={() => setFps(f.val)}
                  className={`flex items-center justify-between p-2.5 rounded-xl border transition-all ${
                    fps === f.val
                      ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                      : "border-zinc-200 dark:border-white/10 bg-zinc-50 dark:bg-zinc-900/50 text-zinc-600 dark:text-zinc-400 hover:border-zinc-300 dark:hover:border-zinc-700"
                  }`}
                >
                  <span className="text-sm font-bold">{f.val}</span>
                  <span className="text-[9px] font-medium uppercase tracking-wider opacity-70">
                    {f.label}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-8 pt-6 border-t border-zinc-200 dark:border-white/5 flex justify-end gap-3">
          <button
            onClick={() => setCurrentView("title_screen")}
            className="px-4 py-2 text-xs font-semibold text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-300 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            className="px-5 py-2 rounded-xl bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 text-xs font-bold hover:scale-105 active:scale-95 transition-all flex items-center gap-2 shadow-md"
          >
            Start Editing <ChevronRight className="w-3.5 h-3.5 opacity-70" />
          </button>
        </div>
      </div>
    </div>
  );
}
