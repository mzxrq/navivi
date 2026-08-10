import { useState } from 'react';
import { open } from '@tauri-apps/plugin-dialog';
import { MapPin, Layers, ChevronRight, X, Edit2, ChevronLeft, Image as ImageIcon, Mic, Trash2 } from 'lucide-react';
import { useWorkspace } from '../hooks/useWorkspace';

export function Sidebar() {
  const { routeFile, waypoints, setWaypoints, updateWaypoint } = useWorkspace();
  const [editingId, setEditingId] = useState<string | null>(null);

  const handleRenderVideo = () => {
    if (!confirm("Ready to render? This will generate the configuration for the backend.")) return;
    const jobConfig = { project_name: "GPS_Studio_Export", source_files: { gps_route: routeFile }, waypoints };
    console.log(JSON.stringify(jobConfig, null, 2));
    alert("Config generated! Check DevTools console.");
  };

  const handleClearAll = () => {
    if (confirm("Are you sure you want to clear all waypoints? This cannot be undone.")) {
      setWaypoints([]);
    }
  };

  const handleImageSelect = async (id: string) => {
    const selectedPath = await open({
      multiple: false,
      filters: [{ name: 'Images', extensions: ['png', 'jpg', 'jpeg'] }]
    });
    if (typeof selectedPath === 'string') {
      updateWaypoint(id, { image: selectedPath });
    }
  };

  // --- EDIT MODE VIEW ---
  if (editingId) {
    const wp = waypoints.find(w => w.id === editingId);
    if (!wp) return null;

    return (
      <aside className="w-[340px] bg-zinc-950 border-r border-white/[0.08] flex flex-col p-6 h-full select-none z-10 relative shadow-2xl gap-6">
        <div className="flex-1 flex flex-col min-h-0 space-y-6">
          <button onClick={() => setEditingId(null)} className="flex items-center gap-2 text-xs font-semibold text-zinc-500 hover:text-zinc-300 transition-colors w-fit">
            <ChevronLeft className="w-4 h-4" /> Back to List
          </button>

          <div className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-[11px] font-bold text-zinc-500 uppercase tracking-widest px-1">Location Name</label>
              <input 
                type="text" 
                value={wp.name}
                onChange={(e) => updateWaypoint(wp.id, { name: e.target.value })}
                className="w-full bg-zinc-900/50 border border-white/10 rounded-xl px-3 py-2 text-sm text-zinc-200 outline-none focus:border-zinc-500 transition-colors"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-[11px] font-bold text-zinc-500 uppercase tracking-widest px-1 flex items-center gap-1.5">
                <Mic className="w-3.5 h-3.5" /> AI Script
              </label>
              <textarea 
                value={wp.narration}
                onChange={(e) => updateWaypoint(wp.id, { narration: e.target.value })}
                placeholder="Type what the AI voice should say here..."
                className="w-full bg-zinc-900/50 border border-white/10 rounded-xl px-3 py-2 text-sm text-zinc-200 outline-none focus:border-zinc-500 transition-colors resize-none h-24 custom-scrollbar"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-[11px] font-bold text-zinc-500 uppercase tracking-widest px-1 flex items-center gap-1.5">
                <ImageIcon className="w-3.5 h-3.5" /> Pop-up Picture
              </label>
              <button 
                onClick={() => handleImageSelect(wp.id)}
                className="w-full bg-zinc-900/50 hover:bg-zinc-800/80 border border-white/10 border-dashed rounded-xl px-3 py-3 text-xs font-medium text-zinc-400 hover:text-zinc-200 transition-all flex items-center justify-center gap-2 truncate"
              >
                {wp.image ? <span className="truncate max-w-[200px]" title={wp.image}>Selected: {wp.image.split('\\').pop()}</span> : "Click to browse local files..."}
              </button>
            </div>
          </div>
        </div>

        {/* Safer Delete Button */}
        <div className="shrink-0">
          <button 
            onClick={() => {
              if (confirm(`Remove ${wp.name}?`)) {
                setWaypoints(waypoints.filter(w => w.id !== wp.id));
                setEditingId(null);
              }
            }}
            className="w-full py-2.5 rounded-xl border border-transparent text-zinc-500 text-xs font-semibold hover:border-red-500/20 hover:text-red-400 hover:bg-red-500/5 transition-all flex justify-center items-center gap-2"
          >
            <Trash2 className="w-4 h-4" /> Remove Waypoint
          </button>
        </div>
      </aside>
    );
  }

  // --- STANDARD LIST VIEW ---
  return (
    <aside className="w-[340px] bg-zinc-950 border-r border-white/[0.08] flex flex-col p-6 h-full select-none z-10 relative shadow-2xl gap-6">
      
      {/* Header */}
      <div className="shrink-0 flex items-center gap-3.5">
        <div className="w-10 h-10 rounded-xl bg-zinc-900 flex items-center justify-center border border-white/5 shadow-sm">
          <MapPin className="w-5 h-5 text-zinc-300" />
        </div>
        <div>
          <h1 className="text-base font-semibold text-zinc-200 tracking-tight">Project Config</h1>
          <p className="text-[10px] text-zinc-500 font-medium tracking-widest uppercase">Workspace Settings</p>
        </div>
      </div>

      {/* Dynamic Waypoints List (Flex-1 ensures it scrolls properly) */}
      <div className="flex-1 flex flex-col min-h-0 space-y-3">
        <div className="flex justify-between items-center px-1 shrink-0">
          <h2 className="text-[11px] font-bold text-zinc-500 uppercase tracking-widest flex items-center gap-2">
            <Layers className="w-3.5 h-3.5" /> Waypoints ({waypoints.length})
          </h2>
          {waypoints.length > 0 && (
            <button onClick={handleClearAll} className="text-[10px] font-semibold text-zinc-500 hover:text-red-400 transition-colors">
              Clear All
            </button>
          )}
        </div>

        {waypoints.length === 0 ? (
          <div className="group rounded-2xl border border-dashed border-zinc-800 bg-zinc-900/20 p-8 text-center shrink-0">
            <p className="text-sm font-medium text-zinc-500">Click the map to drop markers</p>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto pr-2 custom-scrollbar space-y-2">
            {waypoints.map((wp, i) => (
              <div key={wp.id} className="flex items-center justify-between bg-zinc-900/30 border border-white/5 p-2.5 rounded-xl group hover:bg-zinc-900/80 transition-colors">
                <div className="flex items-center gap-2.5 overflow-hidden">
                  <div className="w-6 h-6 rounded-md bg-zinc-800/50 text-zinc-500 flex items-center justify-center text-xs font-bold shrink-0 group-hover:text-zinc-300 transition-colors">
                    {i + 1}
                  </div>
                  <div className="flex flex-col">
                    <span className="text-xs font-medium text-zinc-300 truncate max-w-[150px]" title={wp.name}>{wp.name}</span>
                    <div className="flex gap-1.5 mt-0.5">
                      {wp.image && <ImageIcon className="w-3 h-3 text-zinc-500" />}
                      {wp.narration && <Mic className="w-3 h-3 text-zinc-500" />}
                    </div>
                  </div>
                </div>
                <div className="opacity-0 group-hover:opacity-100 flex items-center gap-1 transition-all">
                  <button onClick={() => setEditingId(wp.id)} className="p-1.5 hover:bg-zinc-800 hover:text-white text-zinc-500 rounded-md transition-all">
                    <Edit2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Subdued Render Button */}
      <div className="shrink-0 pt-2">
        <button 
          onClick={handleRenderVideo} 
          className="w-full flex items-center justify-center gap-2 py-3 px-4 rounded-xl bg-zinc-900 hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 border border-white/5 hover:border-white/10 font-medium text-sm transition-all disabled:opacity-40 disabled:pointer-events-none" 
          disabled={waypoints.length === 0}
        >
          Render Video
          <ChevronRight className="w-4 h-4 opacity-50" />
        </button>
      </div>

    </aside>
  );
}