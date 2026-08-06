import { getCurrentWindow } from '@tauri-apps/api/window';
import { Minus, Square, X } from 'lucide-react';

export function TitleBar() {
  const appWindow = getCurrentWindow();

  return (
    // data-tauri-drag-region makes the empty space draggable
    <div 
      data-tauri-drag-region 
      className="absolute top-0 right-0 left-0 h-10 flex justify-end items-center bg-transparent select-none z-50"
    >
      <div className="flex h-full pointer-events-auto">
        <button
          onClick={() => appWindow.minimize()}
          className="inline-flex items-center justify-center w-12 h-full text-slate-400 hover:bg-white/10 hover:text-white transition-colors"
          title="Minimize"
        >
          <Minus className="w-4 h-4 pointer-events-none" />
        </button>
        
        <button
          onClick={() => appWindow.toggleMaximize()}
          className="inline-flex items-center justify-center w-12 h-full text-slate-400 hover:bg-white/10 hover:text-white transition-colors"
          title="Maximize"
        >
          <Square className="w-3.5 h-3.5 pointer-events-none" />
        </button>
        
        <button
          onClick={() => appWindow.close()}
          className="inline-flex items-center justify-center w-12 h-full text-slate-400 hover:bg-red-500 hover:text-white transition-colors"
          title="Close"
        >
          <X className="w-4 h-4 pointer-events-none" />
        </button>
      </div>
    </div>
  );
}