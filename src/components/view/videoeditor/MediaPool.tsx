import { useState, useEffect } from "react";
import { join } from "@tauri-apps/api/path";
import { open } from '@tauri-apps/plugin-dialog';
import { readDir, exists } from "@tauri-apps/plugin-fs"; // ✨ NEW: Native filesystem scanner
import { convertFileSrc } from '@tauri-apps/api/core';
import { useWorkspace } from "../../../hooks/useWorkspace";
import { Search, Film, ImageIcon, Mic, FileAudio, FolderSync } from "../../ui/icons";

type MediaType = "all" | "video" | "audio" | "image" | "text";

interface MediaAsset {
  id: string;
  name: string;
  type: "video" | "audio" | "image" | "text";
  duration?: string;
  source: string;
}

export function MediaPool() {
  const { metadata } = useWorkspace();
  const [filter, setFilter] = useState<MediaType>("all");
  const [searchQuery, setSearchQuery] = useState("");
  
  const [assets, setAssets] = useState<MediaAsset[]>([]);
  const [importedAssets, setImportedAssets] = useState<MediaAsset[]>([]);
  const [isLoaded, setIsLoaded] = useState(false);

  // Auto-Load System for user-imported assets
  useEffect(() => {
    const savedAssets = localStorage.getItem('nle_media_pool');
    if (savedAssets) {
      try {
        setImportedAssets(JSON.parse(savedAssets));
      } catch (error) {
        console.error("Failed to parse saved media pool:", error);
      }
    }
    setIsLoaded(true);
  }, []);

  // Auto-Save System for user-imported assets
  useEffect(() => {
    if (isLoaded) {
      localStorage.setItem('nle_media_pool', JSON.stringify(importedAssets));
    }
  }, [importedAssets, isLoaded]);

  // ✨ TRUE DISK SCANNER
  useEffect(() => {
    const buildAssets = async () => {
      if (!metadata?.directory_path) return;

      const projectDir = metadata.directory_path;
      const baseAssetsDir = await join(projectDir, "assets");
      const generated: MediaAsset[] = [];

      // The new strict folder structure mapped to ClipKinds
      const folders = [
        { name: "video", type: "video" as const },
        { name: "audio", type: "audio" as const },
        { name: "image", type: "image" as const },
        { name: "subtitle", type: "text" as const }
      ];

      for (const folder of folders) {
        const folderPath = await join(baseAssetsDir, folder.name);
        
        if (await exists(folderPath)) {
          try {
            const entries = await readDir(folderPath);
            for (const entry of entries) {
              if (entry.isFile && !entry.name.startsWith('.')) { // Ignore hidden files like .DS_Store
                generated.push({
                  id: crypto.randomUUID(),
                  name: entry.name,
                  type: folder.type,
                  source: await join(folderPath, entry.name),
                  duration: folder.type === "image" || folder.type === "text" ? "00:05" : undefined 
                });
              }
            }
          } catch (err) {
            console.error(`Failed to read folder ${folderPath}:`, err);
          }
        }
      }
      setAssets(generated);
    };

    buildAssets();
  }, [metadata]); // Re-runs whenever the project directory changes

  const handleImportMedia = async () => {
    try {
      const selected = await open({
        multiple: true,
        filters: [{
          name: 'Media',
          extensions: ['mp4', 'mov', 'webm', 'mp3', 'wav', 'png', 'jpg', 'jpeg', 'srt']
        }]
      });

      if (!selected) return;

      const filePaths = Array.isArray(selected) ? selected : [selected];
      const newAssets: MediaAsset[] = [];

      for (const path of filePaths) {
        const ext = path.split('.').pop()?.toLowerCase() || '';
        let type: "video" | "audio" | "image" | "text" = 'image';
        if (['mp4', 'mov', 'webm'].includes(ext)) type = 'video';
        if (['mp3', 'wav'].includes(ext)) type = 'audio';
        if (['srt'].includes(ext)) type = 'text';

        const name = path.split(/[\\/]/).pop() || 'Unknown File';
        let durationStr = "00:05"; 

        if (type === 'audio' || type === 'video') {
          const safeUrl = convertFileSrc(path);
          const durationSeconds = await new Promise<number>((resolve) => {
            const media = document.createElement(type === 'audio' ? 'audio' : 'video');
            media.onloadedmetadata = () => resolve(media.duration);
            media.onerror = () => resolve(5); 
            media.src = safeUrl;
          });

          const mins = Math.floor(durationSeconds / 60).toString().padStart(2, '0');
          const secs = Math.floor(durationSeconds % 60).toString().padStart(2, '0');
          durationStr = `${mins}:${secs}`;
        }

        newAssets.push({
          id: crypto.randomUUID(),
          name: name,
          source: path, 
          type: type,
          duration: durationStr
        });
      }

      setImportedAssets(prev => [...prev, ...newAssets]);
    } catch (error) {
      console.error("Failed to import media:", error);
    }
  };

  const allAssets = [...assets, ...importedAssets];

  const filteredAssets = allAssets.filter(asset => {
    const matchesType = filter === "all" || asset.type === filter;
    const matchesSearch = asset.name.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesType && matchesSearch;
  });

  const getIcon = (type: string) => {
    switch (type) {
      case "video": return <Film className="w-4 h-4 text-navi-500" />
      case "audio": return <Mic className="w-4 h-4 text-purple-500" />
      case "image": return <ImageIcon className="w-4 h-4 text-amber-500" />
      default: return <FileAudio className="w-4 h-4 text-zinc-500" />
    }
  };

  return (
    <div className="w-64 h-full bg-white dark:bg-navidark-800 border-r border-zinc-200 dark:border-navidark-300 flex flex-col shrink-0">
      {/* Header & Search */}
      <div className="p-3 border-b border-zinc-200 dark:border-navidark-300 space-y-3">
        <div className="flex items-center justify-between text-xs font-bold text-zinc-700 dark:text-zinc-200 uppercase tracking-wider">
          <span>Media Pool</span>
          <div className="flex items-center gap-2">
            <button 
              onClick={handleImportMedia} 
              className="bg-navi hover:bg-navi-600 text-white text-[10px] px-2 py-1 rounded transition-colors flex items-center gap-1 shadow-sm"
              title="Import External Media"
            >
              <span className="text-sm leading-none">+</span> Import
            </button>
            <button 
              onClick={() => setImportedAssets([])} 
              className="text-zinc-400 hover:text-red-500 transition-colors" 
              title="Clear Imported Media"
            >
              <FolderSync className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
        
        <div className="relative">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-400" />
          <input
            type="text"
            placeholder="Search assets"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-zinc-100 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded-md py-1.5 pl-8 pr-2 text-xs text-zinc-800 dark:text-zinc-200 placeholder:text-zinc-400 focus:outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
          />
        </div>
      </div>

      {/* Filter Tabs */}
      <div className="flex bg-zinc-50 dark:bg-navidark-700 border-b border-zinc-200 dark:border-navidark-300 p-1">
        {["all", "video", "audio", "image"].map((type) => (
          <button
            key={type}
            onClick={() => setFilter(type as MediaType)}
            className={`flex-1 text-[10px] font-bold uppercase tracking-wider py-1.5 rounded-sm transition-colors ${
              filter === type
                ? "bg-white dark:bg-navidark-500 text-navi-600 dark:text-navi-400 shadow-sm"
                : "text-zinc-500 hover:text-zinc-700 dark:text-navidark-125 dark:hover:text-white"
            }`}
          >
            {type}
          </button>
        ))}
      </div>

      {/* Asset List */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-2 space-y-1">
        {filteredAssets.length === 0 ? (
          <div className="text-center py-8 text-xs text-zinc-400">
            No assets found in /assets directory.
          </div>
        ) : (
          filteredAssets.map((asset) => (
            <div
              key={asset.id}
              draggable="true"
              onDragStart={(e) => {
                e.stopPropagation();
                e.dataTransfer.setData("text", JSON.stringify(asset)); 
                e.dataTransfer.effectAllowed = "copy";
              }}
              className="flex items-center gap-3 p-2 rounded-md hover:bg-zinc-100 dark:hover:bg-navidark-600 cursor-grab active:cursor-grabbing border border-transparent hover:border-zinc-200 dark:hover:border-navidark-400 transition-colors group"
            >
              <div className="shrink-0 bg-zinc-100 dark:bg-navidark-900 p-1.5 rounded pointer-events-none">
                {getIcon(asset.type)}
              </div>
              <div className="flex-1 min-w-0 pointer-events-none">
                <p className="text-xs font-medium text-zinc-700 dark:text-zinc-200 truncate select-none">
                  {asset.name}
                </p>
                {asset.duration && (
                  <p className="text-[10px] text-zinc-400 font-mono">
                    {asset.duration}
                  </p>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}