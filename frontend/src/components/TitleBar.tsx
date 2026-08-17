import { useState, useRef, useEffect } from 'react';
import { useUI } from '../hooks/useUI';
import { useTheme } from '../hooks/useTheme';
import { useWorkspace } from '../hooks/useWorkspace';
import { Menu, X, Minus, Square, Map, ChevronRight, Sun, Moon, PanelBottom } from 'lucide-react';
import { Window } from '@tauri-apps/api/window';

export function TitleBar() {
  const { currentView, setCurrentView, showVideoPanel, setShowVideoPanel, showToast } = useUI();
  const { theme, setTheme } = useTheme();
  const { saveProject, metadata, updateMetadata } = useWorkspace();
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleWindow = async (action: 'minimize' | 'maximize' | 'close') => {
    const appWindow = new Window('main');
    if (action === 'minimize') await appWindow.minimize();
    if (action === 'maximize') await appWindow.toggleMaximize();
    if (action === 'close') await appWindow.close();
  };

  const handleSave = async () => {
    setIsMenuOpen(false);
    try {
      const path = await saveProject();
      if (path) {
        showToast(`Project saved to ${path.split(/[/\\]/).pop()}`, "success");
      }
    } catch (err) {
      showToast("Failed to save project.", "error");
    }
  };

  const handleSaveAs = async () => {
    setIsMenuOpen(false);
    
    // Quick "Save As" logic: We ask for a new name, then wipe the ID/Path 
    // so the next 'Save' generates a completely isolated folder.
    const newName = prompt("Enter new project name:", metadata.project_name);
    if (newName) {
      updateMetadata({
        project_name: newName,
        project_id: "", // Blanking this forces a new folder generation!
        directory_path: ""
      });
      showToast("Project renamed. Click 'Save' to generate the new folder.", "info");
    }
  };

  return (
    <div 
      data-tauri-drag-region 
      className="h-10 bg-white dark:bg-[#18181b] border-b border-zinc-200 dark:border-white/5 flex items-center justify-between select-none shrink-0 transition-colors"
    >
      <div className="flex items-center h-full">
        <div className="relative h-full flex items-center" ref={menuRef}>
          <button 
            onClick={() => setIsMenuOpen(!isMenuOpen)}
            className={`h-full px-3 flex items-center transition-colors ${isMenuOpen ? 'bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-white' : 'text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-50 dark:hover:bg-white/5'}`}
          >
            <Menu className="w-4 h-4" />
          </button>

          {isMenuOpen && (
            <div className="absolute top-10 left-2 w-56 bg-white dark:bg-[#1f1f22] border border-zinc-200 dark:border-white/10 rounded-md shadow-2xl py-1 z-[200] text-sm text-zinc-700 dark:text-zinc-300">
              <button 
                onClick={() => { setCurrentView('title_screen'); setIsMenuOpen(false); }}
                className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-emerald-50 dark:hover:bg-emerald-500/10 hover:text-emerald-600 dark:hover:text-emerald-400 transition-colors"
              >
                <span>Project Manager</span>
              </button>
              
              <div className="h-px bg-zinc-200 dark:bg-white/5 my-1 mx-2" />
              
              <button 
                onClick={() => { setCurrentView('editor'); setIsMenuOpen(false); }}
                className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-zinc-100 dark:hover:bg-zinc-700/50 hover:text-zinc-900 dark:hover:text-white transition-colors"
              >
                <span>New Project</span>
              </button>
              
              <button 
                onClick={() => { showToast("Open functionality migrating here soon!", "info"); setIsMenuOpen(false); }}
                className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-zinc-100 dark:hover:bg-zinc-700/50 hover:text-zinc-900 dark:hover:text-white transition-colors"
              >
                <span>Open File...</span>
                <span className="text-xs text-zinc-400 dark:text-zinc-500">Ctrl+O</span>
              </button>

              <div className="h-px bg-zinc-200 dark:bg-white/5 my-1 mx-2" />

              <button 
                onClick={handleSave}
                className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-zinc-100 dark:hover:bg-zinc-700/50 hover:text-zinc-900 dark:hover:text-white transition-colors"
              >
                <span>Save Project</span>
                <span className="text-xs text-zinc-400 dark:text-zinc-500">Ctrl+S</span>
              </button>

              <button 
                onClick={handleSaveAs}
                className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-zinc-100 dark:hover:bg-zinc-700/50 hover:text-zinc-900 dark:hover:text-white transition-colors"
              >
                <span>Save As...</span>
                <span className="text-xs text-zinc-400 dark:text-zinc-500">Ctrl+Shift+S</span>
              </button>

              <div className="h-px bg-zinc-200 dark:bg-white/5 my-1 mx-2" />
              
              <button 
                onClick={() => handleWindow('close')}
                className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-red-50 dark:hover:bg-red-500/20 hover:text-red-600 dark:hover:text-red-400 transition-colors"
              >
                <span>Exit</span>
              </button>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 px-3 text-xs font-medium text-zinc-500 dark:text-zinc-400 pointer-events-none">
          <Map className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-500" />
          <span className="text-zinc-800 dark:text-zinc-300">Navivi</span>
          <ChevronRight className="w-3 h-3 opacity-50" />
          <span className="text-zinc-600 dark:text-zinc-200">
            {currentView === 'title_screen' ? 'Project Manager' : 'Map Editor'}
          </span>

          {metadata.status === 'initialized' && (
            <span className='ml-2 px-1.5 py-0.5 rounded text-[9px] font-bold bbg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-400 uppercase tracking-widest border border-amber-200 dark:border-amber-500/20'>
              Unsaved
            </span>
          )}
        </div>
      </div>

      <div className="flex h-full text-zinc-600 dark:text-zinc-400">
        {currentView === 'editor' && (
          <button onClick={() => setShowVideoPanel(!showVideoPanel)}
          className={`h-full px-3 flex items-center transition-colors ${showVideoPanel ? 'text-emerald-600 dark:text-emerald-400 bg-zinc-100 dark:bg-white/10' : 'hover:bg-zinc-100 dark:hover:bg-white/10 hover:text-zinc-900 dark:hover:text-white'}`}
          title='Toggle Preview Panel'
          >
            <PanelBottom className='w-4 h-4'/>
          </button>
        )}

        <button 
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} 
          className="h-full px-4 hover:bg-zinc-100 dark:hover:bg-white/10 hover:text-zinc-900 dark:hover:text-white transition-colors"
          title="Toggle Theme"
        >
          {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </button>
        <div className="w-px h-4 my-auto bg-zinc-200 dark:bg-white/10 mx-1"></div>
        
        <button onClick={() => handleWindow('minimize')} className="h-full px-4 hover:bg-zinc-100 dark:hover:bg-white/10 hover:text-zinc-900 dark:hover:text-white transition-colors">
          <Minus className="w-4 h-4" />
        </button>
        <button onClick={() => handleWindow('maximize')} className="h-full px-4 hover:bg-zinc-100 dark:hover:bg-white/10 hover:text-zinc-900 dark:hover:text-white transition-colors">
          <Square className="w-3.5 h-3.5" />
        </button>
        <button onClick={() => handleWindow('close')} className="h-full px-4 hover:bg-red-500 hover:text-white transition-colors">
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}