import { getCurrentWindow } from '@tauri-apps/api/window';
import { Minus, Square, X, Menu, Sun, Moon, Monitor } from 'lucide-react';
import { useTheme } from '../hooks/useTheme'; // Import our new hook

export function TitleBar() {
  const appWindow = getCurrentWindow();
  const { theme, setTheme } = useTheme();

  // Cycle through themes
  const cycleTheme = () => {
    if (theme === 'system') setTheme('light');
    else if (theme === 'light') setTheme('dark');
    else setTheme('system');
  };

  // Determine which icon to show
  const ThemeIcon = theme === 'system' ? Monitor : theme === 'light' ? Sun : Moon;

  return (
    <div 
      data-tauri-drag-region 
      // Notice the updated classes here! Base is light, dark: is dark.
      className="h-9 w-full flex justify-between items-center bg-zinc-100 dark:bg-[#09090b] text-zinc-600 dark:text-zinc-500 select-none border-b border-zinc-300 dark:border-white/[0.04] z-50 shrink-0 transition-colors"
    >
      {/* Left: App Menu & Theme Toggle */}
      <div className="flex items-center h-full px-2 gap-1">
        <button 
          className="p-1.5 rounded-md hover:bg-zinc-200 dark:hover:bg-zinc-800/60 hover:text-zinc-900 dark:hover:text-zinc-200 transition-colors"
        >
          <Menu className="w-4 h-4" />
        </button>
        <button 
          onClick={cycleTheme}
          className="p-1.5 rounded-md hover:bg-zinc-200 dark:hover:bg-zinc-800/60 hover:text-zinc-900 dark:hover:text-zinc-200 transition-colors"
          title={`Current Theme: ${theme}`}
        >
          <ThemeIcon className="w-4 h-4" />
        </button>
      </div>

      {/* Center: App Title (Draggable) */}
      <div 
        data-tauri-drag-region 
        className="flex-1 h-full flex items-center justify-center text-[10px] font-bold tracking-widest uppercase text-zinc-500 dark:text-zinc-400 pointer-events-none"
      >
        GPS Studio <span className="mx-2 opacity-30">•</span> Map Editor
      </div>

      {/* Right: Custom Window Controls */}
      <div className="flex h-full items-center px-1.5 py-1 gap-0.5">
        <button 
          onClick={() => appWindow.minimize()}
          className="w-8 h-full flex items-center justify-center rounded-md hover:bg-zinc-200 dark:hover:bg-zinc-800/60 transition-colors"
        >
          <Minus className="w-3.5 h-3.5" />
        </button>
        <button 
          onClick={() => appWindow.toggleMaximize()}
          className="w-8 h-full flex items-center justify-center rounded-md hover:bg-zinc-200 dark:hover:bg-zinc-800/60 transition-colors"
        >
          <Square className="w-3 h-3" />
        </button>
        <button 
          onClick={() => appWindow.close()}
          className="w-8 h-full flex items-center justify-center rounded-md hover:bg-red-500/20 hover:text-red-500 dark:hover:text-red-400 transition-colors"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}