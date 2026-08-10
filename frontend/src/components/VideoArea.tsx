import { Film, Play, SkipBack, SkipForward, Volume2, Maximize, Settings2 } from 'lucide-react';

export function VideoArea() {
  return (
    <div className="h-56 border-t border-zinc-800/60 bg-[#09090b]/95 flex flex-col relative z-10 backdrop-blur-md">
      
      {/* Top Section: Empty State / Video Viewport */}
      <div className="flex-1 flex items-center justify-center relative">
        <p className="text-sm font-medium text-zinc-500">Engine: Waiting for render...</p>
      </div>

      {/* Bottom Section: Media Controls */}
      <div className="w-full px-6 pb-5 pt-2">
        
        {/* Scrubber Bar (Full Width) - Changed to neutral white/zinc */}
        <div className="group cursor-pointer py-2 w-full">
          <div className="h-1.5 w-full bg-zinc-800/80 rounded-full overflow-hidden flex items-center border border-white/5 relative">
            <div className="absolute left-0 top-0 bottom-0 w-0 bg-zinc-200 rounded-full group-hover:bg-white transition-colors" />
          </div>
        </div>

        {/* Controls Row */}
        <div className="flex items-center justify-between mt-2">
          
          {/* Left: Info */}
          <div className="flex flex-col justify-center gap-1 w-1/3">
            <div className="flex items-center gap-1.5 text-[10px] font-bold text-zinc-500 uppercase tracking-widest">
              <Film className="w-3 h-3" />
              <span>Preview</span>
            </div>
            <div className="text-[11px] font-mono font-medium text-zinc-400 whitespace-nowrap">
              00:00:00 / 00:00:00
            </div>
          </div>

          {/* Center: Playback */}
          <div className="flex items-center justify-center gap-6 w-1/3 text-zinc-400">
            <button className="hover:text-zinc-100 transition-colors">
              <SkipBack className="w-4 h-4 fill-current" />
            </button>
            <button className="w-10 h-10 rounded-full bg-zinc-200 text-zinc-950 flex items-center justify-center hover:bg-white hover:scale-105 active:scale-95 transition-all shadow-lg shadow-white/5">
              <Play className="w-5 h-5 ml-0.5 fill-current" />
            </button>
            <button className="hover:text-zinc-100 transition-colors">
              <SkipForward className="w-4 h-4 fill-current" />
            </button>
          </div>

          {/* Right: Tools */}
          <div className="flex items-center justify-end gap-4 w-1/3 text-zinc-400">
             <button className="hover:text-zinc-100 transition-colors">
               <Volume2 className="w-4 h-4" />
             </button>
             <button className="hover:text-zinc-100 transition-colors">
               <Settings2 className="w-4 h-4" />
             </button>
             <div className="h-4 w-px bg-zinc-700/50 mx-1" />
             <button className="hover:text-zinc-100 transition-colors">
               <Maximize className="w-4 h-4" />
             </button>
          </div>

        </div>
      </div>
    </div>
  );
}