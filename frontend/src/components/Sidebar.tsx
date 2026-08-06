import { Settings, MapPin, Sparkles, ChevronRight, Layers } from "lucide-react";

export function Sidebar() {
  return (
    <aside className="w-80 bg-slate-900/90 backdrop-blur-xl border-r border-slate-800/80 flex flex-col justify-between p-5 h-full select-none">
      <div className="space-y-6">
        {/* App Branding - Now acts as the window drag handle */}
        <div
          data-tauri-drag-region
          className="flex items-center gap-3 cursor-default select-none pb-2"
        >
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-500 flex items-center justify-center shadow-lg shadow-blue-500/25 pointer-events-none">
            {/* Ensure child elements don't block the drag event by using pointer-events-none */}
            <MapPin className="w-5 h-5 text-white" />
          </div>
          <div className="pointer-events-none">
            <h1 className="text-sm font-bold text-slate-100 tracking-wide">
              Video Creation
            </h1>
            <p className="text-[11px] text-slate-400 font-medium">naviVi</p>
          </div>
        </div>

        {/* Global Config Card */}
        <div className="space-y-3 bg-slate-800/40 p-3.5 rounded-xl border border-slate-700/40 shadow-inner">
          <div className="flex items-center justify-between text-xs font-semibold text-slate-400 uppercase tracking-wider">
            <span className="flex items-center gap-1.5">
              <Settings className="w-3.5 h-3.5" /> Output Config
            </span>
          </div>
          <div className="space-y-2 pt-1">
            <div className="flex justify-between items-center text-xs">
              <span className="text-slate-400">Target Spec</span>
              <span className="text-[11px] font-mono bg-blue-500/10 text-blue-400 border border-blue-500/20 px-2 py-0.5 rounded-full font-medium">
                1080p • 30 FPS
              </span>
            </div>
            <div className="flex justify-between items-center text-xs">
              <span className="text-slate-400">TTS Engine</span>
              <span className="text-[11px] font-mono bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 px-2 py-0.5 rounded-full font-medium">
                Irodori Local
              </span>
            </div>
          </div>
        </div>

        {/* Waypoints Section */}
        <div className="space-y-3">
          <div className="flex justify-between items-center px-1">
            <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-400 uppercase tracking-wider">
              <Layers className="w-3.5 h-3.5" /> Route Waypoints
            </span>
            <span className="text-[10px] bg-slate-800 text-slate-400 px-2 py-0.5 rounded-full border border-slate-700/50">
              0 Saved
            </span>
          </div>

          <div className="group border border-dashed border-slate-800 hover:border-slate-700 rounded-xl p-6 text-center transition-all bg-slate-950/20">
            <p className="text-xs text-slate-500 group-hover:text-slate-400 transition-colors">
              Click any route segment on the map to drop a waypoint marker
            </p>
          </div>
        </div>
      </div>

      {/* Primary Action Button */}
      <button
        className="w-full relative group overflow-hidden rounded-xl p-0.5 font-semibold text-sm shadow-xl shadow-blue-900/20 active:scale-[0.98] transition-transform disabled:opacity-40 disabled:pointer-events-none"
        disabled
      >
        <div className="absolute inset-0 bg-gradient-to-r from-blue-600 via-indigo-600 to-blue-500 rounded-xl transition-all group-hover:opacity-90" />
        <div className="relative px-4 py-3 bg-slate-900/20 rounded-[10px] flex items-center justify-center gap-2 text-white">
          <Sparkles className="w-4 h-4 text-blue-300 animate-pulse" />
          <span>Render Video</span>
          <ChevronRight className="w-4 h-4 text-slate-300 group-hover:translate-x-0.5 transition-transform" />
        </div>
      </button>
    </aside>
  );
}
