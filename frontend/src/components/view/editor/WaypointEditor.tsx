import { ChevronLeft, Mic, Image as ImageIcon, X, Trash2 } from "lucide-react";
import { ScrubInput } from "../../ui/ScrubInput";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useUI } from "../../../hooks/useUI";
import { open } from "@tauri-apps/plugin-dialog";

export function WaypointEditor({ wpId, onClose }: { wpId: string; onClose: () => void }) {
  const { waypoints, setWaypoints, updateWaypoint, settings } = useWorkspace();
  const { showToast } = useUI();
  
  const wp = waypoints.find((w) => w.id === wpId);
  if (!wp) return null;
  
  const wpImages = wp.images || [];

  const handleImageSelect = async () => {
    if (wpImages.length >= 3) {
      showToast("Maximum of 3 images allowed per waypoint.", "error");
      return;
    }
    const selectedPaths = await open({
      multiple: true,
      filters: [{ name: "Images", extensions: ["png", "jpg", "jpeg"] }],
    });
    if (selectedPaths) {
      const pathsArray = Array.isArray(selectedPaths) ? selectedPaths : [selectedPaths];
      const newImages = [...wpImages, ...pathsArray].slice(0, 3);
      updateWaypoint(wp.id, { images: newImages });
    }
  };

  return (
    <aside className="w-85 shrink-0 bg-white dark:bg-zinc-950 border-r border-zinc-200 dark:border-white/8 flex flex-col p-6 h-full select-none z-10 relative shadow-xl transition-colors gap-6">
      <div className="flex-1 flex flex-col min-h-0 space-y-6 overflow-y-auto custom-scrollbar pr-2">
        <button onClick={onClose} className="flex items-center gap-2 text-xs font-semibold text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-300 transition-colors w-fit shrink-0">
          <ChevronLeft className="w-4 h-4" /> Back to List
        </button>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-[11px] font-bold text-zinc-500 uppercase tracking-widest px-1">Location Name</label>
            <input
              type="text"
              value={wp.name}
              onChange={(e) => updateWaypoint(wp.id, { name: e.target.value })}
              className="w-full bg-zinc-50 dark:bg-zinc-900/50 border border-zinc-200 dark:border-white/10 rounded-xl px-3 py-2 text-sm text-zinc-900 dark:text-zinc-200 outline-none focus:border-zinc-400 dark:focus:border-zinc-500 transition-colors"
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
              className="w-full bg-zinc-50 dark:bg-zinc-900/50 border border-zinc-200 dark:border-white/10 rounded-xl px-3 py-2 text-sm text-zinc-900 dark:text-zinc-200 outline-none focus:border-zinc-400 dark:focus:border-zinc-500 transition-colors resize-none h-24 custom-scrollbar"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-[11px] font-bold text-zinc-500 uppercase tracking-widest px-1 flex items-center gap-1.5">
              <ImageIcon className="w-3.5 h-3.5" /> Pop-up Pictures ({wpImages.length}/3)
            </label>
            
            <div className="flex flex-col gap-2">
              {wpImages.map((img, idx) => (
                <div key={idx} className="flex items-center justify-between bg-zinc-50 dark:bg-zinc-900/50 border border-zinc-200 dark:border-white/10 rounded-lg px-3 py-2 text-xs text-zinc-600 dark:text-zinc-400">
                  <span className="truncate max-w-200px" title={img}>{img.split(/[/\\]/).pop()}</span>
                  <button onClick={() => updateWaypoint(wp.id, { images: wpImages.filter((_, i) => i !== idx) })} className="text-red-500 hover:text-red-600 transition-colors">
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))}
              
              {wpImages.length < 3 && (
                <button onClick={handleImageSelect} className="w-full bg-zinc-50 dark:bg-zinc-900/50 hover:bg-zinc-100 dark:hover:bg-zinc-800/80 border border-zinc-300 dark:border-white/10 border-dashed rounded-xl px-3 py-3 text-xs font-medium text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200 transition-all flex items-center justify-center gap-2">
                  Click to add images...
                </button>
              )}

              {wpImages.length > 0 && (
                <div className="flex gap-2 mt-1">
                  <button onClick={() => updateWaypoint(wp.id, { imageDisplay: "pip" })} className={`flex-1 py-1.5 text-[10px] font-bold uppercase tracking-wider rounded-md transition-all ${wp.imageDisplay !== "fullscreen" ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20" : "bg-zinc-100 dark:bg-zinc-800/50 text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"}`}>PIP Overlay</button>
                  <button onClick={() => updateWaypoint(wp.id, { imageDisplay: "fullscreen" })} className={`flex-1 py-1.5 text-[10px] font-bold uppercase tracking-wider rounded-md transition-all ${wp.imageDisplay === "fullscreen" ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20" : "bg-zinc-100 dark:bg-zinc-800/50 text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"}`}>Fullscreen</button>
                </div>
              )}
            </div>
          </div>
          
          <div className="space-y-3 pt-4 border-t border-zinc-200 dark:border-white/10">
            <h4 className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">Timing & FPS Override</h4>
            <div className="space-y-2">
              <ScrubInput label="Hold Duration" value={wp.duration || settings.duration_seconds} onChange={(v) => updateWaypoint(wp.id, { duration: v })} min={1} max={15} step={0.5} suffix="s" />
              <ScrubInput label="Frame Rate" value={wp.fps || settings.fps} onChange={(v) => updateWaypoint(wp.id, { fps: v })} min={1} max={60} step={1} suffix=" FPS" />
            </div>
          </div>
        </div>
      </div>

      <div className="shrink-0 pt-2 border-t border-zinc-200 dark:border-white/10">
        <button onClick={() => { if (confirm(`Remove ${wp.name}?`)) { setWaypoints(waypoints.filter((w) => w.id !== wp.id)); onClose(); } }} className="w-full py-2.5 rounded-xl border border-transparent text-zinc-500 dark:text-zinc-500 text-xs font-semibold hover:border-red-500/20 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/5 transition-all flex justify-center items-center gap-2">
          <Trash2 className="w-4 h-4" /> Remove Waypoint
        </button>
      </div>
    </aside>
  );
}