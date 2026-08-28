import { useState, useMemo } from "react";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { Search, Film, ImageIcon, Mic, FileAudio, FolderSync } from "../../ui/icons"

type MediaType = "all" | "video" | "audio" | "image";

interface MediaAsset {
    id: string;
    name: string;
    type: "video" | "audio" | "image";
    duration?: string;
}

export function MediaPool() {
    const { waypoints, metadata } = useWorkspace();
    const [filter, setFilter] = useState<MediaType>("all");
    const [searchQuery, setSearchQuery] = useState("");

    const assets = useMemo(() => {
        const generated: MediaAsset[] = [];

        generated.push({ id: "global-vid", name: "overview_flythrough.mp4", type: "video", duration: "00:15" });
        if (metadata.overview_narration) {
            generated.push({ id: "global-aud", name: "overview_voice.wav", type: "audio", duration: "00:10" });
        }

        waypoints.forEach((wp, index) => {
            generated.push({ id: `wp${index}-vid`, name: `${wp.name}_map.mp4`, type: "video", duration: "00:08"});

            if (wp.narration.trim()) {
                generated.push({ id: `wp${index}-aud`, name: `${wp.name}_script.wav`, type: "audio", duration: "00:12" });
            }
            wp.images.forEach((img, imgIndex) => {
                generated.push({ id: `wp${index}-img${imgIndex}`, name: img.split(/[\\]/).pop() || `image_${imgIndex}.jpg`, type: "image" });
            });
        });
        return generated;
    }, [waypoints, metadata.overview_narration]);

    const filteredAssets = assets.filter(asset => {
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
                    <button className="text-zinc-400 hover:text-navi transition-colors" title="Refresh Assets">
                        <FolderSync className="w-3.5 h-3.5" />
                    </button>
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
                        No assets found.
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
                            <div className="flex-1 min-w-0">
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