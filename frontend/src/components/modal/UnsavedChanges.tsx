interface UnsavedChangesProps {
    isOpen: boolean;
    projectName: string;
    onCancel: () => void;
    onDiscard: () => void;
    onSave: () => void;
}

export function UnsavedChanges({ isOpen, projectName, onCancel, onDiscard, onSave }: UnsavedChangesProps) {
    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-[999] flex items-center justify-center bg-black/60 animate-in fade-in">
      <div className="w-96 bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-white/10 rounded-xl shadow-xl p-6 animate-in zoom-in-95 duration-200">
        <h3 className="text-base font-bold text-zinc-900 dark:text-white mb-2">Unsaved Changes</h3>
        <p className="text-sm text-zinc-600 dark:text-zinc-400 mb-6">
          Do you want to save the changes you made to <span className="font-bold text-zinc-900 dark:text-zinc-200">{projectName}</span>?
        </p>
        
        <div className="flex justify-between items-center">
          <button 
            onClick={onCancel} 
            className="px-4 py-2 text-xs font-semibold text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-300 transition-colors"
          >
            Cancel
          </button>
          
          <div className="flex gap-2">
            <button 
              onClick={onDiscard} 
              className="px-4 py-2 bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400 text-xs font-bold rounded-lg hover:bg-red-100 dark:hover:bg-red-500/20 transition-colors"
            >
              Don't Save
            </button>
            
            <button 
              onClick={onSave} 
              className="px-4 py-2 bg-emerald-500 text-white text-xs font-bold rounded-lg hover:bg-emerald-600 transition-colors shadow-sm"
            >
              Save
            </button>
          </div>
        </div>
      </div>
    </div>
    );
}