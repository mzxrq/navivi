import { Film } from 'lucide-react';

export function VideoArea() {
  return (
    <div className="h-44 bg-slate-900/60 backdrop-blur-md border-t border-slate-800/80 p-4 flex flex-col items-center justify-center text-slate-500 select-none">
      <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
        <Film className="w-4 h-4" />
        <span>Video Preview Canvas</span>
      </div>
      <p className="text-xs text-slate-600 mt-1">Rendered output player will automatically attach here</p>
    </div>
  );
}