import { Settings2, Film, MonitorPlay } from "../../ui/icons";

interface ExportPanelProps {
    onExport: () => void;
}

export function ExportPanel({ onExport }: ExportPanelProps) {
    return (
        <div className="flex flex-col gap-6 animate-in fade-in duration-200 p-4">
      <div className="flex items-center gap-2 pb-3 border-b border-zinc-200 dark:border-navidark-400">
        <MonitorPlay className="w-4 h-4 text-navi" />
        <h4 className="text-sm font-bold text-zinc-800 dark:text-zinc-100">Render Settings</h4>
      </div>

      <div className="space-y-4">
        <div className="space-y-1.5">
          <label className="text-[10px] font-bold text-zinc-500 uppercase tracking-wider">Resolution</label>
          <select className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-2 text-xs text-zinc-800 dark:text-zinc-200 focus:outline-none focus:border-navi">
            <option>1080p HD (1920x1080)</option>
            <option>4K UHD (3840x2160)</option>
            <option>Vertical (1080x1920)</option>
          </select>
        </div>

        <div className="space-y-1.5">
          <label className="text-[10px] font-bold text-zinc-500 uppercase tracking-wider">Framerate</label>
          <select className="w-full bg-zinc-50 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded p-2 text-xs text-zinc-800 dark:text-zinc-200 focus:outline-none focus:border-navi">
            <option>30 FPS</option>
            <option>60 FPS</option>
            <option>24 FPS (Cinematic)</option>
          </select>
        </div>
      </div>

      <div className="mt-4 pt-4 border-t border-zinc-200 dark:border-navidark-400">
        <button 
          onClick={onExport}
          className="w-full py-3 bg-navi hover:bg-navi-600 text-white text-sm font-bold rounded-lg shadow-md hover:shadow-lg transition-all flex items-center justify-center gap-2"
        >
          <Film className="w-4 h-4" /> Export Video
        </button>
      </div>
    </div>
    );
}