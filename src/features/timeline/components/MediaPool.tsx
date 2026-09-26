import { useState, useEffect } from "react";
import { join } from "@tauri-apps/api/path";
import { open } from "@tauri-apps/plugin-dialog";
import { readDir, exists } from "@tauri-apps/plugin-fs";
import { convertFileSrc } from "@tauri-apps/api/core";
import { invoke } from "@tauri-apps/api/core";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { useUI } from "../../../hooks/useUI";
import {
  Search,
  Film,
  ImageIcon,
  Mic,
  FileAudio,
  AlertTriangle,
  RefreshCw,
} from "../../../components/ui/icons";
import { t, plural } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";

type MediaType = "all" | "video" | "audio" | "image" | "text";

interface MediaAsset {
  id: string;
  name: string;
  type: "video" | "audio" | "image" | "text";
  duration?: string;
  source: string;
  missing?: boolean;
}

export function MediaPool() {
  const { metadata } = useWorkspace();
  const { showToast } = useUI();
  const [filter, setFilter] = useState<MediaType>("all");
  const [searchQuery, setSearchQuery] = useState("");

  const [assets, setAssets] = useState<MediaAsset[]>([]);
  const [importedAssets, setImportedAssets] = useState<MediaAsset[]>([]);
  const [isLoaded, setIsLoaded] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const projectAssetKey = metadata?.directory_path
    ? `nle_media_pool:${metadata.directory_path}`
    : "nle_media_pool:unsaved";

  // Auto-Load System for user-imported assets
  useEffect(() => {
    setIsLoaded(false);
    setImportedAssets([]);
    const savedAssets = localStorage.getItem(projectAssetKey);
    if (savedAssets) {
      try {
        setImportedAssets(JSON.parse(savedAssets));
      } catch (error) {
        console.error("Failed to parse saved media pool:", error);
      }
    }
    setIsLoaded(true);
  }, [projectAssetKey]);

  // Auto-Save System for user-imported assets
  useEffect(() => {
    if (isLoaded) {
      localStorage.setItem(projectAssetKey, JSON.stringify(importedAssets));
    }
  }, [importedAssets, isLoaded, projectAssetKey]);

  useEffect(() => {
    let cancelled = false;
    const validateImportedAssets = async () => {
      const checked = await Promise.all(
        importedAssets.map(async (asset) => ({
          ...asset,
          missing: !(await exists(asset.source)),
        })),
      );
      if (
        !cancelled &&
        checked.some(
          (asset, index) => asset.missing !== importedAssets[index]?.missing,
        )
      ) {
        setImportedAssets(checked);
      }
    };
    if (importedAssets.length > 0) void validateImportedAssets();
    return () => {
      cancelled = true;
    };
  }, [importedAssets.length]);
  // ✨ TRUE DISK SCANNER
  useEffect(() => {
    const buildAssets = async () => {
      if (!metadata?.directory_path) return;

      const projectDir = metadata.directory_path;
      const baseAssetsDir = await join(projectDir, "assets");
      const generated: MediaAsset[] = [];
      const folders = [
        { name: "video", type: "video" as const, recursive: true },
        { name: "audio", type: "audio" as const, recursive: false },
        { name: "image", type: "image" as const, recursive: false },
        { name: "subtitles", type: "text" as const, recursive: false },
      ];

      for (const folder of folders) {
        const folderPath = await join(baseAssetsDir, folder.name);

        if (await exists(folderPath)) {
          try {
            const foldersToScan = [folderPath];
            while (foldersToScan.length > 0) {
              const currentFolderPath = foldersToScan.pop()!;
              const entries = await readDir(currentFolderPath);
              for (const entry of entries) {
                if (entry.isDirectory && folder.recursive) {
                  foldersToScan.push(await join(currentFolderPath, entry.name));
                  continue;
                }
                if (entry.isFile && !entry.name.startsWith(".")) {
                  const filePath = await join(currentFolderPath, entry.name);
                  let durationStr =
                    folder.type === "image" || folder.type === "text"
                      ? "00:05"
                      : undefined;

                  if (folder.type === "video" || folder.type === "audio") {
                    const safeUrl = convertFileSrc(filePath);
                    const durationSeconds = await new Promise<number>(
                      (resolve) => {
                        const media = document.createElement(
                          folder.type === "audio" ? "audio" : "video",
                        );
                        media.onloadedmetadata = () => resolve(media.duration);
                        media.onerror = () => resolve(0);
                        media.src = safeUrl;
                      },
                    );
                    if (durationSeconds > 0 && isFinite(durationSeconds)) {
                      const mins = Math.floor(durationSeconds / 60)
                        .toString()
                        .padStart(2, "0");
                      const secs = Math.floor(durationSeconds % 60)
                        .toString()
                        .padStart(2, "0");
                      durationStr = `${mins}:${secs}`;
                    }
                  }

                  generated.push({
                    id: crypto.randomUUID(),
                    name: entry.name,
                    type: folder.type,
                    source: filePath,
                    duration: durationStr,
                  });
                }
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
  }, [metadata?.directory_path, refreshToken]);

  const handleImportMedia = async () => {
    try {
      const selected = await open({
        multiple: true,
        filters: [
          {
            name: "Media",
            extensions: [
              "mp4",
              "mov",
              "webm",
              "mp3",
              "wav",
              "png",
              "jpg",
              "jpeg",
              "srt",
            ],
          },
        ],
      });

      if (!selected) return;

      const filePaths = Array.isArray(selected) ? selected : [selected];
      const newAssets: MediaAsset[] = [];

      if (!metadata?.directory_path) {
        throw new Error(t`Save the project before importing media`);
      }

      for (const path of filePaths) {
        const ext = path.split(".").pop()?.toLowerCase() || "";
        let type: "video" | "audio" | "image" | "text" = "image";
        if (["mp4", "mov", "webm"].includes(ext)) type = "video";
        if (["mp3", "wav"].includes(ext)) type = "audio";
        if (["srt"].includes(ext)) type = "text";

        const name = path.split(/[\\/]/).pop() || "Unknown File";
        const folderName = type === "text" ? "subtitles" : type;
        const targetDir = await join(
          metadata.directory_path,
          "assets",
          folderName,
        );
        const normalizedPath = path.replace(/\\/g, "/").toLowerCase();
        const normalizedProjectDir = metadata.directory_path
          .replace(/\\/g, "/")
          .toLowerCase();
        const projectAssetPath = normalizedPath.startsWith(
          `${normalizedProjectDir}/assets/`,
        )
          ? path
          : await invoke<string>("copy_asset_file", {
              sourcePath: path,
              targetDir,
            });
        let durationStr = "00:00";

        if (type === "audio" || type === "video") {
          const safeUrl = convertFileSrc(path);
          const durationSeconds = await new Promise<number>((resolve) => {
            const media = document.createElement(
              type === "audio" ? "audio" : "video",
            );
            media.onloadedmetadata = () => resolve(media.duration);
            media.onerror = () => resolve(5);
            media.src = safeUrl;
          });

          const mins = Math.floor(durationSeconds / 60)
            .toString()
            .padStart(2, "0");
          const secs = Math.floor(durationSeconds % 60)
            .toString()
            .padStart(2, "0");
          durationStr = `${mins}:${secs}`;
        }

        newAssets.push({
          id: crypto.randomUUID(),
          name: name,
          source: projectAssetPath,
          type: type,
          duration: durationStr,
        });
      }

      setImportedAssets((prev) => [...prev, ...newAssets]);
      showToast(
        plural(newAssets.length, {
          one: "1 media asset copied into the project.",
          other: "# media assets copied into the project.",
        }),
        "success",
      );
    } catch (error) {
      console.error("Failed to import media:", error);
      showToast(t`Failed to import media into the project`, "error");
    }
  };

  const allAssets = Array.from(
    new Map(
      [...assets, ...importedAssets].map((asset) => [asset.source, asset]),
    ).values(),
  );

  const filteredAssets = allAssets.filter((asset) => {
    const matchesType = filter === "all" || asset.type === filter;
    const matchesSearch = asset.name
      .toLowerCase()
      .includes(searchQuery.toLowerCase());
    return matchesType && matchesSearch;
  });

  const getIcon = (type: string) => {
    switch (type) {
      case "video":
        return <Film className="w-4 h-4 text-navi-500" />;
      case "audio":
        return <Mic className="w-4 h-4 text-purple-500" />;
      case "image":
        return <ImageIcon className="w-4 h-4 text-amber-500" />;
      default:
        return <FileAudio className="w-4 h-4 text-zinc-500" />;
    }
  };

  return (
    <div className="w-full h-full flex-1 bg-white dark:bg-navidark-800 flex flex-col shrink-0">
      {/* Header & Search */}
      <div className="p-3 border-b border-zinc-200 dark:border-navidark-300 space-y-3">
        <div className="flex items-center justify-between text-xs font-bold text-zinc-700 dark:text-zinc-200 uppercase tracking-wider">
          <span>
            <Trans>Media Pool </Trans>
            <span className="text-[9px] font-normal text-zinc-400">
              {allAssets.length}
            </span>
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={handleImportMedia}
              className="bg-navi hover:bg-navi-600 text-white text-[10px] px-2 py-1 rounded transition-colors flex items-center gap-1 shadow-sm"
              title={t`Import External Media`}
            >
              <span className="text-sm leading-none">+</span> Import
            </button>
            <button
              onClick={() => setRefreshToken((token) => token + 1)}
              className="text-zinc-400 hover:text-red-500 transition-colors"
              title={t`Refresh asset library`}
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        <div className="relative">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-400" />
          <input
            type="text"
            placeholder={t`Search assets`}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-zinc-100 dark:bg-navidark-900 border border-zinc-200 dark:border-navidark-400 rounded-md py-1.5 pl-8 pr-2 text-xs text-zinc-800 dark:text-zinc-200 placeholder:text-zinc-400 focus:outline-none focus:border-navi focus:ring-1 focus:ring-navi transition-all"
          />
        </div>
      </div>

      {/* Filter Tabs */}
      <div className="flex bg-zinc-50 dark:bg-navidark-700 border-b border-zinc-200 dark:border-navidark-300 p-1">
        {["all", "video", "audio", "image", "text"].map((type) => (
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
            <Trans>No assets found in directory</Trans>
          </div>
        ) : (
          filteredAssets.map((asset) => (
            <div
              key={asset.id}
              draggable="true"
              onDragStart={(e) => {
                e.stopPropagation();
                if (asset.missing) {
                  e.preventDefault();
                  showToast(
                    t`This asset is missing from the project`,
                    "warning",
                  );
                  return;
                }
                e.dataTransfer.setData("text", JSON.stringify(asset));
                e.dataTransfer.effectAllowed = "copy";
              }}
              onContextMenu={(e) => {
                e.preventDefault();
                e.stopPropagation();
                window.dispatchEvent(
                  new CustomEvent("open-context-menu", {
                    detail: {
                      x: e.clientX,
                      y: e.clientY,
                      type: "mediapool-item",
                      targetId: asset.id,
                      data: {
                        onDuplicate: () => {
                          const newAsset = {
                            ...asset,
                            id: crypto.randomUUID(),
                            name: asset.name + " (Copy)",
                          };
                          setImportedAssets((prev) => [...prev, newAsset]);
                        },
                        onRemove: () => {
                          setImportedAssets((prev) =>
                            prev.filter((a) => a.id !== asset.id),
                          );
                        },
                        onProperties: () => {
                          alert(
                            `Name: ${asset.name}\nType: ${asset.type}\nDuration: ${asset.duration || "N/A"}\nPath: ${asset.source}`,
                          );
                        },
                      },
                    },
                  }),
                );
              }}
              className={`flex items-center gap-3 p-2 rounded-md border border-transparent transition-colors group ${asset.missing ? "opacity-60 bg-red-50/50 dark:bg-red-950/20" : "hover:bg-zinc-100 dark:hover:bg-navidark-600 cursor-grab active:cursor-grabbing hover:border-zinc-200 dark:hover:border-navidark-400"}`}
            >
              <div className="shrink-0 bg-zinc-100 dark:bg-navidark-900 p-1.5 rounded pointer-events-none">
                {asset.missing ? (
                  <AlertTriangle className="w-4 h-4 text-red-500" />
                ) : asset.type === "image" ? (
                  <img
                    src={convertFileSrc(asset.source)}
                    alt=""
                    className="w-8 h-8 rounded object-cover"
                  />
                ) : (
                  getIcon(asset.type)
                )}
              </div>
              <div className="flex-1 min-w-0 pointer-events-none">
                <p className="text-xs font-medium text-zinc-700 dark:text-zinc-200 truncate select-none">
                  {asset.name}
                </p>
                {asset.missing && (
                  <p className="text-[10px] text-red-500">
                    <Trans>Missing file</Trans>
                  </p>
                )}
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
