import { Settings, MapPin, Sparkles, ChevronRight, Layers } from 'lucide-react';

export function Sidebar() {
  return (
    <aside className="w-[340px] bg-zinc-950 border-r border-white/[0.08] flex flex-col justify-between p-6 h-full select-none z-10 relative shadow-2xl">
      <div className="space-y-8">
        {/* App Branding (Cleaned up, non-draggable) */}
        <div className="flex items-center gap-3.5 pb-2">
          <div className="w-10 h-10 rounded-xl bg-zinc-800 flex items-center justify-center border border-white/10 shadow-sm">
            <MapPin className="w-5 h-5 text-zinc-100" />
          </div>
          <div>
            <h1 className="text-base font-semibold text-zinc-100 tracking-tight">Project Config</h1>
            <p className="text-xs text-zinc-500 font-medium tracking-wide">WORKSPACE SETTINGS</p>
          </div>
        </div>

        {/* Global Config Card */}
        <div className="space-y-4">
          <h2 className="text-[11px] font-bold text-zinc-500 uppercase tracking-widest px-1">Configuration</h2>
          <div className="bg-zinc-900/50 rounded-2xl border border-white/[0.05] p-4 space-y-3 transition-colors hover:bg-zinc-900/80">
            <div className="flex justify-between items-center">
              <span className="text-sm font-medium text-zinc-400 flex items-center gap-2">
                <Settings className="w-4 h-4" /> Resolution
              </span>
              <span className="text-xs font-semibold text-zinc-200 bg-zinc-800 px-2.5 py-1 rounded-md border border-white/10">
                1080p • 30fps
              </span>
            </div>
          </div>
        </div>

        {/* Waypoints Section */}
        <div className="space-y-4">
          <div className="flex justify-between items-center px-1">
            <h2 className="text-[11px] font-bold text-zinc-500 uppercase tracking-widest flex items-center gap-2">
              <Layers className="w-3.5 h-3.5" /> Waypoints
            </h2>
            <span className="text-[10px] font-bold text-zinc-400 bg-zinc-800/50 px-2 py-0.5 rounded-full border border-zinc-700/50">
              0 Active
            </span>
          </div>

          <div className="group rounded-2xl border border-dashed border-zinc-800 hover:border-zinc-700 bg-zinc-900/20 p-8 text-center transition-all duration-300">
            <p className="text-sm font-medium text-zinc-500 group-hover:text-zinc-400 transition-colors">
              Click the map to drop markers
            </p>
          </div>
        </div>
      </div>

      {/* Primary Action Button - Clean, professional monochrome */}
      <button 
        className="w-full relative group overflow-hidden rounded-xl p-[1px] font-semibold text-sm transition-all disabled:opacity-40 disabled:pointer-events-none active:scale-[0.98]"
        disabled
      >
        <div className="absolute inset-0 bg-zinc-700 opacity-80 group-hover:opacity-100 transition-opacity" />
        <div className="relative px-4 py-3.5 bg-zinc-900 backdrop-blur-sm rounded-[11px] flex items-center justify-center gap-2 text-zinc-100 border border-white/10 shadow-[inset_0_1px_0_rgba(255,255,255,0.1)]">
          <Sparkles className="w-4 h-4 text-zinc-400" />
          <span className="tracking-wide">Render Video</span>
          <ChevronRight className="w-4 h-4 text-zinc-500 group-hover:translate-x-1 transition-transform" />
        </div>
      </button>
    </aside>
  );
}