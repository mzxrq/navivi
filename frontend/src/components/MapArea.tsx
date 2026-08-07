import { useEffect, useState } from 'react';
import { listen } from '@tauri-apps/api/event';
import { UploadCloud, CheckCircle2, FileCode } from 'lucide-react';

export function MapArea() {
  const [gpxPath, setGpxPath] = useState<string | null>(null);
  const [isHovering, setIsHovering] = useState(false);

  useEffect(() => {
    // 1. Listen for when a file enters the window
    const unlistenHover = listen('tauri://drag-enter', () => setIsHovering(true));
    
    // 2. Listen for when a file leaves the window without dropping
    const unlistenLeave = listen('tauri://drag-leave', () => setIsHovering(false));
    
    // 3. Listen for the actual file drop
    const unlistenDrop = listen<{ paths: string[] }>('tauri://drop', (event) => {
      setIsHovering(false);
      
      const droppedFiles = event.payload.paths;
      if (droppedFiles && droppedFiles.length > 0) {
        const filePath = droppedFiles[0];
        
        // Basic validation to ensure the user dropped a GPX file
        if (filePath.toLowerCase().endsWith('.gpx')) {
          setGpxPath(filePath);
        } else {
          alert('Please drop a valid .gpx file!');
        }
      }
    });

    // Cleanup listeners when the component unmounts to prevent memory leaks
    return () => {
      unlistenHover.then((f) => f());
      unlistenLeave.then((f) => f());
      unlistenDrop.then((f) => f());
    };
  }, []);

  return (
    <main className="flex-1 relative bg-slate-950 flex items-center justify-center p-6 overflow-hidden">
      {/* Background Ambient Glow */}
      <div className="absolute w-96 h-96 bg-blue-600/5 rounded-full blur-3xl pointer-events-none" />

      {/* Main Dropzone Container */}
      <div 
        className={`w-full h-full border-2 border-dashed rounded-2xl flex flex-col items-center justify-center transition-all duration-300 relative z-10 ${
          isHovering 
            ? 'border-blue-500 bg-blue-500/5 scale-[0.99] shadow-2xl shadow-blue-500/10' 
            : gpxPath 
            ? 'border-emerald-500/40 bg-emerald-500/5' 
            : 'border-slate-800/80 bg-slate-900/20 hover:border-slate-700'
        }`}
      >
        {gpxPath ? (
          // Success State: File Loaded
          <div className="text-center p-6 bg-slate-900/80 backdrop-blur-md border border-emerald-500/30 rounded-2xl shadow-2xl max-w-lg space-y-3">
            <div className="w-12 h-12 rounded-full bg-emerald-500/10 text-emerald-400 flex items-center justify-center mx-auto border border-emerald-500/20">
              <CheckCircle2 className="w-6 h-6" />
            </div>
            <div>
              <h3 className="text-slate-200 font-semibold text-sm">GPS Track Loaded</h3>
              <p className="text-xs text-slate-400 mt-0.5">Ready for map rendering</p>
            </div>
            <div className="flex items-center gap-2 bg-slate-950 px-3 py-2 rounded-lg border border-slate-800/80 text-left w-full overflow-hidden">
              <FileCode className="w-4 h-4 text-slate-500 shrink-0" />
              <p className="text-xs text-slate-300 font-mono truncate" title={gpxPath}>
                {gpxPath}
              </p>
            </div>
          </div>
        ) : (
          // Default/Hover State: Waiting for File
          <div className="text-center space-y-4 pointer-events-none">
            <div className={`w-14 h-14 rounded-2xl flex items-center justify-center mx-auto transition-all ${
              isHovering ? 'bg-blue-500 text-white scale-110' : 'bg-slate-900 text-slate-400 border border-slate-800'
            }`}>
              <UploadCloud className="w-7 h-7" />
            </div>
            <div className="space-y-1">
              <p className="text-slate-200 font-medium text-sm">
                {isHovering ? 'Drop GPX File Now' : 'Drag & Drop GPX Route File'}
              </p>
              <p className="text-xs text-slate-500">Supports standard .gpx files from Garmin, Strava, or OsmAnd</p>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}